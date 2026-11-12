"""Fixtures communes : secret de test, application avec dépôt en mémoire, jetons."""

import pytest
from fastapi.testclient import TestClient

from app.api.deps import reset_login_throttle
from app.api.v1.reports import get_report_service
from app.core.config import get_settings
from app.db.session import get_indicator_repository, get_user_repository
from app.main import app
from app.services.reports import FileReportStore, ReportService
from tests.fakes import SECRET, FakeIndicatorRepository, FakeUserRepository, Journal
from tests.scene import Scene


@pytest.fixture(autouse=True)
def fresh_login_throttle():
    """La limite de la connexion est celle du processus : chaque test repart sans essai compté."""
    reset_login_throttle()
    yield
    reset_login_throttle()


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
def indicators() -> FakeIndicatorRepository:
    return FakeIndicatorRepository()


@pytest.fixture
def journal() -> Journal:
    return Journal()


@pytest.fixture
def reports_dir(tmp_path):
    """Le dossier où le robot dépose ses rapports : vide, propre à chaque test."""
    directory = tmp_path / "rapports"
    directory.mkdir()
    return directory


@pytest.fixture
def client(secret, repo, indicators, journal, reports_dir):
    app.dependency_overrides[get_user_repository] = lambda: repo
    app.dependency_overrides[get_indicator_repository] = lambda: indicators
    app.dependency_overrides[get_report_service] = lambda: ReportService(
        FileReportStore(reports_dir)
    )
    app.state.observer = journal.observer
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        app.state.observer = None


@pytest.fixture
def scene(client, repo) -> Scene:
    """Le client de test et des comptes à la demande, pour provoquer une erreur précise."""
    return Scene(client, repo)
