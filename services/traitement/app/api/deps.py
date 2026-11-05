"""Dépendances FastAPI de l'authentification et de l'autorisation (BE-03).

- `current_user` : sans jeton valide, 401 (`UNAUTHENTICATED`) ;
- `require_role(minimum)` : jeton valide mais rôle insuffisant, 403 (`FORBIDDEN`).
Une route protégée s'écrit `Depends(require_role(Role.ADMIN))` et déclare le même rôle dans
`openapi_extra={"x-required-role": "admin"}` : un test de contrat vérifie que les deux concordent.
"""

from collections.abc import Callable

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings
from app.core.errors import (
    FORBIDDEN,
    RATE_LIMITED,
    UNAUTHENTICATED,
    UPSTREAM_UNAVAILABLE,
    ProblemError,
)
from app.core.ratelimit import LoginThrottle, RateLimited, forwarded_address
from app.db.session import get_user_repository
from app.models import Role, User
from app.repositories.users import UserRepository
from app.services.auth import AuthNotConfigured, AuthService, NotAuthenticated, has_at_least

# `auto_error=False` : l'erreur est produite ici, au format `application/problem+json`.
bearer_scheme = HTTPBearer(auto_error=False, bearerFormat="JWT")


def auth_not_configured() -> ProblemError:
    return ProblemError(
        UPSTREAM_UNAVAILABLE, "L'authentification n'est pas configurée sur ce service."
    )


def unauthenticated() -> ProblemError:
    return ProblemError(
        UNAUTHENTICATED,
        "Jeton absent, invalide ou expiré.",
        headers={"WWW-Authenticate": "Bearer"},
    )


# Une seule limite pour tout le processus (sinon chaque requête repartirait de zéro).
# Reconstruite si la configuration change : c'est ce qui arrive entre deux tests, ou après
# `get_settings.cache_clear()`.
_login_throttle: tuple[tuple[int, int, int], LoginThrottle] | None = None


def get_login_throttle(settings: Settings = Depends(get_settings)) -> LoginThrottle:
    global _login_throttle  # noqa: PLW0603 - état volontairement partagé par le processus
    shape = (
        settings.login_attempts_per_minute,
        settings.login_max_failures,
        settings.login_lockout_s,
    )
    if _login_throttle is None or _login_throttle[0] != shape:
        _login_throttle = (
            shape,
            LoginThrottle(attempts_per_minute=shape[0], max_failures=shape[1], lockout_s=shape[2]),
        )
    return _login_throttle[1]


def reset_login_throttle() -> None:
    """Oublie tous les essais (tests)."""
    global _login_throttle  # noqa: PLW0603
    _login_throttle = None


def client_address(request: Request, settings: Settings) -> str | None:
    peer = request.client.host if request.client else None
    return forwarded_address(
        peer, request.headers.get("x-forwarded-for"), settings.trusted_proxy_hops
    )


def rate_limited(error: RateLimited) -> ProblemError:
    return ProblemError(
        RATE_LIMITED,
        "Trop de tentatives de connexion. Réessayez plus tard.",
        headers={"Retry-After": str(error.retry_after_s)},
    )


def get_auth_service(
    settings: Settings = Depends(get_settings),
    users: UserRepository = Depends(get_user_repository),
) -> AuthService:
    secret = settings.jwt_secret.get_secret_value() if settings.jwt_secret else None
    return AuthService(users, secret=secret, ttl_s=settings.access_token_ttl_s)


def current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    auth: AuthService = Depends(get_auth_service),
) -> User:
    if credentials is None:
        raise unauthenticated()
    try:
        user = auth.authenticate(credentials.credentials)
    except NotAuthenticated as error:
        raise unauthenticated() from error
    except AuthNotConfigured as error:
        raise auth_not_configured() from error
    # L'audit lit ces deux valeurs après la réponse : qui a appelé, même si l'appel est refusé.
    request.state.actor = str(user.user_id)
    request.state.role = user.role.value
    return user


def require_role(minimum: Role) -> Callable[..., User]:
    def dependency(user: User = Depends(current_user)) -> User:
        if not has_at_least(user.role, minimum):
            raise ProblemError(
                FORBIDDEN,
                f"Le rôle `{user.role.value}` ne permet pas cette opération ; "
                f"rôle requis `{minimum.value}`.",
            )
        return user

    return dependency
