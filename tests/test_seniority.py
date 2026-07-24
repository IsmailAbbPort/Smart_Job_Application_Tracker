"""Seniority detection + the seniority / title-keyword / required-language filters."""

from __future__ import annotations

from app.ingest.seniority import detect_seniority
from app.models import Cv, Job


def _job(sid, *, title="Backend Engineer", seniority=None, req=None, embedding=None) -> Job:
    return Job(
        source="t",
        source_id=sid,
        title=title,
        company="c",
        url=f"https://example.com/{sid}",
        is_remote=True,
        is_european=True,
        seniority=seniority,
        required_languages=req or [],
        embedding=embedding,
    )


# --- unit ---


def test_detect_seniority():
    assert detect_seniority("Senior Backend Engineer") == "senior"
    assert detect_seniority("Staff AI Engineer") == "senior"
    assert detect_seniority("Engineering Manager") == "senior"
    assert detect_seniority("Head of Platform") == "senior"
    assert detect_seniority("Working Student - Operations") == "intern"
    assert detect_seniority("Werkstudent Marketing") == "intern"
    assert detect_seniority("Full-Stack Engineer") is None  # mid/unspecified
    assert detect_seniority("UI Engineer II") is None
    assert detect_seniority(None) is None


# --- filters ---


def test_exclude_seniorities_filter(client, session_factory):
    with session_factory() as s:
        s.add_all(
            [
                _job("sen", seniority="senior"),
                _job("int", seniority="intern"),
                _job("mid", seniority=None),
            ]
        )
        s.commit()
    client.put("/preferences", json={"exclude_seniorities": ["senior", "intern"]})
    ids = {i["source_id"] for i in client.get("/jobs").json()["items"]}
    assert ids == {"mid"}  # senior + intern dropped; unspecified kept


def test_exclude_title_keywords_filter(client, session_factory):
    with session_factory() as s:
        s.add_all(
            [
                _job("ml", title="Machine Learning Engineer"),
                _job("swe", title="Backend Engineer"),
                _job("sales", title="Account Executive, Sales"),
            ]
        )
        s.commit()
    client.put("/preferences", json={"exclude_title_keywords": ["machine learning", "sales"]})
    ids = {i["source_id"] for i in client.get("/jobs").json()["items"]}
    assert ids == {"swe"}


def test_required_language_hard_filter(client, session_factory):
    with session_factory() as s:
        s.add(Cv(label="cv", content="x", embedding=[1.0, 0.0, 0.0]))
        s.add_all(
            [
                _job("none", req=[], embedding=[1.0, 0.0, 0.0]),
                _job("de", req=["de"], embedding=[1.0, 0.0, 0.0]),
                _job("en", req=["en"], embedding=[1.0, 0.0, 0.0]),
            ]
        )
        s.commit()
    client.put("/preferences", json={"known_languages": ["en"]})
    ids = {i["source_id"] for i in client.get("/match/shortlist").json()["items"]}
    # German-required dropped; English-required and no-requirement kept.
    assert ids == {"none", "en"}
