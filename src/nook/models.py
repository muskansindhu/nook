from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ArticleDraft(BaseModel):
    """Unpersisted, normalized article produced by a source adapter."""

    source_id: str
    canonical_url: str
    title: str
    external_id: str | None = None
    author: str | None = None
    description: str | None = None
    published_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    score: int | None = None
    comment_count: int | None = None
    reading_time_minutes: int | None = None
    content_markdown: str | None = None  # set only if the source supplies a body
    metadata: dict[str, Any] = Field(default_factory=dict)


class FeedOptions(BaseModel):
    limit: int = 30
    kind: str | None = None  # hn: top/new/best/ask/show ; devto: latest/top
    tag: str | None = None


class SourceHealth(BaseModel):
    ok: bool
    status: str  # enabled / needs_auth / temporarily_unavailable / ...
    detail: str = ""


class SourceError(Exception):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status
