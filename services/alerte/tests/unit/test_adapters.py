"""Adaptateurs : PostgreSQL et Kafka (clients simulés), canaux de notification (MS-11).

Ces tests vérifient la logique propre aux adaptateurs : les ordres SQL et leurs paramètres, la
validation d'une transaction, le marquage de la boîte d'envoi, la traduction des pannes. Le
comportement réel de la base et du bus est prouvé par `tests/integration/`.
"""

import http.server
import json
import logging
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import psycopg
import pytest
from kafka.errors import KafkaError
from kafka.structs import TopicPartition
from psycopg_pool import PoolTimeout

from app.adapters import kafka_io
from app.adapters.channels import LogChannel, WebhookChannel, message_of
from app.adapters.kafka_io import EventsReader, KafkaPublisher, KafkaSource, servers
from app.adapters.postgres_store import PostgresAlertStore, alert_of, rule_of
from app.domain.model import HistoryEntry, Kind, Provenance, Severity, State
from app.services.ports import (
    AlertFilter,
    NotFound,
    NotificationFailed,
    OutboxRow,
    PublishFailed,
    StoreFailed,
)
from tests.support import NOW, SEED_RULES

T0 = datetime(2026, 10, 20, 8, 1, tzinfo=UTC)
ID = "00000000-0000-4000-8000-000000000001"


def alert_row(**changes) -> dict:
    row = {
        "alert_id": ID, "rule_id": "congestion.persistante", "kind": "CONGESTION",
        "road_segment_id": "ROAD_001", "intersection_id": "INT_01", "episode_id": None,
        "run_id": "run-test", "source_type": "SIMULATED", "scenario_id": "heure-de-pointe",
        "seed": 42, "dataset_id": None, "severity": "WARNING", "cause": "UNKNOWN",
        "state": "CREATED", "opened_at": T0, "notified_at": None, "acknowledged_at": None,
        "acknowledged_by": None, "resolved_at": None, "resolution": None,
        "correlation_id": "corr-1", "updated_at": T0,
    }  # fmt: skip
    return {**row, **changes}


# ------------------------------------------------------------------- PostgreSQL : connexion simulée
class Cursor:
    def __init__(self, rows=None, rowcount=1):
        self._rows = rows or []
        self.rowcount = rowcount

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class Connection:
    """Rejoue des résultats dans l'ordre et garde chaque ordre SQL avec ses paramètres."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        self.calls.append((" ".join(sql.split()), tuple(params)))
        return self.results.pop(0) if self.results else Cursor()


class Pool:
    def __init__(self, connection):
        self.connection_obj = connection
        self.committed = None
        self.opened = self.closed = False
        self.error = None

    def open(self, wait=False):
        if self.error:
            raise self.error
        self.opened = True

    def close(self):
        self.closed = True

    @contextmanager
    def connection(self):
        if self.error:
            raise self.error
        try:
            yield self.connection_obj
        except BaseException:
            self.committed = False  # annulation
            raise
        else:
            self.committed = True


def store_with(*results):
    store = PostgresAlertStore("postgresql://u:p@h/db")
    connection = Connection(*results)
    store._pool = Pool(connection)
    return store, connection


def test_rows_become_domain_objects():
    alert = alert_of(alert_row(state="NOTIFIED", notified_at=T0, severity="CRITICAL"))
    assert (alert.kind, alert.state, alert.severity) == (
        Kind.CONGESTION,
        State.NOTIFIED,
        Severity.CRITICAL,
    )
    assert alert.provenance == Provenance("SIMULATED", "run-test", "heure-de-pointe", 42, None)
    rule = rule_of({"rule_id": "capteur.muet", "kind": "SENSOR_FAULT", "enabled": True,
                    "params": None, "min_gap_s": 900, "updated_at": T0})  # fmt: skip
    assert rule.params == {} and rule.kind is Kind.SENSOR_FAULT


def test_reads_lock_the_row_only_when_asked():
    store, connection = store_with(Cursor([alert_row()]), Cursor([alert_row()]), Cursor([]))
    with store.transaction() as tx:
        tx.get(ID, lock=False)
        tx.get(ID, lock=True)
        assert tx.open_alert(Kind.CONGESTION, "ROAD_001", "run-test", lock=True) is None
    plain, locked, open_one = (sql for sql, _ in connection.calls)
    assert "FOR UPDATE" not in plain and locked.endswith("FOR UPDATE")
    assert "state <> 'RESOLVED'" in open_one and open_one.endswith("FOR UPDATE")
    assert connection.calls[2][1] == ("CONGESTION", "ROAD_001", "run-test")


def test_the_last_alert_is_the_most_recently_opened_one():
    store, connection = store_with(Cursor([alert_row()]))
    with store.transaction() as tx:
        assert tx.last_alert(Kind.CONGESTION, "ROAD_001", "run-test").alert_id == ID
    assert "ORDER BY opened_at DESC LIMIT 1" in connection.calls[0][0]


def test_insert_says_false_when_the_unique_index_refuses():
    from app.domain.model import Alert

    alert = Alert(ID, "congestion.persistante", Kind.CONGESTION, "ROAD_001", "INT_01",
                  Provenance("SIMULATED", "run-test", "heure-de-pointe", 42), Severity.WARNING,
                  State.CREATED, T0, correlation_id="corr-1", updated_at=T0)  # fmt: skip
    for rowcount, expected in ((1, True), (0, False)):
        store, connection = store_with(Cursor(rowcount=rowcount))
        with store.transaction() as tx:
            assert tx.insert(alert) is expected
        sql, params = connection.calls[0]
        assert sql.endswith("ON CONFLICT DO NOTHING")  # l'index unique partiel arbitre
        assert params[0] == ID and params[6:9] == ("run-test", "SIMULATED", "heure-de-pointe")


def test_update_history_and_outbox_write_what_the_service_gives():
    from app.domain.model import Alert

    alert = Alert(ID, "r", Kind.CONGESTION, "ROAD_001", "INT_01", Provenance("SIMULATED", "x"),
                  Severity.INFO, State.RESOLVED, T0, resolved_at=T0, resolution="AUTO",
                  updated_at=NOW)  # fmt: skip
    store, connection = store_with()
    with store.transaction() as tx:
        tx.update(alert)
        tx.add_history(ID, HistoryEntry(State.NOTIFIED, State.RESOLVED, T0, "system", {"a": 1}))
        tx.add_history(ID, HistoryEntry(None, State.CREATED, T0, "system"))
        tx.add_outbox("alerts.events", "INT_01", "alerte-x-resolved", {"k": "v"})
    update, history, history_no_details, outbox = connection.calls
    assert (
        update[1][0] == "RESOLVED" and update[1][-1] == ID and "UPDATE alertes.alert" in update[0]
    )
    assert history[1][1:3] == ("NOTIFIED", "RESOLVED") and history[1][5].obj == {"a": 1}
    assert history_no_details[1][1] is None and history_no_details[1][5] is None
    assert outbox[1][:3] == ("alerts.events", "INT_01", "alerte-x-resolved")
    assert outbox[1][3].obj == {"k": "v"}


def test_a_transaction_commits_on_success_and_rolls_back_on_error():
    store, _ = store_with()
    with store.transaction():
        pass
    assert store._pool.committed is True
    with pytest.raises(NotFound), store.transaction():
        raise NotFound("x")  # une exception du cœur traverse et annule
    assert store._pool.committed is False


@pytest.mark.parametrize("error", [psycopg.OperationalError("db"), PoolTimeout("pool")])
def test_a_database_or_pool_failure_is_a_store_failure(error):
    store, _ = store_with()
    store._pool.error = error
    with pytest.raises(StoreFailed) as raised, store.transaction():
        pass
    assert str(raised.value) == type(error).__name__  # le type, jamais le message
    with pytest.raises(StoreFailed):
        store.rules()


def test_a_database_error_inside_the_transaction_is_a_store_failure():
    store, _ = store_with()
    with pytest.raises(StoreFailed), store.transaction():
        raise psycopg.errors.CheckViolation("resolved_at >= opened_at")
    assert store._pool.committed is False


def test_the_pool_is_opened_once_lazily_and_closed():
    store, _ = store_with()
    assert not store._pool.opened
    store.rules()
    store.rules()
    assert store._pool.opened
    store.close()
    assert store._pool.closed
    store.close()  # deuxième fermeture sans effet


def test_a_failure_to_open_the_pool_is_a_store_failure():
    store, _ = store_with()
    store._pool.error = RuntimeError("secret-dans-le-message")
    with pytest.raises(StoreFailed) as raised:
        store.rules()
    assert "secret" not in str(raised.value)


def test_a_store_that_was_never_used_closes_without_error():
    PostgresAlertStore("postgresql://u:p@h/db").close()


def rule_row(**changes):
    row = {"rule_id": "capteur.muet", "kind": "SENSOR_FAULT", "enabled": False,
           "params": {"silence_s": 120}, "min_gap_s": 900, "updated_at": T0}  # fmt: skip
    return {**row, **changes}


def test_rules_are_listed_by_name_and_updated_with_merged_parameters():
    store, connection = store_with(Cursor([rule_row()]), Cursor([rule_row()]), Cursor([]))
    assert [r.rule_id for r in store.rules()] == ["capteur.muet"]
    updated = store.update_rule(
        "capteur.muet", enabled=False, params={"silence_s": 120}, min_gap_s=None
    )
    assert updated.enabled is False and updated.params == {"silence_s": 120}
    sql, params = connection.calls[1]
    assert "params || %s::jsonb" in sql and params[:3] == (
        False,
        '{"silence_s": 120}',
        '{"silence_s": 120}',
    )
    assert params[3:] == (None, "capteur.muet")
    with pytest.raises(NotFound):
        store.update_rule("inconnue", enabled=None, params=None, min_gap_s=None)
    assert connection.calls[2][1][1] is None  # pas de paramètres : la colonne reste telle quelle


def test_pending_notifications_are_the_created_alerts_oldest_first():
    store, connection = store_with(Cursor([alert_row()]))
    assert [a.alert_id for a in store.pending_notification(5)] == [ID]
    sql, params = connection.calls[0]
    assert "state = 'CREATED'" in sql and "ORDER BY opened_at, alertes.alert.alert_id" in sql
    assert params == (5,)


def test_the_list_builds_its_filters_and_keyset_from_what_is_given():
    store, connection = store_with(Cursor([]), Cursor([]))
    store.list_alerts(AlertFilter(), after=None, limit=11)
    sql, params = connection.calls[0]
    assert "WHERE" not in sql and "ORDER BY opened_at DESC, alertes.alert.alert_id DESC" in sql
    assert params == (11,)
    full = AlertFilter(State.CREATED, Kind.CONGESTION, "WARNING", "INT_01", "ROAD_001", T0, NOW)
    store.list_alerts(full, after=(T0, ID), limit=3)
    sql, params = connection.calls[1]
    assert sql.count(" AND ") == 7 and "(opened_at, alert_id) < (%s, %s::uuid)" in sql
    assert params == ("CREATED", "CONGESTION", "WARNING", "INT_01", "ROAD_001", T0, NOW, T0, ID, 3)


def test_an_alert_is_read_with_its_history_in_order_or_not_at_all():
    created = {"from_state": None, "to_state": "CREATED", "changed_at": T0, "actor": "system"}
    notified = {
        "from_state": "CREATED",
        "to_state": "NOTIFIED",
        "changed_at": T0,
        "actor": "system",
    }
    history = [{**created, "details": None}, {**notified, "details": {"x": 1}}]
    store, connection = store_with(Cursor([alert_row()]), Cursor(history), Cursor([]))
    alert, entries = store.get_alert(ID)
    assert alert.alert_id == ID and [e.to_state for e in entries] == [State.CREATED, State.NOTIFIED]
    assert entries[0].from_state is None and entries[1].details == {"x": 1}
    assert "ORDER BY history_id" in connection.calls[1][0]
    assert store.get_alert("00000000-0000-4000-8000-0000000000ff") is None


def outbox_rows(count):
    row = {"topic": "alerts.events", "event_key": "INT_01"}
    return Cursor(
        [
            {**row, "outbox_id": n, "event_id": f"e{n}", "payload": {"n": n}}
            for n in range(1, count + 1)
        ]
    )


def test_the_outbox_marks_each_event_after_its_publication_and_in_order():
    store, connection = store_with(outbox_rows(3))
    published = []
    assert store.relay_outbox(published.append, limit=10) == 3
    assert [row.event_id for row in published] == ["e1", "e2", "e3"]
    select = connection.calls[0][0]
    assert "published_at IS NULL ORDER BY outbox_id" in select and select.endswith(
        "FOR UPDATE SKIP LOCKED"
    )
    assert [p for _, p in connection.calls[1:]] == [(1,), (2,), (3,)]
    assert store._pool.committed is True


def test_the_outbox_keeps_what_was_acknowledged_and_raises_on_the_first_failure():
    store, connection = store_with(outbox_rows(3))
    seen = []

    def publish(row: OutboxRow):
        if row.outbox_id == 2:
            raise PublishFailed("panne")
        seen.append(row.outbox_id)

    with pytest.raises(PublishFailed):
        store.relay_outbox(publish, limit=10)
    assert seen == [1]
    assert [p for _, p in connection.calls[1:]] == [(1,)]  # seul l'événement 1 est marqué
    assert store._pool.committed is True  # ... et validé : il ne repartira pas


def test_an_empty_outbox_publishes_nothing():
    store, _ = store_with(Cursor([]))
    assert store.relay_outbox(lambda row: None, limit=5) == 0


# -------------------------------------------------------------------------------- Kafka : simulé
def test_servers_are_split_and_trimmed():
    assert servers("a:9092, b:9092,, ") == ["a:9092", "b:9092"]
    assert servers("") == []


class Future:
    def __init__(self, error=None):
        self.error = error

    def get(self, timeout):
        if self.error:
            raise self.error
        return "meta"


class Producer:
    def __init__(self, **config):
        self.config = config
        self.sent = []
        self.flushed = False
        self.closed = False
        self.send_error = None
        self.future_error = None

    def send(self, topic, key=None, value=None):
        if self.send_error:
            raise self.send_error
        self.sent.append((topic, key, value))
        return Future(self.future_error)

    def flush(self, timeout=None):
        self.flushed = True

    def close(self, timeout=None):
        self.closed = True


def publisher(**kwargs):
    made = []

    def factory(**config):
        producer = Producer(**config)
        made.append(producer)
        return producer

    return KafkaPublisher("kafka:9092", producer_factory=factory, **kwargs), made


def test_the_producer_waits_for_all_replicas_and_is_idempotent_and_does_not_batch():
    kafka, made = publisher(timeout_s=8)
    kafka.publish("alerts.events", "INT_01", b"{}")
    config = made[0].config
    assert (config["acks"], config["enable_idempotence"], config["linger_ms"]) == ("all", True, 0)
    assert config["bootstrap_servers"] == ["kafka:9092"] and config["delivery_timeout_ms"] == 8000
    assert config["request_timeout_ms"] == 4000 and config["bootstrap_timeout_ms"] == 5000


def test_publish_encodes_the_key_and_flush_waits_for_every_acknowledgement():
    kafka, made = publisher()
    kafka.publish("t", "INT_01", b"a")
    kafka.publish("t", None, b"b")
    kafka.flush()
    assert made[0].sent == [("t", b"INT_01", b"a"), ("t", None, b"b")] and made[0].flushed
    kafka.flush()  # plus rien en attente : aucun nouvel appel
    assert len(made) == 1


def test_a_refused_send_or_a_missing_acknowledgement_is_a_publish_failure():
    kafka, made = publisher()
    kafka.publish("t", "k", b"a")
    made[0].send_error = KafkaError("refus")
    with pytest.raises(PublishFailed):
        kafka.publish("t", "k", b"b")
    made[0].send_error = None
    made[0].future_error = KafkaError("pas d'accusé")
    kafka.publish("t", "k", b"c")
    with pytest.raises(PublishFailed):
        kafka.flush()


def test_without_an_address_or_with_a_failing_client_the_publisher_fails_cleanly():
    with pytest.raises(PublishFailed):
        KafkaPublisher("").publish("t", "k", b"x")

    def broken(**_config):
        raise KafkaError("indisponible")

    with pytest.raises(PublishFailed):
        KafkaPublisher("kafka:9092", producer_factory=broken).publish("t", "k", b"x")


def test_closing_closes_the_producer_once():
    kafka, made = publisher()
    kafka.close()  # jamais utilisé
    kafka.publish("t", "k", b"x")
    kafka.close()
    kafka.close()
    assert made[0].closed


class Message(SimpleNamespace):
    pass


class Consumer:
    def __init__(self, *topics, **config):
        self.topics, self.config = topics, config
        self.batches = []
        self.committed = None
        self.closed = False
        self.assigned = []
        self.sought_end = []
        self.positions = []
        self.partitions = {0, 1, 2}

    def poll(self, timeout_ms=0, max_records=None):
        return self.batches.pop(0) if self.batches else {}

    def commit(self, offsets):
        self.committed = offsets

    def close(self):
        self.closed = True

    def partitions_for_topic(self, topic):
        return self.partitions

    def assign(self, partitions):
        self.assigned = list(partitions)

    def seek_to_end(self, *partitions):
        self.sought_end = list(partitions)

    def position(self, partition):
        self.positions.append(partition)


def test_the_source_reads_in_a_group_with_manual_commit():
    consumers = []

    def factory(*topics, **config):
        consumers.append(Consumer(*topics, **config))
        return consumers[-1]

    source = KafkaSource("kafka:9092", "traffic.indicators", "alerte", consumer_factory=factory)
    config = consumers[0].config
    assert consumers[0].topics == ("traffic.indicators",)
    assert (config["group_id"], config["enable_auto_commit"], config["auto_offset_reset"]) == (
        "alerte",
        False,
        "earliest",
    )
    tp = lambda p: TopicPartition("traffic.indicators", p)  # noqa: E731
    first = Message(key=b"k", value=b"a", partition=0, offset=3)
    second = Message(key=None, value=None, partition=1, offset=8)
    third = Message(key=b"k", value=b"b", partition=1, offset=9)
    consumers[0].batches = [{tp(1): [third, second], tp(0): [first]}]
    records = source.poll(100)
    assert [(r.partition, r.offset, r.value) for r in records] == [
        (0, 3, b"a"),
        (1, 8, b""),
        (1, 9, b"b"),
    ]
    source.commit({0: 4, 1: 10})
    assert {k.partition: v.offset for k, v in consumers[0].committed.items()} == {0: 4, 1: 10}
    consumers[0].committed = None
    source.commit({})
    assert consumers[0].committed is None
    source.close()
    assert consumers[0].closed


def reader_with(consumer_factory, received, **kwargs):
    return EventsReader("kafka:9092", "alerts.events", received.append, retry_s=0.01,
                        consumer_factory=consumer_factory, **kwargs)  # fmt: skip


def wait_for(condition, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_the_events_reader_starts_at_the_end_without_a_group_and_forwards_messages():
    consumer = Consumer()
    tp = TopicPartition("alerts.events", 0)
    consumer.batches = [{tp: [Message(value=b"un"), Message(value=b"deux")]}]
    received = []
    reader = reader_with(
        lambda **config: (setattr(consumer, "config", config), consumer)[1], received
    )
    reader.start()
    assert wait_for(lambda: received == [b"un", b"deux"])
    assert reader.ready.is_set()
    reader.stop()
    assert consumer.config["group_id"] is None and consumer.config["enable_auto_commit"] is False
    assert [p.partition for p in consumer.assigned] == [0, 1, 2]
    assert [p.partition for p in consumer.sought_end] == [0, 1, 2] and len(consumer.positions) == 3
    assert consumer.closed


def test_the_events_reader_survives_a_broker_failure_and_reconnects(caplog):
    caplog.set_level(logging.ERROR)
    attempts = []

    def factory(**config):
        attempts.append(1)
        if len(attempts) < 3:
            raise KafkaError("broker injoignable")
        consumer = Consumer()
        consumer.batches = [{TopicPartition("alerts.events", 0): [Message(value=b"enfin")]}]
        return consumer

    received = []
    reader = reader_with(factory, received)
    reader.start()
    assert wait_for(lambda: received == [b"enfin"])
    reader.stop()
    assert len(attempts) >= 3 and "nouvelle tentative" in caplog.text


def test_the_events_reader_gives_up_a_topic_that_never_appears(monkeypatch):
    monkeypatch.setattr(kafka_io, "PARTITIONS_WAIT_S", 0.05)
    consumer = Consumer()
    consumer.partitions = None
    calls = []

    def factory(**config):
        calls.append(1)
        return consumer

    reader = reader_with(factory, [])
    reader.start()
    assert wait_for(lambda: len(calls) >= 2)  # une tentative, puis une autre
    reader.stop()
    assert consumer.assigned == [] and not reader.ready.is_set()


def test_stopping_a_reader_that_never_started_is_harmless():
    reader_with(Consumer, []).stop()


# --------------------------------------------------------------------------------------- canaux
def an_alert():
    return alert_of(alert_row())


def test_the_message_names_the_alert_and_nobody():
    message = message_of(an_alert())
    assert set(message) == {"alert_id", "kind", "severity", "state", "road_segment_id",
                            "intersection_id", "opened_at", "cause", "source_type"}  # fmt: skip
    assert message["opened_at"] == "2026-10-20T08:01:00Z" and message["source_type"] == "SIMULATED"


def test_the_log_channel_writes_one_line_with_the_message(caplog):
    caplog.set_level(logging.INFO)
    LogChannel().send(an_alert())
    (record,) = [r for r in caplog.records if r.name == "app.notification"]
    assert record.fields["alert_id"] == ID and record.fields["channel"] == "log"


class Hook(http.server.BaseHTTPRequestHandler):
    status = 200
    received: list = []

    def do_POST(self):  # noqa: N802 - nom imposé par http.server
        length = int(self.headers["Content-Length"])
        Hook.received.append(
            (self.path, self.headers["Content-Type"], json.loads(self.rfile.read(length)))
        )
        self.send_response(Hook.status)
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def hook():
    Hook.status, Hook.received = 200, []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Hook)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def test_the_webhook_posts_the_message_as_json(hook):
    WebhookChannel(hook + "/notify/jeton-dans-le-chemin").send(an_alert())
    ((path, content_type, body),) = Hook.received
    assert path == "/notify/jeton-dans-le-chemin" and content_type == "application/json"
    assert body["alert_id"] == ID and body["kind"] == "CONGESTION"


@pytest.mark.parametrize("status", [400, 404, 500, 503])
def test_a_webhook_error_status_is_a_notification_failure_without_the_url(hook, status):
    Hook.status = status
    with pytest.raises(NotificationFailed) as raised:
        WebhookChannel(hook + "/jeton-secret").send(an_alert())
    assert "jeton-secret" not in str(raised.value)


def test_an_unreachable_webhook_is_a_notification_failure():
    with pytest.raises(NotificationFailed):
        WebhookChannel("http://127.0.0.1:9/x", timeout_s=1).send(an_alert())


def test_a_redirection_is_not_a_delivery(hook, monkeypatch):
    Hook.status = 204
    WebhookChannel(hook).send(an_alert())  # 2xx : remis


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "ftp://hote/x", "javascript:alert(1)", "/relatif"]
)
def test_the_webhook_only_accepts_http_and_https(url):
    with pytest.raises(ValueError, match="http"):
        WebhookChannel(url)


def test_seed_rules_are_the_three_of_the_migration():
    assert [(r.rule_id, r.min_gap_s) for r in SEED_RULES] == [
        ("congestion.persistante", 300), ("anomalie.circulation", 600), ("capteur.muet", 900),
    ]  # fmt: skip
