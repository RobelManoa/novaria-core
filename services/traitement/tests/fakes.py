"""Dépôt d'utilisateurs en mémoire pour les tests d'authentification et d'autorisation (BE-03).

Même comportement que `SqlUserRepository` sur ce que les services utilisent : unicité du nom,
valeurs par défaut posées à l'écriture, tri par date de création puis identifiant.
"""

import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from app.core.security import create_access_token, hash_password
from app.models import Role, User
from app.repositories.users import DuplicateUsername

PASSWORD = "mot-de-passe-de-test-12"
SECRET = "secret-de-test-0123456789-0123456789-0123456789"
TTL_S = 1800
ORIGIN = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)


@lru_cache
def hash_of(password: str) -> str:
    """Une empreinte argon2id par mot de passe : le calcul est volontairement lent."""
    return hash_password(password)


class FakeUserRepository:
    def __init__(self) -> None:
        self.users: dict[uuid.UUID, User] = {}

    def get_by_username(self, username: str) -> User | None:
        return next((u for u in self.users.values() if u.username == username), None)

    def get(self, user_id: uuid.UUID) -> User | None:
        return self.users.get(user_id)

    def add(self, user: User) -> User:
        if self.get_by_username(user.username) is not None:
            raise DuplicateUsername(user.username)
        user.user_id = user.user_id or uuid.uuid4()
        user.is_active = True if user.is_active is None else user.is_active
        user.created_at = user.created_at or ORIGIN + timedelta(seconds=len(self.users))
        self.users[user.user_id] = user
        return user

    def list_page(self, *, limit, after, role):
        rows = sorted(self.users.values(), key=lambda u: (u.created_at, u.user_id))
        if role is not None:
            rows = [u for u in rows if u.role == role]
        if after is not None:
            rows = [u for u in rows if (u.created_at, u.user_id) > after]
        return rows[:limit]

    def make(
        self,
        username: str,
        role: Role = Role.VIEWER,
        *,
        password: str = PASSWORD,
        active: bool = True,
    ) -> User:
        return self.add(
            User(username=username, password_hash=hash_of(password), role=role, is_active=active)
        )


def bearer(user: User, *, secret: str = SECRET) -> dict[str, str]:
    """En-tête d'un jeton valide pour cet utilisateur."""
    token = create_access_token(user.user_id, user.role, secret=secret, ttl_s=TTL_S)
    return {"Authorization": f"Bearer {token.value}"}
