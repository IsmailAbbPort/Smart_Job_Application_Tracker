"""Pydantic response schemas for the API layer."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
    url: str
    posted_at: datetime | None
    ingested_at: datetime


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


class CvOut(BaseModel):
    id: int
    label: str
    embedded: bool
    created_at: datetime


class CvDetail(CvOut):
    content: str


class ShortlistItem(JobOut):
    similarity: float


class ShortlistResponse(BaseModel):
    cv_id: int
    count: int
    items: list[ShortlistItem]


class PreferencesOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    remote_only: bool
    require_european: bool
    exclude_countries: list[str]
    exclude_cities: list[str]
    updated_at: datetime


class PreferencesUpdate(BaseModel):
    remote_only: bool | None = None
    require_european: bool | None = None
    exclude_countries: list[str] | None = None
    exclude_cities: list[str] | None = None
