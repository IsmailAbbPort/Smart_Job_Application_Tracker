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
    """Source that reports HTTP errors the way the real adapters now do.

    Sets its attributes in `fetch`, not in `__init__`, because that is what the real
    adapters do and the difference matters: the runner reads them after calling
    fetch, so a double that filled them in early would pass even if the runner read
    them at the wrong time.
    """

    ttl_seconds = 3600

    def __init__(self, name, jobs, http_errors, *, fetched_slugs=None, full_catalog=False):
        self.name = name
        self._jobs = jobs
        self._http_errors = http_errors
        self._fetched_slugs = fetched_slugs
        self.full_catalog = full_catalog
        self.http_errors: dict[str, int] = {}
        if fetched_slugs is not None:
            self.fetched_slugs: frozenset[str] | set[str] = frozenset()

    def fetch(self, client, session):  # noqa: ANN001 - args unused
        self.http_errors = dict(self._http_errors)
        if self._fetched_slugs is not None:
            self.fetched_slugs = set(self._fetched_slugs)
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


def test_worst_means_most_serious_not_numerically_largest(monkeypatch, session, no_throttle):
    # A rejected or moved endpoint (401/403) is a thing to go and fix; a 404 is
    # usually just a board that closed. Picking the larger number reported the 404
    # and pointed the message at the wrong one of the two.
    source = _StatusSource("greenhouse", [], {"a": 404, "b": 403})

    stats = _run(monkeypatch, session, source)

    assert "403" in stats.error


def test_boards_that_answered_but_had_nothing_are_not_a_dead_source(
    monkeypatch, session, no_throttle
):
    # Greenhouse answered for eight companies that simply have no openings, and
    # 404'd for one that closed its board. Judging that on "no jobs plus some bad
    # status" called the whole source down and sent a false alarm.
    source = _StatusSource(
        "greenhouse", [], {"closed": 404}, fetched_slugs={"acme", "globex"}, full_catalog=True
    )

    stats = _run(monkeypatch, session, source)

    assert stats.error is None
    assert stats.http_errors == {"closed": 404}


def test_a_source_whose_every_board_failed_is_down(monkeypatch, session, no_throttle):
    source = _StatusSource(
        "greenhouse", [], {"acme": 503, "globex": 503}, fetched_slugs=set(), full_catalog=True
    )

    stats = _run(monkeypatch, session, source)

    assert stats.error is not None
    assert "503" in stats.error


def test_a_failed_fetch_is_recorded_on_the_throttle_row(monkeypatch, session):
    # record_fetch is what the per-source TTL reads. The other tests stub it out, so
    # nothing covered the fact that a failing source still has to write that row -
    # if it did not, the next run would re-hit a dead source with no backoff at all.
    recorded: list[tuple] = []
    monkeypatch.setattr(runner.cache, "should_fetch", lambda *a, **k: True)
    monkeypatch.setattr(
        runner.cache,
        "record_fetch",
        lambda session, name, *, status, count: recorded.append((name, status, count)),
    )

    _run(monkeypatch, session, _StatusSource("remotive", [], {"remotive": 503}))

    assert recorded == [("remotive", "error", 0)]


def test_a_raising_source_is_also_recorded(monkeypatch, session):
    recorded: list[tuple] = []
    monkeypatch.setattr(runner.cache, "should_fetch", lambda *a, **k: True)
    monkeypatch.setattr(
        runner.cache,
        "record_fetch",
        lambda session, name, *, status, count: recorded.append((name, status, count)),
    )

    class _Boom:
        name = "remotive"
        ttl_seconds = 3600

        def fetch(self, client, session):  # noqa: ANN001
            raise httpx.ConnectError("getaddrinfo failed")

    stats = _run(monkeypatch, session, _Boom())

    assert "ConnectError" in stats.error
    assert recorded == [("remotive", "error", 0)]


def test_http_errors_survive_into_the_summary(monkeypatch, session, no_throttle):
    # The notifier reads ["sources"], so the error has to reach that far.
    monkeypatch.setattr(
        runner, "SOURCES", {"remotive": _StatusSource("remotive", [], {"remotive": 503})}
    )

    payload = runner.ingest_all(session).as_dict()

    assert payload["sources"][0]["error"] is not None
    assert payload["sources"][0]["http_errors"] == {"remotive": 503}
