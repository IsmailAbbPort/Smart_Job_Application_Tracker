"""Embedding providers behind one interface, plus the text we embed.

`Embedder` is the seam: OpenAIEmbedder in production, FakeEmbedder in tests. The
document builders decide *what* text represents a job / CV for retrieval.
"""

from __future__ import annotations

import functools
import hashlib
import re
from typing import Protocol

from fastapi import Depends, HTTPException

from app.config import Settings, get_settings

EMBED_DIM = 1536
EMBED_MODEL = "text-embedding-3-small"

# Retrieve-stage cap on the job body, in tokens (~3k chars). The retrieve stage
# only needs recall, and the LLM judge later reads the full posting, so a lossy
# but dense document is the right trade here. See build_job_document.
_MAX_JOB_DESC_TOKENS = 768
_MAX_CV_CHARS = 20000

# Common boilerplate blurbs that dilute the embedding signal (they say nothing
# about the actual role). Best-effort: paragraphs matching these are dropped
# before embedding. Deliberately conservative to avoid eating real requirements.
_BOILERPLATE = re.compile(
    r"equal opportunity|regardless of race|regardless of gender|regardless of religion|"
    r"how to apply|to apply[,:]|please submit|please apply|about us\b|about the company|"
    r"who we are|our mission|our values|what we offer|we offer\b|benefits include|"
    r"perks and benefits|diversity (?:and|&) inclusion|reasonable accommodation|e-verify",
    re.IGNORECASE,
)


class Embedder(Protocol):
    """Turns texts into vectors. One vector per input, order preserved."""

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbedder:
    """Calls OpenAI's embeddings API, chunking large batches.

    `dimensions` (when set) truncates the output vector via Matryoshka support on
    text-embedding-3 models, so a larger model can be pinned to the stored 1536-dim
    column without a migration.
    """

    def __init__(
        self,
        api_key: str,
        model: str = EMBED_MODEL,
        dimensions: int | None = None,
        batch_size: int = 128,
    ):
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self._model = model
        self._dimensions = dimensions
        self._batch = batch_size

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        kwargs = {"dimensions": self._dimensions} if self._dimensions else {}
        for start in range(0, len(texts), self._batch):
            chunk = [t if t.strip() else " " for t in texts[start : start + self._batch]]
            resp = self._client.embeddings.create(model=self._model, input=chunk, **kwargs)
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


@functools.lru_cache(maxsize=1)
def _encoder():
    # cl100k_base is the tokenizer for text-embedding-3-* (and GPT-4-class models).
    import tiktoken

    return tiktoken.get_encoding("cl100k_base")


def _truncate_tokens(text: str, max_tokens: int) -> str:
    """Trim text to at most max_tokens (token-based, not char-based, so cost and
    the model's 8k input limit are respected the same way for any language)."""
    if not text:
        return ""
    tokens = _encoder().encode(text)
    if len(tokens) <= max_tokens:
        return text
    return _encoder().decode(tokens[:max_tokens])


def clean_description(text: str) -> str:
    """Drop common boilerplate paragraphs so the embedded text is denser with the
    actual role. Best-effort and conservative; the judge still reads the full text.
    Falls back to the original if stripping would empty it."""
    if not text:
        return ""
    paragraphs = re.split(r"\n\s*\n", text)
    kept = [p for p in paragraphs if p.strip() and not _BOILERPLATE.search(p)]
    return "\n\n".join(kept).strip() or text.strip()


def build_job_document(job) -> str:
    """The text used to embed a job: title + company + location + a cleaned,
    token-capped body. Title/company/location are kept whole (high signal); only
    the free-text body is stripped of boilerplate and truncated.

    Future work (deferred until the golden-set evals exist to measure the gain):
    for very long postings, chunk the body into several vectors and retrieve on the
    best-matching chunk (max-sim), or LLM-distill the requirements before embedding.
    Both raise precision but add storage/cost/complexity, and the LLM judge already
    supplies precision downstream, so the simple capped document is the right call
    for now.
    """
    body = _truncate_tokens(clean_description(job.description or ""), _MAX_JOB_DESC_TOKENS)
    parts = [
        job.title or "",
        f"at {job.company}" if job.company else "",
        job.location or "",
        body,
    ]
    return "\n".join(p for p in parts if p)


def build_cv_document(content: str) -> str:
    return (content or "")[:_MAX_CV_CHARS]


def get_embedder(settings: Settings = Depends(get_settings)) -> Embedder:
    """FastAPI dependency. Real OpenAI embedder; 503 if the key is missing.

    Model + dimensions come from settings, so the embedder is swappable via env.
    """
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not configured; embeddings are unavailable.",
        )
    return OpenAIEmbedder(
        settings.openai_api_key,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )
