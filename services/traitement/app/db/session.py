"""Session SQLAlchemy du compte `svc_app` (schéma `app`), ouverte par requête (BE-03)."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.errors import UPSTREAM_UNAVAILABLE, ProblemError
from app.repositories.users import SqlUserRepository


class DatabaseNotConfigured(RuntimeError):
    """`APP_DATABASE_URL` n'est pas fournie."""


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    url = get_settings().app_database_url
    if url is None:
        raise DatabaseNotConfigured("Variable APP_DATABASE_URL absente.")
    engine = create_engine(url.get_secret_value(), pool_pre_ping=True)
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
