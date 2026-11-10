"""Vérification des jetons d'accès émis par l'API métier (BE-03) : JWT HS256, même clé `JWT_SECRET`.

Ce service ne crée aucun jeton et ne connaît aucun utilisateur : il vérifie la signature,
l'algorithme (fixé à HS256, jamais lu dans le jeton : `alg: none` est refusé), l'expiration et
la présence des revendications `sub`, `role`, `iat`, `exp`. Les rôles et leur ordre sont ceux du
contrat OpenAPI.
"""

from dataclasses import dataclass
from enum import StrEnum

import jwt

ALGORITHM = "HS256"
REQUIRED_CLAIMS = ("sub", "role", "iat", "exp")


class Role(StrEnum):
    """Du plus faible au plus fort."""

    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"


LEVEL = {Role.VIEWER: 0, Role.OPERATOR: 1, Role.ADMIN: 2}


class InvalidToken(Exception):
    """Jeton illisible, mal signé, expiré ou incomplet (aucun détail n'est donné au client)."""


@dataclass(frozen=True)
class Claims:
    subject: str  # identifiant de l'utilisateur : ce qui s'écrit dans `acknowledged_by`
    role: Role


def has_at_least(role: Role, minimum: Role) -> bool:
    return LEVEL[role] >= LEVEL[minimum]


def decode_token(token: str, *, secret: str) -> Claims:
    try:
        payload = jwt.decode(
            token, secret, algorithms=[ALGORITHM], options={"require": list(REQUIRED_CLAIMS)}
        )
        subject = payload["sub"]
        if not isinstance(subject, str) or not subject:
            raise ValueError("sub")
        return Claims(subject, Role(payload["role"]))
    except (jwt.PyJWTError, ValueError, TypeError, KeyError) as error:
        raise InvalidToken from error
