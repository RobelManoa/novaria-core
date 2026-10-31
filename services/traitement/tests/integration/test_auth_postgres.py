"""Authentification et comptes contre un vrai PostgreSQL migré par Alembic (BE-03).

Mêmes parcours que les tests de contrat, mais avec le dépôt SQL, la vraie contrainte d'unicité, les
vraies dates et la vraie requête de pagination. Ignoré sans `NOVARIA_TEST_POSTGRES_ADMIN_URL`
(voir `tests/integration/postgres.py`).
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import cli
from app.core.config import get_settings
from app.db import session as session_module
from app.db.session import get_user_repository
from app.main import app
from app.models import Role, User
from app.repositories.users import DuplicateUsername, SqlUserRepository
from app.services.users import UserService
from tests.fakes import PASSWORD, SECRET
from tests.integration.postgres import needs_postgres
from tests.openapi_checks import check, schema

pytestmark = needs_postgres


@pytest.fixture
def session(migrated_database):
    with Session(migrated_database, expire_on_commit=False) as session:
        yield session


@pytest.fixture
def repository(session):
    return SqlUserRepository(session)


@pytest.fixture
def client(migrated_database, monkeypatch):
    """L'application complète, branchée sur la base jetable (fuseau de session : Tokyo)."""
    monkeypatch.setenv("JWT_SECRET", SECRET)
    get_settings.cache_clear()
    moteur = create_engine(
        migrated_database.url, connect_args={"options": "-c timezone=Asia/Tokyo"}
    )

    def depot():
        with Session(moteur, expire_on_commit=False) as session:
            yield SqlUserRepository(session)

    app.dependency_overrides[get_user_repository] = depot
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        moteur.dispose()
        get_settings.cache_clear()


def login(client, username: str, password: str = PASSWORD) -> dict[str, str]:
    reponse = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert reponse.status_code == 200, reponse.text
    return {"Authorization": f"Bearer {reponse.json()['access_token']}"}


def seed(repository, username: str, role: Role) -> User:
    return UserService(repository).create(username, PASSWORD, role)


# --- Dépôt ------------------------------------------------------------------------------------


def test_the_repository_fills_the_identifier_the_date_and_the_status(repository):
    user = seed(repository, "alice", Role.OPERATOR)
    assert user.user_id is not None
    assert user.created_at.tzinfo is not None
    assert user.is_active is True
    assert repository.get(user.user_id).username == "alice"
    assert repository.get_by_username("alice").user_id == user.user_id
    assert repository.get_by_username("inconnu") is None


def test_a_taken_username_is_refused_by_the_database_and_reported_as_a_duplicate(repository):
    seed(repository, "alice", Role.VIEWER)
    with pytest.raises(DuplicateUsername):
        seed(repository, "alice", Role.ADMIN)
    assert seed(repository, "bob", Role.VIEWER).username == "bob", "la session reste utilisable"


def test_a_row_that_breaks_another_constraint_is_not_reported_as_a_duplicate(repository):
    with pytest.raises(IntegrityError):
        repository.add(
            User(username="alice", password_hash="mot-de-passe-en-clair", role=Role.VIEWER)
        )


def test_pages_follow_the_creation_order_without_gap_or_overlap(repository):
    for numero in range(7):
        seed(repository, f"user{numero}", Role.ADMIN if numero % 2 else Role.VIEWER)
    service = UserService(repository)
    vus, curseur = [], None
    while True:
        page = service.list_page(limit=3, cursor=curseur)
        vus += [u.username for u in page.items]
        curseur = page.next_cursor
        if curseur is None:
            break
    assert vus == [f"user{n}" for n in range(7)]
    admins = service.list_page(limit=10, role=Role.ADMIN)
    assert [u.username for u in admins.items] == ["user1", "user3", "user5"]


# --- Application complète ---------------------------------------------------------------------


def test_the_full_journey_login_then_protected_routes_then_refusals(client, repository):
    seed(repository, "admin1", Role.ADMIN)
    seed(repository, "viewer1", Role.VIEWER)
    admin, viewer = login(client, "admin1"), login(client, "viewer1")

    assert client.get("/api/v1/users").status_code == 401
    assert client.get("/api/v1/users", headers=viewer).status_code == 403
    assert client.get("/api/v1/users", headers=admin).status_code == 200
    assert client.get("/api/v1/auth/me", headers=viewer).json()["username"] == "viewer1"

    cree = client.post(
        "/api/v1/users",
        headers=admin,
        json={"username": "nouveau", "password": "un-mot-de-passe-long", "role": "operator"},
    )
    assert cree.status_code == 201
    assert (
        client.post(
            "/api/v1/users",
            headers=admin,
            json={"username": "nouveau", "password": "un-mot-de-passe-long", "role": "viewer"},
        ).status_code
        == 409
    )
    assert login(client, "nouveau", "un-mot-de-passe-long")


def test_dates_are_in_utc_for_the_contract_even_when_the_database_session_is_not(
    client, repository
):
    seed(repository, "admin1", Role.ADMIN)
    reponse = client.get("/api/v1/auth/me", headers=login(client, "admin1"))
    check(reponse.json(), schema("User"))
    assert reponse.json()["created_at"].endswith("Z")


def test_a_disabled_account_loses_its_token_at_once(client, repository, migrated_database):
    seed(repository, "alice", Role.ADMIN)
    en_tete = login(client, "alice")
    assert client.get("/api/v1/auth/me", headers=en_tete).status_code == 200
    with migrated_database.begin() as connexion:
        connexion.execute(text("UPDATE app.users SET is_active = false"))
    assert client.get("/api/v1/auth/me", headers=en_tete).status_code == 401
    refus = client.post("/api/v1/auth/login", json={"username": "alice", "password": PASSWORD})
    assert refus.json()["code"] == "INVALID_CREDENTIALS"


def test_a_role_change_applies_to_the_existing_token_at_once(client, repository, migrated_database):
    seed(repository, "alice", Role.ADMIN)
    en_tete = login(client, "alice")
    assert client.get("/api/v1/users", headers=en_tete).status_code == 200
    with migrated_database.begin() as connexion:
        connexion.execute(text("UPDATE app.users SET role = 'viewer'"))
    assert client.get("/api/v1/users", headers=en_tete).status_code == 403


def test_a_pagination_through_the_api_matches_the_database(client, repository):
    seed(repository, "admin1", Role.ADMIN)
    for numero in range(5):
        seed(repository, f"user{numero}", Role.VIEWER)
    en_tete = login(client, "admin1")
    noms, curseur = [], None
    while True:
        params = {"limit": 4} | ({"cursor": curseur} if curseur else {})
        page = client.get("/api/v1/users", params=params, headers=en_tete).json()
        check(page, schema("UserPage"))
        noms += [u["username"] for u in page["items"]]
        curseur = page["next_cursor"]
        if curseur is None:
            break
    assert noms == ["admin1", *[f"user{n}" for n in range(5)]]


# --- Ligne de commande ------------------------------------------------------------------------


def test_the_command_line_creates_the_first_administrator_who_can_then_log_in(
    client, migrated_database, monkeypatch, capsys
):
    adresse = migrated_database.url.render_as_string(hide_password=False)
    monkeypatch.setenv("APP_DATABASE_URL", adresse)
    get_settings.cache_clear()
    session_module.get_session_factory.cache_clear()
    try:
        saisies = iter([PASSWORD, PASSWORD])
        code = cli.main(
            ["create-user", "premier", "--role", "admin"], prompt=lambda _: next(saisies)
        )
    finally:
        session_module.get_session_factory.cache_clear()
    assert code == 0
    assert "Compte créé" in capsys.readouterr().out
    monkeypatch.setenv("JWT_SECRET", SECRET)
    get_settings.cache_clear()
    en_tete = login(client, "premier")
    assert client.get("/api/v1/users", headers=en_tete).status_code == 200
