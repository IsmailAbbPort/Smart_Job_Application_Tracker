"""Role-family classification (embedding-space) + the include_role_families filter."""

from __future__ import annotations

from app.ai import role_family
from app.ai.role_family import RoleClassifier, assign_family, build_centroids
from app.models import Job


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
    out = clf.classify_titles(
        ["Backend Engineer", "Account Executive", "Mystery Role"], embedder
    )
    assert out == ["engineering", "sales", None]


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
