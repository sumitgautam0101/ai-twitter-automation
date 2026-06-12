"""HTTP API for the dashboard (FastAPI).

The dashboard is a browser app, so the "shared SQLite" bridge gets a thin HTTP
layer: reads query the DB directly, slow actions (fetch/generate/publish) go
through the ``commands`` table and are executed by the background worker that
``opensocial serve`` runs alongside this app. Fast state transitions
(approve/reject/edit, toggles, config edits) are applied synchronously.

Secrets saved from the dashboard are Fernet-encrypted into ``app_settings`` as
``secret:<ENV_NAME>`` and injected into the process environment so sources,
and litellm pick them up without a restart.
"""

from __future__ import annotations

import json
import os
import random
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import func, select

from opensocial.core import approval as approval_logic
from opensocial.core.config import load_all_niches
from opensocial.core.db import (
    Command,
    ContentItemNiche,
    ContentItemRow,
    GeneratedPost,
    Log,
    PostHistory,
    add_platform_account,
    enqueue_command,
    get_app_setting,
    list_platform_accounts,
    make_session_factory,
    published_today_count,
    reset_database,
    set_app_setting,
    source_statuses,
    upsert_source_status,
)
from opensocial.core.scheduler import ScheduleConfig, due_slot_count, resolve_slots
from opensocial.core.settings import (
    get_followed_niches,
    load_ai_config,
    resolve_settings,
    save_ai_config,
    set_followed_niches,
)
from opensocial.sources import available_sources, get_source

# ---------------------------------------------------------------------------
# Source metadata for the dashboard
# ---------------------------------------------------------------------------

SOURCE_LABELS = {
    "rss": "RSS",
    "hackernews": "Hacker News",
    "googlenews": "Google News",
    "medium": "Medium",
    "devto": "dev.to",
    "github_releases": "GitHub Releases",
    "arxiv": "arXiv",
    "nasa": "NASA",
    "yfinance": "yfinance",
    "reddit": "Reddit",
    "youtube": "YouTube",
    "producthunt": "Product Hunt",
    "guardian": "The Guardian",
}

# source -> (env var names, "required" | "optional")
SOURCE_KEYS: dict[str, tuple[tuple[str, ...], str]] = {
    "guardian": (("GUARDIAN_API_KEY",), "required"),
    "youtube": (("YOUTUBE_API_KEY",), "required"),
    "producthunt": (("PRODUCTHUNT_TOKEN",), "required"),
    "github_releases": (("GITHUB_TOKEN",), "optional"),
    "nasa": (("NASA_API_KEY",), "optional"),
}

# Sources shown in the dashboard but not yet usable: surfaced with an "upcoming"
# badge and a locked enable toggle. Remove an entry here to make it usable.
UPCOMING_SOURCES: frozenset[str] = frozenset({"youtube"})

# Dynamic sources take a user-supplied origin URL (feed / subreddit / channel)
# that maps into a niche's per-source config list. Everything else is "static":
# a fixed origin that simply runs for whatever niches reference it. ``key`` is
# the niche-config list the parsed origin is appended to; ``label`` drives the
# dashboard's add-origin input; ``defaults`` seed a freshly-created source block.
ORIGIN_SPEC: dict[str, dict] = {
    "reddit": {
        "key": "subreddits",
        "label": "subreddit URL or name",
        "defaults": {"sort": "hot", "limit": 25},
        "max_origins": 10,
    },
    "youtube": {
        "key": "channel_ids",
        "label": "YouTube channel URL (/channel/UC…)",
        "defaults": {"limit": 10, "transcripts": True},
    },
    "rss": {
        "key": "feeds",
        "label": "RSS / Atom feed URL",
        "defaults": {},
    },
}
DYNAMIC_SOURCES = set(ORIGIN_SPEC)

# Per-source ceiling on user-added origins (subreddits / feeds / channels).
# Sources may override via ``ORIGIN_SPEC[name]["max_origins"]``.
MAX_ORIGINS = 20


def _max_origins(name: str) -> int:
    return ORIGIN_SPEC.get(name, {}).get("max_origins", MAX_ORIGINS)


def _parse_reddit_origin(value: str) -> str | None:
    """Extract a subreddit name from a URL, an ``r/name``, or a bare name."""
    s = value.strip().rstrip("/")
    m = re.search(r"reddit\.com/r/([A-Za-z0-9_]+)", s, re.I)
    if m:
        return m.group(1)
    m = re.fullmatch(r"(?:r/)?([A-Za-z0-9_]+)", s)
    return m.group(1) if m else None


def _parse_youtube_origin(value: str) -> str | None:
    """Extract a channel id (``UC…``) when present, else the handle/name as-is.

    Note: ``@handle`` / ``/c/`` / ``/user/`` URLs aren't resolvable to a channel
    id without the Data API, so they're stored verbatim — prefer ``/channel/UC…``
    URLs for reliable fetching.
    """
    s = value.strip().rstrip("/")
    m = re.search(r"/channel/(UC[\w-]+)", s)
    if m:
        return m.group(1)
    m = re.search(r"(UC[\w-]{20,})", s)
    if m:
        return m.group(1)
    m = re.search(r"/(@[\w.-]+)", s) or re.search(r"/(?:c|user)/([\w.-]+)", s)
    if m:
        return m.group(1)
    return s or None


def _parse_rss_origin(value: str) -> str | None:
    """RSS origins are stored verbatim (the feed URL)."""
    s = value.strip()
    return s or None


_ORIGIN_PARSERS = {
    "reddit": _parse_reddit_origin,
    "youtube": _parse_youtube_origin,
    "rss": _parse_rss_origin,
}


def _parse_origin(name: str, value: str) -> str | None:
    parser = _ORIGIN_PARSERS.get(name)
    return parser(value) if parser else None


def _origin_display(name: str, value: str) -> str:
    """A human label for an origin (``r/bitcoin``, a netloc, the channel id)."""
    if name == "reddit":
        return f"r/{value}"
    if name == "rss":
        netloc = urlparse(value).netloc
        return netloc or value
    return value


# Credential groups for the Settings → Credentials tab. X is special-cased
# (stored as an encrypted platform account, not env secrets).
CREDENTIAL_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("OpenAI", ("OPENAI_API_KEY",)),
    ("Anthropic", ("ANTHROPIC_API_KEY",)),
    ("YouTube", ("YOUTUBE_API_KEY",)),
    ("Product Hunt", ("PRODUCTHUNT_TOKEN",)),
    ("The Guardian", ("GUARDIAN_API_KEY",)),
    ("NASA", ("NASA_API_KEY",)),
    ("GitHub", ("GITHUB_TOKEN",)),
    ("Unsplash", ("UNSPLASH_ACCESS_KEY",)),
]

ALLOWED_SECRET_ENVS = {env for _, envs in CREDENTIAL_GROUPS for env in envs}

# AI provider keys surfaced inline on the AI providers card (set/not-set).
AI_KEY_ENVS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")

COMMAND_TYPES = {
    "fetch_sources",
    "generate_posts",
    "run_slots",
    "post_now",
    "regenerate_post",
}

_NICHE_PREFIX = re.compile(r"^\[([a-z0-9_-]+)\]\s*", re.I)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _today_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    ref = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = ref.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def inject_stored_secrets(session_factory) -> int:
    """Decrypt every ``secret:*`` app setting into ``os.environ``.

    Env vars already set by the operator are never overwritten. Returns how
    many were injected.
    """
    from opensocial.core.db import AppSetting
    from opensocial.core.secrets import SecretsError, decrypt_credentials

    injected = 0
    with session_factory() as s:
        settings = resolve_settings(s)
        rows = s.execute(
            select(AppSetting).where(AppSetting.key.like("secret:%"))
        ).scalars()
        for row in rows:
            env_name = row.key.split(":", 1)[1]
            if os.environ.get(env_name):
                continue
            try:
                value = decrypt_credentials(
                    row.value.encode("ascii"), settings.secret_key
                ).get("value")
            except SecretsError:
                continue
            if value:
                os.environ[env_name] = value
                injected += 1
    return injected


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class SettingsPatch(BaseModel):
    dry_run: bool | None = None
    app_mode: str | None = None
    global_daily_cap: int | None = None
    autopilot_fetch_minutes: int | None = None


class ResetIn(BaseModel):
    confirm: bool = False
    clear_credentials: bool = False


class CommandIn(BaseModel):
    type: str
    payload: dict | None = None


class EditIn(BaseModel):
    text: str


class SourcePatch(BaseModel):
    enabled: bool | None = None


class OriginIn(BaseModel):
    niche: str
    url: str | None = None  # POST: the origin URL to parse
    value: str | None = None  # DELETE: the parsed value to remove


class OriginEditIn(BaseModel):
    niche: str  # the origin's current niche
    value: str  # the origin's current parsed value (being edited)
    url: str  # the new origin URL (re-parsed)
    new_niche: str | None = None  # optional: move the origin to another niche


class AiConfigIn(BaseModel):
    text: dict | None = None


class FollowedIn(BaseModel):
    slugs: list[str]


class SecretIn(BaseModel):
    key: str
    value: str


class XAccountIn(BaseModel):
    label: str = "default"
    api_key: str
    api_secret: str
    access_token: str
    access_token_secret: str
    daily_post_cap: int | None = None


class SchedulePut(BaseModel):
    windows: list[list[str]]
    posts_per_day: list[int]
    min_gap_minutes: int


class RandomizeIn(BaseModel):
    window: list[str]  # ["HH:MM", "HH:MM"] — posting time range for the day
    total_posts: int  # total posts/day, split randomly across scheduled niches
    min_gap_minutes: int | None = None


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    db_path: str | Path = "opensocial.db",
    config_dir: str | Path = "config/niches",
) -> FastAPI:
    session_factory = make_session_factory(db_path)
    config_dir = Path(config_dir)
    # Keep the fallback encryption keyfile next to the DB.
    os.environ.setdefault(
        "OPENSOCIAL_KEYFILE", str(Path(db_path).resolve().parent / "opensocial.key")
    )

    app = FastAPI(title="OpenX API")
    app.state.session_factory = session_factory
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5174", "http://127.0.0.1:5174"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def niches():
        return load_all_niches(config_dir)

    def niche_or_404(slug: str):
        path = config_dir / f"{slug}.json"
        if not path.exists():
            raise HTTPException(404, f"no niche config for {slug!r}")
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh), path

    def write_niche(path: Path, data: dict) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")

    def secret_key_or_400(session) -> str:
        from opensocial.core.secrets import keyfile_secret

        settings = resolve_settings(session)
        if settings.secret_key:
            return settings.secret_key
        # First secret saved from the dashboard: create the local keyfile.
        return keyfile_secret(create=True)

    # ---- status & settings ------------------------------------------------

    @app.get("/api/status")
    def status():
        with session_factory() as s:
            settings = resolve_settings(s)
            published = published_today_count(s)
            queue_pending = s.execute(
                select(func.count()).select_from(GeneratedPost).where(
                    GeneratedPost.status == "draft"
                )
            ).scalar()
        return {
            "dry_run": settings.dry_run,
            "app_mode": settings.app_mode,
            "global_daily_cap": settings.global_daily_cap,
            "autopilot_fetch_minutes": settings.autopilot_fetch_minutes,
            "max_post_attempts": settings.max_post_attempts,
            "secret_key_set": bool(settings.secret_key),
            "published_today": published,
            "queue_pending": int(queue_pending or 0),
        }

    @app.patch("/api/settings")
    def patch_settings(patch: SettingsPatch):
        with session_factory() as s:
            if patch.dry_run is not None:
                set_app_setting(s, "dry_run", "true" if patch.dry_run else "false")
            if patch.app_mode is not None:
                if patch.app_mode not in ("manual", "auto"):
                    raise HTTPException(422, "app_mode must be 'manual' or 'auto'")
                set_app_setting(s, "app_mode", patch.app_mode)
            if patch.global_daily_cap is not None:
                if patch.global_daily_cap < 0:
                    raise HTTPException(422, "global_daily_cap must be >= 0")
                set_app_setting(s, "global_daily_cap", str(patch.global_daily_cap))
            if patch.autopilot_fetch_minutes is not None:
                if patch.autopilot_fetch_minutes < 0:
                    raise HTTPException(422, "autopilot_fetch_minutes must be >= 0")
                set_app_setting(
                    s, "autopilot_fetch_minutes", str(patch.autopilot_fetch_minutes)
                )
        return status()

    @app.post("/api/reset")
    def reset(body: ResetIn):
        """Wipe runtime data (and optionally credentials). Config files survive."""
        if not body.confirm:
            raise HTTPException(422, "confirm must be true to reset the database")
        with session_factory() as s:
            deleted = reset_database(s, clear_credentials=body.clear_credentials)
        # Drop in-process secrets too so cleared keys stop being used immediately.
        if body.clear_credentials:
            for env in ALLOWED_SECRET_ENVS:
                os.environ.pop(env, None)
        return {"ok": True, "cleared_credentials": body.clear_credentials, "deleted": deleted}

    # ---- overview ----------------------------------------------------------

    @app.get("/api/overview")
    def overview():
        start, end = _today_bounds()
        with session_factory() as s:
            published_by_niche = dict(
                s.execute(
                    select(GeneratedPost.niche_slug, func.count())
                    .join(PostHistory, PostHistory.generated_post_id == GeneratedPost.id)
                    .where(
                        PostHistory.status == "success",
                        PostHistory.attempted_at >= start,
                        PostHistory.attempted_at < end,
                    )
                    .group_by(GeneratedPost.niche_slug)
                ).all()
            )
            found_by_niche = dict(
                s.execute(
                    select(ContentItemNiche.niche_slug, func.count())
                    .join(
                        ContentItemRow,
                        ContentItemRow.id == ContentItemNiche.content_item_id,
                    )
                    .where(ContentItemRow.fetched_at >= start)
                    .group_by(ContentItemNiche.niche_slug)
                ).all()
            )
            cand_by_niche = dict(
                s.execute(
                    select(ContentItemNiche.niche_slug, func.count())
                    .join(
                        ContentItemRow,
                        ContentItemRow.id == ContentItemNiche.content_item_id,
                    )
                    .where(
                        ContentItemRow.fetched_at >= start,
                        ContentItemNiche.status == "candidate",
                    )
                    .group_by(ContentItemNiche.niche_slug)
                ).all()
            )
            spend = s.execute(
                select(func.coalesce(func.sum(PostHistory.cost_estimate), 0.0)).where(
                    PostHistory.attempted_at >= start,
                    PostHistory.attempted_at < end,
                )
            ).scalar()
            with_link = s.execute(
                select(func.count()).select_from(PostHistory).where(
                    PostHistory.attempted_at >= start,
                    PostHistory.attempted_at < end,
                    PostHistory.included_source_link.is_(True),
                    PostHistory.status == "success",
                )
            ).scalar()
            eligible = s.execute(
                select(func.count()).select_from(GeneratedPost).where(
                    GeneratedPost.status == "draft"
                )
            ).scalar()
            logs = list(
                s.execute(
                    select(Log).order_by(Log.id.desc()).limit(10)
                ).scalars()
            )
            statuses = source_statuses(s)
            settings = resolve_settings(s)
            selected = set(get_followed_niches(s))

        all_niches = niches()
        # Total = every installed source plugin; active = those explicitly
        # enabled (sources start disabled on a fresh DB — the user enables them).
        all_source_names = available_sources()
        enabled_sources = sum(
            1
            for name in all_source_names
            if name in statuses and statuses[name].enabled_globally
        )

        funnel = []
        for n in all_niches:
            # Show a niche only if it's selected AND has at least one source
            # that is enabled for the niche AND globally enabled.
            has_enabled_source = any(
                scfg.get("enabled") is not False
                and (name in statuses and statuses[name].enabled_globally)
                for name, scfg in n.sources.items()
            )
            if not (n.slug in selected and has_enabled_source):
                continue
            funnel.append(
                {
                    "slug": n.slug,
                    "display_name": n.display_name,
                    "enabled": n.enabled,
                    "selected": True,
                    "found": found_by_niche.get(n.slug, 0),
                    "candidates": cand_by_niche.get(n.slug, 0),
                    "published": published_by_niche.get(n.slug, 0),
                }
            )

        activity = []
        for row in logs:
            m = _NICHE_PREFIX.match(row.message)
            activity.append(
                {
                    "id": row.id,
                    "ts": _iso(row.logged_at),
                    "level": row.level,
                    "msg": row.message,
                    "niche": m.group(1) if m else None,
                }
            )

        return {
            "published_today": sum(published_by_niche.values()),
            "global_daily_cap": settings.global_daily_cap,
            "pending_total": int(eligible or 0),
            "sources_active": enabled_sources,
            "sources_total": len(all_source_names),
            "spend_today": round(float(spend or 0.0), 4),
            "published_with_link": int(with_link or 0),
            "funnel": funnel,
            "activity": activity,
            # First-run onboarding: the pipeline can't do anything until the
            # user has both enabled a source and selected a niche.
            "setup": {
                "selected_niches": len(selected),
                "enabled_sources": enabled_sources,
                "needs_setup": len(selected) == 0 or enabled_sources == 0,
            },
        }

    # ---- niches ------------------------------------------------------------

    @app.get("/api/niches")
    def list_niches():
        with session_factory() as s:
            followed = set(get_followed_niches(s))
            statuses = source_statuses(s)

        def has_enabled_source(n) -> bool:
            # At least one source enabled for the niche AND globally enabled.
            return any(
                scfg.get("enabled") is not False
                and (name in statuses and statuses[name].enabled_globally)
                for name, scfg in n.sources.items()
            )

        return [
            {
                "slug": n.slug,
                "display_name": n.display_name,
                "enabled": n.enabled,
                "followed": n.slug in followed,
                "has_enabled_source": has_enabled_source(n),
            }
            for n in niches()
        ]

    # Declared before ``/api/niches/{slug}`` so the path param doesn't match it.
    @app.get("/api/niches/followed")
    def get_followed():
        with session_factory() as s:
            return {"followed": get_followed_niches(s)}

    @app.put("/api/niches/followed")
    def put_followed(body: FollowedIn):
        valid = {n.slug for n in niches()}
        unknown = [s for s in body.slugs if s not in valid]
        if unknown:
            raise HTTPException(422, f"unknown niche slug(s): {', '.join(unknown)}")
        with session_factory() as s:
            saved = set_followed_niches(s, body.slugs)
        return {"followed": saved}

    @app.get("/api/niches/{slug}")
    def get_niche(slug: str):
        data, _ = niche_or_404(slug)
        return data

    @app.put("/api/niches/{slug}")
    def put_niche(slug: str, config: dict):
        data, path = niche_or_404(slug)
        if config.get("slug") != slug:
            raise HTTPException(422, "config slug must match the URL slug")
        write_niche(path, config)
        return config

    @app.put("/api/niches/{slug}/schedule")
    def put_schedule(slug: str, sched: SchedulePut):
        data, path = niche_or_404(slug)
        for win in sched.windows:
            if len(win) != 2 or not all(re.fullmatch(r"\d{2}:\d{2}", w) for w in win):
                raise HTTPException(422, f"bad window {win!r} (use ['HH:MM','HH:MM'])")
        if len(sched.posts_per_day) != 2:
            raise HTTPException(422, "posts_per_day must be [min, max]")
        data["schedule"] = {
            "windows": sched.windows,
            "posts_per_day": sched.posts_per_day,
            "min_gap_minutes": sched.min_gap_minutes,
        }
        write_niche(path, data)
        return data["schedule"]

    @app.delete("/api/niches/{slug}/schedule")
    def delete_schedule(slug: str):
        """Take a niche off the schedule (drop its ``schedule`` block)."""
        data, path = niche_or_404(slug)
        if "schedule" in data:
            del data["schedule"]
            write_niche(path, data)
        return {"ok": True, "slug": slug}

    @app.post("/api/schedule/randomize")
    def randomize_schedule(body: RandomizeIn):
        """Randomly spread a daily post total across the scheduled niches.

        The total is split as a random multinomial draw over the niches that
        are currently on the schedule; each niche's windows are set to the
        given posting time range and its ``posts_per_day`` to its share.
        """
        win = body.window
        if len(win) != 2 or not all(re.fullmatch(r"\d{2}:\d{2}", w) for w in win):
            raise HTTPException(422, "window must be ['HH:MM','HH:MM']")
        if win[0] >= win[1]:
            raise HTTPException(422, "window start must be before end")
        if body.total_posts < 0:
            raise HTTPException(422, "total_posts must be >= 0")

        scheduled = [n for n in niches() if (n.raw or {}).get("schedule")]
        if not scheduled:
            raise HTTPException(400, "no niches on the schedule to randomize")

        slugs = [n.slug for n in scheduled]
        shares = {slug: 0 for slug in slugs}
        for _ in range(body.total_posts):
            shares[random.choice(slugs)] += 1

        for n in scheduled:
            data, path = niche_or_404(n.slug)
            existing = data.get("schedule") or {}
            gap = body.min_gap_minutes
            if gap is None:
                gap = int(existing.get("min_gap_minutes", 45))
            share = shares[n.slug]
            data["schedule"] = {
                "windows": [list(win)],
                "posts_per_day": [share, share],
                "min_gap_minutes": int(gap),
            }
            write_niche(path, data)
        return schedule()

    # ---- schedule (resolved slots) ------------------------------------------

    @app.get("/api/schedule")
    def schedule():
        now = datetime.now(timezone.utc)
        out = []
        with session_factory() as s:
            for n in niches():
                # Only niches that have a schedule block are "on the schedule".
                if not (n.raw or {}).get("schedule"):
                    continue
                cfg = ScheduleConfig.from_niche(n.raw)
                slots = resolve_slots(cfg, n.slug, now)
                due = due_slot_count(slots, now)
                published = published_today_count(s, niche_slug=n.slug, day=now)
                out.append(
                    {
                        "slug": n.slug,
                        "display_name": n.display_name,
                        "enabled": n.enabled,
                        "windows": [
                            [w[0].strftime("%H:%M"), w[1].strftime("%H:%M")]
                            for w in cfg.windows
                        ],
                        "posts_per_day": list(cfg.posts_per_day),
                        "min_gap_minutes": cfg.min_gap_minutes,
                        "slots": [_iso(t) for t in slots],
                        "due": due,
                        "published_today": published,
                        "owes": max(0, due - published) if n.enabled else 0,
                    }
                )
        return {"now": _iso(now), "niches": out}

    # ---- posts (queue) -------------------------------------------------------

    @app.get("/api/posts")
    def posts(niche: str | None = None, status: str | None = None, limit: int = 200):
        stmt = (
            select(GeneratedPost, ContentItemRow.source_name)
            .join(
                ContentItemRow,
                GeneratedPost.content_item_id == ContentItemRow.id,
                isouter=True,
            )
            .order_by(GeneratedPost.created_at.desc())
            .limit(min(limit, 500))
        )
        if niche:
            stmt = stmt.where(GeneratedPost.niche_slug == niche)
        if status:
            stmt = stmt.where(GeneratedPost.status == status)
        with session_factory() as s:
            rows = s.execute(stmt).all()
            return [
                {
                    "id": p.id,
                    "niche": p.niche_slug,
                    "type": p.post_type,
                    "status": p.status,
                    "text": p.text,
                    "priority": p.priority_score,
                    "media_url": p.media_url,
                    "source": source_name,
                    "independent": p.content_item_id is None,
                    "attempts": p.post_attempts,
                    "error": p.post_error,
                    "created_at": _iso(p.created_at),
                    "scheduled_at": _iso(p.scheduled_at),
                }
                for p, source_name in rows
            ]

    def _post_or_404(s, post_id: str) -> GeneratedPost:
        post = s.get(GeneratedPost, post_id)
        if post is None:
            raise HTTPException(404, "post not found")
        return post

    @app.post("/api/posts/{post_id}/approve")
    def approve_post(post_id: str):
        with session_factory() as s:
            post = approval_logic.approve(s, _post_or_404(s, post_id))
            return {"id": post.id, "status": post.status}

    @app.post("/api/posts/{post_id}/reject")
    def reject_post(post_id: str):
        with session_factory() as s:
            post = approval_logic.reject(s, _post_or_404(s, post_id))
            return {"id": post.id, "status": post.status}

    @app.post("/api/posts/{post_id}/edit")
    def edit_post(post_id: str, body: EditIn):
        if not body.text.strip():
            raise HTTPException(422, "text must not be empty")
        with session_factory() as s:
            post = approval_logic.edit(s, _post_or_404(s, post_id), body.text.strip())
            return {"id": post.id, "status": post.status, "text": post.text}

    # ---- raw fetched content -------------------------------------------------

    @app.get("/api/content")
    def content(
        source: str | None = None,
        niche: str | None = None,
        q: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ):
        """Raw fetched ``content_items`` (newest first), filterable by source.

        Backs the dashboard's Raw Data tab: the unmodified item as it landed
        from the source plugin, including ``raw_metadata`` and ``engagement``.

        Returns ``{"total": N, "items": [...]}`` where ``total`` is the full
        count for the filter (ignoring paging) and ``items`` is the requested
        page, so the tab can paginate rather than silently truncate.
        """
        page = min(max(limit, 1), 500)
        start = max(offset, 0)

        def _apply_filters(stmt):
            if source:
                stmt = stmt.where(ContentItemRow.source_name == source)
            niche_slugs = [n for n in (niche or "").split(",") if n.strip()]
            if niche_slugs:
                stmt = stmt.join(
                    ContentItemNiche,
                    ContentItemNiche.content_item_id == ContentItemRow.id,
                ).where(ContentItemNiche.niche_slug.in_(niche_slugs))
            if q:
                stmt = stmt.where(ContentItemRow.title.ilike(f"%{q}%"))
            return stmt

        stmt = _apply_filters(
            select(ContentItemRow)
            .order_by(ContentItemRow.fetched_at.desc())
            .limit(page)
            .offset(start)
        )
        count_stmt = _apply_filters(
            select(func.count(func.distinct(ContentItemRow.id)))
        )
        with session_factory() as s:
            total = s.execute(count_stmt).scalar_one()
            rows = list(s.execute(stmt).scalars())
            ids = [r.id for r in rows]
            links: dict[str, list[dict]] = {}
            if ids:
                for cin in s.execute(
                    select(ContentItemNiche).where(
                        ContentItemNiche.content_item_id.in_(ids)
                    )
                ).scalars():
                    links.setdefault(cin.content_item_id, []).append(
                        {"niche": cin.niche_slug, "status": cin.status}
                    )
            items = [
                {
                    "id": r.id,
                    "source": r.source_name,
                    "category": r.source_category,
                    "title": r.title,
                    "url": r.url,
                    "author": r.author,
                    "summary": r.summary,
                    "body": r.body,
                    "published_at": _iso(r.published_at),
                    "fetched_at": _iso(r.fetched_at),
                    "media_urls": r.media_urls or [],
                    "tags": r.tags or [],
                    "language": r.language,
                    "sentiment": r.sentiment,
                    "engagement": r.engagement,
                    "raw_metadata": r.raw_metadata or {},
                    "niches": links.get(r.id, []),
                }
                for r in rows
            ]
            return {"total": total, "items": items}

    # ---- history -------------------------------------------------------------

    @app.get("/api/history")
    def history(days: int = 1, status: str | None = None, limit: int = 300):
        since = datetime.now(timezone.utc) - timedelta(days=max(1, days))
        stmt = (
            select(PostHistory, GeneratedPost)
            .join(GeneratedPost, GeneratedPost.id == PostHistory.generated_post_id)
            .where(PostHistory.attempted_at >= since)
            .order_by(PostHistory.attempted_at.desc())
            .limit(min(limit, 1000))
        )
        if status:
            stmt = stmt.where(PostHistory.status == status)
        with session_factory() as s:
            rows = s.execute(stmt).all()
            return [
                {
                    "id": h.id,
                    "ts": _iso(h.attempted_at),
                    "niche": p.niche_slug,
                    "type": p.post_type,
                    "status": h.status,
                    "cost": h.cost_estimate,
                    "link": h.included_source_link,
                    "url": h.platform_post_url,
                    # dry-run publishes record success with no platform post id
                    "dry": h.status == "success" and h.platform_post_id is None
                    and h.platform_post_url is None,
                    "error": h.error_message,
                }
                for h, p in rows
            ]

    # ---- logs ------------------------------------------------------------------

    @app.get("/api/logs")
    def logs(level: str | None = None, after_id: int = 0, limit: int = 300):
        stmt = select(Log).order_by(Log.id.desc()).limit(min(limit, 1000))
        if level and level != "all":
            stmt = stmt.where(Log.level == level)
        if after_id:
            stmt = stmt.where(Log.id > after_id)
        with session_factory() as s:
            rows = list(s.execute(stmt).scalars())
        rows.reverse()
        return [
            {
                "id": r.id,
                "ts": _iso(r.logged_at),
                "level": r.level,
                "msg": r.message,
            }
            for r in rows
        ]

    # ---- sources ------------------------------------------------------------------

    @app.get("/api/sources")
    def sources():
        all_niches = niches()
        usage: dict[str, dict] = {}
        origins: dict[str, list] = {name: [] for name in ORIGIN_SPEC}
        for n in all_niches:
            for name, scfg in n.sources.items():
                u = usage.setdefault(name, {"niches": [], "enabled_in": 0})
                u["niches"].append(n.slug)
                if scfg.get("enabled") is not False and n.enabled:
                    u["enabled_in"] += 1
                spec = ORIGIN_SPEC.get(name)
                if spec:
                    for value in scfg.get(spec["key"]) or []:
                        origins[name].append(
                            {
                                "niche": n.slug,
                                "value": value,
                                "display": _origin_display(name, value),
                            }
                        )

        with session_factory() as s:
            statuses = source_statuses(s)

        out = []
        for name in available_sources():
            row = statuses.get(name)
            envs, requirement = SOURCE_KEYS.get(name, ((), None))
            key_set = all(os.environ.get(e) for e in envs) if envs else None
            u = usage.get(name, {"niches": [], "enabled_in": 0})
            kind = "dynamic" if name in DYNAMIC_SOURCES else "static"
            out.append(
                {
                    "id": name,
                    "name": SOURCE_LABELS.get(name, name),
                    "kind": kind,
                    "upcoming": name in UPCOMING_SOURCES,
                    "category": getattr(get_source(name), "category", None),
                    "enabled": row.enabled_globally if row is not None else False,
                    "last_fetch_at": _iso(row.last_fetch_at) if row is not None else None,
                    "last_status": row.last_fetch_status if row is not None else None,
                    "ok": (row.last_fetch_status or "ok").startswith("ok")
                    if row is not None
                    else True,
                    "key": requirement,
                    "key_envs": list(envs),
                    "key_set": key_set,
                    "niches": u["niches"],
                    "enabled_in": u["enabled_in"],
                    "origin_label": ORIGIN_SPEC[name]["label"] if kind == "dynamic" else None,
                    "origins": origins.get(name, []) if kind == "dynamic" else [],
                    "max_origins": _max_origins(name) if kind == "dynamic" else None,
                }
            )
        return out

    @app.patch("/api/sources/{name}")
    def patch_source(name: str, patch: SourcePatch):
        if name not in available_sources():
            raise HTTPException(404, f"unknown source {name!r}")
        if patch.enabled and name in UPCOMING_SOURCES:
            raise HTTPException(409, f"{name!r} is upcoming and can't be enabled yet")
        with session_factory() as s:
            row = upsert_source_status(s, name, enabled=patch.enabled)
            return {"id": name, "enabled": row.enabled_globally}

    def _origin_add(niche_slug: str, name: str, spec: dict, value: str) -> None:
        """Append a parsed origin to a niche's source block (seeding it if new)."""
        data, path = niche_or_404(niche_slug)
        sources = data.setdefault("sources", {})
        block = sources.get(name)
        if not isinstance(block, dict):
            block = dict(spec["defaults"])
            if name == "rss":
                block.setdefault("category", niche_slug)
            sources[name] = block
        lst = block.setdefault(spec["key"], [])
        if value not in lst:
            lst.append(value)
        write_niche(path, data)

    def _origin_remove(niche_slug: str, name: str, spec: dict, value: str) -> None:
        """Remove an origin from a niche, dropping the block once it's empty."""
        data, path = niche_or_404(niche_slug)
        block = (data.get("sources") or {}).get(name)
        if not isinstance(block, dict):
            return
        lst = block.get(spec["key"]) or []
        if value in lst:
            lst.remove(value)
        if lst:
            block[spec["key"]] = lst
        else:
            data["sources"].pop(name, None)
        write_niche(path, data)

    def _origin_spec_or_404(name: str) -> dict:
        spec = ORIGIN_SPEC.get(name)
        if spec is None:
            raise HTTPException(404, f"{name!r} is not a dynamic source")
        return spec

    def _parse_origin_or_422(name: str, url: str | None) -> str:
        if not url or not url.strip():
            raise HTTPException(422, "url is required")
        value = _parse_origin(name, url)
        if not value:
            raise HTTPException(422, f"could not parse a {name} origin from {url!r}")
        return value

    def _origin_count(name: str, spec: dict) -> int:
        """Total origins saved for a dynamic source across all niches."""
        return sum(
            len(scfg.get(spec["key"]) or [])
            for n in niches()
            for sname, scfg in n.sources.items()
            if sname == name
        )

    @app.post("/api/sources/{name}/origins")
    def add_origin(name: str, body: OriginIn):
        spec = _origin_spec_or_404(name)
        value = _parse_origin_or_422(name, body.url)
        cap = _max_origins(name)
        if _origin_count(name, spec) >= cap:
            raise HTTPException(422, f"{name} is capped at {cap} origins")
        _origin_add(body.niche, name, spec, value)
        return {
            "name": name,
            "niche": body.niche,
            "value": value,
            "display": _origin_display(name, value),
        }

    @app.put("/api/sources/{name}/origins")
    def update_origin(name: str, body: OriginEditIn):
        """Edit a saved origin: re-parse the new url and (optionally) move niches."""
        spec = _origin_spec_or_404(name)
        if not body.value:
            raise HTTPException(422, "value (the origin being edited) is required")
        new_value = _parse_origin_or_422(name, body.url)
        target = body.new_niche or body.niche
        _origin_remove(body.niche, name, spec, body.value)
        _origin_add(target, name, spec, new_value)
        return {
            "name": name,
            "niche": target,
            "value": new_value,
            "display": _origin_display(name, new_value),
        }

    @app.delete("/api/sources/{name}/origins")
    def remove_origin(name: str, body: OriginIn):
        spec = _origin_spec_or_404(name)
        if not body.value:
            raise HTTPException(422, "value is required")
        _origin_remove(body.niche, name, spec, body.value)
        return {"name": name, "niche": body.niche, "removed": body.value}

    # ---- global AI config ---------------------------------------------------

    @app.get("/api/ai")
    def get_ai():
        with session_factory() as s:
            cfg = load_ai_config(s)
        # Surface which AI keys are present so the card can show set/not-set
        # without exposing the secrets themselves.
        cfg["key_status"] = {
            env: bool(os.environ.get(env)) for env in AI_KEY_ENVS
        }
        return cfg

    @app.put("/api/ai")
    def put_ai(body: AiConfigIn):
        text = body.text or {}
        if (text.get("provider") or "").lower() == "local" and not (text.get("endpoint") or "").strip():
            raise HTTPException(422, "endpoint is required for the local provider")
        with session_factory() as s:
            saved = save_ai_config(s, {"text": text})
        saved["key_status"] = {env: bool(os.environ.get(env)) for env in AI_KEY_ENVS}
        return saved

    # ---- commands --------------------------------------------------------------------

    @app.post("/api/commands")
    def post_command(cmd: CommandIn):
        if cmd.type not in COMMAND_TYPES:
            raise HTTPException(422, f"unknown command type {cmd.type!r}")
        with session_factory() as s:
            row = enqueue_command(s, cmd.type, cmd.payload or {})
            return {
                "id": row.id,
                "type": row.type,
                "status": row.status,
                "created_at": _iso(row.created_at),
            }

    @app.get("/api/commands")
    def get_commands(ids: str = "", limit: int = 40):
        with session_factory() as s:
            stmt = select(Command).order_by(Command.id.desc()).limit(min(limit, 200))
            if ids:
                try:
                    id_list = [int(i) for i in ids.split(",") if i.strip()]
                except ValueError:
                    raise HTTPException(422, "ids must be comma-separated integers")
                stmt = select(Command).where(Command.id.in_(id_list))
            rows = list(s.execute(stmt).scalars())
            return [
                {
                    "id": c.id,
                    "type": c.type,
                    "payload": c.payload,
                    "status": c.status,
                    "result": c.result,
                    "created_at": _iso(c.created_at),
                    "finished_at": _iso(c.finished_at),
                }
                for c in rows
            ]

    # ---- credentials --------------------------------------------------------------

    @app.get("/api/credentials")
    def credentials():
        with session_factory() as s:
            accounts = list_platform_accounts(s, platform="x")
        groups = [
            {
                "platform": "Twitter / X",
                "type": "x_account",
                "keys": [
                    {"name": "api_key", "set": bool(accounts)},
                    {"name": "api_secret", "set": bool(accounts)},
                    {"name": "access_token", "set": bool(accounts)},
                    {"name": "access_token_secret", "set": bool(accounts)},
                ],
                "accounts": [a.account_label for a in accounts],
            }
        ]
        for platform, envs in CREDENTIAL_GROUPS:
            groups.append(
                {
                    "platform": platform,
                    "type": "env",
                    "keys": [
                        {"name": e, "set": bool(os.environ.get(e))} for e in envs
                    ],
                }
            )
        return groups

    @app.post("/api/credentials")
    def set_credential(body: SecretIn):
        if body.key not in ALLOWED_SECRET_ENVS:
            raise HTTPException(422, f"unknown credential key {body.key!r}")
        if not body.value.strip():
            raise HTTPException(422, "value must not be empty")
        from opensocial.core.secrets import encrypt_credentials

        with session_factory() as s:
            key = secret_key_or_400(s)
            blob = encrypt_credentials({"value": body.value.strip()}, key)
            set_app_setting(s, f"secret:{body.key}", blob.decode("ascii"))
        os.environ[body.key] = body.value.strip()
        return {"key": body.key, "set": True}

    @app.post("/api/credentials/x")
    def set_x_account(body: XAccountIn):
        from opensocial.core.secrets import encrypt_credentials

        creds = {
            "api_key": body.api_key,
            "api_secret": body.api_secret,
            "access_token": body.access_token,
            "access_token_secret": body.access_token_secret,
        }
        if not all(v.strip() for v in creds.values()):
            raise HTTPException(422, "all four X credentials are required")
        with session_factory() as s:
            key = secret_key_or_400(s)
            blob = encrypt_credentials(creds, key)
            add_platform_account(
                s,
                account_label=body.label,
                credentials_encrypted=blob,
                daily_post_cap=body.daily_post_cap,
            )
        return {"label": body.label, "set": True}

    return app
