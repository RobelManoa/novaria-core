"""En-têtes de sécurité (BE-08) : présents sur toutes les réponses, erreurs et 500 compris."""

import asyncio

import pytest

from app.core.headers import (
    BASE_HEADERS,
    CONTENT_SECURITY_POLICY,
    SecurityHeadersMiddleware,
    headers_for,
)
from app.db.session import get_user_repository
from app.main import app
from tests.fakes import PASSWORD

EVERYWHERE = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "content-security-policy": CONTENT_SECURITY_POLICY,
}


def assert_secured(response):
    for name, value in EVERYWHERE.items():
        assert response.headers.get(name) == value, name


@pytest.mark.parametrize(
    ("method", "path", "status"),
    [
        ("get", "/api/v1/health", 200),
        ("get", "/api/v1/auth/me", 401),
        ("get", "/api/v1/inconnue", 404),
        ("delete", "/api/v1/auth/login", 405),
        ("post", "/api/v1/auth/login", 422),
        ("get", "/openapi.json", 200),
    ],
)
def test_every_response_carries_the_security_headers(client, method, path, status):
    response = client.request(method, path)
    assert response.status_code == status
    assert_secured(response)


def test_a_server_error_carries_them_too(client, repo):
    def broken():
        raise RuntimeError("panne")

    app.dependency_overrides[get_user_repository] = broken
    response = client.post("/api/v1/auth/login", json={"username": "alice", "password": PASSWORD})
    assert response.status_code == 500
    assert_secured(response)


def test_the_429_carries_them_too(client, repo):
    repo.make("alice")
    for _ in range(6):
        response = client.post("/api/v1/auth/login", json={"username": "alice", "password": "faux"})
    assert response.status_code == 429
    assert_secured(response)


def test_a_token_is_never_cached(client, repo):
    repo.make("alice")
    login = client.post("/api/v1/auth/login", json={"username": "alice", "password": PASSWORD})
    assert login.status_code == 200
    assert login.headers["cache-control"] == "no-store"
    rejected = client.post("/api/v1/auth/login", json={"username": "alice", "password": "faux"})
    assert rejected.headers["cache-control"] == "no-store"
    me = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}
    )
    assert me.headers["cache-control"] == "no-store"


def test_other_routes_do_not_get_a_cache_policy_of_ours(client):
    assert "cache-control" not in client.get("/api/v1/health").headers


@pytest.mark.parametrize("path", ["/docs", "/redoc"])
def test_the_documentation_pages_keep_working_without_the_content_policy(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert "content-security-policy" not in response.headers
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


def test_the_policy_only_exempts_the_documentation():
    assert "Content-Security-Policy" in headers_for("/api/v1/health")
    assert "Content-Security-Policy" in headers_for(
        "/documents"
    )  # `/docs` n'est pas un préfixe de mot
    assert "Content-Security-Policy" not in headers_for("/docs")
    assert "Content-Security-Policy" not in headers_for("/docs/oauth2-redirect")
    assert "Content-Security-Policy" not in headers_for("/redoc")
    assert set(BASE_HEADERS) <= set(headers_for("/docs"))


# --- Branchement ASGI -------------------------------------------------------------------------


async def run(inner, scope_type="http", path="/api/v1/health"):
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await SecurityHeadersMiddleware(inner)({"type": scope_type, "path": path}, receive, send)
    return sent


def test_a_header_the_route_already_chose_is_not_replaced():
    async def inner(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"x-frame-options", b"SAMEORIGIN"), (b"cache-control", b"max-age=5")],
            }
        )
        await send({"type": "http.response.body", "body": b""})

    sent = asyncio.run(run(inner, path="/api/v1/auth/me"))
    headers = {k.decode(): v.decode() for k, v in sent[0]["headers"]}
    assert headers["x-frame-options"] == "SAMEORIGIN"
    assert headers["cache-control"] == "max-age=5"
    assert headers["x-content-type-options"] == "nosniff"


def test_a_non_http_scope_goes_through_untouched():
    seen = []

    async def inner(scope, receive, send):
        seen.append(scope["type"])

    asyncio.run(run(inner, scope_type="lifespan"))
    assert seen == ["lifespan"]
