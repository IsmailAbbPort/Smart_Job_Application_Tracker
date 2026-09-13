"""/jobs/cities, /jobs/countries, /jobs/languages: corpus option sources for filters."""

from __future__ import annotations

from app.models import Job


def _job(sid, *, city=None, country=None, language=None) -> Job:
    return Job(
        source="test",
        source_id=sid,
        title="Engineer",
        company="Acme",
        url=f"https://example.com/{sid}",
        is_remote=True,
        is_european=True,
        city=city,
        country=country,
        language=language,
    )


def _seed(session_factory) -> None:
    with session_factory() as s:
        s.add_all(
            [
                _job("1", city="Berlin", country="Germany", language="de"),
                _job("2", city="Berlin", country="Germany", language="en"),
                _job("3", city="Paris", country="France", language="en"),
                _job("4", city=None, country=None, language=None),  # nulls excluded
                _job("5", city="", country="", language="en"),  # blanks excluded
            ]
        )
        s.commit()


def test_cities_counts_and_order(client, session_factory):
    _seed(session_factory)
    rows = client.get("/jobs/cities").json()
    names = [r["name"] for r in rows]
    assert names == ["Berlin", "Paris"]  # most frequent first, nulls/blanks dropped
    assert rows[0]["count"] == 2


def test_countries_counts_and_order(client, session_factory):
    _seed(session_factory)
    rows = client.get("/jobs/countries").json()
    assert [r["name"] for r in rows] == ["Germany", "France"]
    assert rows[0]["count"] == 2


def test_languages_ordered_by_frequency(client, session_factory):
    _seed(session_factory)
    rows = client.get("/jobs/languages").json()
    # en appears 3x, de 1x -> en first.
    assert rows[0]["code"] == "en"
    assert rows[0]["count"] == 3
