"""Failure taxonomy: a failure becomes a code (for dedup) and one readable line.

The bot is the only channel through which the background pipeline can report that
something is wrong, and raw exception text on a phone does not tell you whether to
top up a balance, reconnect wifi or restart Docker. Each line therefore names the
remedy, not the traceback.

Pure string and attribute inspection, so every branch is a unit test. It takes
either a live exception or the error string already captured in `IngestStats`
(which is `f"{type(exc).__name__}: {exc}"`), because a per-source failure has been
flattened to a string by the time the run row is written.

The provider SDKs are deliberately not imported here: 402 from Anthropic arrives as
a plain `APIStatusError` and OpenAI's `insufficient_quota` arrives as a 429 that is
otherwise indistinguishable from a real rate limit, so both are recognised by
status + error code rather than by exception class.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# "No internet" is deliberately not scoped to a source: wifi being off fails every
# source at once, and five identical lines is five times the noise and no more news.
NO_INTERNET = "no_internet"
DATABASE = "database"
MISSING_OPENAI_KEY = "no_openai_key"

_STATUS_RE = re.compile(r"\b([45]\d\d)\b")
_TIMEOUT_NAMES = frozenset(
    {
        "TimeoutException",
        "ConnectTimeout",
        "ReadTimeout",
        "WriteTimeout",
        "PoolTimeout",
        "APITimeoutError",
    }
)
_CREDIT_MARKERS = ("insufficient_quota", "billing_error", "credit balance is too low")


@dataclass(frozen=True)
class Problem:
    """One named failure: `code` is compared across runs, `line` is what is sent."""

    code: str
    line: str

    def as_dict(self) -> dict:
        return {"code": self.code, "line": self.line}


def _kind(err: str | Exception) -> str:
    """The exception class name, live or as captured in the leading string token."""
    if isinstance(err, Exception):
        return type(err).__name__
    head, sep, _ = err.partition(":")
    return head.strip() if sep else ""


def _text(err: str | Exception) -> str:
    return err if isinstance(err, str) else f"{type(err).__name__}: {err}"


def _provider(err: str | Exception) -> str | None:
    if isinstance(err, str):
        return None
    root = type(err).__module__.split(".")[0]
    return {"anthropic": "Anthropic", "openai": "OpenAI"}.get(root)


def _status(err: str | Exception) -> int | None:
    if isinstance(err, Exception):
        status = getattr(err, "status_code", None)
        if status is None:
            status = getattr(getattr(err, "response", None), "status_code", None)
        if isinstance(status, int):
            return status
    match = _STATUS_RE.search(_text(err))
    return int(match.group(1)) if match else None


def _markers(err: str | Exception) -> str:
    """Lowercased error text plus whatever machine-readable code the SDK carries."""
    parts = [_text(err)]
    if isinstance(err, Exception):
        for attr in ("code", "type"):
            value = getattr(err, attr, None)
            if isinstance(value, str):
                parts.append(value)
        body = getattr(err, "body", None)
        if isinstance(body, dict):
            inner = body.get("error")
            parts.append(str(inner if inner is not None else body))
    return " ".join(parts).lower()


def classify_problem(err: str | Exception, *, source: str | None = None) -> Problem:
    """Map one failure onto a named problem with a plain-language line."""
    where = source or "a source"
    kind = _kind(err)
    status = _status(err)
    provider = _provider(err)
    markers = _markers(err)

    # Credits first, and outside the provider branch: `provider` comes from the
    # exception's module, so a failure already flattened to a string can never enter
    # that branch, and an exhausted balance was being reported as a plain rate limit
    # (its HTTP status is 429) with a promise to backfill that no later run can keep.
    # The markers are provider-specific strings, so a job board's 429 cannot match.
    if any(marker in markers for marker in _CREDIT_MARKERS):
        slug = provider.lower() if provider else "ai"
        who = provider or "AI provider"
        return Problem(
            f"credits:{slug}",
            f"{who} credits exhausted. Top up or the judge and letters stay off.",
        )

    if provider is not None:
        slug = provider.lower()
        if status in (401, 403):
            return Problem(f"key:{slug}", f"AI key rejected ({provider}). Check the key in .env.")
        if status == 429:
            return Problem(
                f"ratelimit:{slug}",
                f"{provider} rate-limited the run. Enrichment is incomplete; "
                "the next run backfills it.",
            )
        if kind in _TIMEOUT_NAMES:
            return Problem(
                f"timeout:{slug}",
                f"Timed out reaching {provider}. Enrichment is incomplete; "
                "the next run backfills it.",
            )
        if kind == "APIConnectionError":
            return Problem(NO_INTERNET, "No internet: could not reach the APIs. Will retry.")

    if kind in _TIMEOUT_NAMES:
        return Problem(
            f"timeout:{where}",
            f"Timed out reaching {where}. Possibly a slow or dropped connection.",
        )
    if kind == "ConnectError":
        return Problem(NO_INTERNET, "No internet: could not reach the job sources. Will retry.")
    if kind == "OperationalError":
        return Problem(DATABASE, "Database unreachable. The Postgres container is probably down.")

    if status is not None:
        if status >= 500:
            return Problem(
                f"down:{where}", f"{where} is down (HTTP {status}). Their problem, not ours."
            )
        if status == 429:
            return Problem(
                f"ratelimit:{where}", f"{where} rate-limited us. Backing off until the next run."
            )
        if status in (401, 403, 404):
            return Problem(
                f"refused:{where}",
                f"{where} refused us (HTTP {status}). The endpoint or slug may have changed.",
            )

    return Problem(f"unexpected:{where}", f"Unexpected error: {_text(err)[:200]}.")


def collect_problems(
    *,
    status: str,
    error: str | None,
    sources: list[dict] | None,
    inserted: int,
    ai_failures: list[Exception] | None = None,
    embedding_skipped: bool = False,
) -> list[Problem]:
    """Every problem a finished run should report, deduplicated by code, in order.

    Dedup by code is what collapses "no internet" from five dead sources into the
    one line that is actually the news.
    """
    problems: list[Problem] = []
    seen: set[str] = set()

    def add(problem: Problem) -> None:
        if problem.code not in seen:
            seen.add(problem.code)
            problems.append(problem)

    if status == "failed" and error:
        add(classify_problem(error))
    for src in sources or []:
        if src.get("error"):
            add(classify_problem(src["error"], source=src.get("source") or "a source"))
    for exc in ai_failures or []:
        add(classify_problem(exc))
    if embedding_skipped and inserted > 0:
        add(
            Problem(
                MISSING_OPENAI_KEY,
                f"No OpenAI key: {inserted} new jobs ingested but not embedded or classified.",
            )
        )
    return problems


def recovered_label(code: str) -> str:
    """The human name of a problem that has cleared ('down:remotive' -> 'remotive')."""
    _, sep, scope = code.partition(":")
    if sep and scope not in ("", "a source"):
        return scope
    return code.replace("_", " ").replace(":", " ").strip()


# What a run has to have exercised before a vanished problem counts as fixed.
# "run" means the pipeline simply got to the end, which is the only evidence there
# is for a problem that was never scoped to anything smaller.
RUN_SCOPE = "run"
AI_SCOPE = "ai"
INTERNET_SCOPE = "internet"
_CODE_SCOPES = {
    NO_INTERNET: INTERNET_SCOPE,
    DATABASE: "database",
    # Deliberately the provider and not "the key was missing": the key being absent
    # is why the embedder never ran, so only a run that actually called OpenAI has
    # the standing to say this is fixed.
    MISSING_OPENAI_KEY: "openai",
}


def recovery_scope(code: str) -> str:
    """The scope a run must have re-checked before `code` can be called recovered.

    'down:remotive' -> 'remotive', 'credits:openai' -> 'openai', 'credits:ai' ->
    'ai', 'no_internet' -> 'internet', anything unscoped -> 'run'.
    """
    if code in _CODE_SCOPES:
        return _CODE_SCOPES[code]
    _, sep, scope = code.partition(":")
    if not sep or scope in ("", "a source"):
        return RUN_SCOPE
    return scope
