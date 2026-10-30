"""Corps des requêtes et réponses des routes d'authentification et de comptes (BE-03).

Mêmes champs et mêmes bornes que les schémas `LoginRequest`, `Token`, `User`, `UserCreate` et
`UserPage` de `contracts/openapi/api-metier.openapi.yaml`.
"""

import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.models import Role

USERNAME_PATTERN = r"^[a-z0-9_.-]+$"


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - type de jeton, pas un secret
    expires_in: int = Field(ge=1, description="Durée de vie en secondes.")


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    username: str
    role: Role
    is_active: bool
    created_at: datetime

    @field_serializer("created_at")
    def created_at_in_utc(self, value: datetime) -> datetime:
        """Le contrat veut une date UTC (`...Z`), quel que soit le fuseau de la session de base."""
        return value.astimezone(UTC)


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=64, pattern=USERNAME_PATTERN)
    password: str = Field(min_length=12, max_length=128)
    role: Role


class UserPage(BaseModel):
    items: list[UserResponse]
    next_cursor: str | None
