"""Regression tests for tool-use output coercion.

The live judge 500'd when Haiku collapsed two adjacent list fields into one string:
`matched_requirements` came back as the concatenated JSON of both the matched
requirements AND the gaps, with the `gaps` key dropped. That is a schema-valid-
looking tool call that `model_validate` rejects. `coerce_tool_input` splits the
concatenated arrays and backfills the dropped field before validation.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.ai.tooluse import coerce_tool_input
from app.schemas import FabricationCheck, MatchVerdict


def _haiku_verdict_payload() -> dict:
    """The exact shape Haiku returned that broke the judge: the matched-requirements
    array and the gaps array concatenated into the one string field, no `gaps` key."""
    matched = [{"requirement": "Python", "cv_evidence": "Built FastAPI services"}]
    gaps = ["Kubernetes at scale - not evidenced", "Temporal - not mentioned"]
    return {
        "overall_score": 35,
        "verdict": "weak",
        "one_line_verdict": "Some overlap but missing core requirements.",
        "dimension_scores": {"skills": 40, "seniority": 30, "domain": 35, "location_remote": 60},
        # Two JSON arrays back to back in one string, exactly as the model emitted them.
        "matched_requirements": json.dumps(matched) + "\n" + json.dumps(gaps),
        # gaps intentionally absent
    }


def test_concatenated_arrays_and_missing_gaps_fail_without_coercion():
    # Encodes the bug: the raw payload does not validate as-is.
    with pytest.raises(ValidationError):
        MatchVerdict.model_validate(_haiku_verdict_payload())


def test_coercion_splits_concatenated_arrays_and_recovers_gaps():
    verdict = MatchVerdict.model_validate(
        coerce_tool_input(MatchVerdict, _haiku_verdict_payload())
    )
    assert verdict.overall_score == 35
    assert [r.requirement for r in verdict.matched_requirements] == ["Python"]
    # The gaps the model merged into the other field are recovered, not dropped.
    assert verdict.gaps == ["Kubernetes at scale - not evidenced", "Temporal - not mentioned"]


def test_coercion_defaults_truly_missing_list_to_empty():
    payload = {
        "overall_score": 80,
        "verdict": "strong",
        "one_line_verdict": "Strong fit.",
        "dimension_scores": {"skills": 90, "seniority": 80, "domain": 75, "location_remote": 100},
        "matched_requirements": [{"requirement": "Python", "cv_evidence": "10y Python"}],
        # gaps absent and no overflow to recover it from -> empty, not a 500
    }
    verdict = MatchVerdict.model_validate(coerce_tool_input(MatchVerdict, payload))
    assert verdict.gaps == []


def test_coercion_handles_raw_newlines_inside_stringified_values():
    # The model leaves literal newlines inside string values; strict JSON rejects them.
    matched = '[\n  {\n    "requirement": "Owns\nprojects",\n    "cv_evidence": "Led\nteams"\n  }\n]'
    payload = {
        "overall_score": 60,
        "verdict": "medium",
        "one_line_verdict": "Decent fit.",
        "dimension_scores": {"skills": 60, "seniority": 60, "domain": 60, "location_remote": 90},
        "matched_requirements": matched,
    }
    verdict = MatchVerdict.model_validate(coerce_tool_input(MatchVerdict, payload))
    assert verdict.matched_requirements[0].requirement == "Owns\nprojects"


def test_coercion_salvages_truncated_stringified_array():
    # The model exceeded max_tokens mid-array: two complete objects, third cut off.
    truncated = (
        '[{"requirement": "A", "cv_evidence": "e1"}, '
        '{"requirement": "B", "cv_evidence": "e2"}, '
        '{"requirement": "C", "cv_evidence": "e'
    )
    payload = {
        "overall_score": 55,
        "verdict": "medium",
        "one_line_verdict": "Partial.",
        "dimension_scores": {"skills": 55, "seniority": 55, "domain": 55, "location_remote": 80},
        "matched_requirements": truncated,
    }
    verdict = MatchVerdict.model_validate(coerce_tool_input(MatchVerdict, payload))
    # The two complete requirements survive; the cut-off one is dropped, no 500.
    assert [r.requirement for r in verdict.matched_requirements] == ["A", "B"]


def test_coercion_repairs_stringified_fabrication_claims():
    payload = {
        "claims": json.dumps(
            [{"claim": "Knows Python", "supported": True, "evidence": "CV lists Python"}]
        ),
        # placeholders omitted -> already optional, stays default
    }
    check = FabricationCheck.model_validate(coerce_tool_input(FabricationCheck, payload))
    assert check.claims[0].claim == "Knows Python"
    assert check.placeholders == []


def test_coercion_leaves_valid_payload_untouched():
    payload = {
        "claims": [{"claim": "x", "supported": False, "evidence": ""}],
        "placeholders": ["[NEEDS INPUT: a metric]"],
    }
    check = FabricationCheck.model_validate(coerce_tool_input(FabricationCheck, payload))
    # A natural-language placeholder that starts with '[' must not be JSON-parsed away.
    assert check.placeholders == ["[NEEDS INPUT: a metric]"]
    assert check.claims[0].supported is False
