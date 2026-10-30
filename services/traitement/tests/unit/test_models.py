"""Modèle métier du schéma `app` (BE-02).

Forme de la table, fidélité au contrat OpenAPI et au dictionnaire de données.
"""

import re
import uuid
from pathlib import Path

import pytest
import yaml
from sqlalchemy import Boolean, DateTime, String, Text, Uuid
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable, UniqueConstraint

from app.models import SCHEMA, Base, Role, User
from app.models.base import NAMING_CONVENTION
from app.models.user import USERNAME_PATTERN

RACINE = Path(__file__).resolve().parents[4]
CONTRAT = RACINE / "contracts" / "openapi" / "api-metier.openapi.yaml"
DICTIONNAIRE = RACINE / "docs" / "03-donnees" / "dictionnaire-de-donnees.md"
TABLE = User.__table__
EMPREINTE = "$argon2id$exemple"


@pytest.fixture(scope="module")
def contrat() -> dict:
    return yaml.safe_load(CONTRAT.read_text(encoding="utf-8"))["components"]["schemas"]


def test_the_schema_is_app_and_it_holds_exactly_one_table_for_now():
    assert SCHEMA == "app"
    assert Base.metadata.schema == "app"
    assert set(Base.metadata.tables) == {"app.users"}
    assert TABLE.schema == "app"
    assert TABLE.comment


def test_the_columns_have_the_expected_types_and_nullability():
    attendu = {
        "user_id": Uuid,
        "username": String,
        "password_hash": Text,
        "role": String,
        "is_active": Boolean,
        "created_at": DateTime,
    }
    assert list(TABLE.columns.keys()) == list(attendu)
    for nom, type_ in attendu.items():
        colonne = TABLE.columns[nom]
        assert colonne.nullable is False, nom
        assert colonne.comment, f"{nom} sans commentaire"
        assert isinstance(colonne.type, type_), nom
    assert TABLE.columns["username"].type.length == 64
    assert TABLE.columns["created_at"].type.timezone is True


def test_the_primary_key_is_the_user_id_and_the_username_is_unique():
    assert [c.name for c in TABLE.primary_key.columns] == ["user_id"]
    uniques = {
        c.name: [col.name for col in c.columns]
        for c in TABLE.constraints
        if isinstance(c, UniqueConstraint)
    }
    assert uniques == {"uq_users_username": ["username"]}


def test_every_constraint_has_a_stable_name_from_the_convention():
    noms = {c.name for c in TABLE.constraints}
    assert noms == {
        "pk_users",
        "uq_users_username",
        "ck_users_username_format",
        "ck_users_role_valid",
        "ck_users_password_hash_is_a_hash",
    }
    assert set(NAMING_CONVENTION) == {"ix", "uq", "ck", "fk", "pk"}


def test_the_server_defaults_let_the_database_fill_identifier_status_and_date():
    assert str(TABLE.columns["user_id"].server_default.arg) == "gen_random_uuid()"
    assert str(TABLE.columns["is_active"].server_default.arg) == "true"
    assert TABLE.columns["created_at"].server_default is not None
    assert TABLE.columns["role"].server_default is None, (
        "le rôle est toujours choisi, jamais deviné"
    )
    assert TABLE.columns["username"].server_default is None


def test_a_python_side_identifier_is_generated_when_none_is_given():
    colonne = TABLE.columns["user_id"]
    assert isinstance(colonne.default.arg(None), uuid.UUID)
    assert User(username="alice", password_hash=EMPREINTE, role=Role.ADMIN).role is Role.ADMIN


def test_no_column_can_hold_a_clear_text_password():
    assert "password" not in TABLE.columns
    assert "password_hash" in TABLE.columns
    gardes = {str(c.sqltext) for c in TABLE.constraints if hasattr(c, "sqltext")}
    assert "left(password_hash, 1) = '$'" in gardes


def test_the_role_values_are_stored_as_the_contract_spells_them():
    assert [r.value for r in Role] == ["viewer", "operator", "admin"]
    assert Role("operator") is Role.OPERATOR
    assert Role.ADMIN == "admin"
    assert TABLE.columns["role"].type.enums == ["viewer", "operator", "admin"]


def test_the_roles_are_the_ones_of_the_openapi_contract(contrat):
    assert contrat["Role"]["enum"] == [r.value for r in Role]


def test_the_username_rule_is_the_one_of_the_contract(contrat):
    creation = contrat["UserCreate"]["properties"]["username"]
    longueur = f"{{{creation['minLength']},{creation['maxLength']}}}"
    assert creation["pattern"] == "^[a-z0-9_.-]+$"
    assert USERNAME_PATTERN == "^[a-z0-9_.-]" + longueur + "$"
    assert TABLE.columns["username"].type.length == creation["maxLength"]
    assert re.fullmatch(USERNAME_PATTERN, "a.b-c_9")
    for refuse in ("ab", "A" * 3, "a b", "é" * 3, "x" * 65, "", "a;drop"):
        assert re.fullmatch(USERNAME_PATTERN, refuse) is None, refuse


def test_the_table_exposes_every_field_of_the_user_schema_of_the_contract(contrat):
    expose = set(contrat["User"]["properties"])
    assert expose == {"user_id", "username", "role", "is_active", "created_at"}
    assert set(contrat["User"]["required"]) == expose
    assert expose <= set(TABLE.columns.keys())
    assert set(TABLE.columns.keys()) - expose == {"password_hash"}, (
        "seule l'empreinte reste interne"
    )


def test_the_ddl_is_valid_for_postgresql_and_names_the_schema():
    ddl = str(CreateTable(TABLE).compile(dialect=postgresql.dialect()))
    assert "CREATE TABLE app.users" in ddl
    assert "user_id UUID DEFAULT gen_random_uuid() NOT NULL" in ddl
    assert "CONSTRAINT ck_users_role_valid CHECK (role IN ('viewer', 'operator', 'admin'))" in ddl


def test_the_dictionary_describes_every_column_of_the_table():
    texte = DICTIONNAIRE.read_text(encoding="utf-8")
    section = texte[texte.index("### 11.2 Schéma `app`") : texte.index("## 12. Points ouverts")]
    assert "`app.users`" in section
    for nom in TABLE.columns.keys():
        assert f"`{nom}`" in section, f"colonne {nom} absente du dictionnaire (section 11.2)"
    for contrainte in (
        "ck_users_username_format",
        "ck_users_role_valid",
        "ck_users_password_hash_is_a_hash",
        "uq_users_username",
    ):
        assert contrainte in section
    assert "alembic_version" in section
