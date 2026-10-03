"""Grade a judge's facts into a verdict, using the user's rules. Pure: no I/O.

The judge model only extracts facts (requirements checked against the CV, and the
posting's eligibility constraints). Deciding how harsh to be is done here, in rules a
person can read and change, because asking the model for a tier made it severe: it
treated every unevidenced line as disqualifying and never rated a good fit "strong".

Rules (fixed before measuring, see evals/README.md):
- Dealbreakers (any one -> weak): none of the role's countries is one the candidate may
  work in; citizenship/clearance not met; a required spoken language the candidate lacks;
  on-site/hybrid when the user wants remote only (or, when the posting's work mode is
  unknown, the job's ingested remote flag is false); more than `max_experience_gap` years
  short; a senior/lead role when the candidate has fewer than SENIOR_MIN_YEARS years.
  Unknown facts are never dealbreakers.
- Score: must-haves carry the score (met 1, partial 0.5, absent 0); nice-to-haves only
  add. A dealbreaker caps the score.
- Tier: strong = no dealbreaker, must-have ratio >= STRONG_RATIO and at most one absent
  must-have. medium = no dealbreaker and ratio >= MEDIUM_RATIO. Otherwise weak.

The must-haves that carry the score are the ones the model marked core, because a ratio
over every listed line made the tier depend on how finely the model split the posting: a
posting whose requirements came back as 21 product areas scored medium where the same
posting split into 8 scored strong. Lines that slipped in as requirements but are nothing
more than a constraint ("3+ years of experience", "can work in Germany") are dropped here
too, since they are graded as constraints. A line that merely mentions one ("12+ years in
ML with proven leadership at scale") is still graded, so the seniority ask still counts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.schemas import (
    Importance,
    JudgeFacts,
    MatchedRequirement,
    MatchTier,
    MatchVerdict,
    RequirementStatus,
    Seniority,
    Tristate,
    WorkMode,
)

# Countries where EU/EEA work rights apply: EU27 + Iceland, Liechtenstein, Norway.
EEA_COUNTRIES = frozenset(
    "AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE "
    "IS LI NO".split()
)

DEFAULT_MAX_EXPERIENCE_GAP = 2
SENIOR_MIN_YEARS = 4
STRONG_RATIO = 0.75
MEDIUM_RATIO = 0.5
DEALBREAKER_SCORE_CAP = 25
# Below this many core must-haves the model did not really pick out a core, so fall back
# to grading every must-have rather than resting the tier on one or two lines.
MIN_CORE = 3

_CREDIT = {RequirementStatus.met: 1.0, RequirementStatus.partial: 0.5, RequirementStatus.absent: 0}

# Spoken languages, listed so that "fluent in German" reads as a language constraint while
# "fluent in Python" stays a skill.
_SPOKEN = (
    "english|german|french|spanish|italian|dutch|portuguese|polish|swedish|danish"
    "|norwegian|finnish|arabic|hebrew|mandarin|chinese|japanese|korean|russian"
    "|ukrainian|czech|slovak|romanian|hungarian|greek|turkish|bulgarian|croatian"
)

# Requirements that are really eligibility constraints. They are graded from
# PostingConstraints, so counting them again as unmet skills double-penalizes the pair.
# Each pattern swallows its own object ("right to work in the EU", not just "right to
# work") so that removing it from a line leaves nothing but filler when the line was
# nothing else, which is what `_is_only_a_constraint` tests for.
_CONSTRAINT_RE = re.compile(
    r"\d+\s*(?:\+|-\s*\d+|to\s*\d+)?\s*years?(?:\s+of)?"
    r"(?:\s+(?:professional|commercial|relevant|industry|hands[- ]on|practical))?"
    r"(?:\s+experience)?"
    r"|(?:several|many|multiple)?\s*years? of (?:[a-z]+ )?experience"
    r"|(?:the\s+)?(?:legal\s+)?right to work(?:\s+in\s+[^.,;]*)?"
    r"|work (?:permit|authoriz\w*|visa)(?:\s+(?:in|for)\s+[^.,;]*)?"
    r"|(?:visa|work permit|immigration|relocation)\s+sponsorship"
    r"|sponsorship\s+(?:is\s+)?(?:not\s+)?(?:available|provided|offered|required)"
    r"|eligib\w+ to work(?:\s+in\s+[^.,;]*)?"
    r"|legally (?:able to )?work(?:\s+in\s+[^.,;]*)?"
    r"|citizenship|security clearance"
    r"|language proficiency|native speaker"
    r"|(?:fluent|fluency|native|business[- ]level|professional)\s+(?:in\s+)?"
    rf"(?:written and spoken\s+)?(?:{_SPOKEN})\b"
    r"|(?:based|located|residing|resident)\s+in\s+[^.,;]*"
    r"|relocat\w*(?:\s+to\s+[^.,;]*)?"
    r"|time ?zone overlap|willing to travel"
    r"|fully remote|work remotely|remote[- ]first|work from (?:home|anywhere)",
    re.IGNORECASE,
)

# Words that carry no skill of their own, so what is left of a line after the constraint
# phrase is removed can be checked for an actual requirement hiding in it.
_FILLER = frozenset(
    "a an and or the of in with at on for to be is are as you your we our this that "
    "least minimum min plus over up can must have has should will would able "
    "not no none available provided offered unfortunately "
    "experience experienced working work professional relevant commercial industry "
    "hands practical proven demonstrated strong solid deep track record "
    "candidate candidates applicant applicants ideally preferably required requirement "
    "role position job team company years year".split()
)

_WORD_RE = re.compile(r"[a-z]+")


def _is_only_a_constraint(text: str) -> bool:
    """True when the line is nothing but an eligibility or tenure constraint.

    A constraint phrase buried in a wider requirement ("proven leadership at scale with
    12+ years in ML", "Go language proficiency") leaves real words behind, so the line is
    still graded as a skill. Dropping those was both losing skills and, worse, hiding the
    seniority asks that should push a senior role down.
    """
    if not _CONSTRAINT_RE.search(text):
        return False
    rest = _CONSTRAINT_RE.sub(" ", text)
    return not [w for w in _WORD_RE.findall(rest.lower()) if w not in _FILLER]


@dataclass(frozen=True)
class CandidateRules:
    """The user's side of the grading: preferences and active filters."""

    remote_only: bool = False
    known_languages: list[str] = field(default_factory=list)
    years_experience: int | None = None
    max_experience_gap: int | None = None


def rules_from_preferences(prefs) -> CandidateRules:
    """Build rules from a SearchPreferences row plus its last shortlist query (the
    filters the user is currently browsing with, which win over the saved defaults)."""
    query = getattr(prefs, "last_shortlist_query", None) or {}
    remote = query.get("is_remote")
    gap = query.get("max_experience_gap")
    return CandidateRules(
        remote_only=bool(prefs.remote_only) or remote is True,
        known_languages=list(prefs.known_languages or []),
        years_experience=prefs.years_experience,
        max_experience_gap=gap if gap is not None else prefs.max_experience_gap,
    )


def verdict_from_facts(
    facts: dict | None, rules: CandidateRules, job_is_remote: bool | None = None
) -> MatchVerdict | None:
    """Grade stored facts JSON; None when absent or unreadable (a pre-facts row)."""
    if not facts:
        return None
    try:
        return decide(JudgeFacts.model_validate(facts), rules, job_is_remote)
    except ValidationError:
        return None


def _countries(codes: list[str]) -> set[str]:
    out: set[str] = set()
    for code in codes:
        code = code.strip().upper()
        out |= EEA_COUNTRIES if code in ("EU", "EEA") else {code}
    return out


def _dealbreakers(
    facts: JudgeFacts, rules: CandidateRules, job_is_remote: bool | None
) -> list[str]:
    c = facts.constraints
    out: list[str] = []
    where = f" ({c.location})" if c.location else ""
    role_countries = _countries(c.work_countries)
    rights = _countries(c.candidate_work_rights)
    if role_countries and rights and not role_countries & rights:
        out.append(f"No right to work where the role requires{where}")
    if c.citizenship_or_clearance and c.citizenship_or_clearance_ok == Tristate.no:
        out.append(f"Requires {c.citizenship_or_clearance}")
    languages = {code.lower() for code in (rules.known_languages or c.candidate_languages)}
    if languages:
        missing = [code for code in c.required_languages if code.lower() not in languages]
        if missing:
            out.append(f"Requires a language you don't list: {', '.join(missing)}")
    if rules.remote_only and c.work_mode in (WorkMode.onsite, WorkMode.hybrid):
        out.append(f"{c.work_mode.value.capitalize()}{where}, and you want remote only")
    elif rules.remote_only and c.work_mode == WorkMode.unknown and job_is_remote is False:
        out.append(f"No remote option stated{where}, and you want remote only")
    years = (
        rules.years_experience
        if rules.years_experience is not None
        else c.candidate_years_experience
    )
    gap_limit = (
        rules.max_experience_gap
        if rules.max_experience_gap is not None
        else DEFAULT_MAX_EXPERIENCE_GAP
    )
    if years is not None and c.min_years_experience is not None:
        if c.min_years_experience - years > gap_limit:
            out.append(f"Asks for {c.min_years_experience}+ years; you have about {years}")
    if years is not None and years < SENIOR_MIN_YEARS:
        if c.seniority in (Seniority.senior, Seniority.lead):
            out.append(f"{c.seniority.value.capitalize()}-level role")
    return out


def decide(
    facts: JudgeFacts, rules: CandidateRules, job_is_remote: bool | None = None
) -> MatchVerdict:
    """Grade one pair's facts under the given rules. job_is_remote is the ingested remote
    flag, used only when the model could not tell the posting's work mode."""
    skills = [r for r in facts.requirements if not _is_only_a_constraint(r.requirement)]
    must = [r for r in skills if r.importance == Importance.must_have]
    nice = [r for r in skills if r.importance == Importance.nice_to_have]
    graded = [r for r in must if r.core]
    if len(graded) < MIN_CORE:
        graded = must
    must_ratio = sum(_CREDIT[r.status] for r in graded) / len(graded) if graded else 1.0
    nice_ratio = sum(_CREDIT[r.status] for r in nice) / len(nice) if nice else 0.0
    absent_must = sum(1 for r in graded if r.status == RequirementStatus.absent)

    dealbreakers = _dealbreakers(facts, rules, job_is_remote)
    score = round(90 * must_ratio + 10 * nice_ratio)
    if dealbreakers:
        score = min(score, DEALBREAKER_SCORE_CAP)
        tier = MatchTier.weak
    elif must_ratio >= STRONG_RATIO and absent_must <= 1:
        tier = MatchTier.strong
    elif must_ratio >= MEDIUM_RATIO:
        tier = MatchTier.medium
    else:
        tier = MatchTier.weak

    return MatchVerdict(
        overall_score=score,
        verdict=tier,
        one_line_verdict=facts.summary,
        dealbreakers=dealbreakers,
        requirements=facts.requirements,
        matched_requirements=[
            MatchedRequirement(requirement=r.requirement, cv_evidence=r.cv_evidence)
            for r in facts.requirements
            if r.status != RequirementStatus.absent and r.cv_evidence
        ],
        gaps=dealbreakers
        + [r.requirement for r in must if r.status == RequirementStatus.absent]
        + [r.requirement for r in nice if r.status == RequirementStatus.absent],
    )
