"""Gestion des comptes, réservée aux administrateurs (BE-03) : `/api/v1/users`."""

import uuid

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import require_role
from app.core.errors import CONFLICT, NOT_FOUND, VALIDATION_ERROR, ProblemError
from app.db.session import get_user_repository
from app.models import Role, User
from app.repositories.users import DuplicateUsername, UserRepository
from app.schemas.users import UserCreate, UserPage, UserResponse
from app.services.users import DEFAULT_LIMIT, MAX_LIMIT, InvalidCursor, UserService

router = APIRouter(prefix="/users", tags=["users"])
ADMIN = {"x-required-role": Role.ADMIN.value}


def get_user_service(users: UserRepository = Depends(get_user_repository)) -> UserService:
    return UserService(users)


@router.get("", response_model=UserPage, openapi_extra=ADMIN)
def list_users(
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: str | None = Query(None, max_length=512),
    role: Role | None = None,
    _: User = Depends(require_role(Role.ADMIN)),
    service: UserService = Depends(get_user_service),
) -> UserPage:
    try:
        page = service.list_page(limit=limit, cursor=cursor, role=role)
    except InvalidCursor as error:
        raise ProblemError(
            VALIDATION_ERROR,
            "1 champ invalide.",
            errors=[{"field": "query.cursor", "message": "Curseur inconnu."}],
        ) from error
    items = [UserResponse.model_validate(user) for user in page.items]
    return UserPage(items=items, next_cursor=page.next_cursor)


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    openapi_extra=ADMIN,
)
def create_user(
    body: UserCreate,
    response: Response,
    _: User = Depends(require_role(Role.ADMIN)),
    service: UserService = Depends(get_user_service),
) -> User:
    try:
        user = service.create(body.username, body.password, body.role)
    except DuplicateUsername as error:
        raise ProblemError(CONFLICT, "Ce nom d'utilisateur existe déjà.") from error
    response.headers["Location"] = f"/api/v1/users/{user.user_id}"
    return user


@router.get("/{user_id}", response_model=UserResponse, openapi_extra=ADMIN)
def get_user(
    user_id: uuid.UUID,
    _: User = Depends(require_role(Role.ADMIN)),
    service: UserService = Depends(get_user_service),
) -> User:
    user = service.get(user_id)
    if user is None:
        raise ProblemError(NOT_FOUND, "Utilisateur inconnu.")
    return user
