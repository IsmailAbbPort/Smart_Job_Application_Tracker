"""Daily rate limits on the paid AI endpoints (app/ratelimit.py + route wiring)."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException

from app import ratelimit
from app.models import AiUsage, Cv, Job


class FakeRequest:
    """Minimal stand-in for starlette Request: only what ratelimit reads."""

    def __init__(self, ip: str = "1.2.3.4", forwarded: str | None = None):
        self.headers: dict[str, str] = {}
        if forwarded:
            self.headers["x-forwarded-for"] = forwarded
        self.client = type("Client", (), {"host": ip})()


def _job(source_id: str, *, embedding=None) -> Job:
    return Job(
        source="test",
        source_id=source_id,
        title="Engineer",
        company="Acme",
        url=f"https://example.com/{source_id}",
        description="Python FastAPI Postgres role.",
        is_remote=True,
        is_european=True,
        embedding=embedding,
    )


# --- unit: consume / refund / charge ---


def test_consume_increments_then_blocks_at_per_identity_cap(session, monkeypatch):
    monkeypatch.setattr(ratelimit, "_limits", lambda a: (2, 100))
    req = FakeRequest()
    ratelimit.consume(session, req, None, "judge")
    ratelimit.consume(session, req, None, "judge")
    with pytest.raises(HTTPException) as exc:
        ratelimit.consume(session, req, None, "judge")
    assert exc.value.status_code == 429
    assert "2" in exc.value.detail and "UTC" in exc.value.detail


def test_global_cap_blocks_across_different_identities(session, monkeypatch):
    monkeypatch.setattr(ratelimit, "_limits", lambda a: (100, 2))
    ratelimit.consume(session, FakeRequest(ip="1.1.1.1"), None, "judge")
    ratelimit.consume(session, FakeRequest(ip="2.2.2.2"), None, "judge")
    with pytest.raises(HTTPException) as exc:
        ratelimit.consume(session, FakeRequest(ip="3.3.3.3"), None, "judge")
    assert exc.value.status_code == 429
    assert "next month" in exc.value.detail.lower()


def test_global_monthly_cap_ignores_prior_months(session, monkeypatch):
    monkeypatch.setattr(ratelimit, "_limits", lambda a: (100, 2))
    # Usage dated in a prior month is over the cap on its own, but must not count
    # toward the current month's global ceiling (the cap is monthly, not lifetime).
    session.add(AiUsage(identity="ip:old", action="judge", day=date(2000, 1, 15), count=9))
    session.commit()
    ratelimit.consume(session, FakeRequest(ip="1.1.1.1"), None, "judge")
    ratelimit.consume(session, FakeRequest(ip="2.2.2.2"), None, "judge")
    with pytest.raises(HTTPException) as exc:
        ratelimit.consume(session, FakeRequest(ip="3.3.3.3"), None, "judge")
    assert exc.value.status_code == 429


def test_refund_frees_a_unit(session, monkeypatch):
    monkeypatch.setattr(ratelimit, "_limits", lambda a: (1, 100))
    req = FakeRequest()
    ratelimit.consume(session, req, None, "judge")  # at cap
    ratelimit.refund(session, req, None, "judge")  # back under
    ratelimit.consume(session, req, None, "judge")  # allowed again


def test_user_and_guest_ip_have_separate_buckets(session, monkeypatch):
    monkeypatch.setattr(ratelimit, "_limits", lambda a: (1, 100))
    req = FakeRequest()
    ratelimit.consume(session, req, 7, "judge")  # identity user:7
    ratelimit.consume(session, req, None, "judge")  # identity ip:... (separate)
    with pytest.raises(HTTPException):
        ratelimit.consume(session, req, 7, "judge")  # user:7 now over


def _trust_forwarded(monkeypatch, trusted: bool) -> None:
    """Override the trust_forwarded_for setting read by _identity."""
    stub = type("S", (), {"trust_forwarded_for": trusted})()
    monkeypatch.setattr(ratelimit, "get_settings", lambda: stub)


def test_forwarded_for_is_the_guest_identity_when_trusted(session, monkeypatch):
    monkeypatch.setattr(ratelimit, "_limits", lambda a: (1, 100))
    _trust_forwarded(monkeypatch, True)
    # Behind a trusted proxy: the same proxied client (X-Forwarded-For) shares a
    # bucket even if the peer IP differs.
    ratelimit.consume(session, FakeRequest(ip="10.0.0.1", forwarded="9.9.9.9"), None, "judge")
    with pytest.raises(HTTPException):
        ratelimit.consume(session, FakeRequest(ip="10.0.0.2", forwarded="9.9.9.9"), None, "judge")


def test_forwarded_for_ignored_when_untrusted(session, monkeypatch):
    monkeypatch.setattr(ratelimit, "_limits", lambda a: (1, 100))
    _trust_forwarded(monkeypatch, False)
    # Default (no trusted proxy): X-Forwarded-For is ignored, so a spoofed header
    # can't mint a fresh bucket. Same peer IP shares one bucket regardless of XFF.
    ratelimit.consume(session, FakeRequest(ip="10.0.0.1", forwarded="9.9.9.9"), None, "judge")
    with pytest.raises(HTTPException):
        ratelimit.consume(session, FakeRequest(ip="10.0.0.1", forwarded="8.8.8.8"), None, "judge")


def test_charge_refunds_when_the_wrapped_call_raises(session, monkeypatch):
    monkeypatch.setattr(ratelimit, "_limits", lambda a: (1, 100))
    req = FakeRequest()
    with pytest.raises(RuntimeError):
        with ratelimit.charge(session, req, None, "judge"):
            raise RuntimeError("llm failed")
    # The failed call was refunded, so a real one still fits under the cap.
    with ratelimit.charge(session, req, None, "judge"):
        pass


# --- routes: judge + letter ---


def test_judge_route_returns_429_over_cap(judge_client, session_factory, monkeypatch):
    monkeypatch.setattr(ratelimit, "_limits", lambda a: (1, 100))
    with session_factory() as s:
        s.add(Cv(label="CV", content="Python FastAPI engineer"))
        s.add_all([_job("a"), _job("b")])
        s.commit()
        ids = [j.id for j in s.query(Job).order_by(Job.id).all()]

    assert judge_client.post(f"/match/{ids[0]}").status_code == 200
    resp = judge_client.post(f"/match/{ids[1]}")
    assert resp.status_code == 429
    assert "assessment" in resp.json()["detail"].lower()


def test_cached_judge_is_not_charged(judge_client, session_factory, monkeypatch):
    monkeypatch.setattr(ratelimit, "_limits", lambda a: (1, 100))
    with session_factory() as s:
        s.add(Cv(label="CV", content="Python FastAPI engineer"))
        s.add(_job("a"))
        s.commit()
        job_id = s.query(Job).one().id

    assert judge_client.post(f"/match/{job_id}").status_code == 200  # charges the 1 allowed
    # Same job again = cache hit, so it must not be charged (would be 429 if it were).
    assert judge_client.post(f"/match/{job_id}").status_code == 200


def test_letter_route_returns_429_over_cap(letter_client, session_factory, monkeypatch):
    monkeypatch.setattr(ratelimit, "_limits", lambda a: (1, 100))
    with session_factory() as s:
        cv = Cv(label="CV", content="Python FastAPI Postgres engineer")
        s.add(cv)
        s.add_all([_job("a"), _job("b")])
        s.commit()
        cv_id = cv.id
        ids = [j.id for j in s.query(Job).order_by(Job.id).all()]

    assert letter_client.post(f"/letters/{ids[0]}", params={"cv_id": cv_id}).status_code == 200
    resp = letter_client.post(f"/letters/{ids[1]}", params={"cv_id": cv_id})
    assert resp.status_code == 429
    assert "cover letter" in resp.json()["detail"].lower()
