"""Jetons d'essai : signés avec une clé générée à l'exécution, jamais écrite dans le dépôt."""

import secrets
import time

import jwt

KEY = secrets.token_urlsafe(48)


def bearer(
    role: str = "viewer", *, sub: str = "user-1", key: str = KEY, lifetime: int = 600
) -> dict:
    """L'en-tête `Authorization` d'un appelant ; `lifetime` négatif : un jeton déjà expiré."""
    issued = int(time.time())
    claims = {"sub": sub, "role": role, "iat": issued, "exp": issued + lifetime}
    return {"Authorization": "Bearer " + jwt.encode(claims, key, algorithm="HS256")}
