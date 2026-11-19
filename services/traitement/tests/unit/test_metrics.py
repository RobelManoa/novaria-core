"""Métriques Prometheus (MS-16) : compteurs, histogrammes, intergiciel HTTP et `GET /metrics`.

Même fichier dans tous les services.
"""

import re
import threading

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.metrics import BUCKETS, MetricsMiddleware, Registry, metrics_response


def build() -> tuple[TestClient, Registry]:
    registry = Registry()
    registry.describe("novaria_http_requests_total", "counter", "requêtes")
    registry.describe("novaria_http_requests_in_flight", "gauge", "en cours")
    app = FastAPI()
    app.add_middleware(MetricsMiddleware, service="essai", registry=registry)

    @app.get("/items/{item_id}")
    def item(item_id: str) -> dict[str, str]:
        if item_id == "boom":
            raise HTTPException(status_code=503, detail="indisponible")
        return {"id": item_id}

    @app.get("/metrics")
    def metrics():
        return metrics_response(registry=registry)

    return TestClient(app, raise_server_exceptions=False), registry


def sample(text: str, name: str, **labels: str) -> float:
    pattern = re.compile(rf"^{re.escape(name)}\{{(.*)\}} (\S+)$", re.M)
    for found in pattern.finditer(text):
        if all(f'{k}="{v}"' in found.group(1) for k, v in labels.items()):
            return float(found.group(2))
    raise AssertionError(f"série absente : {name} {labels}\n{text}")


def test_a_counter_counts_by_label_set():
    registry = Registry()
    registry.inc("c", {"a": "1"})
    registry.inc("c", {"a": "1"}, 2)
    registry.inc("c", {"a": "2"})
    assert registry.value("c", {"a": "1"}) == 3
    assert registry.value("c", {"a": "2"}) == 1
    assert registry.value("c", {"a": "absent"}) == 0


def test_a_gauge_keeps_the_last_value():
    registry = Registry()
    registry.set("g", 5)
    registry.set("g", 2)
    assert registry.value("g") == 2


def test_a_histogram_is_cumulative_and_has_sum_and_count():
    registry = Registry()
    for value in (0.004, 0.2, 20.0):
        registry.observe("h", value, {"r": "x"})
    text = registry.render()
    assert sample(text, "h_bucket", r="x", le="0.005") == 1
    assert sample(text, "h_bucket", r="x", le="0.25") == 2
    assert sample(text, "h_bucket", r="x", le="+Inf") == 3
    assert sample(text, "h_count", r="x") == 3
    assert abs(sample(text, "h_sum", r="x") - 20.204) < 1e-9
    assert len(BUCKETS) == 11


def test_label_values_are_escaped_so_a_line_cannot_be_forged():
    registry = Registry()
    registry.inc("c", {"x": 'a"b\nc\\d'})
    line = next(row for row in registry.render().splitlines() if row.startswith("c{"))
    assert line == 'c{x="a\\"b\\nc\\\\d"} 1'


def test_the_middleware_counts_requests_by_route_template_and_status_class():
    client, _ = build()
    assert client.get("/items/42").status_code == 200
    assert client.get("/items/43").status_code == 200
    assert client.get("/items/boom").status_code == 503
    text = client.get("/metrics").text
    assert (
        sample(
            text,
            "novaria_http_requests_total",
            route="/items/{item_id}",
            status="2xx",
            service="essai",
        )
        == 2
    )
    assert sample(text, "novaria_http_requests_total", route="/items/{item_id}", status="5xx") == 1


def test_a_path_with_an_identifier_never_becomes_a_label():
    client, _ = build()
    client.get("/items/secret-value-123")
    assert "secret-value-123" not in client.get("/metrics").text


def test_unknown_routes_share_one_label_so_series_do_not_explode():
    client, _ = build()
    for path in ("/a", "/b", "/c"):
        assert client.get(path).status_code == 404
    text = client.get("/metrics").text
    assert sample(text, "novaria_http_requests_total", route="inconnue", status="4xx") == 3


def test_the_metrics_endpoint_does_not_count_itself():
    client, _ = build()
    client.get("/metrics")
    client.get("/metrics")
    assert 'route="/metrics"' not in client.get("/metrics").text


def test_the_duration_histogram_is_filled_and_in_flight_returns_to_zero():
    client, _ = build()
    client.get("/items/1")
    text = client.get("/metrics").text
    assert (
        sample(text, "novaria_http_request_duration_seconds_count", route="/items/{item_id}") == 1
    )
    assert sample(text, "novaria_http_requests_in_flight", service="essai") == 0


def test_the_content_type_is_the_prometheus_text_format():
    client, _ = build()
    assert client.get("/metrics").headers["content-type"].startswith("text/plain; version=0.0.4")


def test_counters_are_safe_between_threads():
    registry = Registry()

    def work() -> None:
        for _ in range(500):
            registry.inc("c")

    threads = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert registry.value("c") == 4000
