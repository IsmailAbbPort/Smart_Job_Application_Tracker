"""Grading judge facts into a verdict: dealbreakers, score and tier rules."""

from __future__ import annotations

from types import SimpleNamespace

from app.ai.decide import CandidateRules, decide, rules_from_preferences
from app.schemas import JudgeFacts


def _facts(requirements=(), **constraints) -> JudgeFacts:
    base = {
        "work_mode": "remote",
        "location": "",
        "work_countries": [],
        "candidate_work_rights": ["EU"],
        "citizenship_or_clearance": "",
        "citizenship_or_clearance_ok": "unknown",
        "required_languages": [],
        "candidate_languages": ["en"],
        "min_years_experience": None,
        "candidate_years_experience": 1,
        "seniority": "mid",
    }
    base.update(constraints)
    return JudgeFacts.model_validate(
        {
            "requirements": [
                {
                    "requirement": req[2] if len(req) > 2 else f"req {i}",
                    "importance": req[0],
                    "cv_evidence": "",
                    "status": req[1],
                    "core": req[3] if len(req) > 3 else True,
                }
                for i, req in enumerate(requirements)
            ],
            "constraints": base,
            "summary": "fits",
        }
    )


MUST_MET = [("must_have", "met")] * 4


def test_all_must_haves_met_no_dealbreaker_is_strong():
    v = decide(_facts(MUST_MET), CandidateRules())
    assert v.verdict == "strong" and v.dealbreakers == []
    assert v.overall_score == 90


def test_one_absent_must_have_can_still_be_strong():
    reqs = [("must_have", "met")] * 4 + [("must_have", "absent")]
    assert decide(_facts(reqs), CandidateRules()).verdict == "strong"


def test_two_absent_must_haves_is_not_strong():
    reqs = [("must_have", "met")] * 6 + [("must_have", "absent")] * 2
    assert decide(_facts(reqs), CandidateRules()).verdict == "medium"


def test_partial_counts_half():
    reqs = [("must_have", "partial")] * 4
    v = decide(_facts(reqs), CandidateRules())
    assert v.overall_score == 45 and v.verdict == "medium"


def test_core_must_haves_carry_the_tier():
    # A posting split into many lines scores on the handful the model marked core, so the
    # tier does not depend on how finely the model chopped up the responsibilities.
    reqs = [("must_have", "met")] * 4 + [
        ("must_have", "absent", f"area {i}", False) for i in range(17)
    ]
    v = decide(_facts(reqs), CandidateRules())
    assert v.verdict == "strong" and v.overall_score == 90


def test_fewer_than_three_core_falls_back_to_every_must_have():
    reqs = [("must_have", "met", "core skill", True)] * 2 + [
        ("must_have", "absent", f"area {i}", False) for i in range(6)
    ]
    assert decide(_facts(reqs), CandidateRules()).verdict == "weak"


def test_constraints_listed_as_requirements_are_not_graded_as_skills():
    # The model still slips these in despite the prompt; they are graded as constraints.
    reqs = MUST_MET + [
        ("must_have", "absent", "3+ years of professional experience"),
        ("must_have", "absent", "You can legally work in Germany"),
        ("must_have", "absent", "Fluent in German"),
    ]
    v = decide(_facts(reqs), CandidateRules())
    assert v.verdict == "strong" and v.gaps == []


def test_a_real_skill_that_mentions_remote_work_is_still_graded():
    reqs = [("must_have", "absent", "Clear written communication in a remote, async team")] * 4
    assert decide(_facts(reqs), CandidateRules()).verdict == "weak"


def test_nice_to_haves_never_lower_the_tier():
    reqs = MUST_MET + [("nice_to_have", "absent")] * 5
    v = decide(_facts(reqs), CandidateRules())
    assert v.verdict == "strong" and v.overall_score == 90


def test_mostly_absent_is_weak():
    reqs = [("must_have", "absent")] * 3 + [("must_have", "met")]
    assert decide(_facts(reqs), CandidateRules()).verdict == "weak"


def test_onsite_is_dealbreaker_only_when_remote_only():
    facts = _facts(MUST_MET, work_mode="onsite", location="Munich")
    assert decide(facts, CandidateRules()).verdict == "strong"
    v = decide(facts, CandidateRules(remote_only=True))
    assert v.verdict == "weak" and v.overall_score == 25
    assert "remote only" in v.dealbreakers[0] and "Munich" in v.dealbreakers[0]


def test_role_countries_outside_candidate_rights_are_a_dealbreaker():
    # Regression: the model answered "yes, can work there" for US/Canada-only roles.
    # Code now intersects the role's countries with the candidate's work rights.
    v = decide(
        _facts(MUST_MET, work_countries=["US", "CA"], location="US/Canada"), CandidateRules()
    )
    assert v.verdict == "weak" and "right to work" in v.dealbreakers[0]
    assert (
        decide(_facts(MUST_MET, work_countries=["DE", "US"]), CandidateRules()).verdict == "strong"
    )
    assert decide(_facts(MUST_MET, work_countries=["EU"]), CandidateRules()).verdict == "strong"
    assert decide(_facts(MUST_MET, work_countries=["NO"]), CandidateRules()).verdict == "strong"
    assert decide(_facts(MUST_MET, work_countries=["GB"]), CandidateRules()).verdict == "weak"


def test_unstated_countries_or_rights_are_not_dealbreakers():
    assert decide(_facts(MUST_MET, work_countries=[]), CandidateRules()).dealbreakers == []
    facts = _facts(MUST_MET, work_countries=["US"], candidate_work_rights=[])
    assert decide(facts, CandidateRules()).dealbreakers == []


def test_citizenship_dealbreaker():
    facts = _facts(
        MUST_MET, citizenship_or_clearance="French citizenship", citizenship_or_clearance_ok="no"
    )
    assert decide(facts, CandidateRules()).dealbreakers == ["Requires French citizenship"]


def test_unknown_facts_are_never_dealbreakers():
    facts = _facts(
        MUST_MET,
        work_mode="unknown",
        candidate_years_experience=None,
        min_years_experience=10,
    )
    assert decide(facts, CandidateRules(remote_only=True)).dealbreakers == []


def test_unknown_work_mode_falls_back_to_job_remote_flag_when_remote_only():
    facts = _facts(MUST_MET, work_mode="unknown", location="Paris")
    rules = CandidateRules(remote_only=True)
    assert decide(facts, rules, job_is_remote=None).dealbreakers == []
    assert decide(facts, rules, job_is_remote=True).dealbreakers == []
    v = decide(facts, rules, job_is_remote=False)
    assert v.verdict == "weak" and "No remote option" in v.dealbreakers[0]
    assert decide(facts, CandidateRules(), job_is_remote=False).dealbreakers == []


def test_required_language_uses_preferences_over_cv():
    facts = _facts(MUST_MET, required_languages=["ko"], candidate_languages=["en"])
    assert decide(facts, CandidateRules()).verdict == "weak"
    assert decide(facts, CandidateRules(known_languages=["en", "ko"])).verdict == "strong"


def test_experience_gap_up_to_two_years_is_fine():
    assert decide(_facts(MUST_MET, min_years_experience=3), CandidateRules()).verdict == "strong"
    v = decide(_facts(MUST_MET, min_years_experience=4), CandidateRules())
    assert v.verdict == "weak" and "4+ years" in v.dealbreakers[0]


def test_experience_uses_preference_years_and_gap():
    facts = _facts(MUST_MET, min_years_experience=5, candidate_years_experience=1)
    assert decide(facts, CandidateRules(years_experience=3)).verdict == "strong"
    assert decide(facts, CandidateRules(years_experience=3, max_experience_gap=1)).verdict == "weak"


def test_senior_role_is_dealbreaker_for_junior_candidate():
    assert decide(_facts(MUST_MET, seniority="senior"), CandidateRules()).verdict == "weak"
    facts = _facts(MUST_MET, seniority="senior", candidate_years_experience=6)
    assert decide(facts, CandidateRules()).verdict == "strong"


def test_matched_and_gaps_are_derived_for_letters():
    facts = JudgeFacts.model_validate(
        {
            "requirements": [
                {
                    "requirement": "React",
                    "importance": "must_have",
                    "cv_evidence": "Built React apps",
                    "status": "met",
                    "core": True,
                },
                {
                    "requirement": "Kubernetes",
                    "importance": "must_have",
                    "cv_evidence": "",
                    "status": "absent",
                    "core": True,
                },
            ],
            "constraints": _facts().constraints.model_dump(),
            "summary": "ok",
        }
    )
    v = decide(facts, CandidateRules())
    assert [m.requirement for m in v.matched_requirements] == ["React"]
    assert v.gaps == ["Kubernetes"]


def test_rules_from_preferences_prefer_active_filters():
    prefs = SimpleNamespace(
        remote_only=False,
        known_languages=["en", "uk"],
        years_experience=1,
        max_experience_gap=4,
        last_shortlist_query={"is_remote": True, "max_experience_gap": 2},
    )
    rules = rules_from_preferences(prefs)
    assert rules.remote_only is True and rules.max_experience_gap == 2
    assert rules.known_languages == ["en", "uk"] and rules.years_experience == 1
