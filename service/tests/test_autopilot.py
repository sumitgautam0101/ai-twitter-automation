"""Autopilot timed-refresh gating (workspace model).

In auto mode the worker tops up the draft queue on a cadence, but only inside
the day's posting window: from ``X`` minutes before the first slot (a warm-up)
to ``X`` minutes before the last slot, at most once per ``X`` minutes. Fetch is
a single shared pass; generation runs per auto-mode workspace. These tests pin
the schedule + throttle decisions with fetch/generate stubbed out.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from opensocial.core import commands
from opensocial.core.commands import (
    _window_for_niches,
    _workspace_niches,
    autopilot_refresh,
)
from opensocial.core.db import (
    Base,
    add_platform_account,
    get_app_setting,
    make_engine,
    set_app_setting,
)
from opensocial.core.scheduler import ScheduleConfig, resolve_slots
from opensocial.core.settings import set_followed_niches, set_scoped_setting

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
def workspace(session_factory):
    """A workspace (X account) in auto mode that follows the 'tech' niche."""
    with session_factory() as s:
        acct = add_platform_account(
            s, account_label="ws", credentials_encrypted=b"x"
        )
        wid = acct.id
        set_app_setting(s, "autopilot_fetch_minutes", str(X))  # global cadence
        set_scoped_setting(s, wid, "app_mode", "auto")
        set_followed_niches(s, ["tech"], wid)
    return wid


@pytest.fixture()
def config_dir(tmp_path, workspace):
    d = tmp_path / "niches"
    d.mkdir()
    (d / "tech.json").write_text(
        json.dumps({**NICHE, "account_id": workspace}), encoding="utf-8"
    )
    return str(d)


@pytest.fixture()
def no_real_work(monkeypatch):
    """Stub fetch/generate so only the gating logic runs."""
    monkeypatch.setattr(commands, "_do_fetch", lambda *a, **k: {"tech": 2})
    monkeypatch.setattr(commands, "_do_generate", lambda *a, **k: {"tech": 1})


def _now():
    return datetime.now(timezone.utc)


def _slots(now):
    return resolve_slots(ScheduleConfig.from_niche(NICHE), "tech", now)


# --- window resolution ----------------------------------------------------


def test_window_spans_first_to_last_slot(session_factory, config_dir, workspace):
    now = _now()
    niches = _workspace_niches(session_factory, config_dir, workspace, None)
    first, last = _window_for_niches(niches, now)
    slots = _slots(now)
    assert first == slots[0] and last == slots[-1]


def test_no_window_without_followed_niches(session_factory, config_dir, workspace):
    with session_factory() as s:
        set_followed_niches(s, [], workspace)  # unfollow everything
    niches = _workspace_niches(session_factory, config_dir, workspace, None)
    first, last = _window_for_niches(niches, _now())
    assert first is None and last is None


# --- refresh gating -------------------------------------------------------


def test_fires_inside_window(session_factory, config_dir, workspace, no_real_work):
    now = _slots(_now())[0]  # local-aware first slot, inside [first-X, last-X]
    result = autopilot_refresh(session_factory, config_dir=config_dir, now=now)
    assert result == {"fetched": {"tech": 2}, "generated": {"tech": 1}}
    with session_factory() as s:
        assert get_app_setting(s, "autopilot_last_refresh") is not None


def test_throttled_within_cadence(session_factory, config_dir, workspace, no_real_work):
    now = _slots(_now())[0]
    assert autopilot_refresh(session_factory, config_dir=config_dir, now=now)
    later = now + timedelta(minutes=X - 1)
    assert autopilot_refresh(
        session_factory, config_dir=config_dir, now=later
    ) is None


def test_fires_again_after_cadence(session_factory, config_dir, workspace, no_real_work):
    slots = _slots(_now())
    now = slots[0]
    assert autopilot_refresh(session_factory, config_dir=config_dir, now=now)
    later = now + timedelta(minutes=X)
    if later > slots[-1] - timedelta(minutes=X):
        pytest.skip("window too short for a second cadence step today")
    assert autopilot_refresh(
        session_factory, config_dir=config_dir, now=later
    ) is not None


def test_skips_before_warmup(session_factory, config_dir, workspace, no_real_work):
    first = _slots(_now())[0]
    too_early = first - timedelta(minutes=X + 5)  # before the warm-up point
    assert autopilot_refresh(
        session_factory, config_dir=config_dir, now=too_early
    ) is None


def test_skips_after_last_slot_minus_x(session_factory, config_dir, workspace, no_real_work):
    last = _slots(_now())[-1]
    too_late = last - timedelta(minutes=X - 5)  # past last_slot - X
    assert autopilot_refresh(
        session_factory, config_dir=config_dir, now=too_late
    ) is None


def test_disabled_in_manual_mode(session_factory, config_dir, workspace, no_real_work):
    with session_factory() as s:
        set_scoped_setting(s, workspace, "app_mode", "manual")
    now = _slots(_now())[0]
    assert autopilot_refresh(
        session_factory, config_dir=config_dir, now=now
    ) is None


def test_disabled_when_cadence_zero(session_factory, config_dir, workspace, no_real_work):
    with session_factory() as s:
        set_app_setting(s, "autopilot_fetch_minutes", "0")
    now = _slots(_now())[0]
    assert autopilot_refresh(
        session_factory, config_dir=config_dir, now=now
    ) is None
