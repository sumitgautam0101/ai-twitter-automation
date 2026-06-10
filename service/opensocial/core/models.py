"""The normalized content format shared across the whole pipeline.

Every source plugin returns ``ContentItem`` objects; nothing downstream
(filtering, AI generation, publishing) ever needs to know which source an
item came from.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ContentItem(BaseModel):
    """A single piece of source content, normalized to a common shape.

    Field availability varies by source (see project.md). The standard
    fallback for AI input is ``content_for_ai`` below.
    """

    source_name: str
    source_category: str
    title: str
    url: str

    body: str | None = None  # full text/transcript/abstract, when available
    summary: str | None = None
    author: str | None = None

    published_at: datetime
    fetched_at: datetime = Field(default_factory=_utcnow)

    media_urls: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    language: str = "en"
    sentiment: float | None = None  # -1..1; populated only by GDELT today
    engagement: dict | None = None  # shape varies per source
    raw_metadata: dict = Field(default_factory=dict)

    @staticmethod
    def make_id(source_name: str, url: str) -> str:
        """Stable de-duplication id: ``sha256(source_name + url)``."""
        return hashlib.sha256(f"{source_name}{url}".encode("utf-8")).hexdigest()

    @property
    def id(self) -> str:
        return self.make_id(self.source_name, self.url)

    @property
    def content_for_ai(self) -> str:
        """The best available text to feed downstream AI generation."""
        return self.body or self.summary or self.title
