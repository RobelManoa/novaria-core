"""Adaptateurs Kafka avec un faux producteur et un faux consommateur (broker réel : intégration)."""

from types import SimpleNamespace

import pytest
from kafka.errors import KafkaError, KafkaTimeoutError
from kafka.structs import OffsetAndMetadata, TopicPartition

from app.flux.adapters.kafka_io import KafkaPublisher, KafkaSource
from app.flux.ports import PublishFailed


class FakeFuture:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error

    def get(self, timeout=None):
        if self._error:
            raise self._error
        return "ok"


class FakeProducer:
    def __init__(self, **options) -> None:
        self.options = options
        self.sent: list[tuple[str, bytes | None, bytes]] = []
        self.flushed = 0
        self.closed = False
        self.next_error: Exception | None = None

    def send(self, topic, key=None, value=None):
        self.sent.append((topic, key, value))
        return FakeFuture(self.next_error)

    def flush(self, timeout=None):
        self.flushed += 1

    def close(self, timeout=None):
        self.closed = True


def publisher(**kw):
    made = []

    def factory(**options):
        made.append(FakeProducer(**options))
        return made[0]

    return KafkaPublisher("kafka:9092, autre:9092", producer_factory=factory, **kw), made


def test_le_producteur_attend_les_accuses_et_est_idempotent():
    pub, made = publisher()

    pub.publish("traffic.indicators", "INT_01", b"{}")
    pub.publish("errors.dlq", None, b"{}")
    assert made[0].flushed == 0  # l'envoi part en lot, sans attendre message par message
    pub.flush()

    options = made[0].options
    assert options["acks"] == "all" and options["enable_idempotence"] is True
    assert options["bootstrap_servers"] == ["kafka:9092", "autre:9092"]
    assert made[0].sent == [
        ("traffic.indicators", b"INT_01", b"{}"),
        ("errors.dlq", None, b"{}"),
    ]
    assert made[0].flushed == 1
    pub.flush()  # rien à attendre
    assert made[0].flushed == 1
    pub.close()
    assert made[0].closed


def test_les_delais_du_producteur_respectent_la_regle_de_kafka_python():
    """Défaut trouvé à l'intégration : livraison 10 000 ms, 10 020 ms exigés (linger + requête)."""
    for timeout_s in (10.0, 3.0, 30.0):
        pub, made = publisher(timeout_s=timeout_s)
        pub.publish("t", None, b"{}")
        options = made[0].options
        assert options["delivery_timeout_ms"] > options["linger_ms"] + options["request_timeout_ms"]


def test_un_accuse_en_echec_leve_publish_failed():
    pub, made = publisher()
    pub.publish("traffic.indicators", "INT_01", b"{}")
    made[0].next_error = None
    pub._pending[0] = ("traffic.indicators", FakeFuture(KafkaTimeoutError("délai")))

    with pytest.raises(PublishFailed, match="KafkaTimeoutError"):
        pub.flush()


def test_un_envoi_refuse_leve_publish_failed():
    pub, made = publisher()
    pub.publish("traffic.indicators", "INT_01", b"{}")

    def refuse(*args, **kwargs):
        raise KafkaError("refusé")

    made[0].send = refuse
    with pytest.raises(PublishFailed):
        pub.publish("traffic.indicators", "INT_01", b"{}")


def test_sans_adresse_du_broker_la_publication_echoue():
    with pytest.raises(PublishFailed, match="KAFKA_BOOTSTRAP_SERVERS"):
        KafkaPublisher("  ").publish("t", None, b"{}")


def test_un_amorcage_en_echec_leve_publish_failed():
    def broken(**options):
        raise KafkaError("pas de broker")

    with pytest.raises(PublishFailed):
        KafkaPublisher("kafka:9092", producer_factory=broken).publish("t", None, b"{}")


def test_trop_de_messages_en_attente_declenche_l_attente_des_accuses(monkeypatch):
    monkeypatch.setattr("app.flux.adapters.kafka_io.MAX_PENDING", 3)
    pub, made = publisher()

    for index in range(3):
        pub.publish("t", None, str(index).encode())

    assert made[0].flushed == 1 and pub._pending == []


class FakeConsumer:
    def __init__(self, topic, **options) -> None:
        self.topic, self.options = topic, options
        self.batches: list[dict] = []
        self.committed: dict | None = None
        self.polled: dict | None = None
        self.closed = False

    def poll(self, timeout_ms=0, max_records=None):
        self.polled = {"timeout_ms": timeout_ms, "max_records": max_records}
        return self.batches.pop(0) if self.batches else {}

    def commit(self, offsets=None):
        self.committed = offsets

    def close(self):
        self.closed = True


def record(partition, offset, key=b"INT_01", value=b"{}"):
    return SimpleNamespace(partition=partition, offset=offset, key=key, value=value)


def source():
    made = []

    def factory(topic, **options):
        made.append(FakeConsumer(topic, **options))
        return made[0]

    return KafkaSource(
        "kafka:9092", "iot.raw", "traitement-flux", max_records=50, consumer_factory=factory
    ), made


def test_le_consommateur_valide_a_la_main_dans_un_groupe_et_lit_depuis_le_debut():
    _, made = source()

    options = made[0].options
    assert made[0].topic == "iot.raw"
    assert options["group_id"] == "traitement-flux"
    assert options["enable_auto_commit"] is False
    assert options["auto_offset_reset"] == "earliest"


def test_la_lecture_rend_les_messages_par_partition_et_offset():
    src, made = source()
    tp = lambda p: TopicPartition("iot.raw", p)  # noqa: E731
    made[0].batches = [{tp(1): [record(1, 7), record(1, 8)], tp(0): [record(0, 3, value=None)]}]

    records = src.poll(250)

    assert [(r.partition, r.offset) for r in records] == [(0, 3), (1, 7), (1, 8)]
    assert records[0].value == b""  # un message sans valeur est lu comme vide, donc refusé en aval
    assert made[0].polled == {"timeout_ms": 250, "max_records": 50}


def test_la_validation_envoie_le_prochain_offset_de_chaque_partition():
    src, made = source()

    src.commit({0: 10, 2: 4})

    assert made[0].committed == {
        TopicPartition("iot.raw", 0): OffsetAndMetadata(10, "", -1),
        TopicPartition("iot.raw", 2): OffsetAndMetadata(4, "", -1),
    }


def test_rien_a_valider_ne_touche_pas_le_broker():
    src, made = source()

    src.commit({})

    assert made[0].committed is None
    src.close()
    assert made[0].closed
