"""Adaptateurs Kafka et MongoDB (MS-08) : clients simulés, aucune connexion réelle."""

import threading

import pytest
from bson.errors import InvalidDocument
from kafka.errors import KafkaConnectionError, KafkaTimeoutError
from pymongo.errors import DuplicateKeyError, PyMongoError, ServerSelectionTimeoutError, WriteError

from app.adapters.kafka_publisher import KafkaEventPublisher
from app.adapters.mongo_store import MongoCollections, MongoRawEvents, MongoRejects
from app.services.ingestion import PublishFailed, StoreFailed

# --- Kafka ------------------------------------------------------------------------------------


class FakeFuture:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.timeouts: list[float] = []

    def get(self, timeout: float):
        self.timeouts.append(timeout)
        if self.error:
            raise self.error
        return "metadata"


class FakeProducer:
    created: list["FakeProducer"] = []

    def __init__(self, **config) -> None:
        self.config = config
        self.sent: list[tuple[str, bytes | None, bytes]] = []
        self.future = FakeFuture()
        self.closed_with: float | None = None
        FakeProducer.created.append(self)

    def send(self, topic, key=None, value=None):
        self.sent.append((topic, key, value))
        return self.future

    def close(self, timeout):
        self.closed_with = timeout


@pytest.fixture(autouse=True)
def reset_producers():
    FakeProducer.created = []


def publisher(servers="kafka:9092", **kwargs) -> KafkaEventPublisher:
    return KafkaEventPublisher(servers, producer_factory=FakeProducer, **kwargs)


def test_a_message_is_sent_with_its_key_as_bytes_and_the_broker_acknowledgement_is_awaited():
    kafka = publisher(timeout_s=7)
    kafka.publish("iot.raw", "INT_01", b"{}")
    producer = FakeProducer.created[0]
    assert producer.sent == [("iot.raw", b"INT_01", b"{}")]
    assert producer.future.timeouts == [7]


def test_a_message_without_key_is_sent_without_key():
    publisher().publish("errors.dlq", None, b"{}")
    assert FakeProducer.created[0].sent[0][1] is None


def test_the_producer_waits_for_all_replicas_and_cannot_duplicate_on_its_own_retries():
    publisher("a:9092, b:9092").publish("iot.raw", "INT_01", b"{}")
    config = FakeProducer.created[0].config
    assert config["acks"] == "all"
    assert config["enable_idempotence"] is True
    assert config["bootstrap_servers"] == ["a:9092", "b:9092"]
    assert config["client_id"] == "novaria-collecte"


def test_everything_that_could_wait_for_a_missing_broker_is_bounded_by_the_timeout():
    publisher(timeout_s=3).publish("iot.raw", "INT_01", b"{}")
    config = FakeProducer.created[0].config
    assert config["bootstrap_timeout_ms"] == 3000
    assert config["request_timeout_ms"] == 3000
    assert config["delivery_timeout_ms"] == 3000
    assert config["max_block_ms"] == 3000
    publisher(timeout_s=30).publish("iot.raw", "INT_01", b"{}")
    wide = FakeProducer.created[1].config
    assert wide["bootstrap_timeout_ms"] == wide["request_timeout_ms"] == 5000
    assert wide["delivery_timeout_ms"] == 30000


def test_the_producer_is_created_once_even_when_threads_publish_together():
    kafka = publisher()
    threads = [
        threading.Thread(target=kafka.publish, args=("iot.raw", "INT_01", b"{}")) for _ in range(20)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(FakeProducer.created) == 1
    assert len(FakeProducer.created[0].sent) == 20


def test_nothing_is_connected_until_the_first_publication():
    publisher()
    assert FakeProducer.created == []


@pytest.mark.parametrize("error", [KafkaTimeoutError("x"), KafkaConnectionError("x")])
def test_a_broker_that_does_not_acknowledge_is_a_publish_failure_naming_only_the_error_type(error):
    kafka = publisher()
    kafka.publish("iot.raw", "INT_01", b"{}")
    FakeProducer.created[0].future = FakeFuture(error)
    with pytest.raises(PublishFailed) as raised:
        kafka.publish("iot.raw", "INT_01", b"{}")
    assert str(raised.value) == type(error).__name__


def test_a_broker_down_at_start_fails_the_publication_and_the_next_one_tries_again():
    attempts = []

    def factory(**config):
        attempts.append(config)
        if len(attempts) == 1:
            raise KafkaConnectionError("tous les courtiers sont injoignables")
        return FakeProducer(**config)

    kafka = KafkaEventPublisher("kafka:9092", producer_factory=factory)
    with pytest.raises(PublishFailed):
        kafka.publish("iot.raw", "INT_01", b"{}")
    kafka.publish("iot.raw", "INT_01", b"{}")
    assert len(attempts) == 2
    assert FakeProducer.created[0].sent


def test_without_a_configured_address_the_publication_fails_without_trying_to_connect():
    kafka = publisher("")
    with pytest.raises(PublishFailed, match="KAFKA_BOOTSTRAP_SERVERS"):
        kafka.publish("iot.raw", "INT_01", b"{}")
    assert FakeProducer.created == []


def test_closing_flushes_the_producer_and_a_second_close_does_nothing():
    kafka = publisher(timeout_s=4)
    kafka.publish("iot.raw", "INT_01", b"{}")
    kafka.close()
    assert FakeProducer.created[0].closed_with == 4
    kafka.close()
    publisher().close()  # jamais utilisé : rien à fermer


def test_a_publisher_closed_can_publish_again_with_a_new_producer():
    kafka = publisher()
    kafka.publish("iot.raw", "INT_01", b"{}")
    kafka.close()
    kafka.publish("iot.raw", "INT_01", b"{}")
    assert len(FakeProducer.created) == 2


# --- MongoDB ----------------------------------------------------------------------------------


class FakeCollection:
    def __init__(self) -> None:
        self.documents: list[dict] = []
        self.find_result: dict | None = None
        self.error: Exception | None = None
        self.errors_once: list[Exception] = []
        self.queries: list[tuple] = []

    def find_one(self, query, projection=None):
        self.queries.append((query, projection))
        if self.error:
            raise self.error
        return self.find_result

    def insert_one(self, document):
        if self.errors_once:
            raise self.errors_once.pop(0)
        if self.error:
            raise self.error
        self.documents.append(document)


class FakeClient:
    instances: list["FakeClient"] = []

    def __init__(self, url, **options) -> None:
        self.url, self.options = url, options
        self.collections: dict[str, FakeCollection] = {}
        self.closed = False
        FakeClient.instances.append(self)

    def __getitem__(self, database):
        return self

    def __getattr__(self, name):
        raise AttributeError(name)

    def get(self, name):
        return self.collections.setdefault(name, FakeCollection())

    def close(self):
        self.closed = True


class Database:
    def __init__(self, client: FakeClient) -> None:
        self.client = client

    def __getitem__(self, name):
        return self.client.get(name)


FakeClient.__getitem__ = lambda self, database: Database(self)  # type: ignore[method-assign]


@pytest.fixture(autouse=True)
def reset_clients():
    FakeClient.instances = []


def collections() -> MongoCollections:
    return MongoCollections(
        "mongodb://u:p@h/db", "novaria", timeout_ms=1500, client_factory=FakeClient
    )


def test_the_connection_is_opened_on_first_use_with_short_timeouts_and_an_application_name():
    mongo = collections()
    assert FakeClient.instances == []
    mongo.collection("raw_events")
    mongo.collection("rejects")
    (client,) = FakeClient.instances
    assert client.options["serverSelectionTimeoutMS"] == 1500
    assert client.options["connectTimeoutMS"] == 1500
    assert client.options["appname"] == "novaria-collecte"


def test_the_client_is_shared_between_threads():
    mongo = collections()
    threads = [threading.Thread(target=mongo.collection, args=("raw_events",)) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(FakeClient.instances) == 1


def test_closing_closes_the_client_once():
    mongo = collections()
    mongo.close()
    mongo.collection("raw_events")
    mongo.close()
    mongo.close()
    assert FakeClient.instances[0].closed


def test_an_id_is_found_by_the_unique_key_and_only_the_key_is_read():
    mongo = collections()
    store = MongoRawEvents(mongo)
    collection = mongo.collection("raw_events")
    assert store.exists("a") is False
    collection.find_result = {"_id": 1}
    assert store.exists("a") is True
    assert collection.queries[0] == ({"id": "a"}, {"_id": 1})


def test_a_new_document_is_stored_and_a_second_one_with_the_same_id_is_reported_not_raised():
    mongo = collections()
    store = MongoRawEvents(mongo)
    assert store.insert({"id": "a"}) is True
    mongo.collection("raw_events").errors_once = [DuplicateKeyError("E11000")]
    assert store.insert({"id": "a"}) is False


@pytest.mark.parametrize("error", [ServerSelectionTimeoutError("injoignable"), PyMongoError("x")])
def test_a_database_that_does_not_answer_is_a_store_failure(error):
    mongo = collections()
    store = MongoRawEvents(mongo)
    mongo.collection("raw_events").error = error
    with pytest.raises(StoreFailed) as read:
        store.exists("a")
    with pytest.raises(StoreFailed) as written:
        store.insert({"id": "a"})
    assert str(read.value) == str(written.value) == type(error).__name__


def test_a_rejection_is_archived_as_received():
    mongo = collections()
    MongoRejects(mongo).insert({"reason": "x", "original_payload": {"a": 1}})
    assert mongo.collection("rejects").documents == [{"reason": "x", "original_payload": {"a": 1}}]


@pytest.mark.parametrize(
    "refusal", [InvalidDocument("clé avec octet nul"), WriteError("validation")]
)
def test_a_payload_that_bson_refuses_is_archived_as_json_text_instead_of_being_lost(refusal):
    mongo = collections()
    mongo.collection("rejects").errors_once = [refusal]
    MongoRejects(mongo).insert({"reason": "x", "original_payload": {"a\x00b": [1, {"c": None}]}})
    (document,) = mongo.collection("rejects").documents
    assert document["original_payload"] == '{"a\\u0000b": [1, {"c": null}]}'


def test_a_text_payload_stays_text_in_the_fallback():
    mongo = collections()
    mongo.collection("rejects").errors_once = [InvalidDocument("x")]
    MongoRejects(mongo).insert({"reason": "x", "original_payload": "déjà du texte"})
    assert mongo.collection("rejects").documents[0]["original_payload"] == "déjà du texte"


def test_an_archive_that_cannot_be_written_is_a_store_failure():
    mongo = collections()
    mongo.collection("rejects").error = ServerSelectionTimeoutError("x")
    with pytest.raises(StoreFailed):
        MongoRejects(mongo).insert({"reason": "x", "original_payload": {}})


# --- Amorçage suspendu : la limite est ferme ---------------------------------------------------


class SlowFactory:
    """Un `KafkaProducer` dont la création reste suspendue tant qu'on ne la libère pas."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.started = threading.Event()
        self.calls = 0

    def __call__(self, **config):
        self.calls += 1
        self.started.set()
        self.release.wait(timeout=30)
        return FakeProducer(**config)


def test_a_creation_that_hangs_fails_the_publication_at_the_deadline_not_later():
    import time

    factory = SlowFactory()
    kafka = KafkaEventPublisher("kafka:9092", timeout_s=0.3, producer_factory=factory)
    started = time.monotonic()
    with pytest.raises(PublishFailed, match="amorçage"):
        kafka.publish("iot.raw", "INT_01", b"{}")
    assert time.monotonic() - started < 2, "l'appelant n'attend pas la fin de la création"
    factory.release.set()


def test_the_next_attempt_reuses_the_creation_in_progress_instead_of_starting_another():
    factory = SlowFactory()
    kafka = KafkaEventPublisher("kafka:9092", timeout_s=0.2, producer_factory=factory)
    for _ in range(3):
        with pytest.raises(PublishFailed):
            kafka.publish("iot.raw", "INT_01", b"{}")
    assert factory.calls == 1, "une seule création, quel que soit le nombre de tentatives"
    factory.release.set()
    kafka2 = kafka
    for _ in range(50):  # la création se termine en arrière-plan
        try:
            kafka2.publish("iot.raw", "INT_01", b"{}")
            break
        except PublishFailed:
            continue
    assert factory.calls == 1
    assert len(FakeProducer.created) == 1
    assert FakeProducer.created[0].sent


def test_closing_while_a_creation_is_pending_closes_the_producer_when_it_arrives():
    factory = SlowFactory()
    kafka = KafkaEventPublisher("kafka:9092", timeout_s=0.2, producer_factory=factory)
    with pytest.raises(PublishFailed):
        kafka.publish("iot.raw", "INT_01", b"{}")
    kafka.close()
    factory.release.set()
    deadline = 50
    while deadline and not (FakeProducer.created and FakeProducer.created[0].closed_with):
        threading.Event().wait(0.05)
        deadline -= 1
    assert FakeProducer.created[0].closed_with == 1


def test_requests_arriving_during_a_creation_share_it_and_none_waits_longer_than_the_deadline():
    import time

    factory = SlowFactory()
    kafka = KafkaEventPublisher("kafka:9092", timeout_s=0.3, producer_factory=factory)
    outcomes: list[str] = []

    def publish() -> None:
        started = time.monotonic()
        try:
            kafka.publish("iot.raw", "INT_01", b"{}")
            outcomes.append("ok")
        except PublishFailed:
            outcomes.append(f"échec en {time.monotonic() - started:.1f}s")

    threads = [threading.Thread(target=publish) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert factory.calls == 1, "une seule tentative d'amorçage pour 20 requêtes"
    assert all(outcome.startswith("échec en 0.") for outcome in outcomes), outcomes
    factory.release.set()


def test_a_failed_creation_is_forgotten_so_the_next_publication_tries_again():
    calls = []

    def flaky(**config):
        calls.append(1)
        if len(calls) == 1:
            raise KafkaConnectionError("refusée")
        return FakeProducer(**config)

    kafka = KafkaEventPublisher("kafka:9092", producer_factory=flaky)
    with pytest.raises(PublishFailed, match="KafkaConnectionError"):
        kafka.publish("iot.raw", "INT_01", b"{}")
    kafka.publish("iot.raw", "INT_01", b"{}")
    assert len(calls) == 2


def test_a_configuration_error_in_the_factory_is_not_hidden_as_a_broker_failure():
    def broken(**config):
        raise ValueError("Unrecognized configs: {'x': 1}")

    kafka = KafkaEventPublisher("kafka:9092", producer_factory=broken)
    with pytest.raises(ValueError, match="Unrecognized"):
        kafka.publish("iot.raw", "INT_01", b"{}")
