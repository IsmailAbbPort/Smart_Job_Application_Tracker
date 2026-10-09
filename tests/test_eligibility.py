"""Eligibility: sponsorship / remote-region / timezone detection + filters."""

from __future__ import annotations

from app.ingest.eligibility import (
    detect_remote_region,
    detect_visa_sponsorship,
    extract_required_utc_offsets,
    extract_work_countries,
    timezone_overlap_hours,
)
from app.models import Cv, Job


def _job(sid, *, embedding=None, visa=None, region=None, offsets=None, is_remote=True) -> Job:
    return Job(
        source="test",
        source_id=sid,
        title="Engineer",
        company="Acme",
        url=f"https://example.com/{sid}",
        is_remote=is_remote,
        is_european=True,
        embedding=embedding,
        visa_sponsorship=visa,
        remote_region=region,
        required_utc_offsets=offsets or [],
    )


# --- unit ---


def test_detect_visa_sponsorship():
    assert detect_visa_sponsorship("Visa sponsorship is available.") is True
    assert detect_visa_sponsorship("We are unable to sponsor visas.") is False
    assert detect_visa_sponsorship("You must already be authorized to work here.") is False
    assert detect_visa_sponsorship("Nothing about visas here.") is None
    # A refusal is the operative constraint even when an offer is also mentioned.
    assert (
        detect_visa_sponsorship("We can sponsor visas, but no sponsorship for this role.") is False
    )


def test_detect_remote_region():
    assert detect_remote_region("Remote, US-based only.", is_remote=True) == "us"
    assert detect_remote_region("Remote within Europe.", is_remote=True) == "eu"
    assert detect_remote_region("We sell into the united states.", is_remote=True) is None
    assert detect_remote_region("US-based remote.", is_remote=False) is None  # on-site ignored


def test_timezone_extraction_and_overlap():
    assert extract_required_utc_offsets("Must work CET hours.") == [1]
    assert extract_required_utc_offsets("Overlap with PST.") == [-8]
    assert extract_required_utc_offsets("Distributed, async.") == []
    assert extract_required_utc_offsets("Pacific time zone required.") == [-8]  # phrase
    # Cairo (+2): great overlap with CET (+1), none with Pacific (-8).
    assert timezone_overlap_hours([1], 2) == 7
    assert timezone_overlap_hours([-8], 2) == 0
    assert timezone_overlap_hours([], 2) is None  # unknown requirement -> neutral


def test_timezone_ignores_lowercase_foreign_words():
    # Abbreviations must be UPPERCASE: German "ist" / French "est"/"cet" are not tz.
    assert extract_required_utc_offsets("Das Team ist komplett remote.") == []
    assert extract_required_utc_offsets("Le poste est ouvert dans cet environnement.") == []


# --- filters ---


def test_require_sponsorship_filter(client, session_factory):
    with session_factory() as s:
        s.add_all([_job("yes", visa=True), _job("no", visa=False), _job("unknown", visa=None)])
        s.commit()
    client.put("/preferences", json={"require_sponsorship": True})
    ids = {i["source_id"] for i in client.get("/jobs").json()["items"]}
    assert ids == {"yes", "unknown"}  # explicit refusal dropped; unknown kept


def test_exclude_remote_regions_filter(client, session_factory):
    with session_factory() as s:
        s.add_all([_job("us", region="us"), _job("eu", region="eu"), _job("open", region=None)])
        s.commit()
    client.put("/preferences", json={"exclude_remote_regions": ["US"]})  # case-insensitive
    ids = {i["source_id"] for i in client.get("/jobs").json()["items"]}
    assert ids == {"eu", "open"}


def test_shortlist_timezone_overlap_gate(client, session_factory):
    with session_factory() as s:
        s.add(Cv(label="cv", content="x", embedding=[1.0, 0.0, 0.0]))
        s.add_all(
            [
                _job("cet", embedding=[1.0, 0.0, 0.0], offsets=[1]),  # +2 vs +1 -> 7h
                _job("pst", embedding=[1.0, 0.0, 0.0], offsets=[-8]),  # +2 vs -8 -> 0h
                _job("async", embedding=[1.0, 0.0, 0.0], offsets=[]),  # unknown -> kept
            ]
        )
        s.commit()
    client.put("/preferences", json={"user_utc_offset": 2, "min_timezone_overlap_hours": 4})
    items = client.get("/match/shortlist").json()["items"]
    ids = {i["source_id"] for i in items}
    assert ids == {"cet", "async"}  # PST dropped (0h < 4h); unknown kept
    cet = next(i for i in items if i["source_id"] == "cet")
    assert cet["timezone_overlap_hours"] == 7


def test_backfill_sets_eligibility(client, session_factory):
    with session_factory() as s:
        s.add(
            Job(
                source="test",
                source_id="j",
                title="Backend Engineer",
                company="Acme",
                url="https://example.com/j",
                is_remote=True,
                is_european=True,
                description=(
                    "Remote role, US-based only. We are unable to sponsor visas. "
                    "You must overlap with PST working hours. " * 3
                ),
            )
        )
        s.commit()
    client.post("/ingest/backfill")
    with session_factory() as s:
        job = s.query(Job).filter_by(source_id="j").one()
        assert job.visa_sponsorship is False
        assert job.remote_region == "us"
        assert job.required_utc_offsets == [-8]


def test_extract_work_countries_reads_a_stated_restriction():
    cases = [
        ("Must be located in France.", ["FR"]),
        ("This role is open to experts located anywhere in the United Kingdom.", ["GB"]),
        ("Must have resided in the United States for the past three consecutive years.", ["US"]),
        (
            "This role is available for candidates located in the UK, Germany, "
            "Spain, Ireland and Sweden.",
            ["DE", "ES", "GB", "IE", "SE"],
        ),
        ("We are looking for candidates in the UK, Spain and Ireland only.", ["ES", "GB", "IE"]),
        ("You need an existing right to work in Germany.", ["DE"]),
    ]
    for text, expected in cases:
        assert extract_work_countries(text) == expected, text


def test_extract_work_countries_ignores_a_country_that_is_not_a_restriction():
    # The whole point of scoping to a sentence with a restriction cue: a posting names
    # plenty of countries it is not hiring in. A false block hides a real job.
    for text in (
        "We sell into the United States and Canada.",
        "Our customers are German Mittelstand companies in Germany.",
        "If you are based in France, you will have a French contract.",
        "We have offices in London, New York, San Francisco, and Warsaw.",
        "This role is remote and can be executed globally.",
        "Our teams are distributed between France, USA, UK, Germany and Singapore.",
        "GitLab hires new team members in countries around the world.",
        "We are hiring across France, Spain, Belgium, and Canada.",
    ):
        assert extract_work_countries(text) == [], text
    assert extract_work_countries(None) == []
    assert extract_work_countries("") == []


def test_a_negated_scope_is_not_read_as_an_allowlist():
    # The worst failure mode available: "we cannot hire in the US" read as "only the US"
    # would hide every job the posting is actually open to.
    for text in (
        "We are not able to hire in the US.",
        "This role is not open to candidates based in the United States.",
        "We cannot hire candidates located in Germany.",
        "Unfortunately we are unable to hire candidates based in France.",
    ):
        assert extract_work_countries(text) == [], text


def test_a_dotted_abbreviation_is_not_split_mid_sentence():
    assert extract_work_countries("Must be located in the U.S.") == ["US"]
    assert extract_work_countries("Candidates must be based in the U.K.") == ["GB"]


def test_a_place_that_merely_contains_a_country_name_is_not_a_restriction():
    # "Atlanta, Georgia" is a US city, "New South Wales" is Australian, and "Jersey City"
    # is in New Jersey. Reading any of them as its namesake country hides the wrong jobs.
    assert extract_work_countries("Must be based in Atlanta, Georgia") == []
    assert extract_work_countries("Candidates must be located in Jersey City") == []
    assert extract_work_countries("Must be based in New South Wales") == ["AU"]


def test_greenhouse_boilerplate_restriction_falls_back_to_the_location():
    # The sentence names no country; the posting's own location is the restriction.
    text = (
        "Positions listed as Remote are only available for remote work "
        "within the specified country."
    )
    assert extract_work_countries(text, ["US"]) == ["US"]
    assert extract_work_countries(text, []) == []
