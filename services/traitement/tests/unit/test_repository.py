"""Dépôt SQL des utilisateurs et session (BE-03), sans base : requêtes lues, pas exécutées.

Leur exécution réelle est vérifiée par `tests/integration/test_auth_postgres.py`.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.errors import ProblemError
from app.db import session as session_module
from app.models import Role, User
from app.repositories.users import DuplicateUsername, SqlUserRepository

APRES = (datetime(2026, 10, 1, 8, 0, tzinfo=UTC), uuid.UUID(int=7))


def sql_of(statement) -> str:
    return str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


def new_user() -> User:
    return User(username="alice", password_hash="$argon2id$x", role=Role.VIEWER)


def violation(contrainte: str) -> IntegrityError:
    return IntegrityError("INSERT", {}, Exception(f'violates constraint "{contrainte}"'))


def test_a_user_is_added_committed_and_refreshed():
    session = MagicMock()
    user = new_user()
    assert SqlUserRepository(session).add(user) is user
    session.add.assert_called_once_with(user)
    session.commit.assert_called_once_with()
    session.refresh.assert_called_once_with(user)


def test_a_taken_username_becomes_a_duplicate_error_and_the_session_is_rolled_back():
    session = MagicMock()
    session.commit.side_effect = violation("uq_users_username")
    with pytest.raises(DuplicateUsername):
        SqlUserRepository(session).add(new_user())
    session.rollback.assert_called_once_with()
    session.refresh.assert_not_called()


def test_any_other_integrity_error_is_not_hidden_as_a_duplicate():
    session = MagicMock()
    session.commit.side_effect = violation("ck_users_role_valid")
    with pytest.raises(IntegrityError):
        SqlUserRepository(session).add(new_user())
    session.rollback.assert_called_once_with()


def test_a_user_is_looked_up_by_username_with_a_bound_value():
    session = MagicMock()
    session.scalar.return_value = "résultat"
    assert SqlUserRepository(session).get_by_username("alice' OR '1'='1") == "résultat"
    statement = session.scalar.call_args.args[0]
    sql = sql_of(statement)
    assert "WHERE app.users.username = 'alice'' OR ''1''=''1'" in sql
    assert ":username_1" in str(statement) or "%(username_1)s" in str(statement.compile())


def test_a_user_is_looked_up_by_primary_key():
    session = MagicMock()
    identifiant = uuid.uuid4()
    SqlUserRepository(session).get(identifiant)
    session.get.assert_called_once_with(User, identifiant)


def test_a_page_is_ordered_and_limited_without_filter():
    session = MagicMock()
    session.scalars.return_value = iter([])
    assert SqlUserRepository(session).list_page(limit=5, after=None, role=None) == []
    sql = sql_of(session.scalars.call_args.args[0])
    assert "ORDER BY app.users.created_at, app.users.user_id" in sql
    assert "LIMIT 5" in sql
    assert "WHERE" not in sql


def test_a_page_starts_after_the_cursor_and_keeps_one_role():
    session = MagicMock()
    session.scalars.return_value = iter([])
    SqlUserRepository(session).list_page(limit=2, after=APRES, role=Role.ADMIN)
    sql = sql_of(session.scalars.call_args.args[0])
    assert "(app.users.created_at, app.users.user_id) >" in sql
    assert "app.users.role = 'admin'" in sql


def test_the_session_factory_needs_the_database_address(monkeypatch):
    monkeypatch.delenv("APP_DATABASE_URL", raising=False)
    get_settings.cache_clear()
    session_module.get_session_factory.cache_clear()
    with pytest.raises(session_module.DatabaseNotConfigured):
        session_module.get_session_factory()
    with pytest.raises(ProblemError) as erreur:
        next(session_module.get_user_repository())
    assert erreur.value.kind.status == 503
    get_settings.cache_clear()


def test_a_session_is_opened_per_request_and_closed_after_it(monkeypatch):
    monkeypatch.setenv("APP_DATABASE_URL", "sqlite://")
    get_settings.cache_clear()
    session_module.get_session_factory.cache_clear()
    try:
        generateur = session_module.get_user_repository()
        depot = next(generateur)
        assert isinstance(depot, SqlUserRepository)
        with pytest.raises(StopIteration):
            next(generateur)
    finally:
        session_module.get_session_factory.cache_clear()
        get_settings.cache_clear()
