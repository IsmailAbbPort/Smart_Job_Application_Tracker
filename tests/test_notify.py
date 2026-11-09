"""The Telegram notifier: what it says, when it stays silent, and what it survives.

The taxonomy tests are built from real exception instances and real provider error
bodies rather than from strings invented to match the implementation, because the
whole point of the classifier is to recognise what the SDKs actually raise.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.exc import OperationalError

from app import scheduler
from app.config import Settings
from app.models import PipelineRun
from app.notify import telegram
from app.notify.problems import Problem, classify_problem, collect_problems
from app.notify.telegram import format_run_message

NOW = datetime(2026, 11, 5, 15, 2, tzinfo=UTC)
_REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
# Spelled out rather than Settings(): a developer's real .env must not decide
# whether these tests exercise the configured or the unconfigured path.
UNCONFIGURED = Settings(telegram_bot_token=None, telegram_chat_id=None, notify_heartbeat_days=0)


def make_run(**fields) -> PipelineRun:
    """An unpersisted run row. Column defaults only apply on insert, so spell them."""
    defaults = {
        "started_at": NOW,
        "finished_at": NOW,
        "trigger": "schedule",
        "status": "ok",
        "inserted": 0,
        "updated": 0,
        "removed_stale": 0,
        "embedded": 0,
        "classified": 0,
        "sources": {},
        "problems": [],
        "checked": [],
        "error": None,
        "notified_at": None,
    }
    return PipelineRun(**{**defaults, **fields})


def _sources(*entries: dict) -> dict:
    return {"sources": list(entries)}


# --- taxonomy ------------------------------------------------------------------


def test_no_internet_does_not_name_a_source():
    # Wifi off fails every source at once; five identical lines is five times the
    # noise and no more news, so the code is unscoped and collapses in dedup.
    problem = classify_problem(httpx.ConnectError("[Errno 11001] getaddrinfo failed"))

    assert problem.code == "no_internet"
    assert "No internet" in problem.line
    assert classify_problem(httpx.ConnectError("x"), source="lever").code == "no_internet"


@pytest.mark.parametrize(
    "exc",
    [httpx.ConnectTimeout("timed out"), httpx.ReadTimeout("timed out"), httpx.PoolTimeout("x")],
)
def test_timeouts_are_a_timeout_not_a_dead_connection(exc):
    # ConnectTimeout is NOT a subclass of ConnectError, so matching on ConnectError
    # alone would have sent "no internet" for a merely slow source.
    problem = classify_problem(exc, source="remotive")

    assert problem.code == "timeout:remotive"
    assert "Timed out reaching remotive" in problem.line


def test_source_5xx_is_their_problem():
    problem = classify_problem("HTTPStatusError: HTTP 503", source="remotive")

    assert problem.code == "down:remotive"
    assert "HTTP 503" in problem.line


def test_source_429_backs_off():
    assert classify_problem("HTTPStatusError: HTTP 429", source="lever").code == "ratelimit:lever"


def test_source_403_points_at_a_changed_endpoint():
    problem = classify_problem("HTTPStatusError: HTTP 403", source="ashby")

    assert problem.code == "refused:ashby"
    assert "may have changed" in problem.line


def test_rejected_ai_key_names_the_provider():
    import anthropic

    exc = anthropic.AuthenticationError(
        "invalid x-api-key", response=httpx.Response(401, request=_REQUEST), body=None
    )

    problem = classify_problem(exc)

    assert problem.code == "key:anthropic"
    assert "Check the key in .env" in problem.line


def test_anthropic_billing_error_is_credits_not_an_unexpected_error():
    # 402 arrives as a plain APIStatusError (the SDK exports no BillingError), so it
    # is recognised by the error body's type, not by an exception class.
    import anthropic

    exc = anthropic.APIStatusError(
        "Your credit balance is too low to access the Anthropic API",
        response=httpx.Response(402, request=_REQUEST),
        body={"type": "error", "error": {"type": "billing_error", "message": "too low"}},
    )

    problem = classify_problem(exc)

    assert problem.code == "credits:anthropic"
    assert "Top up" in problem.line


def test_openai_insufficient_quota_beats_the_plain_rate_limit():
    # insufficient_quota is a 429, so ordering matters: matched as a rate limit it
    # would promise a backfill next run that can never happen without a top-up.
    import openai

    exc = openai.RateLimitError(
        "You exceeded your current quota",
        response=httpx.Response(429, request=_REQUEST),
        body={"error": {"code": "insufficient_quota", "type": "insufficient_quota"}},
    )

    problem = classify_problem(exc)

    assert problem.code == "credits:openai"


def test_openai_quota_is_credits_even_once_flattened_to_a_string():
    # The provider is recognised from the exception's module, so a failure already
    # flattened to a string could never enter the provider branch - and the credit
    # check lived inside it. An exhausted OpenAI balance (the likeliest real failure
    # here) was therefore reported as a plain rate limit, promising a backfill next
    # run that cannot happen until somebody tops up.
    flattened = (
        "RateLimitError: Error code: 429 - {'error': {'message': 'You exceeded your current "
        "quota, please check your plan and billing details.', 'type': 'insufficient_quota', "
        "'code': 'insufficient_quota'}}"
    )

    problem = classify_problem(flattened)

    assert problem.code == "credits:ai"
    assert "Top up" in problem.line


def test_anthropic_credits_are_credits_even_once_flattened_to_a_string():
    flattened = (
        "APIStatusError: Your credit balance is too low to access the Anthropic API; "
        "{'type': 'error', 'error': {'type': 'billing_error'}}"
    )

    assert classify_problem(flattened).code == "credits:ai"


def test_a_known_provider_still_gets_its_own_credit_code():
    # The unscoped code is the fallback for a string, not a replacement: a live
    # exception still names the provider, so the two never collapse in dedup.
    import openai

    exc = openai.RateLimitError(
        "You exceeded your current quota",
        response=httpx.Response(429, request=_REQUEST),
        body={"error": {"code": "insufficient_quota"}},
    )

    assert classify_problem(exc).code == "credits:openai"


def test_a_plain_source_429_is_not_mistaken_for_exhausted_credits():
    # The credit markers have to be specific enough that an ordinary rate limit from
    # a job board does not read as a billing problem.
    assert classify_problem("HTTPStatusError: HTTP 429", source="lever").code == "ratelimit:lever"


def test_provider_429_reports_incomplete_enrichment():
    import openai

    exc = openai.RateLimitError(
        "Rate limit reached", response=httpx.Response(429, request=_REQUEST), body=None
    )

    problem = classify_problem(exc)

    assert problem.code == "ratelimit:openai"
    assert "next run backfills" in problem.line


def test_database_unreachable_points_at_the_container():
    exc = OperationalError("SELECT 1", {}, Exception("connection refused"))

    problem = classify_problem(exc)

    assert problem.code == "database"
    assert "Postgres container" in problem.line


def test_missing_openai_key_is_reported_when_there_are_new_jobs():
    problems = collect_problems(
        status="ok", error=None, sources=[], inserted=12, embedding_skipped=True
    )

    assert [p.code for p in problems] == ["no_openai_key"]
    assert "12 new jobs" in problems[0].line


def test_missing_openai_key_is_silent_when_nothing_was_ingested():
    assert (
        collect_problems(status="ok", error=None, sources=[], inserted=0, embedding_skipped=True)
        == []
    )


def test_an_unmatched_failure_still_says_something_useful():
    problem = classify_problem(ValueError("something odd"), source="lever")

    assert problem.code == "unexpected:lever"
    assert "something odd" in problem.line


def test_identical_problems_from_several_sources_collapse_to_one_line():
    problems = collect_problems(
        status="partial",
        error=None,
        sources=[
            {"source": "lever", "error": "ConnectError: getaddrinfo failed"},
            {"source": "ashby", "error": "ConnectError: getaddrinfo failed"},
            {"source": "remotive", "error": "ConnectError: getaddrinfo failed"},
        ],
        inserted=0,
    )

    assert [p.code for p in problems] == ["no_internet"]


def test_ai_failures_are_classified_too():
    import anthropic

    exc = anthropic.AuthenticationError(
        "invalid x-api-key", response=httpx.Response(401, request=_REQUEST), body=None
    )

    problems = collect_problems(status="ok", error=None, sources=[], inserted=1, ai_failures=[exc])

    assert [p.code for p in problems] == ["key:anthropic"]


# --- format_run_message --------------------------------------------------------


def test_news_leads_with_the_new_jobs_and_names_the_sources():
    run = make_run(
        inserted=12,
        embedded=12,
        classified=12,
        sources=_sources(
            {"source": "greenhouse", "inserted": 7},
            {"source": "lever", "inserted": 3},
            {"source": "ashby", "inserted": 2},
            {"source": "remotive", "inserted": 0},
        ),
    )

    text = format_run_message(run, now=NOW)

    assert text is not None
    lines = text.splitlines()
    # Africa/Cairo, not UTC: a UTC timestamp on a phone is a puzzle every day.
    assert lines[0] == "Job Tracker - 5 Nov 2026, 17:02"
    assert lines[1] == "12 new jobs (greenhouse 7, lever 3, ashby 2)"
    assert lines[2] == "embedded 12, classified 12"
    assert lines[-1] == "Open the Job Tracker shortcut to review."


def test_a_source_error_is_named_on_an_otherwise_successful_run():
    run = make_run(
        status="partial",
        inserted=4,
        sources=_sources({"source": "greenhouse", "inserted": 4}),
        problems=[Problem("down:remotive", "remotive is down (HTTP 503).").as_dict()],
    )

    text = format_run_message(run, now=NOW)

    assert "4 new jobs" in text
    assert "remotive is down (HTTP 503)." in text


def test_a_hard_failure_says_failed_and_classifies_it():
    run = make_run(
        status="failed",
        error="OperationalError: connection refused",
        problems=[Problem("database", "Database unreachable.").as_dict()],
    )

    text = format_run_message(run, now=NOW)

    assert "Pipeline FAILED: OperationalError: connection refused" in text
    assert "Database unreachable." in text


def test_a_clean_quiet_run_says_nothing():
    # An updated-only run is not news, and a bot that pings daily about nothing is
    # a bot whose pings stop being read.
    run = make_run(updated=9, sources=_sources({"source": "lever", "inserted": 0}))

    assert format_run_message(run, now=NOW) is None


def test_a_reclassify_only_run_says_nothing():
    # Every source throttled, so nothing new, but the classifier still walked the
    # whole corpus. The counts are a detail of news, not news themselves.
    run = make_run(embedded=0, classified=4254)

    assert format_run_message(run, now=NOW) is None


def test_a_degraded_but_successful_run_still_reports():
    run = make_run(
        inserted=5,
        problems=[Problem("no_openai_key", "No OpenAI key: 5 new jobs...").as_dict()],
    )

    assert "No OpenAI key" in format_run_message(run, now=NOW)


# --- dedup, recovery, heartbeat ------------------------------------------------


def test_a_standing_problem_set_says_nothing_of_its_own():
    # It used to still append a line, so "collapses instead of nagging" collapsed
    # five lines into one and then nagged that one every single day. A problem you
    # have already been told about is not news until it changes or clears.
    problems = [Problem("down:remotive", "remotive is down (HTTP 503).").as_dict()]
    previous = make_run(started_at=NOW - timedelta(days=3), status="partial", problems=problems)
    run = make_run(status="partial", problems=problems, checked=["remotive"])

    assert format_run_message(run, previous=previous, now=NOW) is None


def test_a_standing_problem_rides_along_on_a_message_that_was_going_out_anyway():
    # Silent on its own, but never silently dropped: anything else worth a message
    # carries a reminder, so a broken source cannot be forgotten.
    problems = [Problem("down:remotive", "remotive is down (HTTP 503).").as_dict()]
    previous = make_run(started_at=NOW - timedelta(days=3), status="partial", problems=problems)
    run = make_run(status="partial", inserted=4, problems=problems, checked=["remotive"])

    text = format_run_message(run, previous=previous, now=NOW)

    assert "4 new jobs" in text
    assert "Standing since 2 Nov" in text
    assert "remotive is down (HTTP 503)." in text


def test_a_standing_problem_rides_along_on_the_heartbeat():
    problems = [Problem("down:remotive", "remotive is down (HTTP 503).").as_dict()]
    previous = make_run(started_at=NOW - timedelta(days=3), status="partial", problems=problems)
    run = make_run(status="partial", problems=problems, checked=["remotive"])

    text = format_run_message(
        run,
        previous=previous,
        heartbeat_days=7,
        last_notified_at=NOW - timedelta(days=9),
        now=NOW,
    )

    assert "Still running." in text
    assert "Standing since 2 Nov" in text


def test_a_changed_problem_set_restates_in_full():
    previous = make_run(
        status="partial", problems=[Problem("down:remotive", "remotive is down.").as_dict()]
    )
    run = make_run(status="partial", problems=[Problem("down:lever", "lever is down.").as_dict()])

    text = format_run_message(run, previous=previous, now=NOW)

    assert "lever is down." in text
    assert "Standing" not in text


def test_a_standing_footnote_names_every_problem_not_just_the_first():
    # The old collapse branch printed problems[0] only. Two sources broken at once
    # is exactly when it mattered, and the second one was dropped on the floor every
    # day for as long as the pair stayed broken.
    problems = [
        Problem("down:remotive", "remotive is down.").as_dict(),
        Problem("down:lever", "lever is down.").as_dict(),
    ]
    previous = make_run(started_at=NOW - timedelta(days=3), status="partial", problems=problems)
    run = make_run(status="partial", inserted=4, problems=problems)

    text = format_run_message(run, previous=previous, now=NOW)

    assert "remotive is down." in text
    assert "lever is down." in text


def test_a_cleared_problem_is_worth_one_recovery_line():
    previous = make_run(
        status="partial", problems=[Problem("down:remotive", "remotive is down.").as_dict()]
    )
    run = make_run(status="ok", checked=["remotive"])

    text = format_run_message(run, previous=previous, now=NOW)

    assert text.endswith("Recovered: remotive")


def test_a_source_that_was_not_re_fetched_has_not_recovered():
    # A throttled source is not fetched at all, so its problem code is absent for a
    # reason that has nothing to do with the source being fixed. Announcing that as
    # a recovery is how the bot teaches you to stop believing it.
    previous = make_run(
        status="partial", problems=[Problem("down:remotive", "remotive is down.").as_dict()]
    )
    run = make_run(status="ok", checked=["greenhouse", "lever"])

    assert format_run_message(run, previous=previous, now=NOW) is None


def test_a_missing_openai_key_does_not_recover_on_a_quiet_night():
    # no_openai_key is only raised when a run inserts something, so a night that
    # ingested nothing used to clear it and report the key as fixed while it was
    # still missing. Only a run that actually called OpenAI can say that.
    previous = make_run(
        inserted=5,
        problems=[Problem("no_openai_key", "No OpenAI key: 5 new jobs...").as_dict()],
    )
    run = make_run(status="ok", checked=["greenhouse", "internet"])

    assert format_run_message(run, previous=previous, now=NOW) is None


def test_a_missing_openai_key_recovers_once_the_embedder_runs():
    previous = make_run(
        inserted=5,
        problems=[Problem("no_openai_key", "No OpenAI key: 5 new jobs...").as_dict()],
    )
    run = make_run(status="ok", checked=["greenhouse", "openai"])

    text = format_run_message(run, previous=previous, now=NOW)

    assert text.endswith("Recovered: no openai key")


def test_the_heartbeat_breaks_a_long_silence():
    run = make_run()

    text = format_run_message(
        run, heartbeat_days=7, last_notified_at=NOW - timedelta(days=9), now=NOW
    )

    assert "Still running. Nothing new in 9 days." in text


def test_the_heartbeat_is_not_due_before_its_time():
    run = make_run()

    assert (
        format_run_message(run, heartbeat_days=7, last_notified_at=NOW - timedelta(days=2), now=NOW)
        is None
    )


def test_heartbeat_days_zero_disables_it():
    run = make_run()

    assert format_run_message(run, heartbeat_days=0, last_notified_at=None, now=NOW) is None


# --- send_message + notify_run -------------------------------------------------


def test_send_message_is_inert_without_credentials(monkeypatch):
    def _no_calls(*args, **kwargs):
        raise AssertionError("no HTTP call should be attempted without credentials")

    monkeypatch.setattr(telegram.httpx, "post", _no_calls)

    assert telegram.send_message("hi", settings=UNCONFIGURED) is False


def test_send_message_never_raises_when_telegram_is_unreachable(monkeypatch):
    def _boom(*args, **kwargs):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(telegram.httpx, "post", _boom)
    configured = Settings(telegram_bot_token="t", telegram_chat_id="1")

    assert telegram.send_message("hi", settings=configured) is False


def test_send_message_posts_plain_text_with_no_parse_mode(monkeypatch):
    sent: dict = {}

    def _post(url, json, timeout):  # noqa: ANN001 - mirrors the httpx signature used
        sent["url"] = url
        sent["json"] = json
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(telegram.httpx, "post", _post)
    configured = Settings(telegram_bot_token="tok", telegram_chat_id="42")

    assert telegram.send_message("Backend_Engineer *at* Acme", settings=configured) is True
    assert sent["url"].endswith("/bottok/sendMessage")
    assert sent["json"]["chat_id"] == "42"
    # No parse_mode: an underscore or asterisk in a job title would break the send.
    assert "parse_mode" not in sent["json"]


def test_notify_run_stamps_notified_at_only_when_it_sends(monkeypatch, session_factory):
    monkeypatch.setattr(telegram, "send_message", lambda text, settings=None: True)
    with session_factory() as s:
        s.add(make_run(inserted=3))
        s.commit()
        run_id = s.query(PipelineRun).one().id

    assert telegram.notify_run(session_factory, run_id, settings=UNCONFIGURED) is True

    with session_factory() as s:
        assert s.get(PipelineRun, run_id).notified_at is not None


def test_notify_run_does_not_stamp_a_silent_run(monkeypatch, session_factory):
    monkeypatch.setattr(
        telegram,
        "send_message",
        lambda text, settings=None: pytest.fail("a quiet run must not send"),
    )
    with session_factory() as s:
        s.add(make_run(updated=2, notified_at=NOW))
        s.commit()
        run_id = s.query(PipelineRun).one().id

    assert telegram.notify_run(session_factory, run_id, settings=UNCONFIGURED) is False


# --- wiring: isolation and interrupted-run recovery ----------------------------


def test_a_broken_notifier_does_not_break_the_pipeline(monkeypatch, session_factory):
    # The jobs are already committed and the row is already closed by the time the
    # notifier runs; a Telegram outage must cost exactly nothing.
    from tests.test_pipeline_run import _stub_pipeline

    monkeypatch.setattr(
        scheduler, "get_settings", lambda: Settings(openai_api_key=None, anthropic_api_key=None)
    )
    _stub_pipeline(monkeypatch, [])

    def _boom(*args, **kwargs):
        raise RuntimeError("telegram exploded")

    monkeypatch.setattr(telegram, "notify_run", _boom)

    summary = scheduler.run_daily_pipeline(session_factory)

    assert summary["ingest"]["inserted"] == 3
    with session_factory() as s:
        assert s.query(PipelineRun).one().status == "ok"


def test_a_leftover_running_row_is_closed_as_failed_at_startup(session_factory):
    with session_factory() as s:
        s.add(make_run(status="running", finished_at=None))
        s.commit()

    assert scheduler.recover_interrupted_run(session_factory) is True

    with session_factory() as s:
        row = s.query(PipelineRun).one()
    assert row.status == "failed"
    assert row.finished_at is not None
    assert "interrupted" in row.error


def test_nothing_to_recover_is_not_a_false_alarm(session_factory):
    with session_factory() as s:
        s.add(make_run(status="ok"))
        s.commit()

    assert scheduler.recover_interrupted_run(session_factory) is False
