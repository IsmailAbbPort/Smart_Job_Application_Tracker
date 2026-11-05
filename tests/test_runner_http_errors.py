"""A source that answers with a bad status must read as down, not as empty.

Regression: every adapter swallowed non-200 with `continue` / `return []`, so a
Remotive 503 produced fetched=0, error=None, status=ok and inserted=0 - identical
to a genuinely empty feed. The run looked clean and no notification was sent, which
is precisely the failure the Telegram notifier exists to report.
"""

from __future__ import annotations

import httpx
import pytest

from app.ingest import runner
from tests.conftest import make_canonical


class _StatusSource:
    """Source that reports HTTP errors the way the real adapters now do."""

    ttl_seconds = 3600

    def __init__(self, name, jobs, http_errors):
        self.name = name
        self._jobs = jobs
        self.http_errors = http_errors

    def fetch(self, client, session):  # noqa: ANN001 - args unused
        return list(self._jobs)


@pytest.fixture
def no_throttle(monkeypatch):
    monkeypatch.setattr(runner.cache, "should_fetch", lambda *a, **k: True)
    monkeypatch.setattr(runner.cache, "record_fetch", lambda *a, **k: None)


def _run(monkeypatch, session, source):
    monkeypatch.setitem(runner.SOURCES, source.name, source)
    return runner.ingest_source(session, source.name, client=httpx.Client())


def test_dead_source_is_an_error_not_an_empty_feed(monkeypatch, session, no_throttle):
    source = _StatusSource("remotive", [], {"remotive": 503})

    stats = _run(monkeypatch, session, source)

    assert stats.error is not None
    assert "503" in stats.error
    assert stats.http_errors == {"remotive": 503}


def test_a_genuinely_empty_feed_is_not_an_error(monkeypatch, session, no_throttle):
    stats = _run(monkeypatch, session, _StatusSource("remotive", [], {}))

    assert stats.error is None
    assert stats.fetched == 0


def test_one_retired_board_among_many_is_not_a_source_failure(monkeypatch, session, no_throttle):
    # Greenhouse iterates many companies; a single 404 is a company that closed its
    # board, not Greenhouse being down. Recorded for visibility, but not an error.
    source = _StatusSource(
        "greenhouse", [make_canonical(source="greenhouse", source_id="acme:1")], {"dead": 404}
    )

    stats = _run(monkeypatch, session, source)

    assert stats.error is None
    assert stats.inserted == 1
    assert stats.http_errors == {"dead": 404}


def test_the_worst_status_is_the_one_reported(monkeypatch, session, no_throttle):
    source = _StatusSource("greenhouse", [], {"a": 404, "b": 503})

    stats = _run(monkeypatch, session, source)

    assert "503" in stats.error


def test_http_errors_survive_into_the_summary(monkeypatch, session, no_throttle):
    # The notifier reads ["sources"], so the error has to reach that far.
    monkeypatch.setattr(
        runner, "SOURCES", {"remotive": _StatusSource("remotive", [], {"remotive": 503})}
    )

    payload = runner.ingest_all(session).as_dict()

    assert payload["sources"][0]["error"] is not None
    assert payload["sources"][0]["http_errors"] == {"remotive": 503}
