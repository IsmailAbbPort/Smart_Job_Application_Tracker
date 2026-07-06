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
    is_remote: bool
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
