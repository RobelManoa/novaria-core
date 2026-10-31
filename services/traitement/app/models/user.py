"""Utilisateur de l'API métier : identité, rôle et état du compte (BE-02).

La forme suit le schéma `User` du contrat OpenAPI (`contracts/openapi/api-metier.openapi.yaml`) :
identifiant, nom, rôle, compte actif, date de création. Le mot de passe n'est jamais stocké :
seulement son empreinte (`password_hash`), calculée par l'authentification (BE-03).
Colonnes et règles : dictionnaire de données, section 11.2.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, Enum, String, Text, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Role(StrEnum):
    """Droit d'accès, du plus faible au plus fort (valeurs de `Role` dans le contrat OpenAPI)."""

    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"


# Mêmes bornes que `UserCreate.username` dans le contrat : 3 à 64 caractères parmi a-z 0-9 _ . -
USERNAME_PATTERN = "^[a-z0-9_.-]{3,64}$"

TABLE_COMMENT = (
    "Utilisateurs de l'API métier (BE-02). "
    "Le mot de passe n'est jamais stocké, seulement son empreinte."
)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(f"username ~ '{USERNAME_PATTERN}'", name="username_format"),
        CheckConstraint("role IN ('viewer', 'operator', 'admin')", name="role_valid"),
        # Les empreintes d'argon2 et de bcrypt commencent par « $ » : un mot de passe saisi tel
        # quel est refusé par la base.
        CheckConstraint("left(password_hash, 1) = '$'", name="password_hash_is_a_hash"),
        {"comment": TABLE_COMMENT},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
        comment="Identifiant exposé par l'API.",
    )
    username: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        comment="Identifiant de connexion : 3 à 64 caractères, a-z 0-9 _ . -, unique.",
    )
    password_hash: Mapped[str] = mapped_column(
        Text,
        comment="Empreinte du mot de passe (algorithme choisi par BE-03), jamais le mot de passe.",
    )
    role: Mapped[Role] = mapped_column(
        Enum(
            Role,
            native_enum=False,
            length=16,
            create_constraint=False,
            values_callable=lambda roles: [role.value for role in roles],
        ),
        comment="Droit d'accès : viewer, operator ou admin.",
    )
    is_active: Mapped[bool] = mapped_column(
        default=True,
        server_default=text("true"),
        comment="Faux : le compte ne peut plus se connecter.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="Création du compte, UTC."
    )
