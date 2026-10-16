from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok_and_revision():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "revision" in body
