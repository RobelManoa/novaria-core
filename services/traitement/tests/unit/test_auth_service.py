"""Connexion, vérification du jeton et hiérarchie des rôles (BE-03) : sans HTTP ni base."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.security import create_access_token
from app.models import Role
from app.services import auth as auth_module
from app.services.auth import (
    ROLE_LEVEL,
    AuthNotConfigured,
    AuthService,
    InvalidCredentials,
    NotAuthenticated,
    has_at_least,
)
from tests.fakes import PASSWORD, SECRET, TTL_S, FakeUserRepository


@pytest.fixture
def repo():
    return FakeUserRepository()


@pytest.fixture
def service(repo):
    return AuthService(repo, secret=SECRET, ttl_s=TTL_S)


def test_the_roles_are_hierarchical():
    assert ROLE_LEVEL == {Role.VIEWER: 1, Role.OPERATOR: 2, Role.ADMIN: 3}
    for role in Role:
        assert has_at_least(role, role)
    assert has_at_least(Role.ADMIN, Role.OPERATOR)
    assert has_at_least(Role.ADMIN, Role.VIEWER)
    assert has_at_least(Role.OPERATOR, Role.VIEWER)
    assert not has_at_least(Role.VIEWER, Role.OPERATOR)
    assert not has_at_least(Role.VIEWER, Role.ADMIN)
    assert not has_at_least(Role.OPERATOR, Role.ADMIN)


def test_a_login_with_the_right_password_gives_a_token_for_that_user(repo, service):
    user = repo.make("alice", Role.OPERATOR)
    jeton = service.login("alice", PASSWORD)
    assert jeton.expires_in == TTL_S
    assert service.authenticate(jeton.value) is user


def test_a_wrong_password_an_unknown_user_and_a_disabled_account_give_the_same_error(repo, service):
    repo.make("alice")
    repo.make("desactive", active=False)
    for username, password in (("alice", "faux"), ("inconnu", PASSWORD), ("desactive", PASSWORD)):
        with pytest.raises(InvalidCredentials):
            service.login(username, password)


def test_an_unknown_user_still_costs_a_hash_verification(service, monkeypatch):
    appels = []
    monkeypatch.setattr(auth_module, "verify_against_decoy", lambda p: appels.append(p))
    with pytest.raises(InvalidCredentials):
        service.login("inconnu", "essai")
    assert appels == ["essai"]


def test_a_known_user_does_not_trigger_the_decoy(repo, service, monkeypatch):
    repo.make("alice")
    appels = []
    monkeypatch.setattr(auth_module, "verify_against_decoy", lambda p: appels.append(p))
    service.login("alice", PASSWORD)
    assert appels == []


def test_a_disabled_account_with_the_right_password_is_refused_after_checking_it(
    repo, service, monkeypatch
):
    repo.make("desactive", active=False)
    verifies = []
    reel = auth_module.verify_password
    monkeypatch.setattr(
        auth_module, "verify_password", lambda h, p: verifies.append(1) or reel(h, p)
    )
    with pytest.raises(InvalidCredentials):
        service.login("desactive", PASSWORD)
    assert verifies == [1], "le temps ne dit pas que le compte existe"


def test_without_a_secret_nothing_is_issued_nor_verified(repo):
    repo.make("alice")
    sans_secret = AuthService(repo, secret=None, ttl_s=TTL_S)
    with pytest.raises(AuthNotConfigured):
        sans_secret.login("alice", PASSWORD)
    with pytest.raises(AuthNotConfigured):
        sans_secret.authenticate("x.y.z")
    with pytest.raises(AuthNotConfigured):
        AuthService(repo, secret="", ttl_s=TTL_S).login("alice", PASSWORD)


def test_authenticate_refuses_garbage_and_expired_tokens(repo, service):
    user = repo.make("alice")
    with pytest.raises(NotAuthenticated):
        service.authenticate("pas-un-jeton")
    vieux = datetime.now(UTC) - timedelta(seconds=TTL_S + 60)
    expire = create_access_token(user.user_id, user.role, secret=SECRET, ttl_s=TTL_S, now=vieux)
    with pytest.raises(NotAuthenticated):
        service.authenticate(expire.value)


def test_a_token_of_a_deleted_or_disabled_account_stops_working_at_once(repo, service):
    user = repo.make("alice")
    jeton = service.login("alice", PASSWORD).value
    assert service.authenticate(jeton) is user
    user.is_active = False
    with pytest.raises(NotAuthenticated):
        service.authenticate(jeton)
    del repo.users[user.user_id]
    with pytest.raises(NotAuthenticated):
        service.authenticate(jeton)


def test_the_role_that_counts_is_the_one_in_the_database_not_the_one_in_the_token(repo, service):
    user = repo.make("alice", Role.ADMIN)
    jeton = service.login("alice", PASSWORD).value
    user.role = Role.VIEWER
    assert service.authenticate(jeton).role is Role.VIEWER


def test_a_token_for_an_unknown_identifier_is_refused(service):
    jeton = create_access_token(uuid.uuid4(), Role.ADMIN, secret=SECRET, ttl_s=TTL_S)
    with pytest.raises(NotAuthenticated):
        service.authenticate(jeton.value)


def test_the_logs_never_contain_the_password_or_the_username(repo, service, caplog):
    repo.make("alice")
    caplog.set_level("INFO", logger="app.auth")
    with pytest.raises(InvalidCredentials):
        service.login("alice", "mot-de-passe-secret-faux")
    service.login("alice", PASSWORD)
    texte = " ".join(f"{r.getMessage()} {getattr(r, 'fields', '')}" for r in caplog.records)
    assert "mot-de-passe-secret-faux" not in texte
    assert PASSWORD not in texte
    assert "alice" not in texte
    assert "wrong_password" in texte
