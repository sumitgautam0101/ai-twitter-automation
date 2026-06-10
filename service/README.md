# OpenSocial — service

The Python automation engine for OpenSocial. See [../project.md](../project.md)
for the full architecture. This is **Phase 1 (Sources)**: the `ContentItem`
model, SQLite storage, the source plugin framework, all source plugins, and a
CLI to fetch & store de-duplicated content.

## Setup

```powershell
cd service
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Usage

Run from the `service/` directory:

```powershell
# List registered source plugins
python -m opensocial sources

# Fetch all niches in config/niches/ into opensocial.db
python -m opensocial fetch

# Fetch a single niche
python -m opensocial fetch --niche crypto
```

Re-running `fetch` only stores genuinely new items — content is de-duplicated
by `sha256(source_name + url)`, so repeat runs won't create duplicates.

## Sources

All 24 sources from [../project.md](../project.md) are covered by 14 plugins —
the RSS-based ones (Decrypt, CoinDesk, The Block, Reuters/MarketWatch, WHO,
Nature/PhysOrg/Futurism, Indie Hackers, YC Blog, HBR) share the generic `rss`
plugin via per-niche feed lists.

| Plugin | `name` | Key? | Env var(s) |
|---|---|---|---|
| Generic RSS/Atom | `rss` | no | — |
| Hacker News (Algolia) | `hackernews` | no | — |
| GDELT DOC 2.0 | `gdelt` | no | — |
| Medium (RSS by tag) | `medium` | no | — |
| Dev.to (Forem API) | `devto` | no | — |
| GitHub Releases | `github_releases` | optional | `GITHUB_TOKEN` |
| ArXiv API | `arxiv` | no | — |
| NASA APOD | `nasa` | optional | `NASA_API_KEY` (DEMO_KEY fallback) |
| Yahoo Finance | `yfinance` | no | — |
| Reddit (asyncpraw) | `reddit` | **yes** | `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` |
| YouTube Data API | `youtube` | **yes** | `YOUTUBE_API_KEY` |
| ProductHunt API v2 | `producthunt` | **yes** | `PRODUCTHUNT_TOKEN` |
| Finnhub | `finnhub` | **yes** | `FINNHUB_API_KEY` |
| The Guardian | `guardian` | **yes** | `GUARDIAN_API_KEY` |

Key-required sources are wired into the niche templates with `"enabled": false`.
Add credentials (env var or a per-source `"api_key"` in the niche JSON), flip
`enabled` to `true`, and re-run. Until then they're skipped; if enabled without
a key they fail with a clear message and the rest of the run continues.

## Niche templates

`config/niches/` ships `crypto`, `tech`, `finance`, `science`, `news`, and
`business`. Each names the sources it pulls from with per-source settings
(feeds, queries, subreddits, symbols, limits).

## Layout

```
opensocial/
  core/
    models.py     # ContentItem — the normalized content format
    db.py         # SQLAlchemy models + idempotent storage
    config.py     # niche JSON loading
  sources/
    base.py       # Source ABC + registry, key/timestamp helpers
    rss.py        # generic RSS/Atom + reusable feed helpers
    <plugin>.py   # one module per source (see table above)
  cli.py          # `fetch`, `sources`
config/niches/
  *.json          # niche templates
```

## Adding a source

Subclass `Source`, set `name` + `category`, implement `async def fetch()`
returning `ContentItem`s, and decorate with `@register`. Import it in
`sources/__init__.py`. Nothing else changes.
