"""Fixtures communes : le service d'ingestion branché sur des faux, et le client HTTP."""

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_ingestion_service
from app.core.config import get_settings
from app.main import app
from tests.support import Rig


@pytest.fixture(autouse=True)
def fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def rig() -> Rig:
    return Rig()


@pytest.fixture
def client(rig):
    app.dependency_overrides[get_ingestion_service] = lambda: rig.service
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
