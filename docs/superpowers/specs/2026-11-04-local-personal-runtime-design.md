# Local personal runtime: desktop launcher, catch-up ingest, Telegram pings

Date: 2026-11-04
Branch: `personal/local` (forked from `main` at `6c7dce4`)
Status: implemented 2026-11-05. The corrections from the audit of this document are
folded in below, so what follows describes the code as built.

## Why

The tracker is finished enough to use. It is not going to be hosted for the
foreseeable future, so the hosted-deploy work (Hetzner, Caddy, HTTPS, Phase 7a
auth) stays parked. What is needed instead is a personal appliance on one
Windows laptop:

1. A desktop shortcut that opens the UI like an app.
2. Ingestion that runs whether or not the UI has ever been opened, and that
   survives sleep and reboots. Today `app/scheduler.py` fires a cron job at
   `INGEST_HOUR_UTC` with `misfire_grace_time=3600`, so a laptop asleep through
   that hour silently skips the day. This is a known live problem, not a
   hypothetical.
3. A Telegram message when a run finds new jobs, or when something breaks, so
   the background pipeline is observable without reading container logs.

## Fork strategy

`main` is the website/portfolio line and must not change. All work here lands on
the long-lived `personal/local` branch in the same repo (`IsmailAbbPort`).

- Sync is one-way: `git merge main` into `personal/local` whenever the website
  version improves. Never merge or cherry-pick `personal/local` into `main`.
- Known recurring friction: the Alembic migration added here takes revision
  `0025_pipeline_run` and chains after `0024_work_rights`, which is `main`'s head
  at the fork (not `0020_saved_views`, as an earlier draft of this document said).
  If `main` later adds its own `0025`, the merge produces two heads. The fix is to
  edit `down_revision` on the personal migration so it chains after main's, then
  `alembic upgrade head`. Expect this at most once per sync.
- Second known friction: this branch also changes `app/ingest/` (the adapters now
  report HTTP status into `IngestStats`, see Component 2), so a `main` that touches
  the same adapters will conflict there. Accepted deliberately: without it a dead
  source is indistinguishable from an empty one and the notifier has nothing to
  report.
- The branch is not pushed as part of this work. Pushing anything requires
  showing `gh auth status` and getting explicit approval first.

## Scope

In scope: pipeline run history, startup catch-up, a Telegram notifier, Windows
launcher and autostart scripts, compose changes for an always-on local stack,
and tests for all of the above.

Out of scope: any hosted deploy, HTTPS, auth changes, CV/fit comparison inside
the notification, and changes to `ENVIRONMENT` (it stays `development`, so the
existing permissive local defaults keep working).

---

## Component 1: pipeline run history

### Schema

New table `pipeline_run`, migration `migrations/versions/0025_pipeline_run.py`
(chains after `0024_work_rights`, the head at the fork). Hand-authored, matching
the style of the existing migrations. One index, `(status, started_at)`, which is
what the catch-up query and `GET /ops/runs` both read.

| column          | type                       | notes                                        |
|-----------------|----------------------------|----------------------------------------------|
| `id`            | Integer PK autoincrement   |                                              |
| `started_at`    | DateTime(timezone=True)    | not null, server default `now()`             |
| `finished_at`   | DateTime(timezone=True)    | nullable until the run ends                  |
| `trigger`       | String(16)                 | `schedule` or `catchup`                      |
| `status`        | String(16)                 | `running`, `ok`, `partial`, `failed`         |
| `inserted`      | Integer, default 0         | new jobs, the number the Telegram ping leads with |
| `updated`       | Integer, default 0         |                                              |
| `removed_stale` | Integer, default 0         |                                              |
| `embedded`      | Integer, default 0         |                                              |
| `classified`    | Integer, default 0         |                                              |
| `sources`       | JSON, default dict         | per-source `{inserted, status, error}`       |
| `problems`      | JSON, default list         | classified problem codes, for dedup and recovery lines |
| `error`         | Text, nullable             | set when the pipeline itself raised          |
| `notified_at`   | DateTime(timezone=True)    | nullable; when a message was actually sent, drives the heartbeat |

Status semantics, made explicit so the notifier has no ambiguity to resolve:

- `running` while in flight.
- `partial` if the pipeline completed but at least one source reported an error.
- `failed` if the pipeline raised before completing.
- `ok` otherwise.

Portable column types only (`JSON`, not `JSONB`), because the test suite runs on
SQLite in-memory, matching the convention in `app/models.py`.

The table earns its place three ways: it is the input to the catch-up decision,
it is the body of the Telegram message, and it answers "when did this last run"
without reading logs.

### Catch-up on startup

`app/scheduler.py` changes:

- A pure, directly testable decision function:
  `should_catch_up(last_success_at: datetime | None, now: datetime, threshold_hours: int) -> bool`.
  Returns `True` when `last_success_at` is `None` or older than the threshold.
  No clock patching, no scheduler, no database.
- `start_scheduler()` keeps the existing `CronTrigger` job, and additionally
  queries the most recent `pipeline_run` whose `status` is `ok` or `partial`.
  If `should_catch_up(...)` is `True`, it registers a one-shot `DateTrigger` job
  roughly 60 seconds out (`id="catchup_ingest"`), so the API is serving before a
  long pipeline starts.
- New setting `ingest_catchup_after_hours: int = 20`, env
  `INGEST_CATCHUP_AFTER_HOURS`. 20 rather than 24 so a laptop opened at a
  slightly earlier hour each day still gets a daily run.
- `max_instances=1` protected the single cron job from itself. With two jobs it
  no longer protects anything, so `run_daily_pipeline` gets a module-level
  `threading.Lock`: acquire non-blocking, and if it is already held, log and
  return `{"skipped": "already running"}`. Keep `max_instances=1` and
  `coalesce=True` on the cron job as well.
- `run_daily_pipeline` writes a `pipeline_run` row with `status="running"` at
  the start, then fills in the totals and final status at the end, inside
  `try/except/finally` so a raising pipeline still closes its row with
  `status="failed"` and the exception text in `error`. It accepts a
  `trigger: str = "schedule"` argument so the catch-up job can record itself.

The existing behavior of skipping embed and classify when `OPENAI_API_KEY` is
absent is preserved; those runs record `embedded=0, classified=0` and still
count as `ok`.

---

## Component 2: Telegram notifier

New package `app/notify/` with `__init__.py` and `telegram.py`.

### Config

Added to `app/config.py` and documented in `.env.example`:

- `telegram_bot_token: str | None = None`
- `telegram_chat_id: str | None = None`
- `notify_heartbeat_days: int = 7` (0 disables; see the blind-spot note)

Both default to `None`, so tests, CI, and anyone cloning the repo see no
behavior change. Notifications are active exactly when both are set.
`docker-compose.yml` passes both through from the root `.env` with the same
`${VAR:-}` pattern already used for `OPENAI_API_KEY`.

### Two pieces, deliberately split

`format_run_message(run, *, previous, heartbeat_days, last_notified_at, now)`
is pure, with no network and no settings access. It returns `None` when there is
nothing worth saying, and a plain-text string otherwise. The three keyword
arguments beyond `previous` are what keep the clock and the config out of it, so
dedup, recovery and the heartbeat are all plain unit tests. Timestamps render in
Africa/Cairo (hardcoded, and `zoneinfo` resolves it inside `python:3.12-slim`
with no extra dependency), since a UTC time on a phone is a daily puzzle.

Send when any of these hold:

- `inserted > 0`
- `status` is `partial` or `failed`
- the run produced any problem line (see Health and problem reporting below),
  including a degraded-but-successful run such as a missing OpenAI key
- a previous problem has cleared, so the recovery is worth one line
- the heartbeat is due

Stay silent when the run succeeded, inserted nothing, and hit no problems.
Updated-only runs are not news.

`send_message(text: str) -> bool` does one `httpx.post` to
`https://api.telegram.org/bot<token>/sendMessage` with a short timeout (10s) and
no `parse_mode`, so a job title containing an underscore, asterisk or bracket
cannot break the send. Returns whether it succeeded; never raises.

### Message shape

Plain text. A `http://localhost:8000` link is dead on a phone, so the message
does not pretend to be one: it says what happened and points at the shortcut.

```
Job Tracker - 4 Nov 2026, 17:02
12 new jobs (greenhouse 7, lever 3, ashby 2)
embedded 12, classified 12
remotive: FAILED (HTTP 503)
Open the Job Tracker shortcut to review.
```

A failed run instead reads:

```
Job Tracker - 4 Nov 2026, 17:02
Pipeline FAILED: <exception summary, truncated>
```

Per-source lines are only listed for sources that inserted something or errored,
so a quiet source does not pad the message.

### Health and problem reporting

The bot is the only channel through which the background pipeline can report
that something is wrong, so a bare "pipeline FAILED" with a stack-trace fragment
is not good enough. Raw exception text is unreadable on a phone and does not
tell you whether to top up a balance, reconnect wifi, or restart Docker.

A second pure function, `classify_problem(exc_or_source_error) -> Problem`,
maps a failure onto a small known set, each with a short plain line and a hint
at the actual remedy. It is pure string and exception-type inspection, so every
row below is a unit test.

| Condition detected | code | Message line |
|---|---|---|
| No route or DNS failure (`httpx.ConnectError`; `socket.gaierror` never surfaces, httpx wraps it) | `no_internet` | `No internet: could not reach the job sources. Will retry.` |
| Request timeouts (`httpx.TimeoutException` and its subclasses) | `timeout:<source>` | `Timed out reaching <source>. Possibly a slow or dropped connection.` |
| Source HTTP 5xx | `down:<source>` | `<source> is down (HTTP 503). Their problem, not ours.` |
| Source HTTP 429 | `ratelimit:<source>` | `<source> rate-limited us. Backing off until the next run.` |
| Source HTTP 401/403/404 | `refused:<source>` | `<source> refused us (HTTP 403). The endpoint or slug may have changed.` |
| Anthropic or OpenAI 401/403 | `key:<provider>` | `AI key rejected (<provider>). Check the key in .env.` |
| Anthropic `billing_error` (a 402 `APIStatusError`, since the SDK exports no `BillingError`), OpenAI `insufficient_quota` (a 429, checked before the plain rate limit) | `credits:<provider>` | `<provider> credits exhausted. Top up or the judge and letters stay off.` |
| Provider 429 after retries | `ratelimit:<provider>` | `<provider> rate-limited the run. Enrichment is incomplete; the next run backfills it.` |
| `OPENAI_API_KEY` missing while jobs need embedding | `no_openai_key` | `No OpenAI key: <n> new jobs ingested but not embedded or classified.` |
| Database unreachable (`sqlalchemy.exc.OperationalError`) | `database` | `Database unreachable. The Postgres container is probably down.` |
| Anything unmatched | `unexpected:<source>` | `Unexpected error: <exception class>: <first 200 chars>.` |

The line never interpolates `<host>`: the source name is what is known at that
point, and a resolved host is not. "No internet" is deliberately the one code with
no source in it, because wifi being off fails every source at once and the problem
list is deduplicated by code: one line, not five identical ones.

The audited draft also had a row for "our own monthly AI cap hit (`ai_usage`
ceiling)". It is dropped: that ceiling is enforced in `app/ratelimit.py` on the
user-facing judge and letter endpoints, so the ingest pipeline cannot reach it and
the line could never fire.

The classifier takes `str | Exception`, because a per-source failure has already
been flattened to a string (`f"{type(exc).__name__}: {exc}"`) in `IngestStats` by
the time the run row is written, while a whole-pipeline or AI failure is still live.

One prerequisite the audited draft missed: every adapter swallowed non-200 with
`continue`/`return []`, so a Remotive 503 produced `fetched=0, error=None, status=ok`
and the taxonomy above would never have seen it. The adapters now record
`http_errors` (endpoint/slug -> status) and the runner escalates to a source error
when a source brought back nothing *and* saw bad statuses; one retired ATS board
among sixty is recorded but is not a source failure.

`AnthropicRoleClassifier.classify_titles` likewise swallowed its per-batch
exceptions into a log line, so a rejected key read as "nothing to classify". It now
keeps them on `last_failures`, and the pipeline classifies those too.

Each line is appended to the run message, so one Telegram message carries both
the news and the problems rather than arriving as two pings. The classifier is
applied both to a whole-pipeline exception and to each per-source error already
captured in `IngestStats`, so a single bad source produces a named line while
the rest of the run still reports its new jobs.

Deduplication, so a persistently broken source cannot turn into a daily nag: a
problem line is only repeated if it differs from the previous run's problem set.
When the identical set recurs, the message collapses to
`Problems unchanged since <date>: <first line>` instead of restating every line,
and when a problem present in the previous run is gone, the message says
`Recovered: <source>`. The previous run's problem set is read from the previous
`pipeline_run` row, so this needs no extra storage.

### The blind spot, stated plainly

Nothing inside the container can report that the container is not running. If
Docker Desktop is closed, the engine drops, or the laptop is simply off, no
message arrives, and silence is indistinguishable from a clean quiet run. Two
cheap partial mitigations are in scope, and neither fully closes it:

- On startup, if the most recent `pipeline_run` row is still `status="running"`,
  the previous process was killed mid-run. Send
  `Previous run was interrupted (laptop sleep or container restart). Catching up now.`
  and mark that stale row `failed`.
- New setting `notify_heartbeat_days: int = 7` (0 disables). If no message has
  been sent for that many days, the next run sends a one-line
  `Still running. Nothing new in <n> days.` so prolonged silence can be
  distinguished from a dead stack.

A genuinely complete answer needs a watchdog outside this machine, which is out
of scope for a local-only tool and is noted here so the gap is a decision rather
than an oversight.

### Wiring and failure isolation

`run_daily_pipeline` calls the notifier in its `finally` block, after the
`pipeline_run` row is closed, inside its own `try/except`: a Telegram outage
logs a warning and never fails the pipeline, never rolls back the run row, and
never loses the ingested jobs.

New ops route so the token and chat id can be verified in one call instead of
waiting a day: `POST /ops/notify-test` in a new `app/routers/ops.py`, mounted in
`app/main.py`. It sends a fixed test message and returns
`{"configured": bool, "sent": bool}`. It returns 503 when the credentials are
absent, mirroring how `get_embedder` and `get_judge` behave without their keys.

Also exposed, since the table now exists and it is one query:
`GET /ops/runs?limit=10` returning recent `pipeline_run` rows. This is how you
check "did it run" from the UI side without Adminer.

---

## Component 3: Windows local runtime

### Compose changes

- `restart: unless-stopped` on `db` and `api`, so the stack comes back with
  Docker Desktop after a reboot or after the engine drops (which it does on this
  machine, unprompted).
- `adminer` moves behind a compose profile (`profiles: ["tools"]`) so it is not
  part of the always-on footprint and is started on demand with
  `docker compose --profile tools up -d adminer`. This also resolves a live
  conflict: the untracked `docker-compose.override.yml` existed only to move
  adminer off the tracked `8080` and onto `8081`; with the profile nothing claims
  a port until adminer is asked for, so the override file is deleted.
- `api` binds `127.0.0.1:8000:8000` rather than `8000:8000`. This laptop joins
  untrusted networks and the local API has no auth in front of it.
- `INGEST_HOUR_UTC` and the new `INGEST_CATCHUP_AFTER_HOURS` stay environment
  driven. The personal branch may hardcode a convenient local hour; `main`'s
  baked-in `14` is a known cleanup that belongs to the website line, not here.

### Scripts

New directory `scripts/local/` with five files: the three below, the `.vbs` shim
`install-autostart.ps1` needs, and `backup-db.cmd`.

`backup-db.cmd` was not in the audited draft and is a gap it should have named:
`pgdata` is a named volume inside Docker Desktop's WSL2 disk image, so nothing that
backs up this folder covers the corpus, and `docker compose down -v` or a Docker
Desktop factory reset discards it. The script gzips a `pg_dump` into `backups/`
(gitignored), keeps the newest 7, and refuses a suspiciously small dump rather than
rotating a good backup out in favour of a broken one. Its timestamp comes from the
db container, because the host's `%DATE%` is locale-specific and `wmic` is gone from
current Windows.

`start-tracker.cmd` is the launcher, and it is idempotent, so running it twice
costs nothing:

1. Probe the Docker engine (`docker info`). If it does not answer, start Docker
   Desktop and poll until the engine responds, with a hard timeout.
2. `docker compose up -d` (no `--build`; building is an install-time step, not
   a per-launch cost).
3. Poll `http://localhost:8000/health` with `curl.exe` (shipped with Windows 11)
   until it returns, up to about two minutes. The waits use `ping -n`, not
   `timeout`, because `timeout.exe` aborts when stdin is redirected, which is
   exactly what the hidden logon task does.
4. Unless `--no-browser` was passed, open the UI in an app-mode browser window
   (`--app=http://localhost:8000` on Chrome or Edge), falling back to the
   default browser if neither is found. App mode is what makes it read as an
   application rather than a tab.
5. On timeout, print the specific step that failed and keep the window open so
   the message is readable.

`install-shortcut.ps1` is a one-time setup step: creates a Desktop `.lnk` pointing
at the launcher, with an icon and a working directory set to the repo root. It is
`WindowStyle = 7` (minimized) rather than the hidden wrapper the audited draft
asked for: a cold Docker start takes a minute or two and step 5 above exists to
keep a failure readable, which a hidden window cannot do.

`install-autostart.ps1` is the other one-time step: registers a logon Scheduled
Task (`JobTrackerAutostart`, one minute after logon, `-Remove` to undo) that runs
`start-tracker.cmd --no-browser` with no window. That one genuinely has to be
invisible, and a Scheduled Task running `cmd.exe` flashes a console at every boot,
so it goes through `start-tracker-hidden.vbs` (`WScript.Shell.Run(..., 0, False)`)
as the fourth file. The launcher skips its `pause` in `--no-browser` mode, since a
hidden task waiting on a keypress would never exit. This is the piece that
makes ingestion genuinely independent of the shortcut. It is preferred over
Docker Desktop's "start at login" GUI toggle because it is scriptable and
because it starts Docker Desktop itself rather than assuming it is already up.

### Platform risk, to be verified before building on it

Windows Application Control on this machine already blocks the project's
`.venv` Python intermittently under both Bash and PowerShell (os error 4551).
A `.cmd` launcher is chosen over a `.ps1` launcher specifically to stay clear of
PowerShell constrained-language-mode surprises. This was verified first, before
the shortcut and autostart work was layered on top: `start-tracker.cmd
--no-browser` runs on this machine and brings the stack up. The two
installers remain PowerShell because they are run manually once and their
failure mode is visible and immediate.

Two consequences worth stating plainly rather than discovering later: keeping
Docker Desktop resident costs roughly 1-2 GB of RAM and some battery life, and a
host-native (no Docker) alternative is not available while the venv is blocked.

---

## Testing

The host Python interpreter is unreliable here, so the suite runs in the
throwaway `uv` container, as the rest of this project's work does:

```
docker run --rm -e UV_PROJECT_ENVIRONMENT=/opt/venv \
  -v "<repo>:/src" -w /src ghcr.io/astral-sh/uv:python3.12-bookworm-slim \
  sh -c "uv sync --frozen --group dev && uv run --no-sync pytest"
```

New tests, all offline and all on SQLite like the existing suite:

- `should_catch_up`: no previous run, a stale run, a fresh run, and a run
  exactly on the threshold boundary.
- `format_run_message`: news (inserted > 0), source error on an otherwise
  successful run, hard failure, and the silent case (returns `None`).
- `classify_problem`: one test per row of the taxonomy table, built from real
  exception instances and real provider error bodies rather than from strings
  invented to match the implementation. The unmatched fallback is covered too.
- Problem dedup: an identical problem set on consecutive runs collapses to the
  `(unchanged since ...)` line; a cleared problem produces a `Recovered:` line;
  a changed problem set restates in full.
- Heartbeat: due and not due, and `notify_heartbeat_days=0` disabling it.
- Interrupted-run recovery: a leftover `status="running"` row at startup is
  marked `failed` and produces the interrupted message.
- Notifier isolation: with `send_message` monkeypatched to raise,
  `run_daily_pipeline` still returns its summary and the `pipeline_run` row is
  still closed with the correct status.
- Run row lifecycle: a raising pipeline closes its row as `failed` with the
  error recorded, rather than leaving it `running` forever.
- Re-entrancy: a second `run_daily_pipeline` call while the lock is held
  returns the skip marker and does not write a second run row.
- `start_scheduler` registers `catchup_ingest` when the last run is stale and
  does not register it when the last run is fresh.
- `POST /ops/notify-test` returns 503 when unconfigured.

Manual verification, which cannot be unit tested and must actually be performed
rather than assumed:

1. [done] Launcher runs on this machine (the platform risk below, checked first).
   `start-tracker.cmd --no-browser` brought the stack up and reached `/health`.
   Still to do once: the cold-start path with the Docker engine stopped, ending in
   an app-mode window on the UI.
2. [done] Migration `0025` applies on real Postgres, and `GET /ops/runs` answers.
3. [done] The startup catch-up fires for real: an empty table on boot queued
   `catchup_ingest`, which closed as `partial` with 1787 inserted / 1545 updated /
   897 removed, and three classified problems, two `lever`/`ashby` timeouts and
   `key:anthropic`. That last one is the point of the whole feature: the
   `ANTHROPIC_API_KEY` in `.env` is being rejected, and before this change that
   fact only existed in a log line nobody reads.
4. [not done] `POST /ops/notify-test` delivering a real message to the real chat
   (needs a bot token and chat id; the route 503s correctly without them).
5. [not done] A forced pipeline run producing a real Telegram message.
6. [not done] A reboot, with the UI never opened, followed by `GET /ops/runs`
   showing a `catchup` run and a Telegram message having arrived.
7. [not done] At least one real problem path end to end: disconnect wifi, force a
   run, and confirm the message says there is no internet rather than printing a
   traceback fragment.

Existing gates stay green: `ruff check .`, `black --check .`, and the full suite.
The fork point measures 457 tests, not the 328 this document first claimed (that
number came from project memory and was stale). After this work: 515 passed, 1
skipped, ruff and black clean, `alembic heads` a single `0025_pipeline_run`.

## Commit plan

Small, build-safe commits on `personal/local`, authored as
`Ismail Abbas <317401387+IsmailAbbPort@users.noreply.github.com>`, with no
AI-attribution trailer, and no push without explicit approval:

1. `feat(ops): record pipeline runs and catch up after downtime` (model,
   migration, scheduler, tests)
2. `feat(notify): telegram ping for new jobs and failures` (notifier, config,
   ops routes, tests)
3. `feat(local): windows launcher, desktop shortcut and logon autostart`
   (compose, scripts, README section)
