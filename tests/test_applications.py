"""Application pipeline: upsert, status transitions, stats, already-applied tags."""

from __future__ import annotations

from app.models import Cv, Job


def _job(sid, *, embedding=None) -> Job:
    return Job(
        source="test",
        source_id=sid,
        title="Engineer",
        company="Acme",
        url=f"https://example.com/{sid}",
        is_remote=True,
        is_european=True,
        embedding=embedding,
    )


def _seed_job(session_factory, sid="j", **kw) -> int:
    with session_factory() as s:
        job = _job(sid, **kw)
        s.add(job)
        s.commit()
        return job.id


def test_upsert_creates_then_updates(client, session_factory):
    job_id = _seed_job(session_factory)

    created = client.post("/applications", json={"job_id": job_id, "status": "saved"})
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "saved"
    assert body["applied_at"] is None
    assert body["job"]["id"] == job_id  # job embedded

    # Advancing past 'saved' stamps applied_at and reuses the same row.
    updated = client.post("/applications", json={"job_id": job_id, "status": "applied"}).json()
    assert updated["id"] == body["id"]
    assert updated["status"] == "applied"
    assert updated["applied_at"] is not None

    assert len(client.get("/applications").json()) == 1  # not duplicated


def test_upsert_missing_job_404(client):
    assert client.post("/applications", json={"job_id": 999, "status": "saved"}).status_code == 404


def test_records_cv_and_notes(client, session_factory):
    with session_factory() as s:
        s.add(Cv(label="cv", content="x"))
        s.commit()
        cv_id = s.query(Cv).one().id
    job_id = _seed_job(session_factory)
    body = client.post(
        "/applications",
        json={"job_id": job_id, "status": "applied", "cv_id": cv_id, "notes": "referred by A"},
    ).json()
    assert body["cv_id"] == cv_id
    assert body["notes"] == "referred by A"


def test_applied_at_not_reset_on_later_stage(client, session_factory):
    job_id = _seed_job(session_factory)
    first = client.post("/applications", json={"job_id": job_id, "status": "applied"}).json()
    later = client.post("/applications", json={"job_id": job_id, "status": "interview"}).json()
    # applied_at is stamped once (when it first left 'saved') and not overwritten.
    assert later["applied_at"] == first["applied_at"]


def test_list_filter_and_stats(client, session_factory):
    with session_factory() as s:
        s.add_all([_job("a"), _job("b"), _job("c")])
        s.commit()
        ids = [j.id for j in s.query(Job).order_by(Job.id).all()]

    client.post("/applications", json={"job_id": ids[0], "status": "applied"})
    client.post("/applications", json={"job_id": ids[1], "status": "interview"})
    client.post("/applications", json={"job_id": ids[2], "status": "applied"})

    applied = client.get("/applications", params={"status": "applied"}).json()
    assert {a["job_id"] for a in applied} == {ids[0], ids[2]}

    stats = client.get("/applications/stats").json()
    assert stats["total"] == 3
    assert stats["by_status"]["applied"] == 2
    assert stats["by_status"]["interview"] == 1
    assert stats["by_status"]["offer"] == 0  # zero-filled


def test_untrack(client, session_factory):
    job_id = _seed_job(session_factory)
    client.post("/applications", json={"job_id": job_id, "status": "saved"})
    assert client.delete(f"/applications/{job_id}").status_code == 204
    assert client.get(f"/applications/{job_id}").status_code == 404


def test_jobs_annotated_with_application_status(client, session_factory):
    job_id = _seed_job(session_factory, sid="tracked")
    client.post("/applications", json={"job_id": job_id, "status": "interview"})

    item = next(i for i in client.get("/jobs").json()["items"] if i["id"] == job_id)
    assert item["application_status"] == "interview"


def test_shortlist_annotated_with_application_status(client, session_factory):
    with session_factory() as s:
        s.add(Cv(label="cv", content="x", embedding=[1.0, 0.0, 0.0]))
        s.commit()
    job_id = _seed_job(session_factory, sid="s1", embedding=[1.0, 0.0, 0.0])
    client.post("/applications", json={"job_id": job_id, "status": "applied"})

    items = client.get("/match/shortlist").json()["items"]
    assert items[0]["application_status"] == "applied"
