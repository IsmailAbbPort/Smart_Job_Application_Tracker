"""Adapter mapping tests: real-shaped fixtures -> CanonicalJob, no network."""

from __future__ import annotations

import httpx
import pytest

from app.ingest.sources import arbeitnow, ashby, greenhouse, lever, remotive
from app.models import TargetCompany
from tests.conftest import load_fixture


def test_greenhouse_parse():
    jobs = greenhouse.parse(load_fixture("greenhouse.json"), slug="gitlab", company="GitLab")
    assert len(jobs) == 2
    remote_job = jobs[0]
    assert remote_job.source == "greenhouse"
    assert remote_job.source_id == "gitlab:123"  # slug-prefixed to avoid collisions
    assert remote_job.title == "Senior Backend Engineer"
    assert remote_job.company == "GitLab"
    assert remote_job.is_remote is True  # "Remote, Germany"
    assert remote_job.description == "Build & ship software."  # unescaped + tags stripped
    assert remote_job.url.endswith("/jobs/123")
    assert remote_job.posted_at is not None and remote_job.posted_at.year == 2026
    # Onsite Berlin role is not remote.
    assert jobs[1].is_remote is False


def test_greenhouse_prefers_curated_company_over_board_name():
    # Remote.com's board reports company_name "Remote"; our curated name must win
    # so it doesn't collide with the work-arrangement.
    payload = {
        "jobs": [
            {
                "id": 9,
                "title": "Accountant",
                "company_name": "Remote",
                "absolute_url": "u",
                "location": {"name": "Remote"},
            }
        ]
    }
    jobs = greenhouse.parse(payload, slug="remotecom", company="Remote.com")
    assert jobs[0].company == "Remote.com"


def test_lever_parse_remote_flag_and_epoch():
    jobs = lever.parse(load_fixture("lever.json"), slug="mistral", company="Mistral AI")
    assert len(jobs) == 2
    ds = jobs[0]
    assert ds.source_id == "mistral:abc-1"
    assert ds.is_remote is True  # workplaceType == remote
    assert ds.location == "Paris"
    assert ds.description == "Do machine learning at scale."  # descriptionPlain passthrough
    assert ds.posted_at is not None and ds.posted_at.tzinfo is not None
    assert jobs[1].is_remote is False  # on-site


def test_ashby_parse_skips_unlisted():
    jobs = ashby.parse(load_fixture("ashby.json"), slug="synthesia", company="Synthesia")
    assert len(jobs) == 1  # the unlisted draft is dropped
    job = jobs[0]
    assert job.source_id == "synthesia:uuid-1"
    assert job.is_remote is True  # direct isRemote bool
    assert job.title == "ML Engineer"
    assert job.posted_at is not None and job.posted_at.year == 2026


def test_arbeitnow_parse():
    jobs = arbeitnow.parse(load_fixture("arbeitnow.json"))
    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "arbeitnow"
    assert job.source_id == "ux-designer-berlin-99001"
    assert job.is_remote is True
    assert job.description == "Join our remote design team & build things."
    assert job.posted_at is not None and job.posted_at.year == 2025


def test_remotive_parse_always_remote():
    jobs = remotive.parse(load_fixture("remotive.json"))
    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "remotive"
    assert job.source_id == "1749306"
    assert job.is_remote is True
    assert job.company == "Coalition Technologies"  # trimmed
    assert job.description == "Write high-quality content & SEO copy."
    assert job.posted_at is not None and job.posted_at.month == 7


# --- fetch: what each adapter reports about bad statuses -----------------------
#
# The parse tests above never call fetch, so the status reporting the notifier
# depends on had no coverage at all in the real adapters: the runner's tests used a
# double that behaved the way the adapters were supposed to. These drive the actual
# fetch methods over a mock transport.


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def _targets(session, ats: str, *slugs: str) -> None:
    for slug in slugs:
        session.add(TargetCompany(company=slug.title(), ats=ats, slug=slug, active=True))
    session.commit()


@pytest.mark.parametrize(
    ("module", "source_class", "ats"),
    [
        (greenhouse, greenhouse.GreenhouseSource, "greenhouse"),
        (lever, lever.LeverSource, "lever"),
        (ashby, ashby.AshbySource, "ashby"),
    ],
)
def test_a_board_level_adapter_separates_answered_boards_from_failed_ones(
    module, source_class, ats, session, monkeypatch
):
    monkeypatch.setattr(module, "_POLITE_DELAY", 0)
    _targets(session, ats, "acme", "closed")

    def handler(request: httpx.Request) -> httpx.Response:
        if "closed" in str(request.url):
            return httpx.Response(404)
        return httpx.Response(200, json=load_fixture(f"{ats}.json"))

    source = source_class()
    jobs = source.fetch(_client(handler), session)

    # The board that answered is recorded even though the other one 404'd, which is
    # what stops the runner calling the whole source down.
    assert source.fetched_slugs == {"acme"}
    assert source.http_errors == {"closed": 404}
    assert jobs


@pytest.mark.parametrize(
    ("module", "source_class", "ats"),
    [
        (greenhouse, greenhouse.GreenhouseSource, "greenhouse"),
        (lever, lever.LeverSource, "lever"),
        (ashby, ashby.AshbySource, "ashby"),
    ],
)
def test_a_board_level_adapter_reports_every_failed_board(
    module, source_class, ats, session, monkeypatch
):
    monkeypatch.setattr(module, "_POLITE_DELAY", 0)
    _targets(session, ats, "acme", "globex")

    source = source_class()
    jobs = source.fetch(_client(lambda request: httpx.Response(503)), session)

    assert jobs == []
    assert source.fetched_slugs == set()
    assert source.http_errors == {"acme": 503, "globex": 503}


def test_remotive_reports_its_one_endpoint_being_down(session):
    source = remotive.RemotiveSource()

    jobs = source.fetch(_client(lambda request: httpx.Response(503)), session)

    assert jobs == []
    assert source.http_errors == {"remotive": 503}


def test_remotive_clears_a_previous_failure_on_a_good_fetch(session):
    # The attribute lives on the source instance, which the runner reuses across
    # runs, so a stale error would make a recovered source look permanently down.
    source = remotive.RemotiveSource()
    source.fetch(_client(lambda request: httpx.Response(503)), session)

    jobs = source.fetch(
        _client(lambda request: httpx.Response(200, json=load_fixture("remotive.json"))), session
    )

    assert jobs
    assert source.http_errors == {}


def test_arbeitnow_keeps_the_pages_it_already_had(session):
    # A bad status on page two is not the source being unreachable: the jobs from
    # page one are real, and the runner sees fetched > 0 and does not call it down.
    payload = load_fixture("arbeitnow.json")
    first = {**payload, "links": {"next": "https://arbeitnow.test/api/page2"}}

    def handler(request: httpx.Request) -> httpx.Response:
        if "page2" in str(request.url):
            return httpx.Response(500)
        return httpx.Response(200, json=first)

    source = arbeitnow.ArbeitnowSource()
    jobs = source.fetch(_client(handler), session)

    assert len(jobs) == 1
    assert source.http_errors == {"arbeitnow": 500}


def test_arbeitnow_reports_a_dead_first_page(session):
    source = arbeitnow.ArbeitnowSource()

    jobs = source.fetch(_client(lambda request: httpx.Response(503)), session)

    assert jobs == []
    assert source.http_errors == {"arbeitnow": 503}
