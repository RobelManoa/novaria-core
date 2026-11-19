"""Reprises avec attente croissante et disjoncteur (MS-16), sans attente ni réseau."""

import pytest

from app.core.resilience import (
    CLOSED,
    HALF_OPEN,
    OPEN,
    CircuitBreaker,
    CircuitOpen,
    backoff_delays,
    retry,
)


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class Boom(Exception):
    pass


def fail() -> None:
    raise Boom("panne")


def test_the_waits_grow_by_the_factor_and_stop_at_the_cap():
    assert backoff_delays(5, base_s=0.1, factor=2, max_s=0.5, jitter=0) == [0.1, 0.2, 0.4, 0.5]
    assert backoff_delays(1) == []
    assert backoff_delays(0) == []


def test_the_jitter_stays_within_its_share_of_the_wait():
    low = backoff_delays(3, base_s=1, factor=1, max_s=9, jitter=0.2, rng=lambda: 0.0)
    high = backoff_delays(3, base_s=1, factor=1, max_s=9, jitter=0.2, rng=lambda: 1.0)
    assert low == [0.8, 0.8]
    assert high == [1.2, 1.2]


def test_a_success_on_the_first_try_does_not_wait():
    waits: list[float] = []
    assert retry(lambda: "ok", sleep=waits.append) == "ok"
    assert waits == []


def test_a_call_is_replayed_with_growing_waits_until_it_succeeds():
    calls, waits = [], []

    def flaky() -> str:
        calls.append(1)
        if len(calls) < 3:
            raise Boom("encore")
        return "enfin"

    assert retry(flaky, attempts=4, base_s=0.1, jitter=0, sleep=waits.append) == "enfin"
    assert len(calls) == 3
    assert waits == [0.1, 0.2]


def test_when_every_try_fails_the_last_error_is_raised_after_attempts_minus_one_waits():
    waits: list[float] = []
    with pytest.raises(Boom):
        retry(fail, attempts=3, base_s=0.1, jitter=0, sleep=waits.append)
    assert waits == [0.1, 0.2]


def test_only_the_listed_errors_are_replayed_and_the_forbidden_ones_never():
    calls = []

    def logic_error() -> None:
        calls.append(1)
        raise ValueError("erreur de logique")

    with pytest.raises(ValueError):
        retry(logic_error, attempts=3, retry_on=(Boom,), sleep=lambda _: None)
    assert len(calls) == 1
    with pytest.raises(Boom):
        retry(fail, attempts=3, never_retry=(Boom,), sleep=lambda _: None)


def test_every_replay_is_reported_to_the_observer():
    events: list[tuple] = []
    with pytest.raises(Boom):
        retry(
            fail,
            attempts=3,
            jitter=0,
            sleep=lambda _: None,
            name="mongo",
            observer=lambda event, **fields: events.append(
                (event, fields["attempt"], fields["error"])
            ),
        )
    assert events == [("retry", 1, "Boom"), ("retry", 2, "Boom")]


def make(threshold: int = 3, reset_s: float = 10.0, events: list | None = None):
    clock = Clock()
    breaker = CircuitBreaker(
        "essai",
        failure_threshold=threshold,
        reset_timeout_s=reset_s,
        trip_on=(Boom,),
        clock=clock,
        observer=(lambda event, **fields: events.append((event, fields)))
        if events is not None
        else None,
    )
    return breaker, clock


def trip(breaker: CircuitBreaker, times: int) -> None:
    for _ in range(times):
        with pytest.raises(Boom):
            breaker.call(fail)


def test_the_circuit_opens_after_the_threshold_of_consecutive_failures():
    breaker, _ = make(threshold=3)
    trip(breaker, 2)
    assert breaker.state == CLOSED
    trip(breaker, 1)
    assert breaker.state == OPEN


def test_a_success_resets_the_count_of_consecutive_failures():
    breaker, _ = make(threshold=3)
    trip(breaker, 2)
    assert breaker.call(lambda: "ok") == "ok"
    trip(breaker, 2)
    assert breaker.state == CLOSED


def test_an_open_circuit_fails_at_once_without_calling_the_dependency():
    breaker, _ = make(threshold=1)
    trip(breaker, 1)
    calls = []
    with pytest.raises(CircuitOpen) as error:
        breaker.call(lambda: calls.append(1))
    assert calls == []
    assert "essai" in str(error.value) and error.value.retry_in_s == 10.0


def test_after_the_delay_one_trial_call_goes_through_and_a_success_closes_the_circuit():
    breaker, clock = make(threshold=1, reset_s=10)
    trip(breaker, 1)
    clock.now += 9.9
    assert breaker.state == OPEN
    clock.now += 0.2
    assert breaker.state == HALF_OPEN
    assert breaker.call(lambda: "revenue") == "revenue"
    assert breaker.state == CLOSED


def test_a_failed_trial_reopens_the_circuit_for_a_new_delay():
    breaker, clock = make(threshold=1, reset_s=10)
    trip(breaker, 1)
    clock.now += 11
    trip(breaker, 1)
    assert breaker.state == OPEN
    clock.now += 5
    assert breaker.state == OPEN
    clock.now += 6
    assert breaker.state == HALF_OPEN


def test_only_one_trial_runs_at_a_time_while_half_open():
    breaker, clock = make(threshold=1, reset_s=10)
    trip(breaker, 1)
    clock.now += 11
    inside: list[str] = []

    def trial() -> str:
        try:
            breaker.call(lambda: "second")
        except CircuitOpen:
            inside.append("refusé")
        return "premier"

    assert breaker.call(trial) == "premier"
    assert inside == ["refusé"]


def test_an_error_that_is_not_a_dependency_failure_neither_counts_nor_blocks_the_trial():
    breaker, clock = make(threshold=1, reset_s=10)
    trip(breaker, 1)
    clock.now += 11
    with pytest.raises(ValueError):
        breaker.call(lambda: (_ for _ in ()).throw(ValueError("logique")))
    assert breaker.state == HALF_OPEN
    assert breaker.call(lambda: "ok") == "ok"
    assert breaker.state == CLOSED


def test_the_observer_sees_calls_rejections_and_every_state_change():
    events: list = []
    breaker, clock = make(threshold=2, reset_s=10, events=events)
    trip(breaker, 2)
    with pytest.raises(CircuitOpen):
        breaker.call(lambda: None)
    clock.now += 11
    breaker.call(lambda: "ok")
    kinds = [(e, f.get("outcome") or f.get("after")) for e, f in events]
    assert kinds == [
        ("call", "error"),
        ("call", "error"),
        ("state", "open"),
        ("rejected", None),
        ("state", "half_open"),
        ("call", "ok"),
        ("state", "closed"),
    ]


def test_the_parameters_are_checked():
    with pytest.raises(ValueError):
        CircuitBreaker("x", failure_threshold=0)
    with pytest.raises(ValueError):
        CircuitBreaker("x", reset_timeout_s=0)
