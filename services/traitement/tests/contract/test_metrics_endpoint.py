"""`GET /metrics` : l'indicateur de dérive exposé (IA-06 : la dérive simulée déclenche l'alerte)."""

import logging

import pytest

from app.drift.monitor import Thresholds
from app.drift.runtime import get_drift_monitor
from app.drift.service import DriftMonitor
from app.main import app
from tests.drift_data import calm, moderately_slower, rush
from tests.fakes import FakeIndicatorRepository

METRICS = "/metrics"


def monitor(reference: str | None = "run-calme") -> DriftMonitor:
    return DriftMonitor(
        reference_run_id=reference, thresholds=Thresholds(), max_rows=20000, cache_s=0
    )


@pytest.fixture
def serve(client, indicators):
    """Remplace le moniteur du processus par un moniteur de test sur l'entrepôt en mémoire."""

    def install(*runs, reference: str | None = "run-calme"):
        indicators.rows += [row for run in runs for row in run]
        shared = monitor(reference)  # un seul moniteur, comme dans le processus
        app.dependency_overrides[get_drift_monitor] = lambda: shared
        return client

    return install


def scrape(client):
    response = client.get(METRICS)
    assert response.status_code == 200, response.text
    values = {}
    for line in response.text.splitlines():
        if not line.startswith("#"):
            name, _, value = line.rpartition(" ")
            values[name] = float(value)
    return response, values


def test_a_simulated_drift_raises_the_alert_indicator_and_logs_the_alert(serve, caplog):
    client = serve(calm("run-calme"), rush("run-pointe"))
    with caplog.at_level(logging.INFO, logger="app.drift"):
        response, values = scrape(client)
    assert response.headers["content-type"].startswith("text/plain")
    assert values["novaria_input_drift_alert"] == 1
    assert values['novaria_input_drift_psi{feature="speed_ratio"}'] > 0.25
    assert [r.getMessage() for r in caplog.records if r.name == "app.drift"] == [
        "dérive des entrées détectée"
    ]


def test_a_stable_warehouse_keeps_the_indicator_at_zero_and_logs_nothing(serve, caplog):
    client = serve(calm("run-calme"))
    with caplog.at_level(logging.INFO, logger="app.drift"):
        _, values = scrape(client)
    assert values["novaria_input_drift_alert"] == 0
    assert values['novaria_input_drift_status{status="OK"}'] == 1
    assert [r for r in caplog.records if r.name == "app.drift"] == []


def test_a_moderate_shift_warns_without_the_alert_indicator(serve):
    _, values = scrape(serve(calm("run-calme"), moderately_slower()))
    assert values["novaria_input_drift_alert"] == 0
    assert values['novaria_input_drift_status{status="WARN"}'] == 1


def test_scraping_again_does_not_log_the_same_alert_twice(serve, caplog):
    client = serve(calm("run-calme"), rush("run-pointe"))
    with caplog.at_level(logging.INFO, logger="app.drift"):
        for _ in range(3):
            scrape(client)
    assert len([r for r in caplog.records if r.name == "app.drift"]) == 1


def test_without_a_reference_run_the_endpoint_says_so_and_stays_quiet(serve, caplog):
    client = serve(calm("run-calme"), reference=None)
    with caplog.at_level(logging.INFO, logger="app.drift"):
        _, values = scrape(client)
    assert values['novaria_input_drift_status{status="NO_REFERENCE"}'] == 1
    assert (values["novaria_input_drift_alert"], values["novaria_input_drift_check_ok"]) == (0, 0)
    assert [r for r in caplog.records if r.name == "app.drift"] == []


def test_an_empty_warehouse_answers_no_data(client, indicators):
    app.dependency_overrides[get_drift_monitor] = lambda: monitor()
    assert isinstance(indicators, FakeIndicatorRepository)
    _, values = scrape(client)
    assert values['novaria_input_drift_status{status="NO_DATA"}'] == 1


def test_the_endpoint_needs_no_token_and_is_not_part_of_the_api_contract(serve):
    client = serve(calm("run-calme"))
    assert "Authorization" not in client.headers
    assert client.get(METRICS).status_code == 200
    assert METRICS not in app.openapi()["paths"]


def test_only_get_is_allowed_and_the_versioned_path_does_not_exist(serve):
    client = serve(calm("run-calme"))
    assert client.post(METRICS).status_code == 405
    assert client.get("/api/v1/metrics").status_code == 404


def test_the_metrics_response_carries_the_security_headers_and_a_correlation_id(serve):
    response = serve(calm("run-calme")).get(METRICS)
    assert response.headers["X-Correlation-ID"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_an_unreachable_warehouse_is_a_503_without_the_address(client):
    from sqlalchemy.exc import OperationalError

    from app.db.session import get_indicator_repository

    def broken():
        raise OperationalError(
            "SELECT 1", {}, Exception("connection refused : postgresql://u:pw@h")
        )

    app.dependency_overrides[get_indicator_repository] = broken
    app.dependency_overrides[get_drift_monitor] = lambda: monitor()
    response = client.get(METRICS)
    assert response.status_code == 503
    assert "postgresql" not in response.text
