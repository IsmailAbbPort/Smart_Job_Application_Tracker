"""/match endpoint tests: embed-jobs backfill and shortlist ranking."""

from __future__ import annotations

from datetime import UTC, datetime

from app.models import Cv, Job


def _job(source_id, *, embedding=None, is_remote=True, is_european=True) -> Job:
    return Job(
        source="test",
        source_id=source_id,
        title="Engineer",
        company="Acme",
        url=f"https://example.com/{source_id}",
        is_remote=is_remote,
        is_european=is_european,
        embedding=embedding,
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
