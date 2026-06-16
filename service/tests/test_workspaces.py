"""Workspace isolation: per-workspace settings, followed niches, AI config,
legacy fallback, and full-workspace deletion."""

from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import sessionmaker

from opensocial.core.db import (
    Base,
    add_platform_account,
    delete_workspace,
    get_platform_account,
    insert_generated_post,
    make_engine,
    record_post_history,
    reset_database,
    set_app_setting,
)
from opensocial.core.settings import (
    get_followed_niches,
    load_ai_config,
    resolve_settings,
    save_ai_config,
    set_followed_niches,
    set_scoped_setting,
)


@pytest.fixture()
def session_factory(tmp_path):
    engine = make_engine(tmp_path / "test.db")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _ws(session, label):
    return add_platform_account(
        session, account_label=label, credentials_encrypted=b"x"
    ).id


def test_settings_are_isolated_per_workspace(session_factory):
    with session_factory() as s:
        a, b = _ws(s, "a"), _ws(s, "b")
        set_scoped_setting(s, a, "dry_run", "false")  # a goes live
        set_scoped_setting(s, a, "app_mode", "auto")
        set_scoped_setting(s, b, "dry_run", "true")   # b stays dry
        set_scoped_setting(s, b, "app_mode", "manual")

        sa, sb = resolve_settings(s, a), resolve_settings(s, b)
        assert sa.dry_run is False and sa.app_mode == "auto"
        assert sb.dry_run is True and sb.app_mode == "manual"


def test_followed_and_ai_are_isolated(session_factory):
    with session_factory() as s:
        a, b = _ws(s, "a"), _ws(s, "b")
        set_followed_niches(s, ["tech", "ai"], a)
        set_followed_niches(s, ["startups"], b)
        assert get_followed_niches(s, a) == ["tech", "ai"]
        assert get_followed_niches(s, b) == ["startups"]

        save_ai_config(s, {"text": {"model": "m-a"}}, a)
        save_ai_config(s, {"text": {"model": "m-b"}}, b)
        assert load_ai_config(s, a)["text"]["model"] == "m-a"
        assert load_ai_config(s, b)["text"]["model"] == "m-b"


def test_legacy_global_settings_are_the_default(session_factory):
    # A pre-workspace install's global keys act as the default a workspace
    # inherits until it overrides them.
    with session_factory() as s:
        wid = _ws(s, "a")
        set_app_setting(s, "dry_run", "false")            # legacy global
        set_followed_niches(s, ["legacy"], None)          # legacy global
        assert resolve_settings(s, wid).dry_run is False
        assert get_followed_niches(s, wid) == ["legacy"]
        # Once the workspace overrides, the namespaced value wins.
        set_scoped_setting(s, wid, "dry_run", "true")
        assert resolve_settings(s, wid).dry_run is True


def test_delete_workspace_removes_only_its_data(session_factory, tmp_path):
    cfg = tmp_path / "niches"
    cfg.mkdir()
    with session_factory() as s:
        a, b = _ws(s, "a"), _ws(s, "b")
        # Shared catalog: niche files are not owned by any workspace.
        (cfg / "na.json").write_text(json.dumps({"slug": "na"}))
        (cfg / "nb.json").write_text(json.dumps({"slug": "nb"}))
        # a draft + history for workspace a, and a followed list for each
        post = insert_generated_post(
            s, niche_slug="na", post_type="news", text="x",
            ai_text_provider="template", platform_account_id=a,
        )
        record_post_history(
            s, generated_post_id=post.id, status="success",
            included_source_link=False, cost_estimate=0.0, platform_account_id=a,
        )
        set_followed_niches(s, ["na", "nb"], a)
        set_followed_niches(s, ["na"], b)
        set_scoped_setting(s, a, "dry_run", "false")
        s.commit()

        deleted = delete_workspace(s, a, config_dir=str(cfg))

    assert deleted["generated_posts"] == 1
    assert deleted["post_history"] == 1
    with session_factory() as s:
        assert get_platform_account(s, a) is None
        assert get_platform_account(s, b) is not None  # other workspace intact
        # a's followed list is gone; b's (which also follows the shared "na") stays
        assert get_followed_niches(s, a) == []
        assert get_followed_niches(s, b) == ["na"]
    # Shared niche files survive a workspace deletion — they belong to no one.
    assert (cfg / "na.json").exists()
    assert (cfg / "nb.json").exists()


def test_reset_clear_credentials_releases_niches_to_pool(session_factory, tmp_path):
    # Clearing credentials wipes all workspaces; niche files survive but must be
    # released (account_id dropped) so they aren't owned by a deleted workspace
    # — otherwise the Niches page hides them from every workspace.
    cfg = tmp_path / "niches"
    cfg.mkdir()
    with session_factory() as s:
        a = _ws(s, "a")
        (cfg / "na.json").write_text(
            json.dumps({"slug": "na", "account_id": a})
        )
        (cfg / "free.json").write_text(json.dumps({"slug": "free"}))
        s.commit()

        deleted = reset_database(s, clear_credentials=True, config_dir=str(cfg))

    assert deleted["niches_released"] == 1
    with session_factory() as s:
        assert get_platform_account(s, a) is None  # workspace gone
    # Both niche files survive; the owned one is now unassigned.
    assert json.loads((cfg / "na.json").read_text()).get("account_id") is None
    assert (cfg / "free.json").exists()


def test_reset_keeps_credentials_leaves_niche_ownership(session_factory, tmp_path):
    # A non-credential reset keeps accounts, so niche ownership is untouched.
    cfg = tmp_path / "niches"
    cfg.mkdir()
    with session_factory() as s:
        a = _ws(s, "a")
        (cfg / "na.json").write_text(
            json.dumps({"slug": "na", "account_id": a})
        )
        s.commit()
        reset_database(s, clear_credentials=False, config_dir=str(cfg))

    with session_factory() as s:
        assert get_platform_account(s, a) is not None
    assert json.loads((cfg / "na.json").read_text()).get("account_id") == a
