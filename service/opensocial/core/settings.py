"""Process-level operational settings, read from the environment.

These are the safety knobs absorbed from the reference implementation. The
defaults are deliberately conservative: publishing is a **dry-run** unless
explicitly switched live, and the app starts in **manual** mode.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    dry_run: bool
    app_mode: str  # "manual" | "auto"
    global_daily_cap: int
    max_post_attempts: int
    secret_key: str | None
    # Autopilot fetch cadence (minutes). In auto mode the worker refreshes the
    # draft queue this often, but only inside the day's posting window. 0 (or
    # negative) disables the timed refresh entirely.
    autopilot_fetch_minutes: int = 30

    @classmethod
    def from_env(cls) -> "Settings":
        # Fail-safe: live only when POST_DRY_RUN is *explicitly* a falsey string.
        # Anything else (unset, typo, "maybe") stays dry so nothing posts by
        # accident.
        raw = os.environ.get("POST_DRY_RUN")
        dry_run = True if raw is None else not _truthy_false(raw)

        mode = (os.environ.get("APP_MODE") or "manual").strip().lower()
        if mode not in ("manual", "auto"):
            mode = "manual"

        return cls(
            dry_run=dry_run,
            app_mode=mode,
            global_daily_cap=int(os.environ.get("GLOBAL_DAILY_CAP", "25")),
            max_post_attempts=int(os.environ.get("MAX_POST_ATTEMPTS", "3")),
            secret_key=os.environ.get("OPENSOCIAL_SECRET_KEY"),
            autopilot_fetch_minutes=int(
                os.environ.get("AUTOPILOT_FETCH_MINUTES", "30")
            ),
        )


def _truthy_false(value: str) -> bool:
    """True when the value explicitly means 'off' (i.e. go live)."""
    return value.strip().lower() in ("0", "false", "no", "off")


def resolve_settings(session) -> Settings:
    """Env settings overlaid with the dashboard's runtime overrides.

    The dashboard persists ``dry_run`` / ``app_mode`` in ``app_settings`` so
    toggling them doesn't need a service restart. The same fail-safe applies:
    dry-run only switches off on an explicit "false".
    """
    from dataclasses import replace

    from opensocial.core.db import get_app_setting

    base = Settings.from_env()

    dry = get_app_setting(session, "dry_run")
    if dry is not None:
        base = replace(base, dry_run=not _truthy_false(dry))

    mode = (get_app_setting(session, "app_mode") or "").strip().lower()
    if mode in ("manual", "auto"):
        base = replace(base, app_mode=mode)

    cap = get_app_setting(session, "global_daily_cap")
    if cap is not None:
        try:
            base = replace(base, global_daily_cap=max(0, int(cap)))
        except (TypeError, ValueError):
            pass

    fetch_min = get_app_setting(session, "autopilot_fetch_minutes")
    if fetch_min is not None:
        try:
            base = replace(base, autopilot_fetch_minutes=max(0, int(fetch_min)))
        except (TypeError, ValueError):
            pass

    if base.secret_key is None:
        from opensocial.core.secrets import keyfile_secret

        key = keyfile_secret()
        if key:
            base = replace(base, secret_key=key)

    return base


# ---------------------------------------------------------------------------
# Global AI provider config (moved out of per-niche config)
# ---------------------------------------------------------------------------

# One AI configuration applies to every niche. Stored as a JSON blob in
# ``app_settings`` under the ``ai`` key.
#
# ``text.provider`` is a friendly provider name (``claude`` / ``chatgpt`` /
# ``local`` / ``template``) rather than a library name; ``ai/text.py`` maps it
# to a concrete model + endpoint. ``endpoint`` is the API base URL — optional
# for the hosted providers (custom gateways), **required** for ``local``.
# API keys are never stored here: they live encrypted in the credentials store
# (``OPENAI_API_KEY`` / ``ANTHROPIC_API_KEY``) and are read from the env.
DEFAULT_AI: dict = {
    "text": {
        "provider": "local",
        "model": "ollama/gemma3:4b",
        "endpoint": "http://localhost:11434",
        "temperature": 0.7,
    },
}


def load_ai_config(session) -> dict:
    """Resolve the global AI config (stored blob overlaid on the defaults).

    Returns the ``ai`` block shape that ``get_text_provider`` /
    ``get_image_provider`` expect, so callers can inject it as ``config['ai']``.
    """
    from opensocial.core.db import get_app_setting

    raw = get_app_setting(session, "ai")
    if not raw:
        return {k: dict(v) for k, v in DEFAULT_AI.items()}

    try:
        stored = json.loads(raw)
    except (TypeError, ValueError):
        stored = {}

    return _merge_ai(stored)


def _merge_ai(stored: dict) -> dict:
    return {"text": {**DEFAULT_AI["text"], **(stored.get("text") or {})}}


def save_ai_config(session, config: dict) -> dict:
    """Persist the global AI config (text generation only)."""
    from opensocial.core.db import set_app_setting

    resolved = _merge_ai(config or {})
    set_app_setting(session, "ai", json.dumps(resolved))
    return resolved


# ---------------------------------------------------------------------------
# Selected niches (the ones the user follows; gates fetch + generation)
# ---------------------------------------------------------------------------

# The user selects the niches that represent their domain. Only selected niches
# are fetched and drafted for; everything else stays dormant. There is no hard
# cap — but fewer, focused niches yield sharper, more relevant posts. Stored as
# a JSON list of slugs in ``app_settings`` under ``followed_niches``.


def get_followed_niches(session) -> list[str]:
    """Return the selected niche slugs (``[]`` if none set)."""
    from opensocial.core.db import get_app_setting

    raw = get_app_setting(session, "followed_niches")
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(value, list):
        return []
    return [str(s) for s in value if isinstance(s, str) and s.strip()]


def set_followed_niches(session, slugs: list[str]) -> list[str]:
    """Persist the selected niches, de-duplicated (no cap).

    Order is preserved; duplicates are dropped keeping first occurrence.
    """
    from opensocial.core.db import set_app_setting

    seen: list[str] = []
    for slug in slugs or []:
        s = str(slug).strip()
        if s and s not in seen:
            seen.append(s)
    set_app_setting(session, "followed_niches", json.dumps(seen))
    return seen
