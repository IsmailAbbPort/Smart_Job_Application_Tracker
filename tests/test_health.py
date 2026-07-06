"""Liveness endpoint test. Pure (no DB), so it stays green in CI without Postgres."""

from fastapi.testclient import TestClient

from app import __version__
from app.main import app

client = TestClient(app)


def test_health_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
