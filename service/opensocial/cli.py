"""OpenX CLI.

Phase 1 commands:
  * ``fetch``   — poll a niche's enabled sources and store new content
  * ``sources`` — list registered source plugins

Phase 2 commands:
  * ``filter``  — apply a niche's filters + near-dup detection to stored content
  * ``queue``   — print a niche's prioritized candidate queue
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

import typer

from opensocial.core.approval import sweep_timeouts
from opensocial.core.commands import autopilot_refresh, process_commands
from opensocial.core.config import NicheConfig, load_all_niches, load_niche
from opensocial.core.db import (
    GeneratedPost,
    add_platform_account,
    list_platform_accounts,
    make_session_factory,
    store_items,
)
from opensocial.core.engine import load_credentials, publish_post, run_due_slots
from opensocial.core.filtering import candidate_queue, filter_niche
from opensocial.core.generate import generate_for_niche, generate_independent
from opensocial.core.settings import Settings
from opensocial.sources import available_sources, get_source

app = typer.Typer(help="OpenX automation service", no_args_is_help=True)


async def _fetch_niche(niche: NicheConfig, session_factory) -> None:
    if not niche.enabled:
        typer.echo(f"[{niche.slug}] disabled — skipping")
        return

    typer.echo(f"[{niche.slug}] {niche.display_name}")
    for source_name, source_cfg in niche.sources.items():
        if source_cfg.get("enabled") is False:
            continue
        try:
            source_cls = get_source(source_name)
        except KeyError as exc:
            typer.echo(f"  ! {exc}")
            continue

        source = source_cls(source_cfg)
        try:
            items = await source.fetch()
        except Exception as exc:  # one bad source shouldn't sink the run
            typer.echo(f"  ! {source_name}: fetch failed ({exc})")
            continue

        with session_factory() as session:
            new, total = store_items(session, items, niche.slug)
        typer.echo(f"  + {source_name}: {new} new / {total} fetched")


async def _run_fetch(niches: list[NicheConfig], db: str) -> None:
    session_factory = make_session_factory(db)
    for niche in niches:
        await _fetch_niche(niche, session_factory)


@app.command()
def fetch(
    niche: str = typer.Option(
        None, "--niche", "-n", help="Slug of a single niche to fetch (default: all)."
    ),
    config_dir: str = typer.Option(
        "config/niches", "--config-dir", help="Directory of niche YAML files."
    ),
    db: str = typer.Option("opensocial.db", "--db", help="SQLite database path."),
) -> None:
    """Fetch and store content for one or all niches."""
    niches = _resolve_niches(niche, config_dir)
    asyncio.run(_run_fetch(niches, db))


def _resolve_niches(niche: str | None, config_dir: str) -> list[NicheConfig]:
    """Load a single niche by slug, or every niche in ``config_dir``."""
    if niche:
        path = Path(config_dir) / f"{niche}.json"
        if not path.exists():
            typer.echo(f"No niche config at {path}", err=True)
            raise typer.Exit(1)
        niches = [load_niche(path)]
    else:
        niches = load_all_niches(config_dir)

    if not niches:
        typer.echo(f"No niche configs found in {config_dir}", err=True)
        raise typer.Exit(1)
    return niches


@app.command(name="filter")
def filter_(
    niche: str = typer.Option(
        None, "--niche", "-n", help="Slug of a single niche to filter (default: all)."
    ),
    config_dir: str = typer.Option(
        "config/niches", "--config-dir", help="Directory of niche JSON files."
    ),
    db: str = typer.Option("opensocial.db", "--db", help="SQLite database path."),
) -> None:
    """Mark stored content as candidate/filtered/duplicate for one or all niches."""
    niches = _resolve_niches(niche, config_dir)
    session_factory = make_session_factory(db)
    for n in niches:
        with session_factory() as session:
            counts = filter_niche(session, n.slug, n.raw)
        typer.echo(
            f"[{n.slug}] {counts['candidate']} candidates, "
            f"{counts['filtered']} filtered, {counts['duplicate']} duplicates"
        )


@app.command()
def queue(
    niche: str = typer.Option(
        ..., "--niche", "-n", help="Slug of the niche to show the queue for."
    ),
    limit: int = typer.Option(20, "--limit", "-l", help="Max candidates to show."),
    config_dir: str = typer.Option(
        "config/niches", "--config-dir", help="Directory of niche JSON files."
    ),
    db: str = typer.Option("opensocial.db", "--db", help="SQLite database path."),
) -> None:
    """Print a niche's prioritized candidate queue (best-first)."""
    niches = _resolve_niches(niche, config_dir)
    n = niches[0]
    session_factory = make_session_factory(db)
    with session_factory() as session:
        ranked = candidate_queue(session, n.slug, n.raw)
        if not ranked:
            typer.echo(f"[{n.slug}] no candidates — run 'filter' first?")
            return
        typer.echo(f"[{n.slug}] {len(ranked)} candidates (showing {min(limit, len(ranked))}):")
        for i, c in enumerate(ranked[:limit], 1):
            typer.echo(
                f"  {i:>2}. [{c.priority_score:.3f}] ({c.row.source_name}) {c.row.title}"
            )


def _print_drafts(slug: str, drafts, *, dry_run: bool) -> None:
    tag = "would generate" if dry_run else "generated"
    if not drafts:
        typer.echo(f"[{slug}] no drafts {tag} — run 'filter' first, or caps are spent?")
        return
    typer.echo(f"[{slug}] {tag} {len(drafts)} draft(s):")
    for i, d in enumerate(drafts, 1):
        kind = "independent" if d.independent else "source"
        img = " [img]" if d.media_url else ""
        typer.echo(f"  {i:>2}. <{d.post_type}/{kind}>{img} {d.text}")


@app.command()
def generate(
    niche: str = typer.Option(
        None, "--niche", "-n", help="Slug of a single niche (default: all)."
    ),
    limit: int = typer.Option(5, "--limit", "-l", help="Max source-derived drafts."),
    independent: bool = typer.Option(
        True, "--independent/--no-independent",
        help="Also run the daily independent-take job.",
    ),
    config_dir: str = typer.Option(
        "config/niches", "--config-dir", help="Directory of niche JSON files."
    ),
    db: str = typer.Option("opensocial.db", "--db", help="SQLite database path."),
) -> None:
    """Generate draft posts for one or all niches (writes to generated_posts)."""
    from opensocial.core.settings import load_ai_config

    niches = _resolve_niches(niche, config_dir)
    session_factory = make_session_factory(db)
    for n in niches:
        with session_factory() as session:
            config = {**n.raw, "ai": load_ai_config(session)}
            drafts = generate_for_niche(session, n.slug, config, limit=limit)
            if independent:
                drafts = drafts + generate_independent(session, n.slug, config)
        _print_drafts(n.slug, drafts, dry_run=False)


@app.command()
def preview(
    niche: str = typer.Option(
        ..., "--niche", "-n", help="Slug of the niche to preview."
    ),
    limit: int = typer.Option(5, "--limit", "-l", help="Max source-derived drafts."),
    config_dir: str = typer.Option(
        "config/niches", "--config-dir", help="Directory of niche JSON files."
    ),
    db: str = typer.Option("opensocial.db", "--db", help="SQLite database path."),
) -> None:
    """Dry-run: show what generation would produce without writing anything."""
    from opensocial.core.settings import load_ai_config

    niches = _resolve_niches(niche, config_dir)
    n = niches[0]
    session_factory = make_session_factory(db)
    with session_factory() as session:
        config = {**n.raw, "ai": load_ai_config(session)}
        drafts = generate_for_niche(session, n.slug, config, limit=limit, persist=False)
        drafts = drafts + generate_independent(session, n.slug, config, persist=False)
    _print_drafts(n.slug, drafts, dry_run=True)


def _mode_banner(settings: Settings) -> None:
    mode = "DRY-RUN" if settings.dry_run else "LIVE"
    typer.echo(f"(app_mode={settings.app_mode}, publishing={mode})")


@app.command()
def keygen() -> None:
    """Print a fresh Fernet key for OPENSOCIAL_SECRET_KEY."""
    from opensocial.core.secrets import generate_key

    typer.echo(generate_key())


@app.command(name="account-add")
def account_add(
    label: str = typer.Option(..., "--label", help="A name for this account."),
    db: str = typer.Option("opensocial.db", "--db", help="SQLite database path."),
    daily_cap: int = typer.Option(
        None, "--daily-cap", help="Optional per-account daily post cap."
    ),
) -> None:
    """Enroll an X account, encrypting its credentials at rest.

    Reads the four X API credentials from the environment: X_API_KEY,
    X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET. Requires
    OPENSOCIAL_SECRET_KEY (make one with `keygen`).
    """
    import os

    from opensocial.core.secrets import SecretsError, encrypt_credentials
    from opensocial.core.settings import Settings

    needed = {
        "api_key": "X_API_KEY",
        "api_secret": "X_API_SECRET",
        "access_token": "X_ACCESS_TOKEN",
        "access_token_secret": "X_ACCESS_TOKEN_SECRET",
    }
    creds = {k: os.environ.get(env) for k, env in needed.items()}
    missing = [env for k, env in needed.items() if not creds[k]]
    if missing:
        typer.echo(f"Missing env vars: {', '.join(missing)}", err=True)
        raise typer.Exit(1)

    secret_key = Settings.from_env().secret_key
    try:
        blob = encrypt_credentials(creds, secret_key)
    except SecretsError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)

    session_factory = make_session_factory(db)
    with session_factory() as session:
        add_platform_account(
            session, account_label=label, credentials_encrypted=blob,
            daily_post_cap=daily_cap,
        )
    typer.echo(f"stored X account '{label}' (credentials encrypted)")


@app.command(name="account-list")
def account_list(
    db: str = typer.Option("opensocial.db", "--db", help="SQLite database path."),
) -> None:
    """List enrolled platform accounts (credentials are never printed)."""
    session_factory = make_session_factory(db)
    with session_factory() as session:
        accounts = list_platform_accounts(session)
    if not accounts:
        typer.echo("no accounts enrolled — see 'account-add'")
        return
    for a in accounts:
        cap = f" cap={a.daily_post_cap}" if a.daily_post_cap else ""
        typer.echo(f"{a.platform}: {a.account_label}{cap}")


@app.command()
def publish(
    niche: str = typer.Option(
        None, "--niche", "-n", help="Slug of a single niche (default: all)."
    ),
    config_dir: str = typer.Option(
        "config/niches", "--config-dir", help="Directory of niche JSON files."
    ),
    db: str = typer.Option("opensocial.db", "--db", help="SQLite database path."),
) -> None:
    """Publish the posts due right now for one or all niches (one-shot)."""
    settings = Settings.from_env()
    _mode_banner(settings)
    niches = _resolve_niches(niche, config_dir)
    session_factory = make_session_factory(db)
    for n in niches:
        with session_factory() as session:
            creds = load_credentials(session, settings)
            outcomes = run_due_slots(session, n.slug, n.raw, settings, credentials=creds)
        if not outcomes:
            typer.echo(f"[{n.slug}] nothing due")
            continue
        for o in outcomes:
            verb = "would post" if o.dry_run else ("posted" if o.ok else "FAILED")
            typer.echo(f"[{n.slug}] {verb} <{o.post_type}> {o.post_id} (${o.cost:.3f})")


@app.command(name="post-now")
def post_now(
    post_id: str = typer.Argument(..., help="generated_posts.id to publish now."),
    config_dir: str = typer.Option("config/niches", "--config-dir"),
    db: str = typer.Option("opensocial.db", "--db", help="SQLite database path."),
) -> None:
    """Publish one specific draft immediately (respects the dry-run fail-safe)."""
    settings = Settings.from_env()
    _mode_banner(settings)
    session_factory = make_session_factory(db)
    with session_factory() as session:
        post = session.get(GeneratedPost, post_id)
        if post is None:
            typer.echo(f"No generated post {post_id}", err=True)
            raise typer.Exit(1)
        niches = _resolve_niches(post.niche_slug, config_dir)
        creds = load_credentials(session, settings)
        outcome = publish_post(session, post, niches[0].raw, settings, credentials=creds)
    verb = "would post" if outcome.dry_run else ("posted" if outcome.ok else "FAILED")
    typer.echo(f"[{post.niche_slug}] {verb} {outcome.post_id}: {outcome.error or 'ok'}")


@app.command()
def commands(
    config_dir: str = typer.Option("config/niches", "--config-dir"),
    db: str = typer.Option("opensocial.db", "--db", help="SQLite database path."),
) -> None:
    """Process the dashboard command queue once (a worker tick)."""
    session_factory = make_session_factory(db)
    ran = process_commands(session_factory, config_dir=config_dir)
    typer.echo(f"processed {ran} command(s)")


@app.command()
def run(
    interval: int = typer.Option(
        60, "--interval", help="Seconds between scheduler ticks."
    ),
    config_dir: str = typer.Option("config/niches", "--config-dir"),
    db: str = typer.Option("opensocial.db", "--db", help="SQLite database path."),
) -> None:
    """Run the scheduler loop: each tick publishes due slots and drains the
    command queue. An overlap guard skips a tick if the previous one is still
    running. Ctrl-C to stop."""
    import threading

    from apscheduler.schedulers.blocking import BlockingScheduler

    from opensocial.core.settings import resolve_settings

    session_factory = make_session_factory(db)
    with session_factory() as session:
        _mode_banner(resolve_settings(session))
    guard = threading.Lock()

    def tick() -> None:
        # Overlap guard: if the previous tick is still running, skip this one.
        if not guard.acquire(blocking=False):
            return
        try:
            # Re-resolve each tick so dashboard toggles apply without restart.
            with session_factory() as session:
                settings = resolve_settings(session)
            process_commands(session_factory, config_dir=config_dir, settings=settings)
            niches = load_all_niches(config_dir)
            # Resolve any approvals left past their timeout before publishing.
            with session_factory() as session:
                sweep_timeouts(session, {n.slug: n.raw for n in niches})
            for n in niches:
                if not n.enabled:
                    continue
                with session_factory() as session:
                    creds = load_credentials(session, settings)
                    run_due_slots(session, n.slug, n.raw, settings, credentials=creds)
        finally:
            guard.release()

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(tick, "interval", seconds=interval, max_instances=1)
    typer.echo(f"scheduler started (tick every {interval}s) — Ctrl-C to stop")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        typer.echo("scheduler stopped")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8765, "--port"),
    interval: int = typer.Option(
        5, "--interval", help="Seconds between background worker ticks."
    ),
    config_dir: str = typer.Option("config/niches", "--config-dir"),
    db: str = typer.Option("opensocial.db", "--db", help="SQLite database path."),
    verbose: bool = typer.Option(
        False, "--verbose", "-v",
        help="Print each HTTP request and a per-tick worker summary to the console.",
    ),
) -> None:
    """Run the dashboard API plus the background worker in one process.

    The worker drains the dashboard command queue, and (in auto mode) refreshes
    the draft queue on a cadence inside the day's posting window and publishes
    due slots — same as `run`, so a separate scheduler process isn't needed
    while serving the dashboard.

    By default this is quiet (worker activity goes to the logs table / dashboard
    Logs page). Pass --verbose to mirror that activity to the terminal.
    """
    import threading
    import time as time_mod

    import uvicorn

    from opensocial.api import create_app, inject_stored_secrets
    from opensocial.core.settings import resolve_settings

    api = create_app(db, config_dir)
    session_factory = api.state.session_factory
    injected = inject_stored_secrets(session_factory)
    if injected:
        typer.echo(f"loaded {injected} stored secret(s) into the environment")

    stop = threading.Event()
    guard = threading.Lock()

    def tick() -> None:
        if not guard.acquire(blocking=False):
            return
        try:
            with session_factory() as session:
                settings = resolve_settings(session)
            ran = process_commands(
                session_factory, config_dir=config_dir, settings=settings
            )
            # Autopilot: keep the draft queue topped up with fresh data inside
            # the day's posting window (no-op outside the window / manual mode).
            autopilot_refresh(
                session_factory, config_dir=config_dir, settings=settings
            )
            niches = load_all_niches(config_dir)
            with session_factory() as session:
                sweep_timeouts(session, {n.slug: n.raw for n in niches})
            published = 0
            for n in niches:
                if not n.enabled:
                    continue
                with session_factory() as session:
                    creds = load_credentials(session, settings)
                    published += len(
                        run_due_slots(
                            session, n.slug, n.raw, settings, credentials=creds
                        )
                    )
            if verbose and (ran or published):
                typer.echo(
                    f"[{datetime.now():%H:%M:%S}] tick — "
                    f"{ran} command(s) run, {published} post(s) published"
                )
        except Exception as exc:  # the worker must outlive any bad tick
            with session_factory() as session:
                from opensocial.core.db import log as db_log

                db_log(session, "error", f"worker tick failed: {exc}")
                session.commit()
            if verbose:
                typer.echo(f"[{datetime.now():%H:%M:%S}] worker tick failed: {exc}")
        finally:
            guard.release()

    def worker() -> None:
        while not stop.is_set():
            tick()
            stop.wait(interval)

    with session_factory() as session:
        _mode_banner(resolve_settings(session))
    thread = threading.Thread(target=worker, daemon=True, name="opensocial-worker")
    thread.start()
    typer.echo(f"API on http://{host}:{port} — worker tick every {interval}s")
    try:
        uvicorn.run(
            api, host=host, port=port,
            log_level="info" if verbose else "warning",
        )
    finally:
        stop.set()


@app.command()
def sources() -> None:
    """List registered source plugins."""
    for name in available_sources():
        typer.echo(name)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
