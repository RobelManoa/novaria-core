"""Connexion et identité de l'appelant (BE-03) : `/api/v1/auth/login` et `/api/v1/auth/me`."""

from fastapi import APIRouter, Depends

from app.api.deps import auth_not_configured, get_auth_service, require_role
from app.core.errors import INVALID_CREDENTIALS, ProblemError
from app.models import Role, User
from app.schemas.users import LoginRequest, TokenResponse, UserResponse
from app.services.auth import AuthNotConfigured, AuthService, InvalidCredentials

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, auth: AuthService = Depends(get_auth_service)) -> TokenResponse:
    """Vérifie les identifiants et émet un jeton d'accès (route publique)."""
    try:
        token = auth.login(body.username, body.password)
    except InvalidCredentials as error:
        raise ProblemError(INVALID_CREDENTIALS, "Identifiant ou mot de passe incorrect.") from error
    except AuthNotConfigured as error:
        raise auth_not_configured() from error
    return TokenResponse(access_token=token.value, expires_in=token.expires_in)


@router.get(
    "/me",
    response_model=UserResponse,
    openapi_extra={"x-required-role": Role.VIEWER.value},
)
def me(user: User = Depends(require_role(Role.VIEWER))) -> User:
    """Utilisateur associé au jeton."""
    return user
