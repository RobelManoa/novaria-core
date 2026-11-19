"""Les dépendances de la collecte derrière leurs disjoncteurs (MS-16).

Réponse immédiate quand le circuit est ouvert, reprises, métriques, journal.
"""

import json
import logging

import pytest

from app.adapters.guards import (
    GuardedPublisher,
    GuardedRawEvents,
    GuardedRejects,
    breaker,
    observer_for,
)
from app.core.metrics import Registry
from app.services.ingestion import PublishFailed, StoreFailed


class Clock:
    now = 0.0

    def __call__(self) -> float:
        return self.now


class Bus:
    """Un producteur dont on commande la panne et dont on compte les appels."""

    def __init__(self) -> None:
        self.down, self.calls = False, 0

    def publish(self, topic, key, value) -> None:
        self.calls += 1
        if self.down:
            raise PublishFailed("KafkaTimeoutError")

    def close(self) -> None:
        self.closed = True


def guarded_bus(threshold: int = 3):
    registry, clock, bus = Registry(), Clock(), Bus()
    circuit = breaker(
        "kafka",
        failures=threshold,
        reset_s=10,
        trip_on=(PublishFailed,),
        registry=registry,
        clock=clock,
    )
    return GuardedPublisher(bus, circuit), bus, registry, clock


def test_a_healthy_bus_passes_messages_and_counts_the_calls():
    publisher, bus, registry, _ = guarded_bus()
    publisher.publish("iot.raw", "INT_01", b"x")
    assert bus.calls == 1
    assert (
        registry.value("novaria_dependency_calls_total", {"dependency": "kafka", "outcome": "ok"})
        == 1
    )
    assert registry.value("novaria_circuit_state", {"dependency": "kafka"}) == 0


def test_after_the_threshold_the_circuit_opens_and_the_bus_is_no_longer_called():
    publisher, bus, registry, _ = guarded_bus(threshold=3)
    bus.down = True
    for _ in range(3):
        with pytest.raises(PublishFailed):
            publisher.publish("iot.raw", None, b"x")
    assert registry.value("novaria_circuit_state", {"dependency": "kafka"}) == 2
    assert registry.value("novaria_circuit_opened_total", {"dependency": "kafka"}) == 1
    before = bus.calls
    with pytest.raises(PublishFailed, match="disjoncteur « kafka » ouvert"):
        publisher.publish("iot.raw", None, b"x")
    assert bus.calls == before, "ouvert : aucun appel au bus, la réponse est immédiate"
    assert (
        registry.value(
            "novaria_dependency_calls_total", {"dependency": "kafka", "outcome": "rejected"}
        )
        == 1
    )


def test_when_the_bus_comes_back_one_trial_closes_the_circuit():
    publisher, bus, registry, clock = guarded_bus(threshold=1)
    bus.down = True
    with pytest.raises(PublishFailed):
        publisher.publish("iot.raw", None, b"x")
    bus.down = False
    clock.now += 11
    publisher.publish("iot.raw", None, b"x")
    assert registry.value("novaria_circuit_state", {"dependency": "kafka"}) == 0


def test_close_reaches_the_real_producer():
    publisher, bus, _, _ = guarded_bus()
    publisher.close()
    assert bus.closed is True


class Mongo:
    def __init__(self, failures: int = 0) -> None:
        self.failures, self.calls = failures, 0

    def exists(self, event_id: str) -> bool:
        self.calls += 1
        if self.calls <= self.failures:
            raise StoreFailed("ServerSelectionTimeoutError")
        return False

    def insert(self, document: dict):
        self.calls += 1
        if self.calls <= self.failures:
            raise StoreFailed("AutoReconnect")
        return True


def guarded_mongo(inner, attempts: int = 3, threshold: int = 2, cls=GuardedRawEvents):
    registry, clock, waits = Registry(), Clock(), []
    circuit = breaker(
        "mongo",
        failures=threshold,
        reset_s=10,
        trip_on=(StoreFailed,),
        registry=registry,
        clock=clock,
    )
    return (
        cls(inner, circuit, attempts, 0.1, observer_for(registry), waits.append),
        registry,
        waits,
        clock,
    )


def test_a_transient_mongo_failure_is_replayed_with_growing_waits_and_succeeds():
    store, registry, waits, _ = guarded_mongo(Mongo(failures=2))
    assert store.exists("id-1") is False
    assert len(waits) == 2 and waits[1] > waits[0], "attente croissante"
    assert registry.value("novaria_dependency_retries_total", {"dependency": "mongo"}) == 2
    assert registry.value("novaria_circuit_state", {"dependency": "mongo"}) == 0


def test_a_failure_that_lasts_raises_after_every_attempt_and_counts_once_for_the_circuit():
    inner = Mongo(failures=99)
    store, registry, _, _ = guarded_mongo(inner, attempts=3, threshold=2)
    with pytest.raises(StoreFailed):
        store.insert({"id": "x"})
    assert inner.calls == 3
    assert (
        registry.value(
            "novaria_dependency_calls_total", {"dependency": "mongo", "outcome": "error"}
        )
        == 1
    )
    assert registry.value("novaria_circuit_state", {"dependency": "mongo"}) == 0, (
        "un seul échec final : encore fermé"
    )


def test_after_two_final_failures_mongo_fails_at_once_without_being_called():
    inner = Mongo(failures=99)
    store, registry, waits, _ = guarded_mongo(inner, attempts=2, threshold=2)
    for _ in range(2):
        with pytest.raises(StoreFailed):
            store.insert({"id": "x"})
    calls, waited = inner.calls, len(waits)
    with pytest.raises(StoreFailed, match="disjoncteur « mongo » ouvert"):
        store.exists("x")
    assert (inner.calls, len(waits)) == (calls, waited), (
        "ni appel ni attente quand le circuit est ouvert"
    )
    assert registry.value("novaria_circuit_state", {"dependency": "mongo"}) == 2


def test_the_reject_archive_is_guarded_the_same_way():
    class Archive:
        calls = 0

        def insert(self, document: dict) -> None:
            self.calls += 1
            raise StoreFailed("AutoReconnect")

    archive = Archive()
    store, _, _, _ = guarded_mongo(archive, attempts=2, threshold=1, cls=GuardedRejects)
    with pytest.raises(StoreFailed):
        store.insert({})
    with pytest.raises(StoreFailed, match="ouvert"):
        store.insert({})
    assert archive.calls == 2


def test_the_state_changes_and_the_replays_are_written_in_the_journal(caplog):
    publisher, bus, _, clock = guarded_bus(threshold=1)
    bus.down = True
    with caplog.at_level(logging.INFO, logger="app.resilience"):
        with pytest.raises(PublishFailed):
            publisher.publish("iot.raw", None, b"x")
        bus.down = False
        clock.now += 11
        publisher.publish("iot.raw", None, b"x")
    messages = [(r.levelno, r.getMessage(), r.fields["dependency"]) for r in caplog.records]
    assert messages == [
        (logging.WARNING, "disjoncteur ouvert", "kafka"),
        (logging.INFO, "disjoncteur semi-ouvert", "kafka"),
        (logging.INFO, "disjoncteur fermé", "kafka"),
    ]


def test_the_metrics_text_exposes_the_circuit_state_for_a_scraper():
    publisher, bus, registry, _ = guarded_bus(threshold=1)
    bus.down = True
    with pytest.raises(PublishFailed):
        publisher.publish("iot.raw", None, b"x")
    text = registry.render()
    assert 'novaria_circuit_state{dependency="kafka"} 2' in text
    assert 'novaria_circuit_opened_total{dependency="kafka"} 1' in text
    assert json.dumps(text)  # texte simple, sans objet Python


def test_without_traffic_an_open_circuit_becomes_half_open_when_metrics_are_read():
    from app.adapters.guards import refresh_circuits

    publisher, bus, registry, clock = guarded_bus(threshold=1)
    bus.down = True
    with pytest.raises(PublishFailed):
        publisher.publish("iot.raw", None, b"x")
    assert registry.value("novaria_circuit_state", {"dependency": "kafka"}) == 2
    clock.now += 11  # le délai de reprise est écoulé, mais aucun appel n'est venu
    refresh_circuits(registry)
    assert registry.value("novaria_circuit_state", {"dependency": "kafka"}) == 1
