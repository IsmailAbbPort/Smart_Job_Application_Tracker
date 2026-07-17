"""Embedder + document builder unit tests."""

from __future__ import annotations

from app.ai.embedder import (
    EMBED_DIM,
    FakeEmbedder,
    build_cv_document,
    build_job_document,
    clean_description,
)
from tests.conftest import make_canonical


def test_fake_embedder_shape_and_determinism():
    emb = FakeEmbedder()
    a1, b = emb.embed(["hello", "world"])
    (a2,) = emb.embed(["hello"])
    assert len(a1) == EMBED_DIM
    assert a1 == a2  # deterministic
    assert a1 != b  # different text -> different vector


def test_fake_embedder_custom_dim():
    assert len(FakeEmbedder(dim=8).embed(["x"])[0]) == 8


def test_build_job_document_includes_key_fields():
    job = make_canonical(title="Senior Backend Engineer", company="GitLab", location="Berlin")
    job.description = "Build things. " * 400  # ~5600 chars, well over the token cap
    doc = build_job_document(job)
    assert "Senior Backend Engineer" in doc
    assert "at GitLab" in doc
    assert "Berlin" in doc
    # Body is token-capped (~768 tokens ≈ 3k chars), so the doc is trimmed but the
    # high-signal header fields survive whole.
    assert len(doc) < len(job.description)
    assert len(doc) < 4000


def test_clean_description_strips_boilerplate():
    text = (
        "We need a Python engineer with FastAPI and Postgres experience.\n\n"
        "About us: we are a fast-growing startup changing the world.\n\n"
        "What we offer: free lunch, ping pong, unlimited PTO.\n\n"
        "You will design and ship backend services."
    )
    cleaned = clean_description(text)
    assert "FastAPI and Postgres" in cleaned
    assert "design and ship backend services" in cleaned
    assert "ping pong" not in cleaned  # boilerplate paragraph removed
    assert "fast-growing startup" not in cleaned


def test_clean_description_never_empties():
    # Everything looks like boilerplate -> fall back to original, not "".
    assert clean_description("About us: we build things.") != ""


def test_build_cv_document_trims():
    assert len(build_cv_document("x" * 50000)) == 20000
    assert build_cv_document("") == ""
