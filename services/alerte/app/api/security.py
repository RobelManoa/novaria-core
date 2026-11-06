"""Authentification des routes : jeton de l'API métier vérifié ici, rôle exigé par route.

Le service ne crée aucun jeton : `current_claims` vérifie celui que l'API métier a émis (même clé
`JWT_SECRET`), `require_role` exige un rôle minimal. 401 sans jeton valide, 403 si le rôle est
insuffisant, 503 si la clé n'est pas configurée. Copie identique dans les services qui vérifient
eux-mêmes les jetons (alerte, réponse) : `scripts/dev/test_gabarit.py` (CODE_PARTAGE).
"""

from collections.abc import Callable

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.auth import Claims, InvalidToken, Role, decode_token, has_at_least
from app.core.config import Settings, get_settings
from app.core.errors import UPSTREAM_UNAVAILABLE, ProblemError
from app.core.problems import FORBIDDEN, UNAUTHENTICATED

# `auto_error=False` : l'erreur est produite ici, au format `application/problem+json`.
bearer_scheme = HTTPBearer(auto_error=False, bearerFormat="JWT")


def unauthenticated() -> ProblemError:
    return ProblemError(
        UNAUTHENTICATED,
        "Jeton absent, invalide ou expiré.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def current_claims(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> Claims:
    if credentials is None:
        raise unauthenticated()
    if settings.jwt_secret is None:
        raise ProblemError(
            UPSTREAM_UNAVAILABLE, "L'authentification n'est pas configurée sur ce service."
        )
    try:
        return decode_token(credentials.credentials, secret=settings.jwt_secret.get_secret_value())
    except InvalidToken as error:
        raise unauthenticated() from error


def require_role(minimum: Role) -> Callable[..., Claims]:
    """401 sans jeton valide, 403 si le rôle est insuffisant. Même contrat que l'API métier."""

    def dependency(claims: Claims = Depends(current_claims)) -> Claims:
        if not has_at_least(claims.role, minimum):
            raise ProblemError(
                FORBIDDEN,
                f"Le rôle `{claims.role.value}` ne permet pas cette opération ; "
                f"rôle requis `{minimum.value}`.",
            )
        return claims

    return dependency
