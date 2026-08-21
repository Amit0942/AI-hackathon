"""Smoke test for Step 0.1 exit criteria: the app is runnable and testable."""

from fastapi.testclient import TestClient

from agentiq.api.main import app


def test_health_ok() -> None:
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body
