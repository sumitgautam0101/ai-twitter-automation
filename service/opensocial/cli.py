"""OpenSocial CLI.

Phase 1 commands:
  * ``fetch``   — poll a niche's enabled sources and store new content
  * ``sources`` — list registered source plugins
"""

from __future__ import annotations

import asyncio

import typer

from opensocial.core.config import NicheConfig, load_all_niches, load_niche
from opensocial.core.db import make_session_factory, store_items
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
    if niche:
        from pathlib import Path

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

    asyncio.run(_run_fetch(niches, db))


@app.command()
def sources() -> None:
    """List registered source plugins."""
    for name in available_sources():
        typer.echo(name)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
