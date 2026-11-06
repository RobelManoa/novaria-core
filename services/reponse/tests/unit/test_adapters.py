"""Adaptateurs Kafka et MongoDB, sur des faux clients (les vrais : tests d'intégration)."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from bson import ObjectId
from kafka.errors import KafkaError
from pymongo.errors import PyMongoError

from app.adapters.kafka_io import KafkaPublisher, KafkaSource, NoPartitionsAssigned, servers
from app.adapters.mongo_audit import (
    COMMAND_ACTIONS,
    InvalidCursor,
    MongoAuditLog,
    decode_cursor,
    encode_cursor,
)
from app.services.ports import AuditFailed, PublishFailed


# =========================================================================== MongoDB
class FakeCursor:
    def __init__(self, docs):
        self.docs = docs
        self.sorted_by = None
        self.max = None

    def sort(self, keys):
        self.sorted_by = keys
        return self

    def limit(self, n):
        self.max = n
        return self

    def __iter__(self):
        return iter(self.docs[: self.max])


class FakeCollection:
    def __init__(self):
        self.docs: list[dict] = []
        self.inserted: list[dict] = []
        self.queries: list[dict] = []
        self.error: Exception | None = None
        self.last_cursor: FakeCursor | None = None

    def insert_one(self, doc):
        if self.error:
            raise self.error
        doc["_id"] = ObjectId()  # comme pymongo, qui ajoute `_id` au document reçu
        self.inserted.append(doc)

    def find(self, query):
        if self.error:
            raise self.error
        self.queries.append(query)
        self.last_cursor = FakeCursor(list(self.docs))
        return self.last_cursor


class FakeClient:
    def __init__(self, url, **options):
        self.url, self.options = url, options
        self.collection = FakeCollection()
        self.closed = False

    def get_default_database(self):
        return {"audit_logs": self.collection}

    def close(self):
        self.closed = True


def audit_log(**kwargs) -> tuple[MongoAuditLog, FakeClient]:
    clients = []

    def factory(url, **options):
        clients.append(FakeClient(url, **options))
        return clients[0]

    return MongoAuditLog(
        "mongodb://svc:motdepasse-d-essai@mongo/db", client_factory=factory, **kwargs
    ), clients[0]


def test_the_client_is_configured_with_short_timeouts_and_utc_dates():
    log, client = audit_log(timeout_ms=1500)
    assert client.options["tz_aware"] is True
    assert (
        client.options["serverSelectionTimeoutMS"] == 1500
        and client.options["socketTimeoutMS"] == 1500
    )
    log.close()
    assert client.closed


def test_an_entry_is_inserted_as_a_copy_so_the_caller_keeps_its_own():
    log, client = audit_log()
    entry = {
        "ts": datetime.now(UTC),
        "service": "reponse",
        "actor": "u",
        "action": "a",
        "outcome": "ok",
    }
    log.record(entry)
    assert "_id" not in entry and "_id" in client.collection.inserted[0]


def test_a_mongo_error_becomes_audit_failed_without_the_message_of_the_driver():
    log, client = audit_log()
    client.collection.error = PyMongoError("mongodb://svc:motdepasse-d-essai@mongo : refus")
    with pytest.raises(AuditFailed) as failure:
        log.record({"ts": datetime.now(UTC)})
    assert "motdepasse" not in str(failure.value) and "PyMongoError" in str(failure.value)
    with pytest.raises(AuditFailed):
        log.history("INT_01", 5, None)


def doc(minutes: int, key: int) -> dict:
    return {
        "_id": ObjectId.from_datetime(datetime(2026, 10, 20, 8, minutes, tzinfo=UTC)),
        "ts": datetime(2026, 10, 20, 8, minutes, tzinfo=UTC),
    }


def test_the_history_reads_only_the_commands_of_this_service_and_this_intersection():
    log, client = audit_log()
    log.history("INT_03", 5, None)
    [query] = client.collection.queries
    assert query == {
        "service": "reponse",
        "action": {"$in": COMMAND_ACTIONS},
        "details.intersection_id": "INT_03",
    }
    assert client.collection.last_cursor.sorted_by == [("ts", -1), ("_id", -1)]


def test_the_history_asks_one_more_than_the_page_to_know_whether_another_follows():
    log, client = audit_log()
    client.collection.docs = [doc(m, m) for m in (9, 8, 7)]
    page, cursor = log.history("INT_01", 2, None)
    assert len(page) == 2 and cursor is not None and client.collection.last_cursor.max == 3
    page, cursor = log.history("INT_01", 3, None)
    assert len(page) == 3 and cursor is None


def test_the_cursor_resumes_strictly_after_the_last_entry_of_the_page():
    log, client = audit_log()
    client.collection.docs = [doc(m, m) for m in (9, 8, 7)]
    _, cursor = log.history("INT_01", 2, None)
    log.history("INT_01", 2, cursor)
    resumed = client.collection.queries[-1]["$or"]
    last_ts = datetime(2026, 10, 20, 8, 8, tzinfo=UTC)
    assert resumed[0] == {"ts": {"$lt": last_ts}}
    assert resumed[1]["ts"] == last_ts and "$lt" in resumed[1]["_id"]


@pytest.mark.parametrize(
    "cursor", ["", "!!!", "e30", "bm90LWpzb24", "W10", "eyJ0cyI6MSwiaWQiOiJ6eiJ9"]
)
def test_a_cursor_that_this_service_did_not_issue_is_refused(cursor):
    with pytest.raises(InvalidCursor):
        decode_cursor(cursor)


def test_cursor_round_trip():
    entry = doc(5, 5)
    stamp, last = decode_cursor(encode_cursor(entry))
    assert (stamp, last) == (entry["ts"], entry["_id"])


# =========================================================================== Kafka : publication
class FakeFuture:
    def __init__(self, error=None):
        self.error = error

    def get(self, timeout=None):
        if self.error:
            raise self.error


class FakeProducer:
    def __init__(self, **options):
        self.options = options
        self.sent = []
        self.flushed = 0
        self.send_error: Exception | None = None
        self.flush_error: Exception | None = None
        self.future_error: Exception | None = None
        self.closed = False

    def send(self, topic, key=None, value=None):
        if self.send_error:
            raise self.send_error
        self.sent.append((topic, key, value))
        return FakeFuture(self.future_error)

    def flush(self, timeout=None):
        self.flushed += 1
        if self.flush_error:
            raise self.flush_error

    def close(self, timeout=None):
        self.closed = True


def publisher(**kwargs):
    producers = []

    def factory(**options):
        producers.append(FakeProducer(**options))
        return producers[0]

    return KafkaPublisher("kafka:9092, ,kafka2:9092", producer_factory=factory, **kwargs), producers


def test_servers_are_split_and_trimmed():
    assert servers("a:1, b:2 ,,") == ["a:1", "b:2"]


def test_the_producer_waits_for_all_replicas_and_is_idempotent():
    pub, producers = publisher(timeout_s=4.0)
    pub.publish("signal.status", "INT_01", b"{}")
    options = producers[0].options
    assert options["acks"] == "all" and options["enable_idempotence"] is True
    assert options["bootstrap_servers"] == ["kafka:9092", "kafka2:9092"]
    assert options["delivery_timeout_ms"] == 4000 and options["linger_ms"] == 0


def test_publish_then_flush_waits_for_the_acknowledgement_of_each_message():
    pub, producers = publisher()
    pub.publish("signal.status", "INT_01", b"a")
    pub.publish("signal.status", None, b"b")
    pub.flush()
    assert producers[0].sent == [("signal.status", b"INT_01", b"a"), ("signal.status", None, b"b")]
    assert producers[0].flushed == 1
    pub.flush()  # rien en attente : pas de second aller-retour
    assert producers[0].flushed == 1


@pytest.mark.parametrize("where", ["send_error", "flush_error", "future_error"])
def test_a_missing_acknowledgement_is_a_publish_failure(where):
    pub, producers = publisher()
    pub.publish("signal.status", "INT_01", b"a")  # crée le producteur
    pub.flush()
    setattr(producers[0], where, KafkaError())
    with pytest.raises(PublishFailed):
        pub.publish("signal.status", "INT_01", b"b")
        pub.flush()


def test_without_a_broker_address_nothing_is_published():
    pub = KafkaPublisher("")
    with pytest.raises(PublishFailed):
        pub.publish("signal.status", None, b"x")


def test_a_producer_that_cannot_connect_is_a_publish_failure():
    def broken(**_options):
        raise KafkaError()

    with pytest.raises(PublishFailed):
        KafkaPublisher("kafka:9092", producer_factory=broken).publish("t", None, b"x")


def test_close_releases_the_producer_once():
    pub, producers = publisher()
    pub.publish("t", None, b"x")
    pub.close()
    pub.close()
    assert producers[0].closed


# =========================================================================== Kafka : lecture
class FakeConsumer:
    def __init__(self, *topics, **options):
        self.topics, self.options = topics, options
        self.metadata_requested = []
        self.assigned = {1}
        self.batches = []
        self.committed = None
        self.closed = False

    def partitions_for_topic(self, topic):
        self.metadata_requested.append(topic)
        return {0, 1, 2}

    def assignment(self):
        return self.assigned

    def poll(self, timeout_ms=0, max_records=None):
        return self.batches.pop(0) if self.batches else {}

    def commit(self, offsets):
        self.committed = offsets

    def close(self):
        self.closed = True


def source(consumer_holder=None, **kwargs):
    holder = consumer_holder if consumer_holder is not None else []

    def factory(*topics, **options):
        holder.append(FakeConsumer(*topics, **options))
        return holder[0]

    return KafkaSource(
        "kafka:9092", "traffic.recommendations", "reponse", consumer_factory=factory, **kwargs
    ), holder


def test_the_group_reads_manually_committed_offsets_from_the_start_after_loading_the_metadata():
    src, holder = source()
    consumer = holder[0]
    assert consumer.options["enable_auto_commit"] is False
    assert (
        consumer.options["auto_offset_reset"] == "earliest"
        and consumer.options["group_id"] == "reponse"
    )
    assert consumer.metadata_requested == ["traffic.recommendations"]  # avant toute jointure
    src.close()
    assert consumer.closed


def test_records_come_back_ordered_by_partition_and_offset():
    src, holder = source()
    message = lambda p, o, v: SimpleNamespace(key=b"k", value=v, partition=p, offset=o)  # noqa: E731
    holder[0].batches = [{"x": [message(1, 5, b"b"), message(0, 9, b"a"), message(0, 2, None)]}]
    got = src.poll(10)
    assert [(r.partition, r.offset, r.value) for r in got] == [
        (0, 2, b""),
        (0, 9, b"a"),
        (1, 5, b"b"),
    ]


def test_commit_gives_the_next_offset_per_partition_and_skips_empty_commits():
    src, holder = source()
    src.commit({})
    assert holder[0].committed is None
    src.commit({0: 8, 2: 3})
    assert sorted((tp.partition, om.offset) for tp, om in holder[0].committed.items()) == [
        (0, 8),
        (2, 3),
    ]


def test_a_group_left_without_partitions_is_detected_instead_of_staying_silent():
    clock = {"now": 0.0}
    src, holder = source(unassigned_limit_s=30, monotonic=lambda: clock["now"])
    holder[0].assigned = set()
    src.poll()  # le chronomètre démarre
    clock["now"] = 29
    src.poll()
    clock["now"] = 31
    with pytest.raises(NoPartitionsAssigned):
        src.poll()


def test_receiving_partitions_resets_the_watchdog():
    clock = {"now": 0.0}
    src, holder = source(unassigned_limit_s=30, monotonic=lambda: clock["now"])
    holder[0].assigned = set()
    src.poll()
    clock["now"] = 25
    holder[0].assigned = {0}
    src.poll()
    holder[0].assigned = set()
    clock["now"] = 50
    src.poll()  # le décompte repart de 50, pas de 0
    clock["now"] = 70
    src.poll()
