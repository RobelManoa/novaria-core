"""Sessions SQLAlchemy ouvertes par requête : schéma `app` (BE-03), entrepôt `dwh` (BE-04)."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.errors import UPSTREAM_UNAVAILABLE, ProblemError
from app.repositories.indicators import SqlIndicatorRepository
from app.repositories.users import SqlUserRepository

# L'entrepôt est servi en lecture seule : PostgreSQL refuse toute écriture sur cette connexion.
READ_ONLY = {"options": "-c default_transaction_read_only=on"}


class DatabaseNotConfigured(RuntimeError):
    """`APP_DATABASE_URL` ou `POSTGRES_URL` n'est pas fournie."""


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    url = get_settings().app_database_url
    if url is None:
        raise DatabaseNotConfigured("Variable APP_DATABASE_URL absente.")
    engine = create_engine(url.get_secret_value(), pool_pre_ping=True)
    return sessionmaker(engine, expire_on_commit=False)


@lru_cache
def get_warehouse_session_factory() -> sessionmaker[Session]:
    url = get_settings().postgres_url
    if url is None:
        raise DatabaseNotConfigured("Variable POSTGRES_URL absente.")
    engine = create_engine(url.get_secret_value(), pool_pre_ping=True, connect_args=READ_ONLY)
    return sessionmaker(engine, expire_on_commit=False)


def get_user_repository() -> Iterator[SqlUserRepository]:
    try:
        factory = get_session_factory()
    except DatabaseNotConfigured as error:
        raise ProblemError(
            UPSTREAM_UNAVAILABLE, "La base des comptes n'est pas configurée."
        ) from error
    with factory() as session:
        yield SqlUserRepository(session)


def get_indicator_repository() -> Iterator[SqlIndicatorRepository]:
    try:
        factory = get_warehouse_session_factory()
    except DatabaseNotConfigured as error:
        raise ProblemError(
            UPSTREAM_UNAVAILABLE, "L'entrepôt de données n'est pas configuré."
        ) from error
    with factory() as session:
        yield SqlIndicatorRepository(session)
