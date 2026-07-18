"""Compensation + effort extraction and the min-salary filter."""

from __future__ import annotations

from app.ingest.compensation import extract_effort_signals, extract_salary
from app.models import Job


def _job(sid, *, salary_max=None, salary_min=None, currency=None) -> Job:
    return Job(
        source="test",
        source_id=sid,
        title="Engineer",
        company="Acme",
        url=f"https://example.com/{sid}",
        is_remote=True,
        is_european=True,
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=currency,
    )


# --- unit ---


def test_extract_salary_ranges():
    assert extract_salary("Salary: $120,000 - $150,000 a year.") == (120000, 150000, "USD")
    assert extract_salary("Comp €60k-80k plus equity.") == (60000, 80000, "EUR")
    assert extract_salary("We pay £90,000.") == (90000, 90000, "GBP")


def test_extract_salary_ignores_noise():
    assert extract_salary("Contribute to your 401k plan.") == (None, None, None)
    assert extract_salary("We have 200 employees.") == (None, None, None)
    assert extract_salary("$40/hour contract.") == (None, None, None)  # hourly, below floor
    assert extract_salary("") == (None, None, None)


def test_extract_salary_skips_funding_finds_pay():
    # Funding/valuation figures precede the real salary; scanning must skip them.
    text = "We raised $781M, valued at $11B. Salary: $120,000 - $150,000 per year."
    assert extract_salary(text) == (120000, 150000, "USD")


def test_extract_effort_signals():
    got = extract_effort_signals("Submit a cover letter and complete our take-home challenge.")
    assert got == ["coding_challenge", "cover_letter"]
    assert extract_effort_signals("Share your portfolio link.") == ["portfolio"]
    assert extract_effort_signals("Apply with your CV.") == []


# --- filter ---


def test_min_salary_filter(client, session_factory):
    with session_factory() as s:
        s.add_all(
            [
                _job("high", salary_max=150000, salary_min=120000, currency="USD"),
                _job("low", salary_max=40000, salary_min=30000, currency="USD"),
                _job("unstated", salary_max=None),
            ]
        )
        s.commit()
    ids = {
        i["source_id"] for i in client.get("/jobs", params={"min_salary": 80000}).json()["items"]
    }
    assert ids == {"high", "unstated"}  # low dropped; unknown-pay kept


def test_min_salary_require_salary(client, session_factory):
    with session_factory() as s:
        s.add_all(
            [
                _job("high", salary_max=150000, currency="USD"),
                _job("unstated", salary_max=None),
            ]
        )
        s.commit()
    ids = {
        i["source_id"]
        for i in client.get("/jobs", params={"min_salary": 80000, "require_salary": "true"}).json()[
            "items"
        ]
    }
    assert ids == {"high"}  # unknown-pay now dropped too


def test_min_salary_currency_only_compares_same_currency(client, session_factory):
    with session_factory() as s:
        s.add_all(
            [
                _job("eur_low", salary_max=50000, currency="EUR"),
                _job("usd_low", salary_max=50000, currency="USD"),
                _job("eur_high", salary_max=90000, currency="EUR"),
            ]
        )
        s.commit()
    ids = {
        i["source_id"]
        for i in client.get(
            "/jobs", params={"min_salary": 60000, "min_salary_currency": "EUR"}
        ).json()["items"]
    }
    # EUR floor drops only the low EUR job; the USD job can't be compared, so it stays.
    assert ids == {"usd_low", "eur_high"}


def test_backfill_sets_compensation(client, session_factory):
    with session_factory() as s:
        s.add(
            Job(
                source="test",
                source_id="c",
                title="Engineer",
                company="Acme",
                url="https://example.com/c",
                is_remote=True,
                is_european=True,
                description=(
                    "Great role. Salary: $120,000 - $150,000. Please include a cover letter. " * 3
                ),
            )
        )
        s.commit()
    client.post("/ingest/backfill")
    with session_factory() as s:
        job = s.query(Job).filter_by(source_id="c").one()
        assert (job.salary_min, job.salary_max, job.salary_currency) == (120000, 150000, "USD")
        assert job.effort_signals == ["cover_letter"]
