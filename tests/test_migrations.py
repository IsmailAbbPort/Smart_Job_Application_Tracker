"""Static checks on the Alembic revision files (the suite never runs migrations)."""

from __future__ import annotations

import re
from pathlib import Path

VERSIONS = Path(__file__).resolve().parent.parent / "migrations" / "versions"
# alembic_version.version_num is VARCHAR(32): a longer id fails only at upgrade time.
_MAX_REVISION_LEN = 32


def _revisions() -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for path in VERSIONS.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        rev = re.search(r'^revision: str = "([^"]+)"', text, re.M)
        down = re.search(r'^down_revision: str \| None = (?:"([^"]+)"|None)', text, re.M)
        assert rev and down, f"{path.name}: no revision/down_revision"
        out[rev.group(1)] = down.group(1)
    return out


def test_revision_ids_fit_alembic_version_column():
    too_long = [r for r in _revisions() if len(r) > _MAX_REVISION_LEN]
    assert too_long == []


def test_revisions_form_a_single_linear_chain():
    revs = _revisions()
    heads = set(revs) - {d for d in revs.values() if d}
    assert len(heads) == 1, f"multiple heads: {sorted(heads)}"
    downs = [d for d in revs.values() if d]
    assert len(downs) == len(set(downs)), "two revisions share a down_revision (branch)"
    assert all(d in revs for d in downs), "a down_revision points at a missing revision"
