"""/match endpoint tests: embed-jobs backfill and shortlist ranking."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models import Cv, Job


def _job(source_id, *, embedding=None, is_remote=True, is_european=True, posted_at=None) -> Job:
    return Job(
        source="test",
        source_id=source_id,
        title="Engineer",
        company="Acme",
        url=f"https://example.com/{source_id}",
        is_remote=is_remote,
        is_european=is_european,
        embedding=embedding,
        posted_at=posted_at,
    )


def test_embed_jobs_backfills(embed_client, session_factory):
    with session_factory() as s:
        s.add_all([_job("a"), _job("b"), _job("c")])
        s.commit()

    body = embed_client.post("/match/embed-jobs").json()
    assert body["embedded"] == 3
    assert body["remaining_unembedded"] == 0

    with session_factory() as s:
        assert all(j.embedding is not None for j in s.query(Job).all())

    # Second run: nothing left to embed.
    assert embed_client.post("/match/embed-jobs").json()["embedded"] == 0


def _seed_cv_and_jobs(session_factory) -> None:
    with session_factory() as s:
        s.add(Cv(label="CV", content="x", embedding=[1.0, 0.0, 0.0]))
        s.add_all(
            [
                _job("match", embedding=[1.0, 0.0, 0.0]),
                _job("close", embedding=[0.8, 0.2, 0.0]),
                _job("far", embedding=[0.2, 1.0, 0.0]),
                _job("us", embedding=[1.0, 0.0, 0.0], is_european=False),
            ]
        )
        s.commit()


def test_shortlist_ranks_by_similarity(client, session_factory):
    _seed_cv_and_jobs(session_factory)
    # Scope to Europe so the non-European perfect-match tie ("us") is excluded.
    body = client.get("/match/shortlist", params={"limit": 10, "europe": "true"}).json()
    ids = [item["source_id"] for item in body["items"]]
    assert ids == ["match", "close", "far"]
    assert body["items"][0]["similarity"] == 1.0


def test_shortlist_europe_filter(client, session_factory):
    _seed_cv_and_jobs(session_factory)
    body = client.get("/match/shortlist", params={"europe": "true"}).json()
    assert "us" not in [item["source_id"] for item in body["items"]]


def test_shortlist_no_cv_404(client):
    assert client.get("/match/shortlist").status_code == 404


def test_shortlist_recency_breaks_fit_ties(client, session_factory):
    now = datetime.now(UTC)
    with session_factory() as s:
        s.add(Cv(label="cv", content="x", embedding=[1.0, 0.0, 0.0]))
        # Identical (perfect) fit; only the post date differs.
        s.add(_job("fresh", embedding=[1.0, 0.0, 0.0], posted_at=now))
        s.add(_job("stale", embedding=[1.0, 0.0, 0.0], posted_at=now - timedelta(days=120)))
        s.commit()
    items = client.get("/match/shortlist").json()["items"]
    ids = [i["source_id"] for i in items]
    assert ids == ["fresh", "stale"]  # equal fit -> fresher first
    assert items[0]["recency_weight"] == 1.0
    assert items[1]["recency_weight"] < 1.0  # stale one was down-weighted


def test_shortlist_recency_does_not_bury_better_fit(client, session_factory):
    now = datetime.now(UTC)
    with session_factory() as s:
        s.add(Cv(label="cv", content="x", embedding=[1.0, 0.0, 0.0]))
        # Clearly better fit but old, vs weaker fit but fresh: fit should still win.
        s.add(_job("old_strong", embedding=[1.0, 0.0, 0.0], posted_at=now - timedelta(days=120)))
        s.add(_job("new_weak", embedding=[0.3, 0.95, 0.0], posted_at=now))
        s.commit()
    ids = [i["source_id"] for i in client.get("/match/shortlist").json()["items"]]
    assert ids[0] == "old_strong"  # the floored decay can't overturn a big fit gap


def test_shortlist_fit_dominates_recency_when_cosine_compressed(client, session_factory):
    # Regression: real cosine values cluster in a narrow band. A stale role with a
    # slightly higher fit must still beat a fresh role with slightly lower fit -
    # freshness must not dominate once fit is normalized across the candidate set.
    now = datetime.now(UTC)
    with session_factory() as s:
        s.add(Cv(label="cv", content="x", embedding=[1.0, 0.0, 0.0]))
        # cosines ~0.9988 vs ~0.9889: close, like the real corpus.
        s.add(_job("stale_better", embedding=[1.0, 0.05, 0.0], posted_at=now - timedelta(days=120)))
        s.add(_job("fresh_worse", embedding=[1.0, 0.15, 0.0], posted_at=now))
        s.commit()
    ids = [i["source_id"] for i in client.get("/match/shortlist").json()["items"]]
    assert ids[0] == "stale_better"


def test_shortlist_max_age_cutoff(client, session_factory):
    now = datetime.now(UTC)
    with session_factory() as s:
        s.add(Cv(label="cv", content="x", embedding=[1.0, 0.0, 0.0]))
        s.add(_job("recent", embedding=[1.0, 0.0, 0.0], posted_at=now - timedelta(days=10)))
        s.add(_job("old", embedding=[1.0, 0.0, 0.0], posted_at=now - timedelta(days=90)))
        s.add(_job("undated", embedding=[1.0, 0.0, 0.0], posted_at=None))
        s.commit()
    ids = {
        i["source_id"]
        for i in client.get("/match/shortlist", params={"max_age_days": 45}).json()["items"]
    }
    assert ids == {"recent", "undated"}  # old dropped; undated kept (unknown != old)


def test_shortlist_uses_latest_cv(client, session_factory):
    with session_factory() as s:
        s.add(
            Cv(
                label="old",
                content="x",
                embedding=[0.0, 1.0, 0.0],
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        s.add(
            Cv(
                label="new",
                content="x",
                embedding=[1.0, 0.0, 0.0],
                created_at=datetime(2026, 7, 1, tzinfo=UTC),
            )
        )
        s.add(_job("match", embedding=[1.0, 0.0, 0.0]))
        s.commit()
    body = client.get("/match/shortlist").json()
    # Latest CV ([1,0,0]) -> the [1,0,0] job is a perfect match.
    assert body["items"][0]["similarity"] == 1.0
