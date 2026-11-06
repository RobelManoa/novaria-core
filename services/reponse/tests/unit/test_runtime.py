"""Les fils du service : envoi des événements, lecture des recommandations, arrêt (MS-12)."""

import threading
import time

from app.adapters.kafka_core import Record
from app.worker.runtime import Runtime
from tests.support import Rig, raw, recommendation_event


def wait_for(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


class FakeSource:
    """Un consommateur en mémoire : des lots à rendre, des offsets validés, un état fermé."""

    def __init__(self, batches=(), fail_on_poll=None):
        self.batches = list(batches)
        self.committed: list[dict] = []
        self.closed = False
        self.fail_on_poll = fail_on_poll
        self.polls = 0

    def poll(self, timeout_ms=0):
        self.polls += 1
        if self.fail_on_poll and self.polls >= self.fail_on_poll:
            raise RuntimeError("coordinateur de groupe perdu")
        time.sleep(0.005)
        return self.batches.pop(0) if self.batches else []

    def commit(self, offsets):
        self.committed.append(dict(offsets))

    def close(self):
        self.closed = True


def record(event, partition=0, offset=0):
    return Record(b"INT_01", raw(event), partition, offset)


def runtime(rig: Rig, *sources, retry_s=0.02) -> Runtime:
    queue = list(sources)

    def factory():
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    return Runtime(
        rig.service,
        rig.dispatcher,
        rig.handler,
        factory,
        tick_interval_s=0.01,
        retry_s=retry_s,
        poll_ms=5,
    )


# =========================================================================== lecture
def test_offsets_are_committed_only_after_the_events_have_left_and_been_acknowledged():
    rig = Rig()
    source = FakeSource(
        [
            [
                record(recommendation_event(at=0), 0, 7),
                record(recommendation_event("INT_02", at=0), 1, 3),
            ],
            [record(recommendation_event(at=1), 0, 8)],
        ]
    )
    app = runtime(rig, source)
    app.start()
    try:
        assert wait_for(lambda: source.committed)
        assert source.committed[0] == {0: 8, 1: 4}  # le prochain offset à lire, par partition
        assert wait_for(lambda: {0: 9} in source.committed)
    finally:
        app.stop()
    assert {e["data"]["decision"]["origin"] for e in rig.status()} >= {"RECOMMENDATION"}


def test_offsets_are_held_back_while_the_bus_is_down_then_committed_together():
    rig = Rig()
    rig.publisher.down = True
    source = FakeSource(
        [[record(recommendation_event(at=0), 0, 1)], [record(recommendation_event(at=1), 0, 2)]]
    )
    app = runtime(rig, source)
    app.start()
    try:
        assert wait_for(lambda: source.polls > 5)
        assert source.committed == []  # rien d'accusé : rien de validé
        rig.publisher.down = False
        assert wait_for(lambda: source.committed)
        assert source.committed[-1][0] == 3
    finally:
        app.stop()


def test_a_poison_message_does_not_stop_the_reading_and_goes_to_the_dead_letter_topic():
    rig = Rig()
    source = FakeSource(
        [[Record(None, b"{pas du json", 0, 0), record(recommendation_event(at=0), 0, 1)]]
    )
    app = runtime(rig, source)
    app.start()
    try:
        assert wait_for(lambda: source.committed)
    finally:
        app.stop()
    assert len(rig.publisher.on("errors.dlq")) == 1
    assert source.committed[0] == {0: 2}


def test_a_reading_failure_closes_the_consumer_and_a_new_one_takes_over():
    rig = Rig()
    broken = FakeSource(fail_on_poll=2)
    healthy = FakeSource([[record(recommendation_event(at=0), 0, 5)]])
    app = runtime(rig, broken, healthy)
    app.start()
    try:
        assert wait_for(lambda: healthy.committed)
    finally:
        app.stop()
    assert broken.closed


def test_a_consumer_that_cannot_be_created_is_retried_without_stopping_the_signals():
    rig = Rig(max_silence_s=5)
    healthy = FakeSource()
    app = runtime(rig, OSError("broker injoignable"), OSError("encore"), healthy)
    app.start()
    try:
        assert wait_for(lambda: healthy.polls > 0)
    finally:
        app.stop()


# =========================================================================== phases et perte
def test_the_ticker_returns_to_the_fixed_plan_even_if_kafka_never_answers():
    """Ni consommateur ni envoi possible : la perte des recommandations est quand même vue."""
    rig = Rig(max_silence_s=10)
    rig.publisher.down = True
    # Une recommandation reçue il y a longtemps (horloge simulée), puis un silence.
    rig.handler.handle(raw(recommendation_event()))
    app = runtime(rig, FakeSource())
    app.start()
    try:
        rig.clock.advance(11)
        assert wait_for(lambda: rig.service.view("INT_01").mode.value == "DEGRADED_FIXED_PLAN")
    finally:
        app.stop(final_drain_s=0.1)


def test_stopping_says_so_on_the_bus_before_leaving():
    rig = Rig()
    rig.handler.handle(raw(recommendation_event()))
    app = runtime(rig, FakeSource())
    app.start()
    app.stop()
    ids = [e["id"] for e in rig.status()]
    assert any(i.startswith("reponse-shutdown-INT_01") for i in ids)
    assert not app.alive


def test_a_failure_in_a_loop_is_survived(monkeypatch):
    rig = Rig()
    calls = {"tick": 0, "drain": 0}
    original_tick, original_drain = rig.service.tick, rig.dispatcher.drain

    def flaky_tick():
        calls["tick"] += 1
        if calls["tick"] == 1:
            raise RuntimeError("défaut passager")
        original_tick()

    def flaky_drain():
        calls["drain"] += 1
        if calls["drain"] == 1:
            raise RuntimeError("défaut passager")
        return original_drain()

    monkeypatch.setattr(rig.service, "tick", flaky_tick)
    monkeypatch.setattr(rig.dispatcher, "drain", flaky_drain)
    app = runtime(rig, FakeSource())
    app.start()
    try:
        assert wait_for(lambda: calls["tick"] > 2 and calls["drain"] > 2)
        assert app.alive
    finally:
        app.stop()


def test_without_kafka_only_the_phases_and_the_dispatch_run():
    rig = Rig()
    app = Runtime(rig.service, rig.dispatcher, None, None, tick_interval_s=0.01)
    app.start()
    try:
        assert app.alive and len(app._threads) == 2
    finally:
        app.stop()
    assert threading.active_count() >= 1
