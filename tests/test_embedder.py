"""Embedder + document builder unit tests."""

from __future__ import annotations

from app.ai.embedder import (
    EMBED_DIM,
    FakeEmbedder,
    build_cv_document,
    build_job_document,
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
    job.description = "Build things. " * 400  # long
    doc = build_job_document(job)
    assert "Senior Backend Engineer" in doc
    assert "at GitLab" in doc
    assert "Berlin" in doc
    assert len(doc) < 2500  # description trimmed


def test_build_cv_document_trims():
    assert len(build_cv_document("x" * 50000)) == 20000
    assert build_cv_document("") == ""
