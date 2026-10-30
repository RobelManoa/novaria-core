"""Empreintes de mots de passe (argon2id) et jetons d'accès JWT (HS256) : BE-03.

Rien ici ne touche à la base ni à HTTP : fonctions pures, testables seules.
Revendications du jeton (contrat OpenAPI, README « Authentification ») : `sub` (identifiant de
l'utilisateur), `role`, `iat`, `exp`. L'algorithme est fixé à HS256 et jamais lu dans le jeton :
un jeton qui annonce `alg: none` ou un autre algorithme est refusé.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.models import Role

ALGORITHM = "HS256"
REQUIRED_CLAIMS = ("sub", "role", "iat", "exp")

_hasher = PasswordHasher()  # argon2id, paramètres par défaut de la bibliothèque (recommandés)


class InvalidToken(Exception):
    """Jeton illisible, mal signé, expiré ou incomplet (aucun détail n'est donné au client)."""


@dataclass(frozen=True)
class AccessToken:
    value: str
    expires_in: int


@dataclass(frozen=True)
class Claims:
    user_id: uuid.UUID
    role: Role
    issued_at: datetime
    expires_at: datetime


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Vrai si le mot de passe correspond à l'empreinte ; faux dans tous les autres cas."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


@lru_cache
def _decoy_hash() -> str:
    return hash_password("mot-de-passe-leurre-jamais-utilise")


def verify_against_decoy(password: str) -> None:
    """Dépense le même temps qu'une vraie vérification quand l'utilisateur n'existe pas.

    Sans cela, une réponse plus rapide révélerait qu'un identifiant est inconnu.
    """
    verify_password(_decoy_hash(), password)


def create_access_token(
    user_id: uuid.UUID, role: Role, *, secret: str, ttl_s: int, now: datetime | None = None
) -> AccessToken:
    issued_at = (now or datetime.now(UTC)).replace(microsecond=0)
    payload = {
        "sub": str(user_id),
        "role": role.value,
        "iat": issued_at,
        "exp": issued_at + timedelta(seconds=ttl_s),
    }
    return AccessToken(jwt.encode(payload, secret, algorithm=ALGORITHM), ttl_s)


def decode_access_token(token: str, *, secret: str) -> Claims:
    """Vérifie signature, algorithme, expiration et présence des revendications."""
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],
            options={"require": list(REQUIRED_CLAIMS)},
        )
        return Claims(
            user_id=uuid.UUID(payload["sub"]),
            role=Role(payload["role"]),
            issued_at=datetime.fromtimestamp(payload["iat"], UTC),
            expires_at=datetime.fromtimestamp(payload["exp"], UTC),
        )
    except (jwt.PyJWTError, ValueError, TypeError, KeyError) as error:
        raise InvalidToken from error
