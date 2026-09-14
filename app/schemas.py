"""Pydantic response schemas for the API layer."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    source_id: str
    title: str
    company: str
    location: str | None
    city: str | None
    country: str | None
    is_remote: bool
    is_european: bool
    language: str | None = None
    required_languages: list[str] = Field(default_factory=list)
    visa_sponsorship: bool | None = None
    remote_region: str | None = None
    required_utc_offsets: list[int] = Field(default_factory=list)
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    effort_signals: list[str] = Field(default_factory=list)
    min_years_experience: int | None = None
    seniority: str | None = None
    role_family: str | None = None
    url: str
    posted_at: datetime | None
    ingested_at: datetime
    # Pipeline status if this job is being tracked (set by list/shortlist routes).
    application_status: str | None = None


class JobDetail(JobOut):
    description: str


class JobList(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[JobOut]


class TargetCompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company: str
    ats: str
    slug: str
    hq: str | None
    remote_policy: str | None
    active: bool


class TargetCompanyCreate(BaseModel):
    company: str
    ats: str  # greenhouse | lever | ashby
    slug: str
    hq: str | None = None
    remote_policy: str | None = None


class TargetCompanyUpdate(BaseModel):
    active: bool


class CvCreate(BaseModel):
    label: str
    content: str


class CvUpload(BaseModel):
    """A CV uploaded as a file (PDF or text), base64-encoded by the browser."""

    label: str
    filename: str
    content_base64: str


class CvFileReplace(BaseModel):
    """A new file for an existing CV (keeps its label), base64-encoded by the browser."""

    filename: str
    content_base64: str


class CvUpdate(BaseModel):
    """Edit an existing CV's label (point 21)."""

    label: str


class CvOut(BaseModel):
    id: int
    label: str
    embedded: bool
    created_at: datetime
    filename: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None


class CvDetail(CvOut):
    content: str


# --- Auth ---


class RegisterIn(BaseModel):
    name: str
    email: str
    password: str


class LoginIn(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str


class ShortlistItem(JobOut):
    similarity: float  # raw cosine fit, before the recency adjustment
    recency_weight: float = 1.0  # freshness multiplier applied for ordering
    timezone_overlap_hours: int | None = None  # working-hours overlap vs the user
    experience_gap: int | None = None  # years the posting requires beyond the user's


class ShortlistResponse(BaseModel):
    cv_id: int
    count: int
    items: list[ShortlistItem]


class RerankRequest(BaseModel):
    """Batch-judge these jobs (the ones the UI is showing) and re-order by fit."""

    job_ids: list[int]
    cv_id: int | None = None
    refresh: bool = False


# --- Match judge (Phase 3): the LLM rerank verdict over a shortlisted job ---


class MatchTier(StrEnum):
    """Coarse fit label, alongside the numeric score."""

    strong = "strong"
    medium = "medium"
    weak = "weak"


class DimensionScores(BaseModel):
    """0-100 sub-scores. The overall score is not a mechanical average of these;
    it is the judge's holistic call, but these show where the fit comes from."""

    skills: int = Field(ge=0, le=100, description="Technical/skills overlap with the role")
    seniority: int = Field(ge=0, le=100, description="Experience level vs what the role expects")
    domain: int = Field(ge=0, le=100, description="Industry/domain relevance")
    location_remote: int = Field(ge=0, le=100, description="Location / remote-eligibility fit")


class MatchedRequirement(BaseModel):
    """One job requirement the CV satisfies, with the receipt."""

    requirement: str = Field(description="A requirement stated in the job posting")
    cv_evidence: str = Field(description="The line/phrase from the CV that supports it")


class MatchVerdict(BaseModel):
    """The judge's structured, evidence-grounded verdict for one (CV, job) pair.

    Doubles as the tool-use input schema sent to Claude, so scores are always
    parseable and every match cites the CV line that supports it.
    """

    overall_score: int = Field(ge=0, le=100, description="Holistic fit, 0-100")
    verdict: MatchTier
    one_line_verdict: str = Field(description="A single sentence summarizing the fit")
    dimension_scores: DimensionScores
    matched_requirements: list[MatchedRequirement] = Field(
        description="Requirements the CV meets, each with its CV evidence line"
    )
    gaps: list[str] = Field(description="Requirements the CV does not evidence")


class MatchOut(MatchVerdict):
    """A stored/just-computed verdict, plus provenance for the API response."""

    job_id: int
    cv_id: int
    model: str
    created_at: datetime


# --- Cover letter + fabrication guard (Phase 4) ---


class FabricationClaim(BaseModel):
    """One factual claim the letter makes about the candidate."""

    claim: str = Field(description="A factual claim the cover letter makes about the candidate")
    supported: bool = Field(description="Whether the CV supports this claim")
    evidence: str = Field(default="", description="CV evidence if supported, else empty")


class FabricationCheck(BaseModel):
    """Raw auditor output (also the tool-use input schema sent to Claude)."""

    claims: list[FabricationClaim] = Field(description="Every claim the letter makes")
    placeholders: list[str] = Field(
        default_factory=list, description="[NEEDS INPUT: ...] markers left for the user to fill"
    )


class FabricationReport(FabricationCheck):
    """The check plus the derived counts the UI shows."""

    unsupported_count: int
    grounded_ratio: float  # supported claims / total, in [0, 1]


class CoverLetterResult(BaseModel):
    """What the drafter returns: the letter body + its fabrication audit."""

    body: str
    fabrication: FabricationReport


class CoverLetterOut(CoverLetterResult):
    """A stored/just-drafted letter, plus provenance for the API response."""

    job_id: int
    cv_id: int
    model: str
    edited: bool  # true once the user has saved their own edits
    created_at: datetime
    updated_at: datetime


class CoverLetterUpdate(BaseModel):
    """Save the user's edited letter body (human-in-the-loop)."""

    body: str


# --- Application pipeline tracking ---


class ApplicationStatus(StrEnum):
    saved = "saved"
    applied = "applied"
    screening = "screening"
    interview = "interview"
    offer = "offer"
    rejected = "rejected"
    ghosted = "ghosted"
    withdrawn = "withdrawn"


class ApplicationUpsert(BaseModel):
    """Create-or-update a tracked application (keyed by job_id)."""

    job_id: int
    status: ApplicationStatus = ApplicationStatus.saved
    cv_id: int | None = None
    notes: str | None = None


class ManualApplicationCreate(BaseModel):
    """Track a job that is not in the ingested corpus (creates a private job row)."""

    title: str
    company: str
    url: str = ""
    location: str | None = None
    description: str = ""
    is_remote: bool = False
    status: ApplicationStatus = ApplicationStatus.saved


class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    cv_id: int | None
    status: ApplicationStatus
    notes: str
    applied_at: datetime | None
    created_at: datetime
    updated_at: datetime
    job: JobOut


# --- Saved views (filter presets) ---


class SavedViewCreate(BaseModel):
    name: str
    filters: dict


class SavedViewUpdate(BaseModel):
    name: str | None = None
    filters: dict | None = None


class SavedViewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    filters: dict
    created_at: datetime
    updated_at: datetime


class PreferencesOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    remote_only: bool
    require_european: bool
    exclude_countries: list[str]
    exclude_cities: list[str]
    known_languages: list[str]
    max_age_days: int | None
    require_sponsorship: bool
    exclude_remote_regions: list[str]
    user_utc_offset: int | None
    min_timezone_overlap_hours: int | None
    min_salary: int | None
    years_experience: int | None
    max_experience_gap: int | None
    exclude_seniorities: list[str]
    exclude_title_keywords: list[str]
    include_role_families: list[str]
    updated_at: datetime


class PreferencesUpdate(BaseModel):
    remote_only: bool | None = None
    require_european: bool | None = None
    exclude_countries: list[str] | None = None
    exclude_cities: list[str] | None = None
    known_languages: list[str] | None = None
    max_age_days: int | None = None
    require_sponsorship: bool | None = None
    exclude_remote_regions: list[str] | None = None
    user_utc_offset: int | None = None
    min_timezone_overlap_hours: int | None = None
    min_salary: int | None = None
    years_experience: int | None = None
    max_experience_gap: int | None = None
    exclude_seniorities: list[str] | None = None
    exclude_title_keywords: list[str] | None = None
    include_role_families: list[str] | None = None
