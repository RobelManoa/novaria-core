"""CORS restreint (BE-08) : l'application est construite avec la configuration que le test veut."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.core.cors import ALLOWED_HEADERS, ALLOWED_METHODS, EXPOSED_HEADERS
from app.db.session import get_indicator_repository, get_user_repository
from app.main import app, create_app
from tests.fakes import PASSWORD

ALLOWED = "http://localhost:8080"
OTHER = "https://pirate.example"
LOGIN = "/api/v1/auth/login"


@pytest.fixture
def make_client(secret, repo, indicators, journal):
    def build(origins: str) -> TestClient:
        application = create_app(Settings(cors_allowed_origins=origins))
        application.dependency_overrides[get_user_repository] = lambda: repo
        application.dependency_overrides[get_indicator_repository] = lambda: indicators
        application.state.observer = journal.observer
        return TestClient(application)

    return build


def cors(response) -> dict[str, str]:
    return {k: v for k, v in response.headers.items() if k.lower().startswith("access-control")}


def grants_nothing(response) -> bool:
    """Aucune autorisation : ni origine, ni identifiants, ni méthodes, ni en-têtes de requête.

    Starlette ajoute `Access-Control-Expose-Headers` à toute réponse qui répond à une origine ;
    sans `Access-Control-Allow-Origin`, le navigateur n'en tire rien.
    """
    return set(cors(response)) <= {"access-control-expose-headers"}


# --- Origine autorisée ------------------------------------------------------------------------


def test_a_listed_origin_may_read_the_response_and_only_that_origin(make_client):
    response = make_client(ALLOWED).get("/api/v1/health", headers={"Origin": ALLOWED})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED
    assert "origin" in response.headers["vary"].lower()


def test_the_response_to_an_allowed_origin_exposes_the_headers_a_script_needs(make_client):
    response = make_client(ALLOWED).get("/api/v1/health", headers={"Origin": ALLOWED})
    exposed = {
        name.strip() for name in response.headers["access-control-expose-headers"].split(",")
    }
    assert exposed == {"X-Correlation-ID", "Retry-After", "Allow", "Deprecation", "Sunset"}
    assert exposed == set(EXPOSED_HEADERS)
    assert {"X-Correlation-ID", "Retry-After"} <= exposed


def test_credentials_are_never_allowed(make_client):
    response = make_client(ALLOWED).get("/api/v1/health", headers={"Origin": ALLOWED})
    assert "access-control-allow-credentials" not in response.headers


def test_several_origins_are_each_allowed_and_nothing_else(make_client):
    client = make_client(f"{ALLOWED}, http://127.0.0.1:5173")
    for origin in (ALLOWED, "http://127.0.0.1:5173"):
        response = client.get("/api/v1/health", headers={"Origin": origin})
        assert response.headers["access-control-allow-origin"] == origin
    assert (
        "access-control-allow-origin"
        not in client.get("/api/v1/health", headers={"Origin": OTHER}).headers
    )


# --- Origine inconnue -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "origin",
    [
        OTHER,
        "http://localhost:8081",
        "https://localhost:8080",
        "http://localhost",
        "null",
        "*",
        "http://localhost:8080.pirate.example",
        "HTTP://LOCALHOST:8080",
    ],
)
def test_any_other_origin_is_granted_nothing(make_client, origin):
    response = make_client(ALLOWED).get("/api/v1/health", headers={"Origin": origin})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
    assert grants_nothing(response)


def test_a_request_without_origin_is_unchanged(make_client):
    response = make_client(ALLOWED).get("/api/v1/health")
    assert response.status_code == 200
    assert cors(response) == {}


# --- Pré-vérification (OPTIONS) ---------------------------------------------------------------


def preflight(client, *, origin=ALLOWED, method="POST", headers="authorization, content-type"):
    return client.options(
        LOGIN,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": headers,
        },
    )


def test_a_preflight_from_an_allowed_origin_lists_the_allowed_methods_and_headers(make_client):
    response = preflight(make_client(ALLOWED))
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED
    assert set(response.headers["access-control-allow-methods"].split(", ")) == set(ALLOWED_METHODS)
    allowed = {
        h.strip().lower() for h in response.headers["access-control-allow-headers"].split(",")
    }
    safelisted = {"accept", "accept-language", "content-language"}  # toujours permis par Starlette
    # Écrits en dur : comparer la réponse à la constante du code ne détecterait pas un ajout.
    assert allowed == {"authorization", "content-type", "x-correlation-id"} | safelisted
    assert {h.lower() for h in ALLOWED_HEADERS} == {
        "authorization",
        "content-type",
        "x-correlation-id",
    }
    assert response.headers["access-control-max-age"] == "600"
    assert "access-control-allow-credentials" not in response.headers


def test_the_methods_allowed_are_get_and_post_only(make_client):
    assert sorted(ALLOWED_METHODS) == ["GET", "POST"]
    client = make_client(ALLOWED)
    for method in ("DELETE", "PUT", "PATCH"):
        assert preflight(client, method=method).status_code == 400, method


def test_a_preflight_asking_for_an_unlisted_header_is_refused(make_client):
    assert preflight(make_client(ALLOWED), headers="x-secret-header").status_code == 400


def test_a_preflight_from_an_unknown_origin_is_refused_without_cors_headers(make_client):
    response = preflight(make_client(ALLOWED), origin=OTHER)
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_every_method_the_api_publishes_is_in_the_cors_list():
    """Une nouvelle route en DELETE ou PATCH oblige à décider ici, pas à l'oublier."""
    published = {
        method for route in app.routes for method in getattr(route, "methods", None) or set()
    } - {"HEAD", "OPTIONS"}
    assert published <= set(ALLOWED_METHODS), published - set(ALLOWED_METHODS)


# --- Erreurs : le script de la page doit pouvoir les lire -------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "status"),
    [
        ("get", "/api/v1/auth/me", 401),
        ("get", "/api/v1/inconnue", 404),
        ("delete", LOGIN, 405),
        ("post", LOGIN, 422),
    ],
)
def test_an_error_response_to_an_allowed_origin_carries_the_cors_headers(
    make_client, method, path, status
):
    response = make_client(ALLOWED).request(method, path, headers={"Origin": ALLOWED}, json=None)
    assert response.status_code == status
    assert response.headers["access-control-allow-origin"] == ALLOWED
    assert response.headers["content-type"].startswith("application/problem+json")


def test_the_429_of_the_login_is_readable_by_the_script_with_its_retry_after(make_client, repo):
    client = make_client(ALLOWED)
    repo.make("alice")
    for _ in range(5):
        client.post(
            LOGIN, json={"username": "alice", "password": "faux"}, headers={"Origin": ALLOWED}
        )
    response = client.post(
        LOGIN, json={"username": "alice", "password": PASSWORD}, headers={"Origin": ALLOWED}
    )
    assert response.status_code == 429
    assert response.headers["access-control-allow-origin"] == ALLOWED
    assert "retry-after" in response.headers["access-control-expose-headers"].lower()


# --- Sans configuration : fermé ---------------------------------------------------------------


@pytest.mark.parametrize("origins", ["", "   ", " , "])
def test_without_origins_cors_is_not_mounted_at_all(make_client, origins):
    client = make_client(origins)
    simple = client.get("/api/v1/health", headers={"Origin": ALLOWED})
    assert simple.status_code == 200
    assert cors(simple) == {}
    refused = preflight(client)
    assert refused.status_code == 405
    assert cors(refused) == {}
    assert refused.headers["content-type"].startswith("application/problem+json")


def test_the_default_configuration_allows_no_origin():
    assert Settings().cors_origins == []


# --- Configuration ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "*",
        "http://localhost:8080,*",
        "localhost:8080",
        "http://localhost:8080/",
        "http://localhost:8080/app",
        "ftp://localhost",
        "http://*.example.com",
        "http://",
        "https://exemple.org?x=1",
        "javascript:alert(1)",
    ],
)
def test_a_wildcard_or_anything_but_an_exact_origin_is_refused_at_startup(value):
    with pytest.raises(ValidationError) as error:
        Settings(cors_allowed_origins=value)
    assert "CORS_ALLOWED_ORIGINS" in str(error.value)


@pytest.mark.parametrize(
    "value",
    [
        "http://localhost:8080",
        "https://app.novaria.example",
        "http://127.0.0.1:5173",
        "http://localhost:8080, https://app.novaria.example",
    ],
)
def test_exact_origins_are_accepted(value):
    assert Settings(cors_allowed_origins=value).cors_origins == [
        v.strip() for v in value.split(",")
    ]


def test_the_origins_come_from_the_environment_variable(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", f"{ALLOWED},https://app.novaria.example")
    assert Settings().cors_origins == [ALLOWED, "https://app.novaria.example"]
