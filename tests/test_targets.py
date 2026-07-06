"""Target-company seeding + /targets management endpoints."""

from __future__ import annotations

from app.ingest.targets import active_targets, seed_target_companies
from app.models import TargetCompany


def test_seed_is_idempotent(session):
    first = seed_target_companies(session)
    assert first > 0  # 32 verified companies from the YAML seed
    total = session.query(TargetCompany).count()
    assert total == first

    second = seed_target_companies(session)
    assert second == 0  # nothing new inserted on a second run
    assert session.query(TargetCompany).count() == total


def test_active_targets_filters_by_vendor_and_active(session):
    seed_target_companies(session)
    greenhouse = active_targets(session, "greenhouse")
    assert len(greenhouse) > 0
    assert all(t.ats == "greenhouse" and t.active for t in greenhouse)

    # Deactivating one drops it from the active set.
    gitlab = next(t for t in greenhouse if t.slug == "gitlab")
    gitlab.active = False
    session.commit()
    assert all(t.slug != "gitlab" for t in active_targets(session, "greenhouse"))


def test_add_list_toggle_delete_target(client):
    # Add
    resp = client.post(
        "/targets",
        json={"company": "Acme", "ats": "greenhouse", "slug": "acme"},
    )
    assert resp.status_code == 201
    target_id = resp.json()["id"]
    assert resp.json()["active"] is True

    # Duplicate (ats, slug) -> 409
    dup = client.post("/targets", json={"company": "Acme", "ats": "greenhouse", "slug": "acme"})
    assert dup.status_code == 409

    # Bad vendor -> 422
    bad = client.post("/targets", json={"company": "X", "ats": "workday", "slug": "x"})
    assert bad.status_code == 422

    # List
    listed = client.get("/targets", params={"ats": "greenhouse"}).json()
    assert any(t["slug"] == "acme" for t in listed)

    # Toggle active off, then filter active=true excludes it
    patched = client.patch(f"/targets/{target_id}", json={"active": False})
    assert patched.status_code == 200 and patched.json()["active"] is False
    active_only = client.get("/targets", params={"active": "true"}).json()
    assert all(t["id"] != target_id for t in active_only)

    # Delete
    assert client.delete(f"/targets/{target_id}").status_code == 204
    assert client.delete(f"/targets/{target_id}").status_code == 404


def test_patch_missing_target_404(client):
    assert client.patch("/targets/999999", json={"active": False}).status_code == 404
