"""Schéma app : table des utilisateurs (BE-02).

Revision ID: 0001
Revises:
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column(
            "user_id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            comment="Identifiant exposé par l'API.",
        ),
        sa.Column(
            "username",
            sa.String(length=64),
            nullable=False,
            comment="Identifiant de connexion : 3 à 64 caractères, a-z 0-9 _ . -, unique.",
        ),
        sa.Column(
            "password_hash",
            sa.Text(),
            nullable=False,
            comment=(
                "Empreinte du mot de passe (algorithme choisi par BE-03), jamais le mot de passe."
            ),
        ),
        sa.Column(
            "role",
            sa.Enum(
                "viewer",
                "operator",
                "admin",
                name="role",
                native_enum=False,
                length=16,
                create_constraint=False,
            ),
            nullable=False,
            comment="Droit d'accès : viewer, operator ou admin.",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
            comment="Faux : le compte ne peut plus se connecter.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="Création du compte, UTC.",
        ),
        sa.CheckConstraint(
            "username ~ '^[a-z0-9_.-]{3,64}$'", name=op.f("ck_users_username_format")
        ),
        sa.CheckConstraint(
            "role IN ('viewer', 'operator', 'admin')", name=op.f("ck_users_role_valid")
        ),
        sa.CheckConstraint(
            "left(password_hash, 1) = '$'", name=op.f("ck_users_password_hash_is_a_hash")
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_users")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
        schema="app",
        comment=(
            "Utilisateurs de l'API métier (BE-02). "
            "Le mot de passe n'est jamais stocké, seulement son empreinte."
        ),
    )


def downgrade() -> None:
    op.drop_table("users", schema="app")
