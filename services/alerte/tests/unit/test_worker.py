"""Notification simulée, relais de la boîte d'envoi et boucle du travailleur (MS-11)."""

import threading

import pytest

from app.adapters.kafka_io import Record
from app.domain.model import State
from app.services.ports import NotificationFailed, PublishFailed, StoreFailed
from app.worker.runner import RulesCache, beat, run
from tests.support import FakePublisher, FakeStore, body, congested, indicator


# ----------------------------------------------------------------------------------- notifier
def test_every_created_alert_is_delivered_once_then_notified(rig):
    rig.feed(congested(0), congested(0, segment="ROAD_002"))
    assert rig.notifier.run_once() == 2
    assert len(rig.channel.delivered) == 2
    assert rig.notifier.run_once() == 0  # plus rien en attente : pas de seconde remise
    assert len(rig.channel.delivered) == 2
    assert {a.state for a in rig.store.alerts()} == {State.NOTIFIED}


def test_a_failing_channel_leaves_the_alert_created_and_retries_later(rig):
    rig.feed(congested(0))
    rig.channel.fail = True
    assert rig.notifier.run_once() == 0
    assert rig.store.alerts()[0].state is State.CREATED
    rig.channel.fail = False
    assert rig.notifier.run_once() == 0  # trop tôt : le délai de reprise n'est pas écoulé
    rig.clock.advance(5)
    assert rig.notifier.run_once() == 1
    assert rig.store.alerts()[0].state is State.NOTIFIED
    assert rig.notifier._not_before == {}  # rien ne s'accumule pour une alerte remise


def test_a_failing_alert_does_not_block_the_others(rig):
    rig.feed(congested(0), congested(0, segment="ROAD_002"))
    first = rig.store.pending_notification(10)[0]
    real_send = rig.channel.send

    def picky(alert):
        if alert.alert_id == first.alert_id:
            raise NotificationFailed("canal en panne pour celle-ci")
        real_send(alert)

    rig.channel.send = picky
    assert rig.notifier.run_once() == 1
    assert [a.state for a in sorted(rig.store.alerts(), key=lambda a: a.road_segment_id)] == [
        State.CREATED,
        State.NOTIFIED,
    ]


def test_an_alert_acknowledged_during_the_delivery_is_not_moved_back(rig):
    rig.feed(congested(0))
    (alert,) = rig.store.alerts()
    sent = rig.channel.send

    def acknowledge_then_send(a):
        sent(a)
        rig.service.acknowledge(a.alert_id, "op")

    rig.channel.send = acknowledge_then_send
    assert rig.notifier.run_once() == 0
    assert rig.store.alerts()[0].state is State.ACKNOWLEDGED


def test_a_resolved_alert_is_never_notified(rig):
    rig.feed(congested(0), indicator(1, "FREE_FLOW"))
    assert rig.notifier.run_once() == 0 and rig.channel.delivered == []


# ------------------------------------------------------------------------------------- relais
def test_the_relay_publishes_in_order_and_marks_each_event_once(rig):
    rig.feed(congested(0))
    rig.notifier.run_once()
    assert rig.relay.run_once() == 2
    assert [e["data"]["state"] for e in rig.publisher.on("alerts.events")] == [
        "CREATED",
        "NOTIFIED",
    ]
    assert rig.relay.run_once() == 0  # déjà publiés
    assert rig.publisher.flushes == 2  # l'accusé du broker avant chaque marquage


def test_a_bus_failure_keeps_the_events_for_the_next_turn(rig):
    """ADR-009 : si Kafka est en panne, les événements attendent dans la base, rien n'est perdu."""
    rig.feed(congested(0))
    rig.publisher.fail = True
    with pytest.raises(PublishFailed):
        rig.relay.run_once()
    assert not rig.store.data.outbox[0]["published"]
    rig.publisher.fail = False
    assert rig.relay.run_once() == 1
    assert rig.store.data.outbox[0]["published"]


def test_the_relay_publishes_a_batch_no_larger_than_its_limit(rig):
    from app.services.relay import OutboxRelay

    rig.feed(*[congested(0, segment=f"ROAD_{n:03d}") for n in range(1, 6)])
    small = OutboxRelay(rig.store, rig.publisher, batch=2)
    assert [small.run_once() for _ in range(3)] == [2, 2, 1]


# ------------------------------------------------------------------------------- la boucle
class Source:
    """Un faux sujet : chaque `poll` rend le lot suivant, puis arrête la boucle."""

    def __init__(self, batches, stop):
        self._batches = list(batches)
        self._stop = stop
        self.committed: list[dict[int, int]] = []

    def poll(self, timeout_ms=0):
        if not self._batches:
            self._stop.set()
            return []
        return self._batches.pop(0)

    def commit(self, offsets):
        self.committed.append(dict(offsets))


def record(event, partition=0, offset=0):
    return Record(b"INT_01", body(event), partition, offset)


def test_the_loop_handles_commits_then_publishes_and_notifies(rig):
    stop = threading.Event()
    source = Source([[record(congested(0), 0, 10), record(congested(1), 0, 11)]], stop)
    handled = run(rig.handler, source, rig.relay, rig.notifier, stop)
    assert handled == 2
    assert source.committed == [{0: 12}]  # prochain offset à lire
    assert [e["data"]["state"] for e in rig.publisher.on("alerts.events")] == [
        "CREATED",
        "NOTIFIED",
    ]


def test_the_notified_event_leaves_in_the_same_turn_as_the_notification(rig):
    """Un seul tour de boucle : le relais repasse après le notificateur, sans tour de plus."""
    stop = threading.Event()

    class OneTurn(Source):
        def poll(self, timeout_ms=0):
            stop.set()  # la boucle ne fera que ce tour
            return super().poll(timeout_ms)

    source = OneTurn([[record(congested(0), 0, 1)]], stop)
    run(rig.handler, source, rig.relay, rig.notifier, stop)
    assert [e["data"]["state"] for e in rig.publisher.on("alerts.events")] == [
        "CREATED",
        "NOTIFIED",
    ]


def test_offsets_are_committed_per_partition(rig):
    stop = threading.Event()
    source = Source(
        [[record(indicator(0), 0, 4), record(indicator(0), 2, 9), record(indicator(1), 0, 5)]], stop
    )
    run(rig.handler, source, rig.relay, rig.notifier, stop)
    assert source.committed == [{0: 6, 2: 10}]


def test_an_empty_poll_commits_nothing_but_still_relays_events_written_by_the_api(rig):
    rig.feed(congested(0))  # écrit par un autre acteur que la boucle (l'API : acquittement)
    stop = threading.Event()
    source = Source([[]], stop)
    run(rig.handler, source, rig.relay, rig.notifier, stop)
    assert source.committed == []
    assert len(rig.publisher.on("alerts.events")) == 2  # CREATED puis NOTIFIED


def test_a_store_failure_stops_the_loop_without_committing_the_offset(rig):
    stop = threading.Event()
    rig.store.fail_outbox = True
    source = Source([[record(congested(0), 0, 3)]], stop)
    with pytest.raises(StoreFailed):
        run(rig.handler, source, rig.relay, rig.notifier, stop)
    assert source.committed == []  # relu au redémarrage


def test_a_bad_message_is_rejected_and_its_offset_is_committed(rig):
    stop = threading.Event()
    source = Source([[Record(None, b"pas du json", 1, 7)]], stop)
    run(rig.handler, source, rig.relay, rig.notifier, stop)
    assert source.committed == [{1: 8}]
    assert len(rig.publisher.on("errors.dlq")) == 1


def test_the_loop_writes_its_heartbeat(rig, tmp_path):
    stop = threading.Event()
    path = tmp_path / "alive"
    run(rig.handler, Source([[]], stop), rig.relay, rig.notifier, stop, heartbeat_file=str(path))
    assert path.exists()


def test_a_heartbeat_that_cannot_be_written_does_not_stop_the_loop(tmp_path, caplog):
    caplog.set_level("WARNING")
    beat(str(tmp_path / "absent" / "alive"))
    assert "fichier de vie non écrit" in caplog.text


# ------------------------------------------------------------------------------------ règles
def test_the_rules_are_cached_for_ttl_seconds():
    store = FakeStore()
    now = [100.0]
    cache = RulesCache(store, 5.0, monotonic=lambda: now[0])
    first = cache.get()
    store.update_rule("capteur.muet", enabled=False, params=None, min_gap_s=None)
    assert cache.get() is first  # encore en mémoire
    now[0] += 5.0
    assert [r.enabled for r in cache.get() if r.rule_id == "capteur.muet"] == [False]


def test_a_rule_change_through_the_api_reaches_the_loop(rig):
    cache = RulesCache(rig.store, 0.0)
    assert any(r.rule_id == "capteur.muet" and r.enabled for r in cache.get())
    rig.store.update_rule("capteur.muet", enabled=False, params=None, min_gap_s=None)
    assert not next(r for r in cache.get() if r.rule_id == "capteur.muet").enabled


def test_fake_publisher_records_topic_key_and_value():
    publisher = FakePublisher()
    publisher.publish("t", "k", b'{"a":1}')
    assert publisher.sent == [("t", "k", {"a": 1})]
