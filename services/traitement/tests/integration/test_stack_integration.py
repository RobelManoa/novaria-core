"""PostgreSQL et MongoDB ensemble, et le chemin de migration que lance l'exploitation (BE-07).

Deux choses que les autres tests d'intégration, chacun sur une seule base, ne prouvent pas :
- `alembic upgrade head` lu depuis `APP_DATABASE_URL`, comme `dev.py db-migrate-app` le lance
  (les autres tests donnent une connexion ouverte à Alembic) ;
- un parcours complet : le compte vient du vrai PostgreSQL (mot de passe vérifié en argon2id), et
  l'entrée d'audit de chaque appel arrive dans le vrai MongoDB sous l'identifiant de ce compte.

Ignorés sans `NOVARIA_TEST_POSTGRES_ADMIN_URL` et `NOVARIA_TEST_MONGO_URL`
(`python scripts/dev/dev.py test-integration` les fournit).
"""

import logging
import uuid

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_user_repository
from app.main import app
from app.models import SCHEMA, Role
from app.repositories.audit import open_collections
from app.repositories.users import SqlUserRepository
from app.services.audit import RecordingObserver
from app.services.users import UserService
from tests.fakes import PASSWORD, SECRET
from tests.integration import mongo, postgres
from tests.integration.mongo import database, erase

needs_both = pytest.mark.skipif(
    not (postgres.ADMIN_URL and mongo.URL),
    reason="PostgreSQL et MongoDB requis (NOVARIA_TEST_POSTGRES_ADMIN_URL, NOVARIA_TEST_MONGO_URL)",
)


def alembic_from_environment() -> Config:
    """La configuration du dépôt, sans connexion fournie : Alembic ouvre la sienne."""
    config = Config(str(postgres.SERVICE / "alembic.ini"))
    config.attributes["configure_logger"] = False
    return config


# --- Migration lancée comme en exploitation ----------------------------------------------------


@postgres.needs_postgres
def test_upgrade_reads_the_address_of_the_database_from_the_environment(
    empty_database, monkeypatch
):
    url = empty_database.url.render_as_string(hide_password=False)
    monkeypatch.setenv("APP_DATABASE_URL", url)
    assert SCHEMA not in inspect(empty_database).get_schema_names()

    command.upgrade(alembic_from_environment(), "head")

    assert "users" in inspect(empty_database).get_table_names(schema=SCHEMA)


@postgres.needs_postgres
def test_upgrading_twice_from_the_environment_changes_nothing(empty_database, monkeypatch):
    monkeypatch.setenv("APP_DATABASE_URL", empty_database.url.render_as_string(hide_password=False))
    command.upgrade(alembic_from_environment(), "head")
    command.upgrade(alembic_from_environment(), "head")
    command.downgrade(alembic_from_environment(), "base")
    assert "users" not in inspect(empty_database).get_table_names(schema=SCHEMA)


@postgres.needs_postgres
def test_the_logging_of_alembic_is_configured_from_the_ini_file_and_restored(
    empty_database, monkeypatch
):
    """Le fichier `alembic.ini` configure les journaux ; le test remet ceux de l'application."""
    monkeypatch.setenv("APP_DATABASE_URL", empty_database.url.render_as_string(hide_password=False))
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    config = Config(
        str(postgres.SERVICE / "alembic.ini")
    )  # sans `configure_logger` : journaux d'Alembic
    try:
        command.upgrade(config, "head")
    finally:
        root.handlers[:] = handlers
        root.setLevel(level)
    assert "users" in inspect(empty_database).get_table_names(schema=SCHEMA)


# --- PostgreSQL et MongoDB ensemble ----------------------------------------------------------


@pytest.fixture
def stack(migrated_database, monkeypatch):
    """L'application complète : comptes dans le PostgreSQL jetable, audit dans le vrai MongoDB."""
    monkeypatch.setenv("JWT_SECRET", SECRET)
    get_settings.cache_clear()
    engine = create_engine(migrated_database.url)
    traces: list[str] = []

    def repository():
        with Session(engine, expire_on_commit=False) as session:
            yield SqlUserRepository(session)

    audit, usage = open_collections(mongo.URL)
    app.dependency_overrides[get_user_repository] = repository
    app.state.observer = RecordingObserver(audit, usage, service="traitement", log=lambda *_: None)

    def account(username: str, role: Role) -> uuid.UUID:
        with Session(engine, expire_on_commit=False) as session:
            created = UserService(SqlUserRepository(session)).create(username, PASSWORD, role)
        traces.append(str(created.user_id))
        return created.user_id

    try:
        yield TestClient(app), account, traces
    finally:
        app.dependency_overrides.clear()
        app.state.observer = None
        engine.dispose()
        get_settings.cache_clear()
        erase(traces, [])


def login(client, username: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@needs_both
def test_every_call_of_a_real_account_is_audited_in_mongodb_under_its_identifier(stack):
    client, account, traces = stack
    admin_id = account("administrateur", Role.ADMIN)
    viewer_id = account("lecteur", Role.VIEWER)
    admin, viewer = login(client, "administrateur"), login(client, "lecteur")

    assert client.get("/api/v1/auth/me", headers=viewer).json()["user_id"] == str(viewer_id)
    assert client.get("/api/v1/users", headers=admin).status_code == 200
    assert client.get("/api/v1/users", headers=viewer).status_code == 403
    assert client.get(f"/api/v1/users/{viewer_id}", headers=admin).status_code == 200
    assert client.get("/api/v1/users").status_code == 401  # sans jeton : compté, pas journalisé

    entries = list(database(mongo.URL).audit_logs.find({"actor": {"$in": traces}}).sort("ts"))
    assert [(e["actor"], e["action"], e["outcome"]) for e in entries] == [
        (str(admin_id), "POST /api/v1/auth/login", "ok"),
        (str(viewer_id), "POST /api/v1/auth/login", "ok"),
        (str(viewer_id), "GET /api/v1/auth/me", "ok"),
        (str(admin_id), "GET /api/v1/users", "ok"),
        (str(viewer_id), "GET /api/v1/users", "denied"),
        (str(admin_id), "GET /api/v1/users/{user_id}", "ok"),
    ]
    assert entries[-1]["details"]["path_params"] == {"user_id": str(viewer_id)}
    texte = str(entries)
    for interdit in ("administrateur", "lecteur", PASSWORD, "argon2", "Bearer", "eyJ"):
        assert interdit not in texte, interdit


@needs_both
def test_a_refused_login_against_the_real_database_is_audited_as_anonymous(stack):
    client, account, _ = stack
    account("administrateur", Role.ADMIN)
    before = database(mongo.URL).audit_logs.count_documents({"actor": "anonymous"})

    wrong = client.post(
        "/api/v1/auth/login", json={"username": "administrateur", "password": "x" * 12}
    )
    unknown = client.post("/api/v1/auth/login", json={"username": "inconnu", "password": PASSWORD})

    assert (wrong.status_code, unknown.status_code) == (401, 401)
    assert wrong.json()["detail"] == unknown.json()["detail"]
    after = database(mongo.URL).audit_logs.find({"actor": "anonymous"}).sort("ts", -1).limit(2)
    assert database(mongo.URL).audit_logs.count_documents({"actor": "anonymous"}) == before + 2
    assert {e["outcome"] for e in after} == {"denied"}


@needs_both
def test_when_mongodb_fails_the_accounts_still_work(stack):
    """L'audit est au mieux : un MongoDB qui échoue ne change aucune réponse (BE-05)."""
    client, account, _ = stack
    account("administrateur", Role.ADMIN)

    class Broken:
        def insert(self, entry):
            raise ConnectionError("injoignable")

        def increment(self, endpoint, bucket):
            raise ConnectionError("injoignable")

    app.state.observer = RecordingObserver(
        Broken(), Broken(), service="traitement", log=lambda *_: None
    )
    admin = login(client, "administrateur")
    assert client.get("/api/v1/auth/me", headers=admin).status_code == 200
    assert app.state.observer.dropped == 2
