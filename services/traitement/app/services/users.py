"""Gestion des comptes : création, lecture, liste paginée par curseur (BE-03)."""

import base64
import binascii
import uuid
from dataclasses import dataclass
from datetime import datetime

from app.core.security import hash_password
from app.models import Role, User
from app.repositories.users import UserRepository

DEFAULT_LIMIT = 100
MAX_LIMIT = 500


class InvalidCursor(ValueError):
    """Le curseur n'a pas été produit par ce service."""


@dataclass(frozen=True)
class Page:
    items: list[User]
    next_cursor: str | None


def encode_cursor(user: User) -> str:
    raw = f"{user.created_at.isoformat()}|{user.user_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        moment, identifier = raw.split("|")
        return datetime.fromisoformat(moment), uuid.UUID(identifier)
    except (binascii.Error, UnicodeDecodeError, ValueError) as error:
        raise InvalidCursor(cursor) from error


class UserService:
    def __init__(self, users: UserRepository) -> None:
        self._users = users

    def create(self, username: str, password: str, role: Role) -> User:
        """Crée le compte ; lève `DuplicateUsername` si le nom est déjà pris."""
        user = User(username=username, password_hash=hash_password(password), role=role)
        return self._users.add(user)

    def get(self, user_id: uuid.UUID) -> User | None:
        return self._users.get(user_id)

    def list_page(
        self, *, limit: int = DEFAULT_LIMIT, cursor: str | None = None, role: Role | None = None
    ) -> Page:
        after = decode_cursor(cursor) if cursor else None
        rows = self._users.list_page(limit=limit + 1, after=after, role=role)
        page = rows[:limit]
        more = len(rows) > limit
        return Page(page, encode_cursor(page[-1]) if more else None)
