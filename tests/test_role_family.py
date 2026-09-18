"""Role-family classification (LLM + embedding fallback) + the include_role_families filter."""

from __future__ import annotations

from types import SimpleNamespace

from app.ai import role_family
from app.ai.role_family import (
    FAMILIES,
    AnthropicRoleClassifier,
    RoleClassifier,
    assign_family,
    build_centroids,
)
from app.models import Job


class _StubAnthropic:
    """Stands in for the Anthropic SDK client: records calls, answers via `respond`.

    `respond(prompt)` returns the tool input dict for that call, or raises to
    simulate an API failure.
    """

    def __init__(self, respond):
        self.calls: list[dict] = []
        self._respond = respond
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        tool = kwargs["tools"][0]["name"]
        payload = self._respond(kwargs["messages"][0]["content"])
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name=tool, input=payload)])


def _numbered(prompt: str) -> list[tuple[int, str]]:
    """Parse the "<index>\t<title>" lines the classifier sends."""
    out = []
    for line in prompt.splitlines():
        idx, sep, title = line.partition("\t")
        if sep and idx.strip().isdigit():
            out.append((int(idx), title))
    return out


class _StubEmbedder:
    """Returns a fixed vector per exact text; unknown text -> zero vector."""

    def __init__(self, table: dict[str, list[float]]):
        self.table = table

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.table.get(t, [0.0, 0.0, 0.0]) for t in texts]


def _job(sid, *, title="Backend Engineer", role_family=None) -> Job:
    return Job(
        source="t",
        source_id=sid,
        title=title,
        company="c",
        url=f"https://example.com/{sid}",
        is_remote=True,
        is_european=True,
        role_family=role_family,
    )


# --- unit: assign_family (pure) ---


def test_assign_family_picks_nearest():
    centroids = {"engineering": [1.0, 0.0], "sales": [0.0, 1.0]}
    fam = assign_family([0.9, 0.1], centroids, min_similarity=0.3, min_margin=0.02)
    assert fam == "engineering"


def test_assign_family_none_below_similarity():
    centroids = {"engineering": [1.0, 0.0], "sales": [0.0, 1.0]}
    # Equidistant -> top cosine 0.707, but we demand 0.8: nothing fits.
    assert assign_family([1.0, 1.0], centroids, min_similarity=0.8, min_margin=0.0) is None


def test_assign_family_none_when_ambiguous():
    centroids = {"engineering": [1.0, 0.0], "sales": [0.0, 1.0]}
    # A dead tie between two families -> margin 0 < 0.05 -> unclassified.
    assert assign_family([1.0, 1.0], centroids, min_similarity=0.3, min_margin=0.05) is None


# --- unit: build_centroids averages per family ---


def test_build_centroids_averages_and_normalizes(monkeypatch):
    monkeypatch.setattr(
        role_family,
        "ROLE_PROTOTYPES",
        {"eng": ["a", "b"], "sales": ["c"]},
    )
    embedder = _StubEmbedder({"a": [2.0, 0.0], "b": [0.0, 0.0], "c": [0.0, 3.0]})
    centroids = build_centroids(embedder)
    assert set(centroids) == {"eng", "sales"}
    # eng = mean([2,0],[0,0]) = [1,0] -> normalized [1,0]; sales normalized [0,1].
    assert centroids["eng"] == [1.0, 0.0]
    assert centroids["sales"] == [0.0, 1.0]


# --- integration: classify_titles end-to-end ---


def test_classify_titles():
    centroids = {"engineering": [1.0, 0.0], "sales": [0.0, 1.0]}
    clf = RoleClassifier(centroids, min_similarity=0.3, min_margin=0.02)
    embedder = _StubEmbedder(
        {
            "Backend Engineer": [1.0, 0.05],
            "Account Executive": [0.05, 1.0],
            "Mystery Role": [1.0, 1.0],  # ambiguous -> None
        }
    )
    out = clf.classify_titles(["Backend Engineer", "Account Executive", "Mystery Role"], embedder)
    assert out == ["engineering", "sales", None]


# --- LLM title classifier ---


def test_llm_classifier_batches_and_maps_by_index():
    def respond(prompt):
        return {
            "labels": [
                {"index": i, "family": "sales" if "Account" in t else "engineering"}
                for i, t in _numbered(prompt)
            ]
        }

    stub = _StubAnthropic(respond)
    titles = [f"Backend Engineer {i}" if i % 2 else f"Account Executive {i}" for i in range(130)]
    out = AnthropicRoleClassifier(client=stub, batch_size=60).classify_titles(titles)

    assert len(stub.calls) == 3  # 60 + 60 + 10
    assert out == ["engineering" if i % 2 else "sales" for i in range(130)]


def test_llm_classifier_unknown_or_missing_labels_are_none():
    def respond(prompt):
        return {"labels": [{"index": 0, "family": "astronaut"}, {"index": 1, "family": "legal"}]}

    out = AnthropicRoleClassifier(client=_StubAnthropic(respond)).classify_titles(
        ["A", "Corporate Paralegal", "C"]
    )
    assert out == [None, "legal", None]


def test_llm_classifier_failed_batch_stays_unclassified():
    # One batch erroring must not lose the others; its titles stay None (retried next run).
    def respond(prompt):
        if "boom" in prompt:
            raise RuntimeError("api down")
        return {"labels": [{"index": i, "family": "engineering"} for i, _ in _numbered(prompt)]}

    out = AnthropicRoleClassifier(client=_StubAnthropic(respond), batch_size=2).classify_titles(
        ["a", "b", "boom", "d"]
    )
    assert out == ["engineering", "engineering", None, None]


def test_families_cover_the_non_engineering_leaks():
    # Regression: legal/comms/office/expert-panel titles had no family, stayed null,
    # and slipped through an engineering-only filter.
    for fam in ("legal", "industrial_eng", "hospitality_retail", "consulting_research", "other"):
        assert fam in FAMILIES
    assert set(role_family.ROLE_PROTOTYPES) <= set(FAMILIES)


def test_suggest_families_for_cv_filters_to_known_and_caps():
    stub = _StubAnthropic(
        lambda prompt: {
            "families": ["engineering", "data_ml", "astronaut", "other", "product", "x"]
        }
    )
    assert AnthropicRoleClassifier(client=stub).suggest_families("CV text") == [
        "engineering",
        "data_ml",
        "product",
    ]


def test_suggest_families_failure_returns_empty():
    def respond(prompt):
        raise RuntimeError("api down")

    assert AnthropicRoleClassifier(client=_StubAnthropic(respond)).suggest_families("CV") == []


# --- /match/classify-roles ---


def test_classify_roles_uses_llm_classifier_without_openai(client, session_factory):
    from app.ai.embedder import get_embedder
    from app.ai.role_family import FakeRoleClassifier, get_role_classifier
    from app.main import app as fastapi_app

    def no_openai():
        raise AssertionError("the LLM path must not need the embedder")

    with session_factory() as s:
        s.add_all(
            [
                _job("eng", title="Backend Engineer"),
                _job("legal", title="Corporate Paralegal"),
                _job("done", title="Account Executive", role_family="sales"),
            ]
        )
        s.commit()
    fastapi_app.dependency_overrides[get_role_classifier] = lambda: FakeRoleClassifier()
    fastapi_app.dependency_overrides[get_embedder] = no_openai

    body = client.post("/match/classify-roles").json()
    assert body["classified"] == 2  # only the unclassified rows
    with session_factory() as s:
        fams = {j.source_id: j.role_family for j in s.query(Job).all()}
    assert fams == {"eng": "engineering", "legal": "legal", "done": "sales"}


# --- filter ---


def test_include_role_families_filter(client, session_factory):
    with session_factory() as s:
        s.add_all(
            [
                _job("eng", role_family="engineering"),
                _job("sales", role_family="sales"),
                _job("unknown", role_family=None),
            ]
        )
        s.commit()
    client.put("/preferences", json={"include_role_families": ["engineering"]})
    ids = {i["source_id"] for i in client.get("/jobs").json()["items"]}
    assert ids == {"eng", "unknown"}  # sales dropped; unclassified kept (null-kept)


def test_include_role_families_normalized(client):
    body = client.put(
        "/preferences", json={"include_role_families": [" Engineering ", "engineering", "SALES"]}
    ).json()
    assert body["include_role_families"] == ["engineering", "sales"]
