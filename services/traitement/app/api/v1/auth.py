"""Connexion et identité de l'appelant (BE-03) : `/api/v1/auth/login` et `/api/v1/auth/me`.

La connexion est limitée en débit (BE-08, `app/core/ratelimit.py`) : trop d'essais d'une même
adresse, ou trop d'échecs sur un même identifiant, donnent `429` et `Retry-After`.
"""

import logging

from fastapi import APIRouter, Depends, Request

from app.api.deps import (
    auth_not_configured,
    client_address,
    get_auth_service,
    get_login_throttle,
    rate_limited,
    require_role,
)
from app.api.responses import errors
from app.core.config import Settings, get_settings
from app.core.errors import INVALID_CREDENTIALS, ProblemError
from app.core.ratelimit import LoginThrottle, RateLimited
from app.models import Role, User
from app.schemas.users import LoginRequest, TokenResponse, UserResponse
from app.services.auth import AuthNotConfigured, AuthService, InvalidCredentials

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger("app.auth")


@router.post("/login", response_model=TokenResponse, responses=errors(401, 422, 429, "5XX"))
def login(
    body: LoginRequest,
    request: Request,
    auth: AuthService = Depends(get_auth_service),
    throttle: LoginThrottle = Depends(get_login_throttle),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    """Vérifie les identifiants et émet un jeton d'accès (route publique, limitée en débit)."""
    try:
        throttle.admit(client_address(request, settings), body.username)
    except RateLimited as error:
        # Ni identifiant ni adresse dans le journal : seulement qu'une limite a joué, et pour
        # combien de temps.
        logger.warning(
            "connexion limitée", extra={"fields": {"retry_after_s": error.retry_after_s}}
        )
        raise rate_limited(error) from error
    try:
        token = auth.login(body.username, body.password)
    except InvalidCredentials as error:
        throttle.failed(body.username)
        raise ProblemError(INVALID_CREDENTIALS, "Identifiant ou mot de passe incorrect.") from error
    except AuthNotConfigured as error:
        raise auth_not_configured() from error
    throttle.succeeded(body.username)
    request.state.actor = str(token.user_id)  # pour l'audit : le compte qui vient de se connecter
    return TokenResponse(access_token=token.value, expires_in=token.expires_in)


@router.get(
    "/me",
    response_model=UserResponse,
    openapi_extra={"x-required-role": Role.VIEWER.value},
    responses=errors(401, "5XX"),
)
def me(user: User = Depends(require_role(Role.VIEWER))) -> User:
    """Utilisateur associé au jeton."""
    return user
