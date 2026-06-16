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
    delete_platform_account,
    delete_workspace,
    get_platform_account,
    get_platform_account_by_label,
    list_platform_accounts,
    make_session_factory,
    store_items,
)
from opensocial.core.engine import (
    load_credentials_for_account,
    publish_post,
    resolve_account_for_niche,
    run_due_slots,
)
from opensocial.core.filtering import candidate_queue, filter_niche
from opensocial.core.generate import generate_for_niche, generate_independent
from opensocial.core.settings import Settings
from opensocial.sources import available_sources, get_source

app = typer.Typer(help="OpenX automation service", no_args_is_help=True)


def _publish_all_workspaces(session_factory, config_dir: str) -> int:
    """Publish due slots for every workspace using its own settings + account.

    Each workspace (X account) publishes the niches it follows under its own
    dry-run / app-mode / cap and as its own account — niches are a shared
    catalog, so two workspaces can follow the same niche and publish
    independently. Falls back to legacy global settings over all niches when no
    workspace exists yet (pre-workspace install). Returns posts published.
    """
    from opensocial.core.db import list_platform_accounts
    from opensocial.core.settings import get_followed_niches, resolve_settings

    niches = load_all_niches(config_dir)
    published = 0
    with session_factory() as s:
        accounts = list_platform_accounts(s)

    if not accounts:
        # Legacy single-setup: one global settings pass over all niches.
        with session_factory() as s:
            settings = resolve_settings(s, None)
        for n in niches:
            if not n.enabled:
                continue
            with session_factory() as s:
                published += len(run_due_slots(s, n.slug, n.raw, settings))
        return published

    for acct in accounts:
        with session_factory() as s:
            ws_settings = resolve_settings(s, acct.id)
            followed = set(get_followed_niches(s, acct.id))
        for n in niches:
            if n.slug not in followed or not n.enabled:
                continue
            with session_factory() as s:
                published += len(
                    run_due_slots(s, n.slug, n.raw, ws_settings, account=acct)
                )
    return published


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
        typer.echo(f"{a.platform}: {a.account_label}{cap}  ({a.id})")


@app.command(name="account-rm")
def account_rm(
    label: str = typer.Option(..., "--label", help="Label of the account to remove."),
    db: str = typer.Option("opensocial.db", "--db", help="SQLite database path."),
) -> None:
    """Remove an enrolled X account by label."""
    session_factory = make_session_factory(db)
    with session_factory() as session:
        acct = get_platform_account_by_label(session, label)
        if acct is None:
            typer.echo(f"no account labelled '{label}'", err=True)
            raise typer.Exit(1)
        delete_platform_account(session, acct.id)
    typer.echo(f"removed X account '{label}'")


@app.command(name="workspace-list")
def workspace_list(
    db: str = typer.Option("opensocial.db", "--db", help="SQLite database path."),
    config_dir: str = typer.Option("config/niches", "--config-dir"),
) -> None:
    """List workspaces (each is an X account) and their followed-niche counts."""
    from opensocial.core.settings import get_followed_niches

    session_factory = make_session_factory(db)
    with session_factory() as session:
        accounts = list_platform_accounts(session)
        if not accounts:
            typer.echo("no workspaces — create one with 'account-add'")
            return
        for a in accounts:
            # Niches are shared; a workspace's count is the niches it follows.
            n = len(get_followed_niches(session, a.id))
            cap = f" cap={a.daily_post_cap}" if a.daily_post_cap else ""
            typer.echo(f"{a.account_label}{cap} — {n} niche(s)  ({a.id})")


@app.command(name="workspace-rm")
def workspace_rm(
    label: str = typer.Option(..., "--label", help="Workspace (account) label."),
    db: str = typer.Option("opensocial.db", "--db", help="SQLite database path."),
    config_dir: str = typer.Option("config/niches", "--config-dir"),
) -> None:
    """Delete a workspace and everything scoped to it (account, its niches,
    drafts, history, and per-workspace settings). The shared content pool and
    sources are left intact."""
    session_factory = make_session_factory(db)
    with session_factory() as session:
        acct = get_platform_account_by_label(session, label)
        if acct is None:
            typer.echo(f"no workspace labelled '{label}'", err=True)
            raise typer.Exit(1)
        deleted = delete_workspace(session, acct.id, config_dir=config_dir)
    typer.echo(f"deleted workspace '{label}': {deleted}")


@app.command(name="niche-account")
def niche_account(
    niche: str = typer.Option(..., "--niche", "-n", help="Niche slug to bind."),
    account: str = typer.Option(
        None, "--account", help="Account label to bind (omit with --clear)."
    ),
    clear: bool = typer.Option(
        False, "--clear", help="Unassign the niche's account instead."
    ),
    config_dir: str = typer.Option("config/niches", "--config-dir"),
    db: str = typer.Option("opensocial.db", "--db", help="SQLite database path."),
) -> None:
    """Bind a niche to an X account (writes ``account_id`` into its JSON config)."""
    import json

    path = Path(config_dir) / f"{niche}.json"
    if not path.exists():
        typer.echo(f"no niche config at {path}", err=True)
        raise typer.Exit(1)

    account_id: str | None = None
    if not clear:
        if not account:
            typer.echo("pass --account <label> or --clear", err=True)
            raise typer.Exit(1)
        session_factory = make_session_factory(db)
        with session_factory() as session:
            acct = get_platform_account_by_label(session, account)
            if acct is None:
                typer.echo(f"no account labelled '{account}'", err=True)
                raise typer.Exit(1)
            account_id = acct.id

    data = json.loads(path.read_text(encoding="utf-8"))
    if clear:
        data.pop("account_id", None)
    else:
        data["account_id"] = account_id
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    if clear:
        typer.echo(f"[{niche}] account unassigned")
    else:
        typer.echo(f"[{niche}] bound to account '{account}'")


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
    """Publish the posts due right now for one or all niches (one-shot).

    Niches are a shared catalog: every workspace publishes the niches it follows
    as its own account under its own settings (dry-run / mode). Falls back to a
    single legacy pass when no workspace exists yet.
    """
    from opensocial.core.db import list_platform_accounts
    from opensocial.core.settings import get_followed_niches, resolve_settings

    niches = _resolve_niches(niche, config_dir)
    session_factory = make_session_factory(db)
    with session_factory() as session:
        accounts = list_platform_accounts(session)

    def _emit(slug: str, outcomes, *, label: str | None = None):
        tag = f"{slug}@{label}" if label else slug
        if not outcomes:
            typer.echo(f"[{tag}] nothing due")
            return
        for o in outcomes:
            verb = "would post" if o.dry_run else ("posted" if o.ok else "FAILED")
            typer.echo(f"[{tag}] {verb} <{o.post_type}> {o.post_id} (${o.cost:.3f})")

    if not accounts:
        with session_factory() as session:
            settings = resolve_settings(session, None)
        for n in niches:
            with session_factory() as session:
                outcomes = run_due_slots(session, n.slug, n.raw, settings)
            _emit(n.slug, outcomes)
        return

    for acct in accounts:
        with session_factory() as session:
            ws_settings = resolve_settings(session, acct.id)
            followed = set(get_followed_niches(session, acct.id))
        for n in niches:
            if n.slug not in followed:
                continue
            with session_factory() as session:
                outcomes = run_due_slots(
                    session, n.slug, n.raw, ws_settings, account=acct
                )
            _emit(n.slug, outcomes, label=acct.account_label)


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
        config = niches[0].raw if niches else {}
        account = (
            get_platform_account(session, post.platform_account_id)
            if post.platform_account_id
            else None
        ) or resolve_account_for_niche(session, config)
        if account is None and not settings.dry_run:
            typer.echo(
                f"[{post.niche_slug}] no account assigned — cannot publish",
                err=True,
            )
            raise typer.Exit(1)
        account_id = account.id if account is not None else None
        creds = (
            load_credentials_for_account(session, settings, account_id)
            if account_id
            else None
        )
        outcome = publish_post(
            session, post, config, settings, credentials=creds,
            platform_account_id=account_id,
        )
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
            process_commands(session_factory, config_dir=config_dir)
            niches = load_all_niches(config_dir)
            # Resolve any approvals left past their timeout before publishing.
            with session_factory() as session:
                sweep_timeouts(session, {n.slug: n.raw for n in niches})
            # Publish per workspace, each under its own settings + account.
            _publish_all_workspaces(session_factory, config_dir)
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
            ran = process_commands(session_factory, config_dir=config_dir)
            # Autopilot: keep the draft queue topped up with fresh data inside
            # the posting window (no-op outside the window / no auto workspaces).
            # Fetch is shared; generation runs per auto-mode workspace.
            autopilot_refresh(session_factory, config_dir=config_dir)
            niches = load_all_niches(config_dir)
            with session_factory() as session:
                sweep_timeouts(session, {n.slug: n.raw for n in niches})
            # Publish per workspace, each under its own settings + account.
            published = _publish_all_workspaces(session_factory, config_dir)
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
