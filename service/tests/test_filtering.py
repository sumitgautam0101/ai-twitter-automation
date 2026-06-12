"""Phase 2 tests — filtering, near-duplicate detection, and prioritization.

Runs entirely against an in-memory SQLite DB with hand-built content, so no
network or live sources are involved.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from opensocial.core.db import Base, make_engine, store_items
from opensocial.core.filtering import candidate_queue, filter_niche
from opensocial.core.models import ContentItem

NICHE = "tech"


@pytest.fixture()
def session_factory(tmp_path):
    engine = make_engine(tmp_path / "test.db")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _item(title, *, url=None, body="", published=None, engagement=None, sentiment=None):
    now = datetime.now(timezone.utc)
    return ContentItem(
        source_name="hackernews",
        source_category="tech",
        title=title,
        url=url or f"https://example.com/{abs(hash(title))}",
        body=body,
        published_at=published or now,
        engagement=engagement,
        sentiment=sentiment,
    )


def test_blocklist_and_relevance_and_age(session_factory):
    old = datetime.now(timezone.utc) - timedelta(days=30)
    items = [
        _item("New open source AI model released"),        # relevant, fresh -> candidate
        _item("Free crypto giveaway, claim now"),          # blocklisted -> filtered
        _item("My cat is very fluffy today"),              # no relevance kw -> filtered
        _item("AI breakthrough from years ago", published=old),  # too old -> filtered
    ]
    config = {
        "filters": {
            "blocklist": ["giveaway"],
            "relevance_keywords": ["ai", "open source", "model"],
            "relevance_threshold": 1,
            "max_age_days": 7,
        }
    }

    with session_factory() as session:
        store_items(session, items, NICHE)
        counts = filter_niche(session, NICHE, config)

    assert counts == {"candidate": 1, "filtered": 3, "duplicate": 0}


def test_near_duplicate_detection(session_factory):
    items = [
        _item("OpenAI releases new GPT model for developers", url="https://a.com/1"),
        _item("OpenAI releases new GPT model for developers today", url="https://b.com/2"),
        _item("Rust 2.0 ships with async overhaul", url="https://c.com/3"),
    ]
    config = {"filters": {"relevance_keywords": [], "dup_threshold": 0.7}}

    with session_factory() as session:
        store_items(session, items, NICHE)
        counts = filter_niche(session, NICHE, config)

    assert counts["candidate"] == 2
    assert counts["duplicate"] == 1


def test_near_duplicate_respects_recent_window(session_factory):
    now = datetime.now(timezone.utc)
    items = [
        _item("OpenAI releases new GPT model for developers",
              url="https://a.com/1", published=now - timedelta(days=10)),
        # Same story but seen 10 days later — outside the dup window, so it is a
        # fresh candidate, not a duplicate of the stale one.
        _item("OpenAI releases new GPT model for developers",
              url="https://b.com/2", published=now),
    ]
    config = {
        "filters": {
            "relevance_keywords": [],
            "dup_threshold": 0.7,
            "dup_window_days": 3,
        }
    }

    with session_factory() as session:
        store_items(session, items, NICHE)
        counts = filter_niche(session, NICHE, config)

    assert counts["candidate"] == 2
    assert counts["duplicate"] == 0


def test_queue_orders_by_priority(session_factory):
    now = datetime.now(timezone.utc)
    # With equal relevance and no sentiment target, recency decides the order.
    items = [
        _item("Old story", published=now - timedelta(hours=48)),
        _item("Freshest story", published=now - timedelta(minutes=5)),
        _item("Fairly fresh story", published=now - timedelta(minutes=10)),
    ]
    config = {
        "filters": {"relevance_keywords": []},
        "prioritization": {
            "recency_weight": 1.0,
            "sentiment_weight": 0.0,
            "half_life_hours": 24,
        },
    }

    with session_factory() as session:
        store_items(session, items, NICHE)
        filter_niche(session, NICHE, config)
        ranked = candidate_queue(session, NICHE, config)

    assert [c.row.title for c in ranked][0] == "Freshest story"
    assert len(ranked) == 3
    # priority scores are sorted descending
    scores = [c.priority_score for c in ranked]
    assert scores == sorted(scores, reverse=True)


def test_relevance_breaks_ties_in_queue(session_factory):
    now = datetime.now(timezone.utc)
    # Two items published at the same instant with no engagement signal, so
    # recency and engagement are identical — relevance must decide the order.
    items = [
        _item("AI model open source release breakthrough", url="https://a.com/1",
              published=now),
        _item("AI thing", url="https://b.com/2", published=now),
    ]
    config = {
        "filters": {
            "relevance_keywords": ["ai", "model", "open source", "release"],
            "relevance_threshold": 1,
        },
        "prioritization": {
            "recency_weight": 0.4,
            "engagement_weight": 0.0,
            "relevance_weight": 0.6,
            "sentiment_weight": 0.0,
            "half_life_hours": 24,
        },
    }

    with session_factory() as session:
        store_items(session, items, NICHE)
        filter_niche(session, NICHE, config)
        ranked = candidate_queue(session, NICHE, config)

    # The item hitting more relevance keywords ranks first.
    assert ranked[0].row.title == "AI model open source release breakthrough"


def test_sentiment_target_matching(session_factory):
    items = [
        _item("Upbeat tech news", url="https://a.com/1", sentiment=0.8),
        _item("Grim tech news", url="https://b.com/2", sentiment=-0.8),
    ]
    config = {
        "filters": {"relevance_keywords": []},
        "prioritization": {
            "recency_weight": 0.0,
            "engagement_weight": 0.0,
            "sentiment_weight": 1.0,
            "sentiment_target": 1.0,
        },
    }

    with session_factory() as session:
        store_items(session, items, NICHE)
        filter_niche(session, NICHE, config)
        ranked = candidate_queue(session, NICHE, config)

    assert ranked[0].row.title == "Upbeat tech news"
