"""OpenSocial CLI.

Phase 1 commands:
  * ``fetch``   — poll a niche's enabled sources and store new content
  * ``sources`` — list registered source plugins

Phase 2 commands:
  * ``filter``  — apply a niche's filters + near-dup detection to stored content
  * ``queue``   — print a niche's prioritized candidate queue
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from opensocial.core.config import NicheConfig, load_all_niches, load_niche
from opensocial.core.db import make_session_factory, store_items
from opensocial.core.filtering import candidate_queue, filter_niche
from opensocial.sources import available_sources, get_source

app = typer.Typer(help="OpenSocial automation service", no_args_is_help=True)


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


@app.command()
def sources() -> None:
    """List registered source plugins."""
    for name in available_sources():
        typer.echo(name)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
