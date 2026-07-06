"""Adapter mapping tests: real-shaped fixtures -> CanonicalJob, no network."""

from __future__ import annotations

from app.ingest.sources import arbeitnow, ashby, greenhouse, lever, remotive
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
