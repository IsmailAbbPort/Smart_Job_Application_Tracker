"""GET /ops/runs and POST /ops/notify-test."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.config import Settings, get_settings
from app.main import app as fastapi_app
from app.notify import telegram
from tests.test_notify import make_run

NOW = datetime(2026, 11, 5, 15, 2, tzinfo=UTC)


def test_runs_lists_the_newest_first(client, session_factory):
    with session_factory() as s:
        s.add(make_run(started_at=NOW - timedelta(days=1), trigger="schedule", inserted=2))
        s.add(make_run(started_at=NOW, trigger="catchup", inserted=7))
        s.commit()

    body = client.get("/ops/runs?limit=10").json()

    assert [r["trigger"] for r in body["runs"]] == ["catchup", "schedule"]
    assert body["runs"][0]["inserted"] == 7


def test_runs_is_empty_before_the_first_run(client):
    assert client.get("/ops/runs").json() == {"runs": []}


def test_runs_names_which_source_broke(client, session_factory):
    # "partial" on its own sends you to the container logs to find out what for,
    # which is the thing this endpoint exists to avoid.
    with session_factory() as s:
        s.add(
            make_run(
                started_at=NOW,
                status="partial",
                inserted=4,
                sources={
                    "sources": [
                        {"source": "greenhouse", "inserted": 4, "error": None},
                        {"source": "remotive", "inserted": 0, "error": "ConnectError: boom"},
                    ]
                },
                checked=["greenhouse", "internet", "run"],
            )
        )
        s.commit()

    run = client.get("/ops/runs").json()["runs"][0]

    assert [src["source"] for src in run["sources"]] == ["greenhouse", "remotive"]
    assert run["sources"][1]["error"] == "ConnectError: boom"
    assert run["checked"] == ["greenhouse", "internet", "run"]


def test_notify_test_503s_when_unconfigured(client):
    # Mirrors get_embedder/get_judge: a missing credential is a 503, not a silent
    # "sent: false" that reads as a delivery failure.
    fastapi_app.dependency_overrides[get_settings] = lambda: Settings(
        telegram_bot_token=None, telegram_chat_id=None
    )
    try:
        resp = client.post("/ops/notify-test")
    finally:
        fastapi_app.dependency_overrides.pop(get_settings, None)

    assert resp.status_code == 503
    assert "TELEGRAM_BOT_TOKEN" in resp.json()["detail"]


def test_notify_test_reports_whether_it_sent(client, monkeypatch):
    monkeypatch.setattr(telegram, "send_message", lambda text, settings=None: True)
    fastapi_app.dependency_overrides[get_settings] = lambda: Settings(
        telegram_bot_token="tok", telegram_chat_id="42"
    )
    try:
        resp = client.post("/ops/notify-test")
    finally:
        fastapi_app.dependency_overrides.pop(get_settings, None)

    assert resp.json() == {"configured": True, "sent": True}
