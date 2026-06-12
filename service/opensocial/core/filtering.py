"""Phase 2 — filtering, near-duplicate detection, and prioritization.

Each niche applies three cheap filters to the content linked to it:

* **blocklist**  — drop items whose text contains any blocked keyword
* **relevance**  — keep only items matching enough relevance keywords
* **age limit**  — drop items older than ``max_age_days``

Surviving items are then checked for **near-duplicates** against the other
items already accepted for the niche (same story reprinted by several
outlets), and each link in ``content_item_niches`` is marked ``candidate``,
``filtered``, or ``duplicate``.

Finally, candidates are ordered into a queue by a weighted blend of recency,
relevance, and how well their sentiment matches the niche's target — the
ordered hand-off to Phase 3 (post generation).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from opensocial.core.db import ContentItemNiche, ContentItemRow

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-z0-9]+")
# Common words that shouldn't count toward near-duplicate similarity.
_STOPWORDS = frozenset(
    "a an and are as at be by for from has have in is it its of on or that the "
    "to was were will with this these those you your we our they their he she".split()
)


@dataclass
class FilterConfig:
    """Per-niche filtering settings, parsed from the niche's ``filters`` block."""

    blocklist: list[str] = field(default_factory=list)
    relevance_keywords: list[str] = field(default_factory=list)
    relevance_threshold: int = 1  # min keyword hits to be considered relevant
    max_age_days: float | None = None
    dup_threshold: float = 0.8  # Jaccard similarity (0..1) above which = duplicate
    dup_window_days: float = 3.0  # only compare against items this recent (per spec)

    @classmethod
    def from_niche(cls, raw: dict) -> "FilterConfig":
        f = (raw or {}).get("filters") or {}
        return cls(
            blocklist=[w.lower() for w in f.get("blocklist", []) if w],
            relevance_keywords=[w.lower() for w in f.get("relevance_keywords", []) if w],
            relevance_threshold=int(f.get("relevance_threshold", 1)),
            max_age_days=(
                float(f["max_age_days"]) if f.get("max_age_days") is not None else None
            ),
            dup_threshold=float(f.get("dup_threshold", 0.8)),
            dup_window_days=float(f.get("dup_window_days", 3.0)),
        )


@dataclass
class PriorityConfig:
    """Weights for ordering candidates, parsed from the niche's ``prioritization``.

    Engagement was removed from the blend: most sources return no engagement
    metrics (so the signal is usually 0), and where it exists it distorts
    cross-source — an upvoted Reddit item would always outrank a metric-less
    paper in the same niche. Any legacy ``engagement_weight`` key is ignored.
    """

    recency_weight: float = 0.5
    relevance_weight: float = 0.3
    sentiment_weight: float = 0.2
    half_life_hours: float = 24.0  # recency score halves every this many hours
    sentiment_target: float | None = None  # -1..1; None disables sentiment matching

    @classmethod
    def from_niche(cls, raw: dict) -> "PriorityConfig":
        p = (raw or {}).get("prioritization") or {}
        target = p.get("sentiment_target")
        return cls(
            recency_weight=float(p.get("recency_weight", 0.5)),
            relevance_weight=float(p.get("relevance_weight", 0.3)),
            sentiment_weight=float(p.get("sentiment_weight", 0.2)),
            half_life_hours=float(p.get("half_life_hours", 24.0)),
            sentiment_target=float(target) if target is not None else None,
        )


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def _item_text(row: ContentItemRow) -> str:
    """All the text a filter should look at, lower-cased."""
    parts = [row.title, row.summary or "", row.body or "", " ".join(row.tags or [])]
    return " ".join(parts).lower()


def _tokens(text: str) -> set[str]:
    return {t for t in _WORD_RE.findall(text.lower()) if t not in _STOPWORDS}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / len(a | b)


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def _relevance_hits(text: str, keywords: list[str]) -> int:
    return sum(1 for kw in keywords if kw in text)


def _evaluate(row: ContentItemRow, cfg: FilterConfig, now: datetime) -> tuple[str, float]:
    """Return ``(status, relevance_score)`` for blocklist/relevance/age only.

    ``status`` is ``"filtered"`` or ``"candidate"``; near-duplicate detection
    happens afterward against the surviving candidates.
    """
    text = _item_text(row)

    for blocked in cfg.blocklist:
        if blocked in text:
            return "filtered", 0.0

    if cfg.max_age_days is not None:
        published = _as_utc(row.published_at)
        if published is not None:
            age_days = (now - published).total_seconds() / 86400.0
            if age_days > cfg.max_age_days:
                return "filtered", 0.0

    hits = _relevance_hits(text, cfg.relevance_keywords)
    if cfg.relevance_keywords:
        if hits < cfg.relevance_threshold:
            return "filtered", 0.0
        # normalize score against the number of keywords actually configured
        relevance = hits / len(cfg.relevance_keywords)
    else:
        relevance = 1.0  # no relevance keywords configured → everything is relevant

    return "candidate", round(relevance, 4)


def filter_niche(session: Session, niche_slug: str, raw_config: dict) -> dict[str, int]:
    """Apply filters + near-duplicate detection for one niche.

    Updates every ``content_item_niches`` row for the niche, setting
    ``status`` (candidate/filtered/duplicate) and ``relevance_score``.
    Returns a count per status.
    """
    cfg = FilterConfig.from_niche(raw_config)
    now = datetime.now(timezone.utc)

    rows = session.execute(
        select(ContentItemNiche, ContentItemRow)
        .join(ContentItemRow, ContentItemNiche.content_item_id == ContentItemRow.id)
        .where(ContentItemNiche.niche_slug == niche_slug)
        .order_by(ContentItemRow.published_at.asc())  # earliest is the "original"
    ).all()

    counts = {"candidate": 0, "filtered": 0, "duplicate": 0}
    # Accepted candidates kept as (published_at, title_tokens), oldest-first, for
    # near-dup comparison. Bounded to a recent window so the check compares only
    # against "recently seen content" (project.md) instead of all history —
    # which also keeps it from degrading to O(n^2) as the table grows.
    window = timedelta(days=cfg.dup_window_days)
    recent: list[tuple[datetime, set[str]]] = []

    for link, row in rows:
        status, relevance = _evaluate(row, cfg, now)

        if status == "candidate":
            published = _as_utc(row.published_at) or now
            # Rows arrive oldest-first, so anything older than the window vs. the
            # current item will stay out of range for all later items too — drop it.
            cutoff = published - window
            while recent and recent[0][0] < cutoff:
                recent.pop(0)

            tokens = _tokens(row.title)
            is_dup = any(
                _jaccard(tokens, seen) >= cfg.dup_threshold for _, seen in recent
            )
            if is_dup:
                status = "duplicate"
            else:
                recent.append((published, tokens))

        link.status = status
        link.relevance_score = relevance if status == "candidate" else 0.0
        counts[status] += 1

    session.commit()
    return counts


# ---------------------------------------------------------------------------
# Prioritization
# ---------------------------------------------------------------------------


def _recency_score(published: datetime | None, now: datetime, half_life_hours: float) -> float:
    published = _as_utc(published)
    if published is None:
        return 0.0
    age_hours = max(0.0, (now - published).total_seconds() / 3600.0)
    return 0.5 ** (age_hours / half_life_hours)


def _sentiment_score(sentiment: float | None, target: float | None) -> float:
    if target is None:
        return 0.0  # disabled — contributes nothing (weight effectively dropped below)
    value = 0.0 if sentiment is None else sentiment
    return 1.0 - abs(value - target) / 2.0  # sentiment range is -1..1


@dataclass
class RankedCandidate:
    row: ContentItemRow
    relevance_score: float
    priority_score: float


def candidate_queue(
    session: Session, niche_slug: str, raw_config: dict
) -> list[RankedCandidate]:
    """Return the niche's ``candidate`` items ordered best-first.

    Score blends recency, relevance, and sentiment match (per
    :class:`PriorityConfig`). Relevance reuses the keyword-hit score already
    computed during filtering (stored on the niche link). Engagement is
    deliberately not a factor — see :class:`PriorityConfig`.
    """
    cfg = PriorityConfig.from_niche(raw_config)
    now = datetime.now(timezone.utc)

    rows = session.execute(
        select(ContentItemNiche, ContentItemRow)
        .join(ContentItemRow, ContentItemNiche.content_item_id == ContentItemRow.id)
        .where(
            ContentItemNiche.niche_slug == niche_slug,
            ContentItemNiche.status == "candidate",
        )
    ).all()
    if not rows:
        return []

    # If sentiment matching is disabled, redistribute its weight to the others.
    w_rec = cfg.recency_weight
    w_rel = cfg.relevance_weight
    w_sent = 0.0 if cfg.sentiment_target is None else cfg.sentiment_weight
    total_w = w_rec + w_rel + w_sent
    if total_w <= 0:
        w_rec, total_w = 1.0, 1.0

    ranked: list[RankedCandidate] = []
    for link, row in rows:
        recency = _recency_score(row.published_at, now, cfg.half_life_hours)
        relevance = link.relevance_score or 0.0
        sentiment = _sentiment_score(row.sentiment, cfg.sentiment_target)
        priority = (
            w_rec * recency + w_rel * relevance + w_sent * sentiment
        ) / total_w
        ranked.append(
            RankedCandidate(
                row=row,
                relevance_score=relevance,
                priority_score=round(priority, 4),
            )
        )

    ranked.sort(key=lambda c: c.priority_score, reverse=True)
    return ranked
