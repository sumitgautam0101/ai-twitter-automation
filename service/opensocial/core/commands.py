"""Dashboard→service command bridge.

The dashboard (via the HTTP API) drops a row in ``commands`` and the service
worker polls, executes it with its already-loaded modules, and records the
outcome. This module is that executor.

Supported command types:
* ``fetch_sources``    — payload ``{"niche": slug?, "source": name?}``
                         → fetch + store + re-filter content
* ``generate_posts``   — payload ``{"niche": slug?, "limit": n?}`` → make drafts
* ``run_slots``        — payload ``{"niche": slug?}`` → publish posts due now
* ``post_now``         — payload ``{"generated_post_id": id}`` → publish one draft
* ``regenerate_post``  — payload ``{"generated_post_id": id}`` → re-run AI for one draft
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from opensocial.core.config import load_all_niches, load_niche
from opensocial.core.db import (
    Command,
    GeneratedPost,
    claim_pending_commands,
    finish_command,
    log,
    source_statuses,
    upsert_source_status,
)
from opensocial.core.engine import load_credentials, publish_post, run_due_slots
from opensocial.core.filtering import filter_niche
from opensocial.core.generate import generate_for_niche, generate_independent
from opensocial.core.settings import Settings


def _niches(config_dir: str, slug: str | None):
    if slug:
        path = Path(config_dir) / f"{slug}.json"
        return [load_niche(path)] if path.exists() else []
    return load_all_niches(config_dir)


def _followed_niches(session_factory, config_dir: str, slug: str | None):
    """Resolve the niche list for a no-slug command: the followed niches only.

    An explicit ``slug`` still targets that single niche (so the dashboard can
    act on any niche on demand). With no slug, only the niches the user follows
    are processed — unfollowed niches stay dormant (no source calls, no drafts).
    """
    if slug:
        return _niches(config_dir, slug)
    from opensocial.core.settings import get_followed_niches

    with session_factory() as s:
        followed = set(get_followed_niches(s))
    return [n for n in load_all_niches(config_dir) if n.slug in followed]


def _stored_api_key(source_row, secret_key: str | None) -> str | None:
    """Decrypt a dashboard-saved API key from ``source_configs.extra_config``."""
    extra = (source_row.extra_config or {}) if source_row is not None else {}
    blob = extra.get("api_key_enc")
    if not blob:
        return None
    from opensocial.core.secrets import SecretsError, decrypt_credentials

    try:
        return decrypt_credentials(blob.encode("ascii"), secret_key).get("api_key")
    except SecretsError:
        return None


def _do_fetch(
    session_factory,
    config_dir: str,
    slug: str | None,
    settings: Settings,
    only_source: str | None = None,
) -> dict:
    from opensocial.core.db import store_items
    from opensocial.sources import get_source

    with session_factory() as s:
        statuses = {
            name: (row.enabled_globally, _stored_api_key(row, settings.secret_key))
            for name, row in source_statuses(s).items()
        }

    niche_list = _followed_niches(session_factory, config_dir, slug)

    async def run() -> dict:
        result: dict[str, int] = {}
        touched: set[str] = set()
        for niche in niche_list:
            if not niche.enabled:
                continue
            for name, scfg in niche.sources.items():
                if only_source and name != only_source:
                    continue
                if scfg.get("enabled") is False:
                    continue
                # No status row → the source is disabled (fresh-DB default).
                enabled_globally, stored_key = statuses.get(name, (False, None))
                if not enabled_globally:
                    continue
                if stored_key and not scfg.get("api_key"):
                    scfg = {**scfg, "api_key": stored_key}
                try:
                    items = await get_source(name)(scfg).fetch()
                except Exception as exc:  # one bad source shouldn't sink the run
                    with session_factory() as s:
                        upsert_source_status(s, name, status=f"error: {exc}")
                        log(s, "error", f"fetch {name} failed: {exc}")
                        s.commit()
                    continue
                with session_factory() as s:
                    new, total = store_items(s, items, niche.slug)
                    upsert_source_status(s, name, status="ok")
                result[f"{niche.slug}:{name}"] = new
                touched.add(niche.slug)

        # Re-filter every niche that got new content so candidates are fresh.
        for niche in niche_list:
            if niche.slug not in touched:
                continue
            with session_factory() as s:
                counts = filter_niche(s, niche.slug, niche.raw)
                log(
                    s, "info",
                    f"[{niche.slug}] filter: {counts['candidate']} candidates, "
                    f"{counts['filtered']} filtered, {counts['duplicate']} duplicates",
                )
                s.commit()
        return result

    return asyncio.run(run())


def _do_generate(session_factory, config_dir: str, slug: str | None, limit: int) -> dict:
    from opensocial.core.settings import load_ai_config

    result: dict[str, int] = {}
    for niche in _followed_niches(session_factory, config_dir, slug):
        if not niche.enabled:
            continue
        with session_factory() as s:
            config = {**niche.raw, "ai": load_ai_config(s)}
            drafts = generate_for_niche(s, niche.slug, config, limit=limit)
            drafts += generate_independent(s, niche.slug, config)
        result[niche.slug] = len(drafts)
    return result


def _do_run_slots(
    session_factory, config_dir: str, slug: str | None, settings: Settings
) -> dict:
    from dataclasses import replace

    # An explicit "run due now" from the dashboard dispatches even in manual
    # mode — the app_mode guard exists to stop *unattended* publishing only.
    settings = replace(settings, app_mode="auto")
    published = 0
    for niche in _followed_niches(session_factory, config_dir, slug):
        if not niche.enabled:
            continue
        with session_factory() as s:
            creds = load_credentials(s, settings)
            outcomes = run_due_slots(
                s, niche.slug, niche.raw, settings, credentials=creds
            )
        published += sum(1 for o in outcomes if o.ok)
    return {"published": published}


def _do_post_now(session_factory, config_dir: str, post_id: str, settings: Settings) -> dict:
    with session_factory() as s:
        post = s.get(GeneratedPost, post_id)
        if post is None:
            return {"error": "post not found"}
        niches = _niches(config_dir, post.niche_slug)
        config = niches[0].raw if niches else {}
        creds = load_credentials(s, settings)
        outcome = publish_post(s, post, config, settings, credentials=creds)
    return {"ok": outcome.ok, "dry_run": outcome.dry_run, "error": outcome.error}


def _do_regenerate(session_factory, config_dir: str, post_id: str) -> dict:
    from opensocial.core.approval import regenerate
    from opensocial.core.settings import load_ai_config

    with session_factory() as s:
        post = s.get(GeneratedPost, post_id)
        if post is None:
            return {"error": "post not found"}
        niches = _niches(config_dir, post.niche_slug)
        config = {**(niches[0].raw if niches else {}), "ai": load_ai_config(s)}
        regenerate(s, post, config)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Autopilot: timed fetch→generate that keeps the draft queue topped up.
# ---------------------------------------------------------------------------


def _autopilot_window(session_factory, config_dir: str, now):
    """Today's global posting window across followed niches: (first, last).

    Returns the earliest first slot and the latest last slot (both tz-aware,
    server-local) among the followed+enabled niches that are on the schedule.
    ``(None, None)`` when nothing is scheduled today.
    """
    from opensocial.core.scheduler import ScheduleConfig, resolve_slots

    first = last = None
    for niche in _followed_niches(session_factory, config_dir, None):
        if not niche.enabled:
            continue
        slots = resolve_slots(ScheduleConfig.from_niche(niche.raw), niche.slug, now)
        if not slots:
            continue
        if first is None or slots[0] < first:
            first = slots[0]
        if last is None or slots[-1] > last:
            last = slots[-1]
    return first, last


def autopilot_refresh(
    session_factory: sessionmaker,
    *,
    config_dir: str = "config/niches",
    settings: Settings,
    now=None,
) -> dict | None:
    """Top up the draft queue with fresh data, on a timed cadence.

    In auto mode the worker calls this every tick. It actually does work only
    when *now* falls inside the day's posting window — from ``X`` minutes before
    the first slot (a warm-up so content is ready) up to ``X`` minutes before
    the last slot — and at most once per ``X`` minutes. ``X`` is
    ``settings.autopilot_fetch_minutes``; 0 disables it. When it fires it runs
    fetch → filter → generate for the followed niches and stamps the run time so
    the cadence is throttled across ticks. Returns a summary dict when it ran,
    else ``None``.
    """
    from datetime import datetime, timedelta, timezone

    from opensocial.core.db import get_app_setting, set_app_setting

    if settings.app_mode != "auto":
        return None
    x_min = int(settings.autopilot_fetch_minutes)
    if x_min <= 0:
        return None

    now = now or datetime.now(timezone.utc)
    first, last = _autopilot_window(session_factory, config_dir, now)
    if first is None:
        return None

    x = timedelta(minutes=x_min)
    window_start = first - x  # warm-up before the first post
    window_end = last - x  # last fetch precedes the last post by X
    now_local = now.astimezone()
    if now_local < window_start or now_local > window_end:
        return None

    # Throttle: at most one refresh per X minutes across ticks.
    with session_factory() as s:
        last_raw = get_app_setting(s, "autopilot_last_refresh")
    if last_raw:
        try:
            last_ts = datetime.fromisoformat(last_raw)
            if now - last_ts < x:
                return None
        except ValueError:
            pass

    fetched = _do_fetch(session_factory, config_dir, None, settings)
    generated = _do_generate(session_factory, config_dir, None, limit=5)
    with session_factory() as s:
        set_app_setting(s, "autopilot_last_refresh", now.isoformat())
        new_items = sum(fetched.values())
        new_drafts = sum(generated.values())
        log(
            s, "info",
            f"autopilot refresh: {new_items} new item(s), {new_drafts} draft(s)",
        )
        s.commit()
    return {"fetched": fetched, "generated": generated}


def process_commands(
    session_factory: sessionmaker,
    *,
    config_dir: str = "config/niches",
    settings: Settings | None = None,
) -> int:
    """Claim and execute all pending commands. Returns how many were run."""
    if settings is None:
        from opensocial.core.settings import resolve_settings

        with session_factory() as s:
            settings = resolve_settings(s)
    with session_factory() as s:
        claimed = claim_pending_commands(s)
        # Detach the lightweight fields we need so the session can close.
        jobs = [(c.id, c.type, dict(c.payload or {})) for c in claimed]

    for cmd_id, ctype, payload in jobs:
        try:
            if ctype == "fetch_sources":
                result = _do_fetch(
                    session_factory, config_dir, payload.get("niche"),
                    settings, payload.get("source"),
                )
            elif ctype == "generate_posts":
                result = _do_generate(
                    session_factory, config_dir, payload.get("niche"),
                    int(payload.get("limit", 5)),
                )
            elif ctype == "run_slots":
                result = _do_run_slots(
                    session_factory, config_dir, payload.get("niche"), settings
                )
            elif ctype == "post_now":
                result = _do_post_now(
                    session_factory, config_dir,
                    payload.get("generated_post_id"), settings,
                )
            elif ctype == "regenerate_post":
                result = _do_regenerate(
                    session_factory, config_dir, payload.get("generated_post_id")
                )
            else:
                result = {"error": f"unknown command type {ctype!r}"}
            status = "failed" if result.get("error") else "done"
        except Exception as exc:  # never let one command kill the worker
            result, status = {"error": str(exc)}, "failed"

        with session_factory() as s:
            cmd = s.get(Command, cmd_id)
            if cmd is not None:
                finish_command(s, cmd, status=status, result=result)
            # Mirror the outcome into the logs table so the dashboard Logs tab
            # shows what the worker did — successes and, crucially, failures
            # (e.g. an LLM BadRequest) that previously only surfaced as a
            # transient toast on the command result.
            label = _describe_command(ctype, payload)
            if status == "failed":
                log(s, "error", f"{label} failed: {result.get('error')}")
            else:
                log(s, "info", f"{label} done: {_summarize_result(result)}")
            s.commit()
    return len(jobs)


def _describe_command(ctype: str, payload: dict) -> str:
    """Short human label for a command, including its niche/source target."""
    target = payload.get("niche") or payload.get("source")
    suffix = f" [{target}]" if target else ""
    return f"{ctype}{suffix}"


def _summarize_result(result: dict) -> str:
    """Compact one-line summary of a command result dict for the logs."""
    if not result:
        return "no changes"
    parts = [f"{k}={v}" for k, v in result.items()]
    return ", ".join(parts)
