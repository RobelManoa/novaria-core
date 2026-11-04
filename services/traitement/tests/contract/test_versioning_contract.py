"""Politique de version `/api/v1` et erreurs de routage (BE-06).

Règles : `contracts/openapi/README.md` (section Versionnement) et `app/core/versioning.py`.
- Toute route de l'API est sous `/api/v1`, dans le service comme dans les contrats.
- La version majeure du contrat (`info.version`) est celle de l'URL.
- Une version inconnue, une route inconnue, une méthode non permise et un slash final répondent
  au format `Problem`, sans redirection ni texte brut.
"""

from datetime import UTC, datetime

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.errors import register_handlers
from app.core.versioning import API_PREFIX, API_VERSION, SUPPORTED_VERSIONS, deprecated
from app.main import app
from app.models import Role
from tests.contract.conftest import CONTRACTS
from tests.contract.test_errors_contract import IMPLEMENTED, USERS, assert_problem
from tests.openapi_checks import API, TRAITEMENT, load

TOOLING = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
NOT_FOUND = {"NOT_FOUND"}


# --- Tout est sous /api/v1 ---------------------------------------------------------------------


def test_the_policy_publishes_a_single_version_for_now():
    assert API_VERSION == "v1"
    assert API_PREFIX == "/api/v1"
    assert SUPPORTED_VERSIONS == ("v1",)


def test_every_router_is_included_under_the_version_prefix():
    """Les routeurs sont inclus avec `API_PREFIX` ; seules les pages de documentation échappent."""
    plain = {route.path for route in app.routes if hasattr(route, "path")}
    included = [route for route in app.routes if not hasattr(route, "path")]
    assert plain == TOOLING
    assert len(included) >= 4, "santé, authentification, comptes, indicateurs"
    assert {route.include_context.prefix for route in included} == {API_PREFIX}


def test_every_published_path_is_under_the_version_prefix():
    published = set(app.openapi()["paths"])
    assert published and all(path.startswith(f"{API_PREFIX}/") for path in published)


def test_every_path_of_the_contracts_is_under_the_version_prefix():
    for contract in (API, TRAITEMENT):
        assert all(path.startswith(f"{API_PREFIX}/") for path in contract["paths"])


def test_the_major_version_of_each_contract_is_the_one_of_the_url():
    major = int(API_VERSION.removeprefix("v"))
    names = ("common.yaml", "api-metier.openapi.yaml", "traitement.openapi.yaml")
    for name in names:
        version = load(CONTRACTS / "openapi" / name)["info"]["version"]
        assert int(version.split(".")[0]) == major, name


def test_the_documentation_pages_stay_outside_the_versioned_api(scene):
    for page in ("/docs", "/openapi.json"):
        assert scene.client.get(page).status_code == 200


# --- Version inconnue -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/api/v2/users", "/api/v0/users", "/api/v10/health", "/api/v2", "/api/v2/", "/api/v01/users"],
)
@pytest.mark.parametrize("method", ["get", "post", "put", "delete"])
def test_an_unpublished_version_is_a_404_that_names_the_published_ones(scene, method, path):
    response = scene.request(method, path, role=Role.ADMIN)
    problem = assert_problem(response, 404, NOT_FOUND)
    assert "Versions disponibles : v1." in problem["detail"]
    assert path.split("/")[2] in problem["detail"]


def test_the_version_error_does_not_depend_on_the_token(scene):
    without = scene.client.get("/api/v2/users")
    with_token = scene.request("get", "/api/v2/users", role=Role.VIEWER)
    assert without.json()["detail"] == with_token.json()["detail"]
    assert without.status_code == with_token.status_code == 404


@pytest.mark.parametrize(
    "path",
    ["/api", "/api/", "/api/users", "/api/V1/users", "/api/v1x/users", "/apiv1/users", "/v1/users"],
)
def test_a_path_that_names_no_version_is_a_plain_unknown_route(scene, path):
    problem = assert_problem(scene.client.get(path), 404, NOT_FOUND)
    assert problem["detail"] == "Cette route n'existe pas."


# --- Route inconnue, méthode non permise, slash final ----------------------------------------


@pytest.mark.parametrize("method", ["get", "post", "put", "patch", "delete"])
@pytest.mark.parametrize("path", ["/", "/nope", "/api/v1/nope", "/api/v1/users/a/b", "/docs/x"])
def test_an_unknown_route_is_a_404_problem_whatever_the_method(scene, method, path):
    assert_problem(scene.client.request(method.upper(), path), 404, NOT_FOUND)


def test_an_unknown_route_is_a_404_even_with_a_valid_token(scene):
    response = scene.request("get", "/api/v1/nope", role=Role.ADMIN)
    assert_problem(response, 404, NOT_FOUND)


def test_the_unknown_route_answer_does_not_repeat_the_path(scene):
    response = scene.client.get("/api/v1/chemin-saisi-par-l-appelant-4e1?cle=valeur-4e1")
    assert "4e1" not in response.text


@pytest.mark.parametrize(("method", "path"), IMPLEMENTED, ids=[f"{m} {p}" for m, p in IMPLEMENTED])
def test_a_slash_at_the_end_is_another_address_and_gets_no_redirect(scene, method, path):
    url = path.replace("{user_id}", "x").replace("{indicator_id}", "x") + "/"
    response = scene.client.request(method.upper(), url, follow_redirects=False)
    assert_problem(response, 404, NOT_FOUND)
    assert "location" not in response.headers


ALLOWED = {
    "/api/v1/health": {"GET"},
    "/api/v1/auth/login": {"POST"},
    "/api/v1/auth/me": {"GET"},
    USERS: {"GET", "POST"},
    f"{USERS}/00000000-0000-4000-8000-000000000000": {"GET"},
    "/api/v1/indicators": {"GET"},
    "/api/v1/indicators/latest": {"GET"},
    "/api/v1/indicators/inconnu": {"GET"},
}


@pytest.mark.parametrize(("path", "allowed"), sorted(ALLOWED.items()))
def test_a_method_that_is_not_allowed_is_a_405_with_the_allow_header(scene, path, allowed):
    for method in ("PUT", "DELETE", "PATCH", "POST", "GET"):
        if method in allowed:
            continue
        response = scene.client.request(method, path)
        problem = assert_problem(response, 405, {"METHOD_NOT_ALLOWED"})
        assert response.headers["Allow"] == ", ".join(sorted(allowed))
        assert problem["title"] == "Méthode non permise"


def test_a_405_does_not_reveal_whether_the_caller_is_authenticated(scene):
    anonymous = scene.client.delete(USERS)
    admin = scene.request("delete", USERS, role=Role.ADMIN)
    assert anonymous.status_code == admin.status_code == 405
    assert anonymous.json()["detail"] == admin.json()["detail"]


def test_head_and_options_on_a_known_route_follow_the_same_rule(scene):
    assert scene.client.head("/api/v1/health").status_code == 405
    options = scene.client.options(USERS)
    assert_problem(options, 405, {"METHOD_NOT_ALLOWED"})


def test_every_implemented_route_answers_its_own_method(scene):
    assert scene.client.get("/api/v1/health").status_code == 200
    assert len(IMPLEMENTED) >= 9


# --- Retrait annoncé : Deprecation et Sunset --------------------------------------------------


def versioned_app(**kwargs) -> TestClient:
    application = FastAPI(redirect_slashes=False)
    register_handlers(application)
    router = APIRouter(prefix=API_PREFIX)

    @router.get("/ancienne", dependencies=[Depends(deprecated(**kwargs))])
    def old_route() -> dict[str, str]:
        return {"ok": "oui"}

    @router.get("/courante")
    def current_route() -> dict[str, str]:
        return {"ok": "oui"}

    application.include_router(router)
    return TestClient(application)


def test_a_route_announced_for_removal_carries_the_deprecation_and_sunset_headers():
    since = datetime(2027, 1, 15, 8, 0, tzinfo=UTC)
    sunset = datetime(2027, 7, 1, 0, 0, tzinfo=UTC)
    client = versioned_app(since=since, sunset=sunset)
    response = client.get("/api/v1/ancienne")
    assert response.status_code == 200
    assert response.headers["Deprecation"] == f"@{int(since.timestamp())}"
    assert response.headers["Sunset"] == "Thu, 01 Jul 2027 00:00:00 GMT"
    current = client.get("/api/v1/courante")
    assert "deprecation" not in current.headers
    assert "sunset" not in current.headers


def test_the_routes_of_the_service_carry_no_deprecation_header_today(scene):
    for method, path in IMPLEMENTED:
        response = scene.request(method, path, role=Role.ADMIN)
        assert "deprecation" not in response.headers, path
        assert "sunset" not in response.headers, path
