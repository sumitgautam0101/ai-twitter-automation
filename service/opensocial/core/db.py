"""SQLite persistence layer (SQLAlchemy 2.0).

Phase 1 owns the ``content_items`` and ``content_item_niches`` tables and
mirrors the ``niche_profiles`` / ``source_configs`` config tables from the
schema in project.md. Later phases add the remaining tables.

Writes are idempotent: re-fetching the same content does not create
duplicates, satisfying the Phase 1 "de-duplicated across repeat runs"
requirement.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    create_engine,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)
from sqlalchemy.types import JSON

from opensocial.core.models import ContentItem


class Base(DeclarativeBase):
    pass


class ContentItemRow(Base):
    __tablename__ = "content_items"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_name: Mapped[str] = mapped_column(String, nullable=False)
    source_category: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str | None] = mapped_column(String)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    media_urls: Mapped[list] = mapped_column(JSON, default=list)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    language: Mapped[str] = mapped_column(String, default="en")
    sentiment: Mapped[float | None] = mapped_column(Float)
    engagement: Mapped[dict | None] = mapped_column(JSON)
    raw_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ContentItemNiche(Base):
    __tablename__ = "content_item_niches"

    content_item_id: Mapped[str] = mapped_column(
        ForeignKey("content_items.id"), primary_key=True
    )
    niche_slug: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, nullable=False)  # candidate|filtered|duplicate
    relevance_score: Mapped[float | None] = mapped_column(Float)


class NicheProfile(Base):
    __tablename__ = "niche_profiles"

    slug: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    config_yaml: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class SourceConfig(Base):
    __tablename__ = "source_configs"

    source_name: Mapped[str] = mapped_column(String, primary_key=True)
    enabled_globally: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_fetch_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_fetch_status: Mapped[str | None] = mapped_column(String)
    extra_config: Mapped[dict | None] = mapped_column(JSON)


def _json_serializer(obj) -> str:
    # raw_metadata can carry feed/API values that aren't natively JSON-safe
    # (e.g. time.struct_time, datetime); ``default=str`` makes them storable.
    return json.dumps(obj, default=str)


def make_engine(db_path: str | Path):
    """Create an engine and ensure all tables exist."""
    engine = create_engine(
        f"sqlite:///{db_path}", future=True, json_serializer=_json_serializer
    )
    Base.metadata.create_all(engine)
    return engine


def make_session_factory(db_path: str | Path) -> sessionmaker[Session]:
    return sessionmaker(bind=make_engine(db_path), future=True)


def _row_values(item: ContentItem) -> dict:
    data = item.model_dump()
    data["id"] = item.id
    return data


def store_items(
    session: Session, items: list[ContentItem], niche_slug: str
) -> tuple[int, int]:
    """Persist items and link each to ``niche_slug``.

    Returns ``(new_items, total_items)``. Existing ids are left untouched, so
    repeat runs add only genuinely new content. The niche link defaults to
    status ``candidate``; Phase 2 filtering refines that.
    """
    new_count = 0
    for item in items:
        result = session.execute(
            sqlite_insert(ContentItemRow)
            .values(**_row_values(item))
            .on_conflict_do_nothing(index_elements=["id"])
        )
        if result.rowcount:
            new_count += 1

        session.execute(
            sqlite_insert(ContentItemNiche)
            .values(
                content_item_id=item.id,
                niche_slug=niche_slug,
                status="candidate",
            )
            .on_conflict_do_nothing(
                index_elements=["content_item_id", "niche_slug"]
            )
        )

    session.commit()
    return new_count, len(items)
