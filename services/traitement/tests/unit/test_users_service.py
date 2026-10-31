"""Comptes : création, lecture, pagination par curseur, configuration d'authentification (BE-03)."""

import pytest
from pydantic import ValidationError

from app.core.config import JWT_SECRET_MIN_LENGTH, Settings
from app.core.security import verify_password
from app.models import Role
from app.repositories.users import DuplicateUsername
from app.services.users import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    InvalidCursor,
    UserService,
    decode_cursor,
    encode_cursor,
)
from tests.fakes import PASSWORD, FakeUserRepository


@pytest.fixture
def repo():
    return FakeUserRepository()


@pytest.fixture
def service(repo):
    return UserService(repo)


def test_a_created_account_keeps_a_hash_and_never_the_password(service):
    user = service.create("alice", PASSWORD, Role.OPERATOR)
    assert user.password_hash != PASSWORD
    assert PASSWORD not in user.password_hash
    assert verify_password(user.password_hash, PASSWORD)
    assert (user.username, user.role, user.is_active) == ("alice", Role.OPERATOR, True)
    assert service.get(user.user_id) is user


def test_a_taken_username_is_refused(service):
    service.create("alice", PASSWORD, Role.VIEWER)
    with pytest.raises(DuplicateUsername):
        service.create("alice", PASSWORD, Role.ADMIN)


def test_an_unknown_identifier_gives_nothing(service):
    import uuid

    assert service.get(uuid.uuid4()) is None


def fill(repo, count):
    for numero in range(count):
        repo.make(f"user{numero:02d}", Role.ADMIN if numero % 5 == 0 else Role.VIEWER)


def test_pages_follow_one_another_without_gap_or_overlap(repo, service):
    fill(repo, 7)
    vus, curseur = [], None
    pages = 0
    while True:
        page = service.list_page(limit=3, cursor=curseur)
        vus += [u.username for u in page.items]
        pages += 1
        curseur = page.next_cursor
        if curseur is None:
            break
    assert pages == 3
    assert vus == [f"user{n:02d}" for n in range(7)]


def test_the_last_page_has_no_next_cursor_even_when_it_is_full(repo, service):
    fill(repo, 6)
    premiere = service.list_page(limit=3)
    assert premiere.next_cursor is not None
    derniere = service.list_page(limit=3, cursor=premiere.next_cursor)
    assert len(derniere.items) == 3
    assert derniere.next_cursor is None


def test_an_empty_list_is_a_page_without_cursor(service):
    page = service.list_page()
    assert (page.items, page.next_cursor) == ([], None)


def test_the_role_filter_keeps_only_that_role_across_pages(repo, service):
    fill(repo, 12)
    page = service.list_page(limit=2, role=Role.ADMIN)
    assert [u.username for u in page.items] == ["user00", "user05"]
    suite = service.list_page(limit=2, cursor=page.next_cursor, role=Role.ADMIN)
    assert [u.username for u in suite.items] == ["user10"]
    assert suite.next_cursor is None


def test_the_limits_are_those_of_the_contract():
    assert (DEFAULT_LIMIT, MAX_LIMIT) == (100, 500)


def test_a_cursor_round_trips_and_is_url_safe(repo):
    user = repo.make("alice")
    curseur = encode_cursor(user)
    assert "=" not in curseur and "+" not in curseur and "/" not in curseur
    assert decode_cursor(curseur) == (user.created_at, user.user_id)


@pytest.mark.parametrize("curseur", ["!!!", "abc", "", "YWJj", "MjAyNnx4", "Zm9vfGJhcg"])
def test_a_cursor_not_made_by_the_service_is_refused(curseur):
    with pytest.raises(InvalidCursor):
        decode_cursor(curseur)


def test_the_authentication_settings_have_safe_defaults():
    reglages = Settings(_env_file=None)
    assert reglages.jwt_secret is None, "aucun secret par défaut"
    assert reglages.app_database_url is None
    assert reglages.access_token_ttl_s == 1800


def test_a_secret_shorter_than_the_minimum_is_refused_at_startup():
    with pytest.raises(ValidationError, match="au moins 32"):
        Settings(_env_file=None, jwt_secret="x" * (JWT_SECRET_MIN_LENGTH - 1))
    assert Settings(_env_file=None, jwt_secret="x" * JWT_SECRET_MIN_LENGTH).jwt_secret


def test_the_secret_and_the_database_address_do_not_appear_in_the_representation():
    reglages = Settings(
        _env_file=None,
        jwt_secret="s" * 40,
        app_database_url="postgresql+psycopg://svc_app:motdepasse@h/d",
    )
    texte = repr(reglages) + str(reglages.model_dump())
    assert "s" * 40 not in texte
    assert "motdepasse" not in texte


@pytest.mark.parametrize("ttl", [59, 86401, 0, -1])
def test_a_token_lifetime_outside_one_minute_to_one_day_is_refused(ttl):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, access_token_ttl_s=ttl)


def test_the_token_lifetime_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("ACCESS_TOKEN_TTL_S", "900")
    monkeypatch.setenv("JWT_SECRET", "k" * 40)
    reglages = Settings(_env_file=None)
    assert reglages.access_token_ttl_s == 900
    assert reglages.jwt_secret.get_secret_value() == "k" * 40
