"""Tests for selected-niches storage (the niches the user follows)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

from opensocial.core.db import Base, make_engine
from opensocial.core.settings import (
    get_followed_niches,
    set_followed_niches,
)


@pytest.fixture()
def session_factory(tmp_path):
    engine = make_engine(tmp_path / "test.db")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def test_default_is_empty(session_factory):
    with session_factory() as s:
        assert get_followed_niches(s) == []


def test_round_trips(session_factory):
    with session_factory() as s:
        saved = set_followed_niches(s, ["tech", "ai"])
        assert saved == ["tech", "ai"]
        assert get_followed_niches(s) == ["tech", "ai"]


def test_dedupes_preserving_order(session_factory):
    with session_factory() as s:
        saved = set_followed_niches(s, ["tech", "ai", "tech", "crypto"])
        assert saved == ["tech", "ai", "crypto"]


def test_no_cap_on_count(session_factory):
    with session_factory() as s:
        many = ["a", "b", "c", "d", "e", "f", "g"]
        saved = set_followed_niches(s, many)
        assert saved == many  # every selection is kept — no hard cap


def test_ignores_blank_entries(session_factory):
    with session_factory() as s:
        saved = set_followed_niches(s, ["tech", "  ", ""])
        assert saved == ["tech"]
