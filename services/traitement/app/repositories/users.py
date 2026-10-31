"""Accès aux utilisateurs du schéma `app` (BE-02) : l'interface et son implémentation SQLAlchemy.

Les services ne dépendent que de `UserRepository` : les tests d'autorisation tournent sur un
dépôt en mémoire, la base réelle est vérifiée par les tests d'intégration.
"""

import uuid
from datetime import datetime
from typing import Protocol

from sqlalchemy import select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Role, User

USERNAME_CONSTRAINT = "uq_users_username"


class DuplicateUsername(Exception):
    """Ce nom d'utilisateur existe déjà."""


class UserRepository(Protocol):
    def get_by_username(self, username: str) -> User | None: ...

    def get(self, user_id: uuid.UUID) -> User | None: ...

    def add(self, user: User) -> User:
        """Enregistre l'utilisateur ; lève `DuplicateUsername` si le nom est pris."""

    def list_page(
        self, *, limit: int, after: tuple[datetime, uuid.UUID] | None, role: Role | None
    ) -> list[User]:
        """Au plus `limit` utilisateurs après `after`, par date de création puis identifiant."""


class SqlUserRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_username(self, username: str) -> User | None:
        return self._session.scalar(select(User).where(User.username == username))

    def get(self, user_id: uuid.UUID) -> User | None:
        return self._session.get(User, user_id)

    def add(self, user: User) -> User:
        self._session.add(user)
        try:
            self._session.commit()
        except IntegrityError as error:
            self._session.rollback()
            if USERNAME_CONSTRAINT in str(error.orig):
                raise DuplicateUsername(user.username) from error
            raise
        self._session.refresh(user)
        return user

    def list_page(
        self, *, limit: int, after: tuple[datetime, uuid.UUID] | None, role: Role | None
    ) -> list[User]:
        query = select(User).order_by(User.created_at, User.user_id).limit(limit)
        if role is not None:
            query = query.where(User.role == role)
        if after is not None:
            query = query.where(tuple_(User.created_at, User.user_id) > tuple_(*after))
        return list(self._session.scalars(query))
