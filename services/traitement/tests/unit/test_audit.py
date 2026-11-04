"""Règles du journal d'audit et des compteurs d'usage (BE-05), sans base ni réseau."""

import json
import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.core.audit import match_template
from app.core.routing import compile_templates
from app.services.audit import (
    ANONYMOUS,
    RETRY_AFTER_FAILURE_S,
    UNMATCHED,
    RecordingObserver,
    RequestEvent,
    bucket_start,
    build_audit_entry,
    outcome_of,
    uuid_params,
)
from tests.fakes import FakeAuditRepository, FakeUsageRepository

DEBUT = datetime(2026, 10, 20, 8, 20, 31, 123456, tzinfo=UTC)
ACTEUR = str(uuid.UUID(int=42))
AUTRE = str(uuid.UUID(int=43))


def event(**changes) -> RequestEvent:
    base = {
        "method": "GET",
        "template": "/api/v1/users/{user_id}",
        "status": 200,
        "started_at": DEBUT,
        "duration_ms": 12.3456,
        "correlation_id": "abc-123",
        "actor": ACTEUR,
        "role": "viewer",
        "path_params": {"user_id": AUTRE},
    }
    return RequestEvent(**(base | changes))


# --- Issue de l'appel -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        (200, "ok"),
        (201, "ok"),
        (204, "ok"),
        (302, "ok"),
        (399, "ok"),
        (400, "error"),
        (401, "denied"),
        (403, "denied"),
        (404, "error"),
        (409, "error"),
        (422, "error"),
        (500, "error"),
        (503, "error"),
    ],
)
def test_the_outcome_follows_the_status_code(status, outcome):
    assert outcome_of(status) == outcome


# --- Tranche de temps -----------------------------------------------------------------------


def test_the_bucket_is_the_utc_hour_that_holds_the_moment():
    assert bucket_start(DEBUT) == datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
    assert bucket_start(datetime(2026, 10, 20, 8, 59, 59, 999999, tzinfo=UTC)).hour == 8
    assert bucket_start(datetime(2026, 10, 20, 9, 0, tzinfo=UTC)).hour == 9


def test_the_bucket_is_computed_in_utc_whatever_the_zone_of_the_moment():
    paris = timezone(timedelta(hours=2))
    assert bucket_start(datetime(2026, 10, 20, 10, 20, tzinfo=paris)) == datetime(
        2026, 10, 20, 8, 0, tzinfo=UTC
    )
    demi_heure = timezone(timedelta(hours=5, minutes=30))
    assert bucket_start(datetime(2026, 10, 20, 13, 50, tzinfo=demi_heure)) == datetime(
        2026, 10, 20, 8, 20, tzinfo=UTC
    ).replace(minute=0)


# --- Paramètres de chemin -------------------------------------------------------------------


def test_only_uuid_path_parameters_are_kept():
    params = {
        "user_id": ACTEUR,
        "name": "alice",
        "pasted": ".".join(["entete", "contenu", "signature"]),
        "short": "1234",
    }
    assert uuid_params(params) == {"user_id": ACTEUR}


@pytest.mark.parametrize(
    "value",
    [
        ACTEUR.upper(),
        ACTEUR + "x",
        "x" + ACTEUR,
        ACTEUR + "\n",
        " " + ACTEUR,
        ACTEUR.replace("-", ""),
        "",
    ],
)
def test_a_value_that_is_not_exactly_a_lowercase_uuid_is_dropped(value):
    assert uuid_params({"user_id": value}) == {}


# --- Contenu d'une entrée -------------------------------------------------------------------


def test_an_entry_holds_who_what_when_and_nothing_else():
    entry = build_audit_entry(event(), "traitement")
    assert entry == {
        "ts": DEBUT,
        "service": "traitement",
        "actor": ACTEUR,
        "action": "GET /api/v1/users/{user_id}",
        "outcome": "ok",
        "correlation_id": "abc-123",
        "details": {
            "status": 200,
            "duration_ms": 12.3,
            "role": "viewer",
            "path_params": {"user_id": AUTRE},
        },
    }


def test_the_timestamp_is_stored_in_utc():
    paris = timezone(timedelta(hours=2))
    entry = build_audit_entry(event(started_at=DEBUT.astimezone(paris)), "traitement")
    assert entry["ts"] == DEBUT
    assert entry["ts"].utcoffset() == timedelta(0)


def test_a_call_without_identified_caller_is_attributed_to_anonymous():
    entry = build_audit_entry(
        event(actor=None, role=None, status=401, path_params={}, template="/api/v1/auth/login"),
        "traitement",
    )
    assert entry["actor"] == ANONYMOUS == "anonymous"
    assert entry["outcome"] == "denied"
    assert "role" not in entry["details"]
    assert "path_params" not in entry["details"]


def test_the_correlation_id_is_omitted_when_there_is_none():
    for missing in ("-", ""):
        assert "correlation_id" not in build_audit_entry(event(correlation_id=missing), "t")


def test_a_path_parameter_that_is_not_a_uuid_never_reaches_the_entry():
    entry = build_audit_entry(event(path_params={"user_id": "eyJhbGciOiJIUzI1NiJ9.secret"}), "t")
    assert "secret" not in json.dumps(entry, default=str)
    assert "path_params" not in entry["details"]


def test_the_entry_fields_are_a_closed_list():
    entry = build_audit_entry(event(), "traitement")
    assert set(entry) <= {
        "ts",
        "service",
        "actor",
        "action",
        "outcome",
        "correlation_id",
        "details",
    }
    assert set(entry["details"]) <= {"status", "duration_ms", "role", "path_params"}


# --- Qui est audité -------------------------------------------------------------------------


def test_an_identified_caller_is_audited():
    assert event().audited


def test_an_unidentified_call_is_not_audited():
    assert not event(actor=None).audited


def test_every_login_attempt_is_audited_even_when_refused():
    login = event(method="POST", template="/api/v1/auth/login", actor=None, status=401)
    assert login.audited


def test_only_a_post_on_the_login_route_counts_as_a_login():
    assert not event(method="GET", template="/api/v1/auth/login", actor=None).audited
    assert not event(method="POST", template="/api/v1/auth/loginx", actor=None).audited


def test_the_endpoint_is_the_method_and_the_route_template():
    assert event().endpoint == "GET /api/v1/users/{user_id}"


# --- Modèles de route -----------------------------------------------------------------------

TEMPLATES = [
    "/api/v1/indicators/{indicator_id}",
    "/api/v1/indicators/latest",
    "/api/v1/indicators",
    "/api/v1/users/{user_id}",
    "/api/v1/users",
]


def test_a_path_is_matched_to_its_template():
    compiled = compile_templates(TEMPLATES)
    assert match_template("/api/v1/users", compiled) == "/api/v1/users"
    assert match_template(f"/api/v1/users/{ACTEUR}", compiled) == "/api/v1/users/{user_id}"
    assert match_template("/api/v1/indicators", compiled) == "/api/v1/indicators"


def test_the_most_precise_template_wins():
    compiled = compile_templates(TEMPLATES)
    assert match_template("/api/v1/indicators/latest", compiled) == "/api/v1/indicators/latest"
    assert match_template("/api/v1/indicators/abc", compiled) == "/api/v1/indicators/{indicator_id}"


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/api/v1/unknown",
        "/api/v1/users/",
        "/api/v1/users/a/b",
        "/x/api/v1/users",
        "/api/v1/users%2F..%2Fx",
        "/api/v1/usersx",
        "/api/v1/users/{user_id}/more",
        "",
    ],
)
def test_an_unknown_path_is_counted_under_one_fixed_key(path):
    assert match_template(path, compile_templates(TEMPLATES)) == UNMATCHED


def test_the_dot_of_a_template_is_not_a_wildcard():
    compiled = compile_templates(["/api/v1.0/items"])
    assert match_template("/api/v1.0/items", compiled) == "/api/v1.0/items"
    assert match_template("/api/v1x0/items", compiled) == UNMATCHED


def test_a_path_cannot_choose_its_own_counter_key():
    compiled = compile_templates(TEMPLATES)
    for path in ("/api/v1/users/{user_id}", "/api/v1/zzz", "/api/v1/users/" + "a" * 10000):
        assert match_template(path, compiled) in {*TEMPLATES, UNMATCHED}


# --- Observateur ----------------------------------------------------------------------------


class Horloge:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class BrokenAudit:
    def insert(self, entry: dict) -> None:
        raise ConnectionError("mongodb://svc_backend:motdepasse@mongo:27017/novaria injoignable")


class BrokenUsage:
    def increment(self, endpoint, bucket) -> None:
        raise TimeoutError("expiré")


def observer(audit=None, usage=None, clock=None):
    failures: list[tuple[str, dict]] = []
    audit = FakeAuditRepository() if audit is None else audit
    usage = FakeUsageRepository() if usage is None else usage
    watcher = RecordingObserver(
        audit,
        usage,
        service="traitement",
        log=lambda message, fields: failures.append((message, fields)),
        **({"monotonic": clock} if clock else {}),
    )
    return watcher, audit, usage, failures


def test_an_audited_call_writes_one_entry_and_one_count():
    watcher, audit, usage, failures = observer()
    watcher.observe(event())
    assert [e["action"] for e in audit.entries] == ["GET /api/v1/users/{user_id}"]
    assert usage.counts == {("GET /api/v1/users/{user_id}", bucket_start(DEBUT)): 1}
    assert failures == []
    assert watcher.dropped == 0


def test_an_unidentified_call_is_counted_but_not_written_to_the_journal():
    watcher, audit, usage, _ = observer()
    watcher.observe(event(actor=None, role=None, status=401))
    assert audit.entries == []
    assert usage.total("GET /api/v1/users/{user_id}") == 1


def test_calls_in_the_same_hour_add_up_and_a_new_hour_starts_a_new_count():
    watcher, _, usage, _ = observer()
    for minutes in (0, 5, 59):
        watcher.observe(event(started_at=DEBUT.replace(minute=minutes)))
    watcher.observe(event(started_at=DEBUT + timedelta(hours=1)))
    counts = sorted(usage.counts.items(), key=lambda item: item[0][1])
    assert [n for _, n in counts] == [3, 1]


def test_each_endpoint_has_its_own_count():
    watcher, _, usage, _ = observer()
    watcher.observe(event())
    watcher.observe(event(method="POST", template="/api/v1/users", status=201))
    watcher.observe(event(template="/api/v1/users"))
    assert usage.total("GET /api/v1/users/{user_id}") == 1
    assert usage.total("POST /api/v1/users") == 1
    assert usage.total("GET /api/v1/users") == 1


def test_a_failing_journal_never_raises_and_is_reported_without_its_message():
    clock = Horloge()
    watcher, _, _, failures = observer(audit=BrokenAudit(), clock=clock)
    watcher.observe(event())
    assert watcher.dropped == 1
    ((message, fields),) = failures
    assert fields == {"error": "ConnectionError", "endpoint": event().endpoint, "dropped": 1}
    assert "motdepasse" not in json.dumps([message, fields])


def test_the_pause_after_a_failure_is_ten_seconds():
    assert RETRY_AFTER_FAILURE_S == 10.0


def test_a_failing_counter_is_also_swallowed():
    watcher, _, _, failures = observer(usage=BrokenUsage(), clock=Horloge())
    watcher.observe(event())
    assert watcher.dropped == 1
    assert failures[0][1]["error"] == "TimeoutError"


def test_after_a_failure_the_next_writes_are_skipped_then_resume():
    clock = Horloge()
    audit = FakeAuditRepository()
    watcher, _, usage, failures = observer(audit=BrokenAudit(), usage=None, clock=clock)
    watcher.observe(event())
    clock.now += RETRY_AFTER_FAILURE_S - 0.1
    watcher.observe(event())
    watcher.observe(event())
    assert watcher.dropped == 3
    assert len(failures) == 1, "une seule alerte pendant la pause"
    assert usage.counts == {}, "rien n'est écrit pendant la pause"

    watcher._audit = audit  # la base est revenue
    clock.now += 0.2
    watcher.observe(event())
    assert len(audit.entries) == 1
    assert watcher.dropped == 3
    assert usage.total(event().endpoint) == 1


def test_the_pause_starts_again_if_the_base_is_still_down():
    clock = Horloge()
    watcher, _, _, failures = observer(audit=BrokenAudit(), clock=clock)
    watcher.observe(event())
    clock.now += RETRY_AFTER_FAILURE_S
    watcher.observe(event())
    assert len(failures) == 2
    assert watcher.dropped == 2
    clock.now += RETRY_AFTER_FAILURE_S - 1
    watcher.observe(event())
    assert len(failures) == 2


def test_the_journal_is_written_before_the_counter():
    ordre: list[str] = []

    class Audit:
        def insert(self, entry):
            ordre.append("audit")

    class Usage:
        def increment(self, endpoint, bucket):
            ordre.append("usage")

    watcher, *_ = observer(audit=Audit(), usage=Usage())
    watcher.observe(event())
    assert ordre == ["audit", "usage"]


def test_a_failed_journal_write_does_not_count_the_call():
    watcher, _, usage, _ = observer(audit=BrokenAudit(), clock=Horloge())
    watcher.observe(event())
    assert usage.counts == {}
