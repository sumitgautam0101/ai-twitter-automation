"""Phase 4 publish engine — best-at-slot-time selection + state machine.

When a slot is due the engine picks the **best-scoring eligible queued post at
that moment** (not a pre-assigned one), so fresh high-priority content can jump
the queue. It enforces, in order: the global daily cap, the per-niche slot
count, the minimum gap since the last publish, and per-type daily caps. Each
publish runs through the retry state machine: a failure bumps ``post_attempts``
and records ``post_error``; after ``max_post_attempts`` the draft is ``failed``.

Publishing honors the dry-run fail-safe via the injected publisher — in dry-run
a ``post_history`` row is still recorded (status ``success``, cost as it would
be) so the dashboard reflects what *would* have gone out.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from opensocial.core.db import (
    GeneratedPost,
    default_platform_account,
    last_published_at,
    log,
    published_today_count,
    record_post_history,
)
from opensocial.core.scheduler import ScheduleConfig, due_slot_count, resolve_slots
from opensocial.core.settings import Settings
from opensocial.publish.base import Publisher, estimate_cost, get_publisher

# Statuses a post can be in and still be eligible to publish. With the approval
# queue retired this is just "draft" — published/rejected/failed are terminal.
ELIGIBLE_STATUSES = ("draft",)


@dataclass
class PublishOutcome:
    post_id: str
    post_type: str
    ok: bool
    dry_run: bool
    cost: float
    error: str | None = None


def load_credentials(
    session: Session, settings: Settings, *, platform: str = "x"
) -> dict | None:
    """Decrypt the default platform account's credentials, if one is enrolled.

    Returns ``None`` (so publishing stays dry-run) when no account exists or the
    key is missing/invalid, rather than raising mid-run.
    """
    acct = default_platform_account(session, platform=platform)
    if acct is None:
        return None
    from opensocial.core.secrets import SecretsError, decrypt_credentials

    try:
        return decrypt_credentials(acct.credentials_encrypted, settings.secret_key)
    except SecretsError:
        log(session, "error", "platform credentials present but key missing/invalid")
        session.commit()
        return None


def _include_link(config: dict, post: GeneratedPost) -> bool:
    """Whether to append the source link. Off by default (cost strategy);
    never for independent posts (they have no source)."""
    if post.content_item_id is None:
        return False
    posting = (config or {}).get("posting") or {}
    return bool(posting.get("include_source_link", False))


def select_post(
    session: Session, niche_slug: str, config: dict
) -> GeneratedPost | None:
    """Highest-priority eligible draft for the niche.

    Volume is bounded by the global daily cap and minimum gap in
    :func:`run_due_slots`, not by per-tone caps (which no longer exist).
    """
    return session.execute(
        select(GeneratedPost)
        .where(
            GeneratedPost.niche_slug == niche_slug,
            GeneratedPost.status.in_(ELIGIBLE_STATUSES),
        )
        .order_by(
            GeneratedPost.priority_score.is_(None),  # non-null scores first
            GeneratedPost.priority_score.desc(),
            GeneratedPost.created_at.asc(),
        )
    ).scalars().first()


def publish_post(
    session: Session,
    post: GeneratedPost,
    config: dict,
    settings: Settings,
    *,
    publisher: Publisher | None = None,
    credentials: dict | None = None,
) -> PublishOutcome:
    """Publish one draft through the retry state machine + cost recording."""
    publisher = publisher or get_publisher(settings, credentials=credentials)
    include_link = _include_link(config, post)
    cost = estimate_cost(included_source_link=include_link)

    result = publisher.publish(text=post.text, media_url=post.media_url)
    now = datetime.now(timezone.utc)
    post.updated_at = now

    if result.ok:
        post.status = "published"
        post.scheduled_at = now
        record_post_history(
            session,
            generated_post_id=post.id,
            status="success",
            included_source_link=include_link,
            cost_estimate=cost,
            platform_post_id=result.platform_post_id,
            platform_post_url=result.platform_post_url,
        )
        tag = "DRY-RUN would post" if result.dry_run else "published"
        log(session, "info", f"[{post.niche_slug}] {tag} <{post.post_type}> {post.id}")
        session.commit()
        return PublishOutcome(
            post_id=post.id, post_type=post.post_type, ok=True,
            dry_run=result.dry_run, cost=cost,
        )

    # Failure path — bump attempts, record error, maybe mark failed.
    post.post_attempts += 1
    post.post_error = result.error
    if post.post_attempts >= settings.max_post_attempts:
        post.status = "failed"
    record_post_history(
        session,
        generated_post_id=post.id,
        status="failed",
        included_source_link=include_link,
        cost_estimate=0.0,
        error_message=result.error,
    )
    log(
        session, "error",
        f"[{post.niche_slug}] publish failed ({post.post_attempts}/"
        f"{settings.max_post_attempts}) {post.id}: {result.error}",
    )
    session.commit()
    return PublishOutcome(
        post_id=post.id, post_type=post.post_type, ok=False,
        dry_run=False, cost=0.0, error=result.error,
    )


def run_due_slots(
    session: Session,
    niche_slug: str,
    config: dict,
    settings: Settings,
    *,
    now: datetime | None = None,
    publisher: Publisher | None = None,
    credentials: dict | None = None,
) -> list[PublishOutcome]:
    """Publish the posts due for a niche at ``now`` (with catch-up).

    No-op in ``manual`` app mode. Otherwise: how many slots are due minus how
    many already went out today = the catch-up target, clamped by the global
    daily cap and the minimum gap.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    if settings.app_mode != "auto":
        return []  # manual mode never auto-publishes

    sched = ScheduleConfig.from_niche(config)
    slots = resolve_slots(sched, niche_slug, now)
    due = due_slot_count(slots, now)
    already = published_today_count(session, niche_slug=niche_slug, day=now)
    target = max(0, due - already)
    if target == 0:
        return []

    # Minimum gap since the last successful publish.
    last = last_published_at(session, niche_slug)
    if last is not None:
        last = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
        if now - last < timedelta(minutes=sched.min_gap_minutes):
            return []

    publisher = publisher or get_publisher(settings, credentials=credentials)
    outcomes: list[PublishOutcome] = []
    for _ in range(target):
        # Global cap is a cross-niche safety net checked each iteration.
        if published_today_count(session, day=now) >= settings.global_daily_cap:
            log(session, "warn", "global daily cap reached — holding posts")
            session.commit()
            break
        post = select_post(session, niche_slug, config)
        if post is None:
            break
        outcomes.append(
            publish_post(
                session, post, config, settings, publisher=publisher,
                credentials=credentials,
            )
        )
    return outcomes
