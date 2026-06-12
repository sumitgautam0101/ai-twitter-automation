"""Autopilot timed-refresh gating.

In auto mode the worker tops up the draft queue on a cadence, but only inside
the day's posting window: from ``X`` minutes before the first slot (a warm-up)
to ``X`` minutes before the last slot, at most once per ``X`` minutes. These
tests pin down that gating without doing real fetch/generate work — the actual
fetch/generate handlers are stubbed so we exercise only the schedule + throttle
decisions.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from opensocial.core import commands
from opensocial.core.commands import _autopilot_window, autopilot_refresh
from opensocial.core.db import Base, get_app_setting, make_engine
from opensocial.core.scheduler import ScheduleConfig, resolve_slots
from opensocial.core.settings import Settings, set_followed_niches

X = 30  # autopilot_fetch_minutes used throughout

NICHE = {
    "slug": "tech",
    "display_name": "Tech",
    "enabled": True,
    "schedule": {"windows": [["09:00", "21:00"]], "posts_per_day": [3, 3]},
    "sources": {},
}


@pytest.fixture()
def session_factory(tmp_path):
    engine = make_engine(tmp_path / "test.db")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


@pytest.fixture()
def config_dir(tmp_path):
    d = tmp_path / "niches"
    d.mkdir()
    (d / "tech.json").write_text(json.dumps(NICHE), encoding="utf-8")
    return str(d)


@pytest.fixture()
def followed(session_factory):
    with session_factory() as s:
        set_followed_niches(s, ["tech"])
    return ["tech"]


@pytest.fixture()
def no_real_work(monkeypatch):
    """Stub fetch/generate so only the gating logic runs."""
    monkeypatch.setattr(commands, "_do_fetch", lambda *a, **k: {"tech": 2})
    monkeypatch.setattr(commands, "_do_generate", lambda *a, **k: {"tech": 1})


def _settings(**over) -> Settings:
    base = dict(dry_run=True, app_mode="auto", global_daily_cap=25,
                max_post_attempts=3, secret_key=None, autopilot_fetch_minutes=X)
    base.update(over)
    return Settings(**base)


def _slots(now):
    return resolve_slots(ScheduleConfig.from_niche(NICHE), "tech", now)


# --- window resolution ----------------------------------------------------


def test_window_spans_first_to_last_slot(session_factory, config_dir, followed):
    now = _slots_now()
    first, last = _autopilot_window(session_factory, config_dir, now)
    slots = _slots(now)
    assert first == slots[0] and last == slots[-1]


def test_no_window_without_followed_niches(session_factory, config_dir):
    # Nothing followed → nothing to refresh.
    first, last = _autopilot_window(session_factory, config_dir, _slots_now())
    assert first is None and last is None


# --- refresh gating -------------------------------------------------------


def _slots_now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def test_fires_inside_window(session_factory, config_dir, followed, no_real_work):
    now = _slots(_slots_now())[0]  # local-aware first slot, inside [first-X, last-X]
    result = autopilot_refresh(
        session_factory, config_dir=config_dir, settings=_settings(), now=now
    )
    assert result == {"fetched": {"tech": 2}, "generated": {"tech": 1}}
    with session_factory() as s:
        assert get_app_setting(s, "autopilot_last_refresh") is not None


def test_throttled_within_cadence(session_factory, config_dir, followed, no_real_work):
    now = _slots(_slots_now())[0]
    s_ = _settings()
    assert autopilot_refresh(session_factory, config_dir=config_dir, settings=s_, now=now)
    # A second call a few minutes later (< X) is throttled.
    later = now + timedelta(minutes=X - 1)
    assert autopilot_refresh(
        session_factory, config_dir=config_dir, settings=s_, now=later
    ) is None


def test_fires_again_after_cadence(session_factory, config_dir, followed, no_real_work):
    slots = _slots(_slots_now())
    now = slots[0]
    s_ = _settings()
    assert autopilot_refresh(session_factory, config_dir=config_dir, settings=s_, now=now)
    later = now + timedelta(minutes=X)
    if later > slots[-1] - timedelta(minutes=X):
        pytest.skip("window too short for a second cadence step today")
    assert autopilot_refresh(
        session_factory, config_dir=config_dir, settings=s_, now=later
    ) is not None


def test_skips_before_warmup(session_factory, config_dir, followed, no_real_work):
    first = _slots(_slots_now())[0]
    too_early = first - timedelta(minutes=X + 5)  # before the warm-up point
    assert autopilot_refresh(
        session_factory, config_dir=config_dir, settings=_settings(), now=too_early
    ) is None


def test_skips_after_last_slot_minus_x(session_factory, config_dir, followed, no_real_work):
    last = _slots(_slots_now())[-1]
    too_late = last - timedelta(minutes=X - 5)  # past last_slot - X
    assert autopilot_refresh(
        session_factory, config_dir=config_dir, settings=_settings(), now=too_late
    ) is None


def test_disabled_in_manual_mode(session_factory, config_dir, followed, no_real_work):
    now = _slots(_slots_now())[0]
    assert autopilot_refresh(
        session_factory, config_dir=config_dir,
        settings=_settings(app_mode="manual"), now=now,
    ) is None


def test_disabled_when_cadence_zero(session_factory, config_dir, followed, no_real_work):
    now = _slots(_slots_now())[0]
    assert autopilot_refresh(
        session_factory, config_dir=config_dir,
        settings=_settings(autopilot_fetch_minutes=0), now=now,
    ) is None
