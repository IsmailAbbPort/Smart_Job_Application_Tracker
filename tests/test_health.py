"""Liveness endpoint test. Pure (no DB), so it stays green in CI without Postgres."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.main import STATIC_DIR, app

client = TestClient(app)


def test_health_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__


def test_root_serves_spa():
    # index.html is now a Vite build artifact (gitignored, produced by `make
    # fe-build` / the Docker Node stage), so skip when it hasn't been built.
    if not (Path(STATIC_DIR) / "index.html").exists():
        pytest.skip("frontend not built; run `make fe-build` to produce app/static/index.html")
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Smart Job" in resp.text  # the single-page UI is served at /
