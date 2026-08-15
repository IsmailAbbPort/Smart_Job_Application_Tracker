"""Language signals: detection, requirement extraction, filter, and backfill."""

from __future__ import annotations

from app.ingest.language import (
    detect_language,
    extract_required_languages,
    extract_required_languages_from_title,
)
from app.models import Cv, Job

_EN = (
    "We are hiring a senior Python backend engineer with FastAPI and Postgres "
    "experience to join our distributed team."
)
_DE = (
    "Wir suchen einen erfahrenen Python-Entwickler mit Kenntnissen in FastAPI "
    "und Postgres fuer unser wachsendes Team in Berlin."
)


def _job(
    sid, *, language=None, required=None, is_european=True, embedding=None, description=""
) -> Job:
    return Job(
        source="test",
        source_id=sid,
        title="Engineer",
        company="Acme",
        url=f"https://example.com/{sid}",
        is_remote=True,
        is_european=is_european,
        language=language,
        required_languages=required or [],
        description=description,
        embedding=embedding,
    )


# --- unit ---


def test_detect_language():
    assert detect_language(_EN) == "en"
    assert detect_language(_DE) == "de"
    assert detect_language("too short") is None  # below the min-chars gate


def test_extract_required_languages():
    assert extract_required_languages("You must be fluent in German.") == ["de"]
    assert extract_required_languages("French C1 is needed.") == ["fr"]
    assert extract_required_languages("German is a plus.") == []  # softened -> not required
    assert extract_required_languages("Python, FastAPI, Docker.") == []


def test_extract_required_languages_from_title():
    f = extract_required_languages_from_title
    # requirement encoded in the title -> caught
    assert f("Solutions Consultant (German Speaking)") == ["de"]
    assert f("Business Support Specialist - German speaking") == ["de"]
    assert f("Quality Assurance Rater - German (Germany)") == ["de"]
    assert f("Solutions Consultant (French Speaking)") == ["fr"]
    # a country/location, not a language requirement -> not flagged
    assert f("Enterprise Solutions Engineer - Germany") == []
    assert f("Deployment Strategist - Germany") == []
    assert f("Backend Engineer") == []
    assert f(None) == []


# --- Tier 2 filter ---


def test_known_languages_filter(client, session_factory):
    with session_factory() as s:
        s.add_all(
            [
                _job("en", language="en"),
                _job("de", language="de"),
                _job("unknown", language=None),
            ]
        )
        s.commit()
    client.put("/preferences", json={"known_languages": ["EN"]})  # upper-cased on purpose

    ids = {i["source_id"] for i in client.get("/jobs").json()["items"]}
    assert ids == {"en", "unknown"}  # German dropped; null language kept


def test_known_languages_normalized_and_returned(client):
    body = client.put("/preferences", json={"known_languages": [" EN ", "en", "De"]}).json()
    assert body["known_languages"] == ["de", "en"]  # trimmed, lowercased, de-duped, sorted


def test_explicit_language_param(client, session_factory):
    with session_factory() as s:
        s.add_all([_job("en", language="en"), _job("de", language="de")])
        s.commit()
    ids = [i["source_id"] for i in client.get("/jobs", params={"language": "de"}).json()["items"]]
    assert ids == ["de"]


def test_languages_facet_endpoint(client, session_factory):
    with session_factory() as s:
        s.add_all(
            [
                _job("a", language="en"),
                _job("b", language="en"),
                _job("c", language="de"),
                _job("d", language=None),
            ]
        )
        s.commit()
    facets = client.get("/jobs/languages").json()
    counts = {f["code"]: f["count"] for f in facets}
    assert counts == {"en": 2, "de": 1}  # null excluded
    assert facets[0]["code"] == "en"  # ordered by count desc


def test_shortlist_respects_known_languages(client, session_factory):
    with session_factory() as s:
        s.add(Cv(label="cv", content="x", embedding=[1.0, 0.0, 0.0]))
        s.add_all(
            [
                _job("en", language="en", embedding=[1.0, 0.0, 0.0]),
                _job("de", language="de", embedding=[1.0, 0.0, 0.0]),
            ]
        )
        s.commit()
    client.put("/preferences", json={"known_languages": ["en"]})
    ids = [i["source_id"] for i in client.get("/match/shortlist").json()["items"]]
    assert ids == ["en"]  # German dropped despite being a perfect vector match


# --- backfill ---


def test_backfill_language(client, session_factory):
    with session_factory() as s:
        s.add_all(
            [
                _job("en", description=_EN),
                _job("de", description=_DE),
            ]
        )
        s.commit()

    body = client.post("/ingest/backfill").json()
    assert body["processed"] == 2

    with session_factory() as s:
        langs = {j.source_id: j.language for j in s.query(Job).all()}
    assert langs == {"en": "en", "de": "de"}
