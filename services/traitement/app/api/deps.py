"""Dépendances FastAPI de l'authentification et de l'autorisation (BE-03).

- `current_user` : sans jeton valide, 401 (`UNAUTHENTICATED`) ;
- `require_role(minimum)` : jeton valide mais rôle insuffisant, 403 (`FORBIDDEN`).
Une route protégée s'écrit `Depends(require_role(Role.ADMIN))` et déclare le même rôle dans
`openapi_extra={"x-required-role": "admin"}` : un test de contrat vérifie que les deux concordent.
"""

from collections.abc import Callable

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings
from app.core.errors import FORBIDDEN, UNAUTHENTICATED, UPSTREAM_UNAVAILABLE, ProblemError
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


def get_auth_service(
    settings: Settings = Depends(get_settings),
    users: UserRepository = Depends(get_user_repository),
) -> AuthService:
    secret = settings.jwt_secret.get_secret_value() if settings.jwt_secret else None
    return AuthService(users, secret=secret, ttl_s=settings.access_token_ttl_s)


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    auth: AuthService = Depends(get_auth_service),
) -> User:
    if credentials is None:
        raise unauthenticated()
    try:
        return auth.authenticate(credentials.credentials)
    except NotAuthenticated as error:
        raise unauthenticated() from error
    except AuthNotConfigured as error:
        raise auth_not_configured() from error


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
