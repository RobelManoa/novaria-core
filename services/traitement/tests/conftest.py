"""Fixtures communes : secret de test, application avec dépôt en mémoire, jetons."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.session import get_user_repository
from app.main import app
from tests.fakes import SECRET, FakeUserRepository


@pytest.fixture
def secret(monkeypatch) -> str:
    """Un secret JWT de test dans l'environnement ; la configuration est relue."""
    monkeypatch.setenv("JWT_SECRET", SECRET)
    monkeypatch.delenv("ACCESS_TOKEN_TTL_S", raising=False)
    get_settings.cache_clear()
    yield SECRET
    get_settings.cache_clear()


@pytest.fixture
def repo() -> FakeUserRepository:
    return FakeUserRepository()


@pytest.fixture
def client(secret, repo):
    app.dependency_overrides[get_user_repository] = lambda: repo
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
