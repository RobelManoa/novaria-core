"""Authentification et rôles contre le contrat OpenAPI de l'API métier (BE-03).

Critère d'acceptation : un accès sans droit renvoie 403 et un accès sans jeton renvoie 401.

Le contrat `contracts/openapi/api-metier.openapi.yaml` dit, pour chaque opération, quel rôle elle
exige (`x-required-role`) et quelles réponses elle peut donner. Ces tests partent de lui :
- pour chaque opération protégée que le service implémente, sans jeton : 401 ; avec chaque rôle
  inférieur au rôle requis : 403 ; avec le rôle requis ou un rôle supérieur : ni 401 ni 403 ;
- toute route du service est protégée, sauf la sonde et la connexion ;
- les corps de réponse (jeton, utilisateur, page, erreur) respectent les schémas du contrat.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.main import app
from app.models import Role
from app.services.auth import ROLE_LEVEL
from tests.fakes import PASSWORD, SECRET, FakeUserRepository, bearer
from tests.openapi_checks import API, PROBLEM, check, schema

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
PUBLIC = {("/api/v1/health", "get"), ("/api/v1/auth/login", "post")}
UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"
NEW_USER = {"username": "nouveau", "password": "un-mot-de-passe-long", "role": "viewer"}


def implemented() -> set[tuple[str, str]]:
    return {(path, method) for path, item in app.openapi()["paths"].items() for method in item}


def protected_operations() -> list[tuple[str, str, Role]]:
    """Opérations du contrat qui exigent un rôle et que le service implémente."""
    sont_la = implemented()
    return [
        (path, method, Role(operation["x-required-role"]))
        for path, item in API["paths"].items()
        for method, operation in item.items()
        if method in HTTP_METHODS and "x-required-role" in operation and (path, method) in sont_la
    ]


PROTECTED = protected_operations()
IDS = [f"{method.upper()} {path} [{role.value}]" for path, method, role in PROTECTED]


def call(client, path: str, method: str, headers: dict | None = None):
    url = path.replace("{user_id}", UNKNOWN_ID)
    body = NEW_USER if (path, method) == ("/api/v1/users", "post") else None
    return client.request(method.upper(), url, headers=headers or {}, json=body)


def documented(path: str, method: str, status: int) -> bool:
    codes = API["paths"][path][method]["responses"]
    return str(status) in codes or f"{status // 100}XX" in codes


def assert_problem(response, status: int, code: str) -> dict:
    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    check(body, PROBLEM)
    assert (body["status"], body["code"]) == (status, code)
    assert body["correlation_id"] == response.headers["X-Correlation-ID"]
    return body


def users_below(required: Role) -> list[Role]:
    return [role for role in Role if ROLE_LEVEL[role] < ROLE_LEVEL[required]]


def users_from(required: Role) -> list[Role]:
    return [role for role in Role if ROLE_LEVEL[role] >= ROLE_LEVEL[required]]


# --- Le contrat est bien ce que les tests croient ------------------------------------------


def test_the_service_implements_the_login_and_the_protected_routes_of_the_contract():
    assert {(p, m) for p, m, _ in PROTECTED} == {
        ("/api/v1/auth/me", "get"),
        ("/api/v1/users", "get"),
        ("/api/v1/users", "post"),
        ("/api/v1/users/{user_id}", "get"),
    }
    assert PUBLIC <= implemented(), "la sonde et la connexion existent"


def test_the_declared_roles_of_the_routes_are_the_roles_of_the_contract():
    openapi = app.openapi()["paths"]
    for path, method, role in PROTECTED:
        assert openapi[path][method]["x-required-role"] == role.value, f"{method} {path}"


def test_the_public_routes_of_the_contract_are_the_two_we_leave_open():
    for path, method in PUBLIC:
        assert API["paths"][path][method]["security"] == []


# --- 401 : sans jeton valide ----------------------------------------------------------------


@pytest.mark.parametrize(("path", "method", "role"), PROTECTED, ids=IDS)
def test_without_a_token_the_access_is_refused_with_401(client, path, method, role):
    reponse = call(client, path, method)
    body = assert_problem(reponse, 401, "UNAUTHENTICATED")
    assert reponse.headers["WWW-Authenticate"] == "Bearer"
    assert body["type"] == "https://novaria.local/problems/unauthenticated"
    assert documented(path, method, 401)


@pytest.mark.parametrize(("path", "method", "role"), PROTECTED, ids=IDS)
def test_with_a_wrong_scheme_or_an_unreadable_token_the_access_is_refused_with_401(
    client, repo, path, method, role
):
    for en_tete in (
        {"Authorization": "Basic YWxpY2U6cGFzcw=="},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer pas-un-jeton"},
        {"Authorization": ""},
    ):
        assert_problem(call(client, path, method, en_tete), 401, "UNAUTHENTICATED")


# --- 403 : jeton valide, rôle insuffisant ---------------------------------------------------


CASES_FORBIDDEN = [
    (path, method, required, role)
    for path, method, required in PROTECTED
    for role in users_below(required)
]
IDS_FORBIDDEN = [f"{m.upper()} {p} avec {r.value}" for p, m, _, r in CASES_FORBIDDEN]


@pytest.mark.parametrize(("path", "method", "required", "role"), CASES_FORBIDDEN, ids=IDS_FORBIDDEN)
def test_with_an_insufficient_role_the_access_is_refused_with_403(
    client, repo, path, method, required, role
):
    appelant = repo.make("appelant", role)
    reponse = call(client, path, method, bearer(appelant))
    body = assert_problem(reponse, 403, "FORBIDDEN")
    assert f"`{role.value}`" in body["detail"]
    assert f"`{required.value}`" in body["detail"]
    assert documented(path, method, 403)
    assert "WWW-Authenticate" not in reponse.headers, "le jeton est bon : ce n'est pas une 401"


CASES_ALLOWED = [
    (path, method, role) for path, method, required in PROTECTED for role in users_from(required)
]
IDS_ALLOWED = [f"{m.upper()} {p} avec {r.value}" for p, m, r in CASES_ALLOWED]


@pytest.mark.parametrize(("path", "method", "role"), CASES_ALLOWED, ids=IDS_ALLOWED)
def test_with_the_required_role_or_a_higher_one_the_access_is_not_refused(
    client, repo, path, method, role
):
    appelant = repo.make("appelant", role)
    reponse = call(client, path, method, bearer(appelant))
    assert reponse.status_code not in (401, 403)
    assert documented(path, method, reponse.status_code), reponse.status_code


# --- Toute route est protégée, sauf la sonde et la connexion --------------------------------


def test_every_route_of_the_api_is_protected_except_the_probe_and_the_login(client):
    """Protégé par défaut : une route ajoutée plus tard sans garde fait échouer ce test."""
    chemins = {
        (path, method)
        for path, item in app.openapi()["paths"].items()
        if path.startswith("/api/v1")
        for method in item
    }
    assert chemins >= PUBLIC, "la sonde et la connexion existent"
    for path, method in sorted(chemins - PUBLIC):
        reponse = call(client, path, method)
        assert reponse.status_code == 401, f"{method.upper()} {path} n'est pas protégée"


# --- Connexion ------------------------------------------------------------------------------


def test_a_login_gives_a_token_that_follows_the_contract(client, repo):
    repo.make("operateur1", Role.OPERATOR)
    reponse = client.post(
        "/api/v1/auth/login", json={"username": "operateur1", "password": PASSWORD}
    )
    assert reponse.status_code == 200
    body = reponse.json()
    check(body, schema("Token"))
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 1800
    assert "WWW-Authenticate" not in reponse.headers


def test_the_token_obtained_at_login_opens_the_routes_of_its_role(client, repo):
    repo.make("operateur1", Role.OPERATOR)
    jeton = client.post(
        "/api/v1/auth/login", json={"username": "operateur1", "password": PASSWORD}
    ).json()["access_token"]
    en_tete = {"Authorization": f"Bearer {jeton}"}
    assert client.get("/api/v1/auth/me", headers=en_tete).status_code == 200
    assert client.get("/api/v1/users", headers=en_tete).status_code == 403


@pytest.mark.parametrize(
    ("username", "password"),
    [("operateur1", "faux"), ("inconnu", PASSWORD), ("desactive", PASSWORD)],
    ids=["mauvais mot de passe", "identifiant inconnu", "compte désactivé"],
)
def test_a_login_that_fails_gives_the_same_401_whatever_the_reason(
    client, repo, username, password
):
    repo.make("operateur1", Role.OPERATOR)
    repo.make("desactive", active=False)
    reponse = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    body = assert_problem(reponse, 401, "INVALID_CREDENTIALS")
    assert body["detail"] == "Identifiant ou mot de passe incorrect."
    assert documented("/api/v1/auth/login", "post", 401)


def test_the_login_is_public_it_needs_no_token(client):
    reponse = client.post("/api/v1/auth/login", json={"username": "inconnu", "password": "x"})
    assert reponse.json()["code"] == "INVALID_CREDENTIALS", "pas UNAUTHENTICATED"


def test_the_probe_is_public(client):
    assert client.get("/api/v1/health").status_code == 200


def test_an_invalid_login_body_gives_a_problem_422(client):
    reponse = client.post("/api/v1/auth/login", json={"username": "ab"})
    assert_problem(reponse, 422, "VALIDATION_ERROR")


def test_an_invalid_login_body_is_at_least_refused_with_422(client):
    assert client.post("/api/v1/auth/login", json={"username": "ab"}).status_code == 422
    assert (
        client.post("/api/v1/auth/login", json={"username": "abc", "password": ""}).status_code
        == 422
    )
    extra = {"username": "abc", "password": "x", "role": "admin"}
    assert client.post("/api/v1/auth/login", json=extra).status_code == 422, "additionalProperties"


# --- Corps de réponse -----------------------------------------------------------------------


def test_me_returns_the_user_of_the_token_as_the_contract_describes_it(client, repo):
    alice = repo.make("alice", Role.VIEWER)
    reponse = client.get("/api/v1/auth/me", headers=bearer(alice))
    assert reponse.status_code == 200
    body = reponse.json()
    check(body, schema("User"))
    assert body["user_id"] == str(alice.user_id)
    assert set(body) == set(API["components"]["schemas"]["User"]["properties"])


def test_no_response_ever_carries_a_password_or_a_hash(client, repo):
    admin = repo.make("admin1", Role.ADMIN)
    en_tete = bearer(admin)
    reponses = [
        client.get("/api/v1/auth/me", headers=en_tete),
        client.get("/api/v1/users", headers=en_tete),
        client.get(f"/api/v1/users/{admin.user_id}", headers=en_tete),
        client.post("/api/v1/users", headers=en_tete, json=NEW_USER),
    ]
    for reponse in reponses:
        assert "argon2" not in reponse.text
        assert "password" not in reponse.text.lower()
        assert NEW_USER["password"] not in reponse.text


def test_a_date_stored_with_another_offset_is_still_given_in_utc(client, repo):
    tokyo = timezone(timedelta(hours=9))
    alice = repo.make("alice", Role.VIEWER)
    alice.created_at = datetime(2026, 10, 1, 17, 0, tzinfo=tokyo)
    reponse = client.get("/api/v1/auth/me", headers=bearer(alice))
    check(reponse.json(), schema("User"))
    assert reponse.json()["created_at"] == "2026-10-01T08:00:00Z"


def test_the_user_list_is_a_page_of_the_contract_and_is_paginated(client, repo):
    admin = repo.make("admin1", Role.ADMIN)
    for numero in range(4):
        repo.make(f"user{numero}")
    en_tete = bearer(admin)
    premiere = client.get("/api/v1/users", params={"limit": 3}, headers=en_tete)
    assert premiere.status_code == 200
    check(premiere.json(), schema("UserPage"))
    assert len(premiere.json()["items"]) == 3
    suite = client.get(
        "/api/v1/users",
        params={"limit": 3, "cursor": premiere.json()["next_cursor"]},
        headers=en_tete,
    )
    check(suite.json(), schema("UserPage"))
    assert len(suite.json()["items"]) == 2
    assert suite.json()["next_cursor"] is None


def test_the_user_list_can_be_filtered_by_role(client, repo):
    admin = repo.make("admin1", Role.ADMIN)
    repo.make("op1", Role.OPERATOR)
    repo.make("v1")
    reponse = client.get("/api/v1/users", params={"role": "operator"}, headers=bearer(admin))
    assert [u["username"] for u in reponse.json()["items"]] == ["op1"]


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 501}, {"limit": "x"}, {"role": "root"}, {"cursor": "x" * 513}],
)
def test_a_list_query_outside_the_contract_bounds_is_refused_with_422(client, repo, params):
    admin = repo.make("admin1", Role.ADMIN)
    assert client.get("/api/v1/users", params=params, headers=bearer(admin)).status_code == 422


def test_a_cursor_that_this_service_did_not_make_is_refused_with_a_problem_422(client, repo):
    admin = repo.make("admin1", Role.ADMIN)
    reponse = client.get(
        "/api/v1/users", params={"cursor": "n-importe-quoi"}, headers=bearer(admin)
    )
    body = assert_problem(reponse, 422, "VALIDATION_ERROR")
    assert body["errors"] == [{"field": "query.cursor", "message": "Curseur inconnu."}]


def test_an_admin_creates_a_user_with_a_location_and_the_user_can_then_log_in(client, repo):
    admin = repo.make("admin1", Role.ADMIN)
    reponse = client.post("/api/v1/users", headers=bearer(admin), json=NEW_USER)
    assert reponse.status_code == 201
    body = reponse.json()
    check(body, schema("User"))
    assert reponse.headers["Location"] == f"/api/v1/users/{body['user_id']}"
    assert (body["username"], body["role"], body["is_active"]) == ("nouveau", "viewer", True)
    connexion = client.post(
        "/api/v1/auth/login",
        json={"username": "nouveau", "password": NEW_USER["password"]},
    )
    assert connexion.status_code == 200


def test_a_taken_username_gives_a_conflict_problem_409(client, repo):
    admin = repo.make("admin1", Role.ADMIN)
    reponse = client.post(
        "/api/v1/users", headers=bearer(admin), json=NEW_USER | {"username": "admin1"}
    )
    assert_problem(reponse, 409, "CONFLICT")
    assert documented("/api/v1/users", "post", 409)


@pytest.mark.parametrize(
    "changes",
    [
        {"username": "ab"},
        {"username": "Majuscule"},
        {"username": "avec espace"},
        {"password": "trop-court"},
        {"password": "x" * 129},
        {"role": "root"},
        {"extra": "champ"},
    ],
)
def test_a_user_creation_outside_the_contract_bounds_is_refused_with_422(client, repo, changes):
    admin = repo.make("admin1", Role.ADMIN)
    reponse = client.post("/api/v1/users", headers=bearer(admin), json=NEW_USER | changes)
    assert reponse.status_code == 422
    assert "nouveau" not in {u.username for u in repo.users.values()}


def test_an_unknown_user_gives_a_not_found_problem_404(client, repo):
    admin = repo.make("admin1", Role.ADMIN)
    reponse = client.get(f"/api/v1/users/{uuid.uuid4()}", headers=bearer(admin))
    assert_problem(reponse, 404, "NOT_FOUND")
    assert client.get("/api/v1/users/pas-un-uuid", headers=bearer(admin)).status_code == 422


def test_a_known_user_is_returned_to_an_admin(client, repo):
    admin = repo.make("admin1", Role.ADMIN)
    alice = repo.make("alice", Role.OPERATOR)
    reponse = client.get(f"/api/v1/users/{alice.user_id}", headers=bearer(admin))
    check(reponse.json(), schema("User"))
    assert reponse.json()["username"] == "alice"


# --- Défaillances ---------------------------------------------------------------------------


def test_without_a_configured_secret_the_login_and_the_protected_routes_answer_503(
    client, repo, monkeypatch
):
    from app.core.config import get_settings

    monkeypatch.delenv("JWT_SECRET")
    get_settings.cache_clear()
    repo.make("alice")
    login = client.post("/api/v1/auth/login", json={"username": "alice", "password": PASSWORD})
    assert_problem(login, 503, "UPSTREAM_UNAVAILABLE")
    protegee = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer abc"})
    assert_problem(protegee, 503, "UPSTREAM_UNAVAILABLE")
    sans_jeton = client.get("/api/v1/auth/me")
    assert_problem(sans_jeton, 401, "UNAUTHENTICATED")


def test_a_database_that_is_down_gives_a_503_without_the_address_or_the_password(client, repo):
    from sqlalchemy.exc import OperationalError

    secret = "motdepasse-de-la-base"

    def en_panne(_):
        raise OperationalError("SELECT 1", {}, Exception(f"password={secret}"))

    repo.get_by_username = en_panne
    reponse = client.post("/api/v1/auth/login", json={"username": "alice", "password": PASSWORD})
    assert_problem(reponse, 503, "UPSTREAM_UNAVAILABLE")
    assert secret not in reponse.text


def test_the_error_bodies_carry_no_trace_and_no_secret(client, repo):
    repo.make("alice", Role.VIEWER)
    reponses = [
        client.get("/api/v1/users"),
        client.get("/api/v1/users", headers=bearer(repo.get_by_username("alice"))),
        client.post("/api/v1/auth/login", json={"username": "alice", "password": "faux"}),
    ]
    for reponse in reponses:
        assert "Traceback" not in reponse.text
        assert "argon2" not in reponse.text
        assert SECRET not in reponse.text


def test_the_fake_repository_is_the_one_the_tests_use(repo):
    assert isinstance(repo, FakeUserRepository)
