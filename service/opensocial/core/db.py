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

import uuid
from datetime import timedelta, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    create_engine,
    func,
    select,
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


class GeneratedPost(Base):
    """A draft post produced by Phase 3 generation.

    ``content_item_id`` is NULL for **independent** posts (e.g. the daily Take)
    that have no source content behind them. ``priority_score`` is carried over
    from the candidate queue so the Phase 4 publisher can pick the best-scoring
    eligible draft at slot time. ``post_attempts`` / ``post_error`` back the
    publish retry state machine.
    """

    __tablename__ = "generated_posts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    content_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("content_items.id")
    )
    niche_slug: Mapped[str] = mapped_column(String, nullable=False)
    post_type: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    media_path: Mapped[str | None] = mapped_column(Text)
    media_url: Mapped[str | None] = mapped_column(Text)
    media_attribution: Mapped[str | None] = mapped_column(Text)
    ai_text_provider: Mapped[str] = mapped_column(String, nullable=False)
    ai_image_provider: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    priority_score: Mapped[float | None] = mapped_column(Float)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime)
    post_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    post_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class PlatformAccount(Base):
    """A posting target (an X account today). Credentials are Fernet-encrypted."""

    __tablename__ = "platform_accounts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    platform: Mapped[str] = mapped_column(String, nullable=False, default="x")
    account_label: Mapped[str] = mapped_column(String, nullable=False)
    credentials_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    daily_post_cap: Mapped[int | None] = mapped_column(Integer)


class PostHistory(Base):
    """One publish attempt's outcome, with its cost estimate."""

    __tablename__ = "post_history"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    generated_post_id: Mapped[str] = mapped_column(
        ForeignKey("generated_posts.id"), nullable=False
    )
    platform: Mapped[str] = mapped_column(String, nullable=False, default="x")
    platform_account_id: Mapped[str | None] = mapped_column(String)
    platform_post_id: Mapped[str | None] = mapped_column(String)
    platform_post_url: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, nullable=False)  # success | failed
    error_message: Mapped[str | None] = mapped_column(Text)
    attempted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    included_source_link: Mapped[bool] = mapped_column(Boolean, nullable=False)
    cost_estimate: Mapped[float] = mapped_column(Float, nullable=False)


class Command(Base):
    """Dashboard→service bridge: the UI drops a row, the service polls + runs it."""

    __tablename__ = "commands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    result: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class Log(Base):
    """Console output mirrored to the DB so the dashboard can show service logs."""

    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    level: Mapped[str] = mapped_column(String, nullable=False)  # info | warn | error
    message: Mapped[str] = mapped_column(Text, nullable=False)
    logged_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class AppSetting(Base):
    """Key/value runtime settings the dashboard can change without a restart.

    Known keys: ``dry_run`` ("true"/"false"), ``app_mode`` ("manual"/"auto"),
    and ``secret:<ENV_NAME>`` for Fernet-encrypted API keys saved from the
    dashboard (base64 text of the encrypted blob).
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


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


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def insert_generated_post(
    session: Session,
    *,
    niche_slug: str,
    post_type: str,
    text: str,
    ai_text_provider: str,
    content_item_id: str | None = None,
    media_path: str | None = None,
    media_url: str | None = None,
    media_attribution: str | None = None,
    ai_image_provider: str | None = None,
    priority_score: float | None = None,
    status: str = "draft",
) -> GeneratedPost:
    """Persist one draft post and return the ORM row (already flushed)."""
    now = _utcnow()
    post = GeneratedPost(
        id=uuid.uuid4().hex,
        content_item_id=content_item_id,
        niche_slug=niche_slug,
        post_type=post_type,
        text=text,
        media_path=media_path,
        media_url=media_url,
        media_attribution=media_attribution,
        ai_text_provider=ai_text_provider,
        ai_image_provider=ai_image_provider,
        status=status,
        priority_score=priority_score,
        post_attempts=0,
        created_at=now,
        updated_at=now,
    )
    session.add(post)
    session.flush()
    return post


def content_ids_with_posts(session: Session, niche_slug: str) -> set[str]:
    """Content item ids that already have a draft for this niche.

    Lets generation skip candidates it has already turned into a post.
    """
    rows = session.execute(
        select(GeneratedPost.content_item_id).where(
            GeneratedPost.niche_slug == niche_slug,
            GeneratedPost.content_item_id.is_not(None),
        )
    ).all()
    return {r[0] for r in rows}


# ---------------------------------------------------------------------------
# Phase 4 helpers — publish history, logs, command queue
# ---------------------------------------------------------------------------


def _day_bounds(day: datetime | None) -> tuple[datetime, datetime]:
    ref = (day or _utcnow()).astimezone(timezone.utc)
    start = ref.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def record_post_history(
    session: Session,
    *,
    generated_post_id: str,
    status: str,
    included_source_link: bool,
    cost_estimate: float,
    platform: str = "x",
    platform_account_id: str | None = None,
    platform_post_id: str | None = None,
    platform_post_url: str | None = None,
    error_message: str | None = None,
) -> PostHistory:
    row = PostHistory(
        id=uuid.uuid4().hex,
        generated_post_id=generated_post_id,
        platform=platform,
        platform_account_id=platform_account_id,
        platform_post_id=platform_post_id,
        platform_post_url=platform_post_url,
        status=status,
        error_message=error_message,
        attempted_at=_utcnow(),
        included_source_link=included_source_link,
        cost_estimate=cost_estimate,
    )
    session.add(row)
    session.flush()
    return row


def published_today_count(
    session: Session, *, niche_slug: str | None = None, day: datetime | None = None
) -> int:
    """Number of successful publishes today (optionally scoped to a niche).

    Successful publishes are ``post_history`` rows with ``status='success'``;
    the niche filter joins back to ``generated_posts``. Used for the global and
    per-niche daily caps and for catch-up math.
    """
    start, end = _day_bounds(day)
    stmt = (
        select(func.count())
        .select_from(PostHistory)
        .where(
            PostHistory.status == "success",
            PostHistory.attempted_at >= start,
            PostHistory.attempted_at < end,
        )
    )
    if niche_slug is not None:
        stmt = stmt.join(
            GeneratedPost, GeneratedPost.id == PostHistory.generated_post_id
        ).where(GeneratedPost.niche_slug == niche_slug)
    return int(session.execute(stmt).scalar() or 0)


def last_published_at(
    session: Session, niche_slug: str
) -> datetime | None:
    """Timestamp of the niche's most recent successful publish (for min-gap)."""
    return session.execute(
        select(func.max(PostHistory.attempted_at))
        .join(GeneratedPost, GeneratedPost.id == PostHistory.generated_post_id)
        .where(
            GeneratedPost.niche_slug == niche_slug,
            PostHistory.status == "success",
        )
    ).scalar()


def log(session: Session, level: str, message: str) -> None:
    """Mirror a log line to the ``logs`` table for the dashboard."""
    session.add(Log(level=level, message=message, logged_at=_utcnow()))
    session.flush()


def add_platform_account(
    session: Session,
    *,
    account_label: str,
    credentials_encrypted: bytes,
    platform: str = "x",
    daily_post_cap: int | None = None,
) -> PlatformAccount:
    """Store (or update by label) an encrypted platform account."""
    existing = session.execute(
        select(PlatformAccount).where(
            PlatformAccount.platform == platform,
            PlatformAccount.account_label == account_label,
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.credentials_encrypted = credentials_encrypted
        existing.daily_post_cap = daily_post_cap
        session.commit()
        return existing
    acct = PlatformAccount(
        id=uuid.uuid4().hex,
        platform=platform,
        account_label=account_label,
        credentials_encrypted=credentials_encrypted,
        daily_post_cap=daily_post_cap,
    )
    session.add(acct)
    session.commit()
    return acct


def list_platform_accounts(
    session: Session, *, platform: str | None = None
) -> list[PlatformAccount]:
    stmt = select(PlatformAccount)
    if platform is not None:
        stmt = stmt.where(PlatformAccount.platform == platform)
    return list(session.execute(stmt).scalars())


def default_platform_account(
    session: Session, *, platform: str = "x"
) -> PlatformAccount | None:
    """The account the publisher uses when none is specified (first by label)."""
    return session.execute(
        select(PlatformAccount)
        .where(PlatformAccount.platform == platform)
        .order_by(PlatformAccount.account_label)
    ).scalars().first()


def get_app_setting(session: Session, key: str) -> str | None:
    row = session.get(AppSetting, key)
    return row.value if row is not None else None


def set_app_setting(session: Session, key: str, value: str) -> None:
    row = session.get(AppSetting, key)
    if row is None:
        session.add(AppSetting(key=key, value=value, updated_at=_utcnow()))
    else:
        row.value = value
        row.updated_at = _utcnow()
    session.commit()


def upsert_source_status(
    session: Session,
    source_name: str,
    *,
    status: str | None = None,
    enabled: bool | None = None,
    extra_config: dict | None = None,
) -> SourceConfig:
    """Record a source's global toggle, last fetch outcome, or stored config."""
    row = session.get(SourceConfig, source_name)
    if row is None:
        row = SourceConfig(source_name=source_name, enabled_globally=True)
        session.add(row)
    if status is not None:
        row.last_fetch_at = _utcnow()
        row.last_fetch_status = status
    if enabled is not None:
        row.enabled_globally = enabled
    if extra_config is not None:
        merged = dict(row.extra_config or {})
        merged.update(extra_config)
        row.extra_config = merged
    session.commit()
    return row


def source_statuses(session: Session) -> dict[str, SourceConfig]:
    rows = session.execute(select(SourceConfig)).scalars()
    return {r.source_name: r for r in rows}


def reset_database(session: Session, *, clear_credentials: bool = False) -> dict[str, int]:
    """Wipe runtime data (content, drafts, history, logs, fetch status).

    Niche config files on disk are never touched. ``clear_credentials`` also
    removes encrypted secrets and platform accounts.
    Returns a per-table count of deleted rows.
    """
    # Order matters: delete children before parents to respect FKs.
    tables = [
        ContentItemNiche,
        PostHistory,
        GeneratedPost,
        ContentItemRow,
        Command,
        Log,
        SourceConfig,
    ]
    if clear_credentials:
        tables += [PlatformAccount]

    deleted: dict[str, int] = {}
    for model in tables:
        count = session.execute(select(func.count()).select_from(model)).scalar() or 0
        session.query(model).delete()
        deleted[model.__tablename__] = int(count)

    # Selected niches are runtime state (stored in app_settings) — clear them so
    # a reset returns to the fresh-DB baseline of nothing selected / enabled.
    followed = session.get(AppSetting, "followed_niches")
    if followed is not None:
        session.delete(followed)
        deleted["followed_niches"] = 1

    if clear_credentials:
        secrets = list(
            session.execute(
                select(AppSetting).where(AppSetting.key.like("secret:%"))
            ).scalars()
        )
        for row in secrets:
            session.delete(row)
        deleted["app_settings_secrets"] = len(secrets)

    session.commit()
    return deleted


def enqueue_command(
    session: Session, type: str, payload: dict | None = None
) -> Command:
    cmd = Command(
        type=type, payload=payload, status="pending", created_at=_utcnow()
    )
    session.add(cmd)
    session.commit()
    return cmd


def claim_pending_commands(session: Session) -> list[Command]:
    """Atomically move pending commands to ``running`` and return them."""
    cmds = list(
        session.execute(
            select(Command).where(Command.status == "pending").order_by(Command.id)
        ).scalars()
    )
    for cmd in cmds:
        cmd.status = "running"
    session.commit()
    return cmds


def finish_command(
    session: Session, cmd: Command, *, status: str, result: dict | None = None
) -> None:
    cmd.status = status
    cmd.result = result
    cmd.finished_at = _utcnow()
    session.commit()
