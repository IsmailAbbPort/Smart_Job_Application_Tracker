"""The cheap shortlist eligibility gate: language and work-country, no model call."""

from __future__ import annotations

from app.ai.decide import CandidateRules
from app.models import Job
from app.shortlist import eligibility_block


def _job(**kw) -> Job:
    base = dict(
        source="test",
        source_id="1",
        title="Backend Engineer",
        company="Acme",
        url="https://example.com/1",
        location="Remote",
        is_remote=True,
        description="",
        language="en",
        required_languages=[],
        work_countries=[],
    )
    base.update(kw)
    return Job(**base)


EU = CandidateRules(known_languages=["en"], work_rights=["EU", "UA"])


def test_nothing_is_blocked_when_the_user_sets_no_preferences():
    off = CandidateRules()
    assert eligibility_block(_job(location="Remote, United States"), off) is None
    assert eligibility_block(_job(language="de", required_languages=["de"]), off) is None


def test_a_posting_in_a_language_the_user_does_not_read_is_blocked():
    assert eligibility_block(_job(language="de"), EU) == "written in de"
    assert eligibility_block(_job(required_languages=["de"]), EU) == "requires de"
    # Undetected language is unknown, not a block.
    assert eligibility_block(_job(language=None), EU) is None


def test_a_stated_restriction_outside_the_users_rights_is_blocked():
    assert eligibility_block(_job(work_countries=["US"]), EU) == "hires only in US"
    # An overlap anywhere is enough, so a multi-country posting stays.
    assert eligibility_block(_job(work_countries=["US", "PL"]), EU) is None
    assert eligibility_block(_job(work_countries=["EU"]), EU) is None


def test_a_remote_job_listed_outside_europe_is_blocked_from_its_location_alone():
    for location in ("Remote, United States", "Remote, Bangalore", "Yerevan", "Montreal"):
        assert eligibility_block(_job(location=location), EU) is not None, location


def test_a_remote_job_listed_in_europe_is_kept_even_outside_the_users_rights():
    # European boards routinely list one office country for a role open EU-wide, so the
    # location alone must not hide it. The judge reads the full text and can still reject.
    for location in ("Remote, United Kingdom", "London", "Zurich"):
        assert eligibility_block(_job(location=location), EU) is None, location


def test_a_stated_restriction_wins_over_the_location():
    # "open to experts located anywhere in the United Kingdom" on a London listing: the
    # location would have been kept, the stated scope is what excludes it.
    job = _job(location="London", work_countries=["GB"])
    assert eligibility_block(job, EU) == "hires only in GB"


def test_an_onsite_job_outside_the_users_rights_is_blocked():
    assert eligibility_block(_job(location="New York", is_remote=False), EU) is not None
    # ... but an unknown location is still kept.
    assert eligibility_block(_job(location="Remote", is_remote=False), EU) is None


def test_search_preferences_works_as_the_rules_object_too():
    # eligibility_block is called with a SearchPreferences row in the shortlist and with
    # CandidateRules in the evals, so both shapes have to work.
    class Prefs:
        known_languages = ["en"]
        work_rights = ["EU"]

    assert eligibility_block(_job(language="fr"), Prefs()) == "written in fr"


def test_the_block_reason_shows_the_postings_own_codes():
    # "EU" must read as "EU", not as a list of all 30 member states.
    class Rules:
        known_languages = []
        work_rights = ["US"]

    assert eligibility_block(_job(work_countries=["EU"]), Rules()) == "hires only in EU"
