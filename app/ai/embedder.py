"""Embedding providers behind one interface, plus the text we embed.

`Embedder` is the seam: OpenAIEmbedder in production, FakeEmbedder in tests. The
document builders decide *what* text represents a job / CV for retrieval.
"""

from __future__ import annotations

import hashlib
from typing import Protocol

from fastapi import Depends, HTTPException

from app.config import Settings, get_settings

EMBED_DIM = 1536
EMBED_MODEL = "text-embedding-3-small"

_MAX_JOB_DESC_CHARS = 2000
_MAX_CV_CHARS = 20000


class Embedder(Protocol):
    """Turns texts into vectors. One vector per input, order preserved."""

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbedder:
    """Calls OpenAI's embeddings API, chunking large batches."""

    def __init__(self, api_key: str, model: str = EMBED_MODEL, batch_size: int = 128):
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self._model = model
        self._batch = batch_size

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), self._batch):
            chunk = [t if t.strip() else " " for t in texts[start : start + self._batch]]
            resp = self._client.embeddings.create(model=self._model, input=chunk)
            out.extend(item.embedding for item in resp.data)
        return out


class FakeEmbedder:
    """Deterministic pseudo-embeddings for tests. No network.

    Same text -> same vector; different text -> different vector. Not semantically
    meaningful, but enough to exercise storage and ranking plumbing.
    """

    def __init__(self, dim: int = EMBED_DIM):
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def _vector(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [digest[i % len(digest)] / 255.0 for i in range(self.dim)]


def build_job_document(job) -> str:
    """The text used to embed a job (title + company + location + trimmed body)."""
    parts = [
        job.title or "",
        f"at {job.company}" if job.company else "",
        job.location or "",
        (job.description or "")[:_MAX_JOB_DESC_CHARS],
    ]
    return "\n".join(p for p in parts if p)


def build_cv_document(content: str) -> str:
    return (content or "")[:_MAX_CV_CHARS]


def get_embedder(settings: Settings = Depends(get_settings)) -> Embedder:
    """FastAPI dependency. Real OpenAI embedder; 503 if the key is missing."""
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not configured; embeddings are unavailable.",
        )
    return OpenAIEmbedder(settings.openai_api_key)
