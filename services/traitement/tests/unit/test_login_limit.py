"""Limitation du débit de la connexion, de bout en bout dans l'API (BE-08)."""

import pytest

from app.api.deps import get_login_throttle
from app.core.config import get_settings
from app.core.ratelimit import LoginThrottle
from app.main import app
from tests.fakes import PASSWORD
from tests.unit.test_ratelimit import Clock

LOGIN = "/api/v1/auth/login"


def attempt(client, username, password=PASSWORD, **headers):
    return client.post(LOGIN, json={"username": username, "password": password}, headers=headers)


@pytest.fixture
def clock() -> Clock:
    return Clock()


def use(login):
    app.dependency_overrides[get_login_throttle] = lambda: login
    return login


@pytest.fixture
def limits(client, clock):
    """Trois échecs par compte, horloge simulée ; le débit par adresse ne gêne pas ces tests."""
    return use(LoginThrottle(attempts_per_minute=1000, max_failures=3, lockout_s=900, clock=clock))


@pytest.fixture
def tight(client, clock):
    """Quatre essais par minute et par adresse ; les échecs par compte ne gênent pas ces tests."""
    return use(LoginThrottle(attempts_per_minute=4, max_failures=1000, lockout_s=900, clock=clock))


def test_the_attempt_after_the_permitted_failures_is_refused_with_429_and_retry_after(
    client, repo, limits
):
    repo.make("alice")
    assert [attempt(client, "alice", "faux").status_code for _ in range(3)] == [401, 401, 401]
    refused = attempt(client, "alice", "faux")
    assert refused.status_code == 429
    assert refused.headers["Retry-After"] == "900"
    assert refused.headers["content-type"].startswith("application/problem+json")
    body = refused.json()
    assert body["code"] == "RATE_LIMITED"
    assert body["status"] == 429
    assert body["correlation_id"] == refused.headers["X-Correlation-ID"]


def test_a_locked_account_refuses_even_the_right_password(client, repo, limits):
    repo.make("alice")
    for _ in range(3):
        attempt(client, "alice", "faux")
    assert attempt(client, "alice").status_code == 429


def test_the_lock_lifts_when_the_time_has_passed(client, repo, limits, clock):
    repo.make("alice")
    for _ in range(3):
        attempt(client, "alice", "faux")
    assert attempt(client, "alice").status_code == 429
    clock.now += 900
    assert attempt(client, "alice").status_code == 200


def test_retry_after_shrinks_as_time_passes(client, repo, limits, clock):
    repo.make("alice")
    for _ in range(3):
        attempt(client, "alice", "faux")
    clock.now += 100
    assert attempt(client, "alice").headers["Retry-After"] == "800"


def test_a_good_login_forgets_the_earlier_failures(client, repo, limits):
    repo.make("alice")
    for _ in range(2):
        assert attempt(client, "alice", "faux").status_code == 401
    assert attempt(client, "alice").status_code == 200
    for _ in range(2):
        assert attempt(client, "alice", "faux").status_code == 401


def test_an_unknown_account_is_limited_exactly_like_a_known_one(client, repo, limits):
    """La limite ne révèle pas si un identifiant existe : mêmes réponses, mêmes délais."""
    repo.make("alice")
    seen = {}
    for name in ("alice", "inconnu-de-tous"):
        statuses = [attempt(client, name, "faux").status_code for _ in range(4)]
        last = attempt(client, name, "faux")
        seen[name] = (
            statuses,
            last.status_code,
            last.headers["Retry-After"],
            last.json()["detail"],
        )
    assert seen["alice"] == seen["inconnu-de-tous"]


def test_the_lock_follows_the_account_not_the_case_of_its_name(client, repo, limits):
    repo.make("alice")
    for name in ("alice", "ALICE", " Alice ", "alice"):
        attempt(client, name, "faux")
    assert attempt(client, "alice").status_code == 429


def test_one_account_locked_does_not_lock_the_others(client, repo, limits):
    repo.make("alice")
    repo.make("bob")
    for _ in range(3):
        attempt(client, "alice", "faux")
    assert attempt(client, "bob").status_code == 200


def test_one_client_is_limited_whatever_the_account(client, repo, tight, clock):
    for name in ("aaa", "bbb", "ccc", "ddd"):
        assert attempt(client, name, "faux").status_code == 401
    refused = attempt(client, "eee", "faux")
    assert refused.status_code == 429
    assert refused.headers["Retry-After"] == "60"
    clock.now += 60
    assert attempt(client, "eee", "faux").status_code == 401


def test_a_request_the_validation_refuses_is_not_counted(client, repo, limits):
    repo.make("alice")
    for _ in range(10):
        assert client.post(LOGIN, json={"username": "al"}).status_code == 422
    assert attempt(client, "alice").status_code == 200


def test_when_authentication_is_not_configured_the_answer_is_503_and_no_failure_is_counted(
    client, repo, limits, monkeypatch
):
    monkeypatch.delenv("JWT_SECRET")
    get_settings.cache_clear()
    for _ in range(6):
        assert attempt(client, "alice").status_code == 503
    monkeypatch.setenv("JWT_SECRET", "-".join(["essai"] * 8))
    get_settings.cache_clear()
    repo.make("alice")
    assert attempt(client, "alice").status_code == 200


def test_the_limit_applies_to_the_login_route_only(client, repo, limits):
    repo.make("alice")
    for _ in range(3):
        attempt(client, "alice", "faux")
    assert attempt(client, "alice").status_code == 429
    assert client.get("/api/v1/health").status_code == 200


def test_a_refused_attempt_is_audited_as_anonymous_with_its_status(client, repo, limits, journal):
    repo.make("alice")
    for _ in range(4):
        attempt(client, "alice", "faux")
    entry = journal.entries[-1]
    assert entry["details"]["status"] == 429
    assert entry["outcome"] == "denied"
    assert entry["actor"] == "anonymous"


def test_a_limited_attempt_is_logged_without_the_name_or_the_address(client, repo, limits, caplog):
    for _ in range(3):
        attempt(client, "alice-la-cible", "faux", **{"X-Forwarded-For": "203.0.113.55"})
    caplog.clear()
    attempt(client, "alice-la-cible", "faux", **{"X-Forwarded-For": "203.0.113.55"})
    (record,) = [r for r in caplog.records if r.name == "app.auth"]
    assert record.levelname == "WARNING"
    assert record.fields == {"retry_after_s": 900}
    assert "alice-la-cible" not in caplog.text
    assert "203.0.113.55" not in caplog.text


# --- Adresse du client ------------------------------------------------------------------------


def test_without_a_trusted_proxy_a_client_cannot_dodge_the_limit_with_the_forwarded_header(
    client, repo, tight
):
    """À 0 relais, un client qui change `X-Forwarded-For` à chaque essai ne contourne rien."""
    for index in range(4):
        forged = {"X-Forwarded-For": f"203.0.113.{index}"}
        assert attempt(client, f"nom{index}", "faux", **forged).status_code == 401
    assert attempt(client, "nom9", "faux", **{"X-Forwarded-For": "203.0.113.99"}).status_code == 429


def test_behind_a_trusted_proxy_two_clients_have_their_own_budget(client, repo, tight, monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    get_settings.cache_clear()
    for index in range(4):
        attempt(client, f"nom{index}", "faux", **{"X-Forwarded-For": "203.0.113.1"})
    assert attempt(client, "nom9", "faux", **{"X-Forwarded-For": "203.0.113.1"}).status_code == 429
    assert attempt(client, "nom9", "faux", **{"X-Forwarded-For": "203.0.113.2"}).status_code == 401


def test_behind_a_trusted_proxy_a_forged_left_entry_does_not_help_the_client(
    client, repo, tight, monkeypatch
):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    get_settings.cache_clear()
    for index in range(4):
        forged = f"198.51.100.{index}, 203.0.113.1"  # le relais a vu 203.0.113.1
        attempt(client, f"nom{index}", "faux", **{"X-Forwarded-For": forged})
    refused = attempt(client, "nom9", "faux", **{"X-Forwarded-For": "198.51.100.77, 203.0.113.1"})
    assert refused.status_code == 429


# --- Réglages par défaut ----------------------------------------------------------------------


def test_the_default_limits_are_the_documented_ones():
    settings = get_settings()
    assert (settings.login_attempts_per_minute, settings.login_max_failures) == (10, 5)
    assert settings.login_lockout_s == 900
    assert settings.trusted_proxy_hops == 0


def test_the_real_throttle_is_shared_by_all_requests_and_rebuilt_when_the_settings_change(
    client, repo, monkeypatch
):
    repo.make("alice")
    for _ in range(5):
        assert attempt(client, "alice", "faux").status_code == 401
    assert attempt(client, "alice").status_code == 429, "un seul limiteur pour tout le processus"
    monkeypatch.setenv("LOGIN_MAX_FAILURES", "8")
    get_settings.cache_clear()
    assert attempt(client, "alice").status_code == 200, "une autre configuration, un autre compteur"
