# OpenSocial — service

The Python automation engine for OpenSocial. See [../project.md](../project.md)
for the full architecture. Implemented so far:

* **Phase 1 (Sources)** — the `ContentItem` model, SQLite storage, the source
  plugin framework, all source plugins, and a CLI to fetch & store
  de-duplicated content.
* **Phase 2 (Filtering & Prioritization)** — per-niche keyword blocklist,
  relevance keywords/threshold, age limits, near-duplicate detection, and a
  prioritized candidate queue.

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

# Filter stored content -> mark candidate / filtered / duplicate
python -m opensocial filter --niche crypto

# Show the prioritized candidate queue (best-first)
python -m opensocial queue --niche crypto --limit 20
```

Re-running `fetch` only stores genuinely new items — content is de-duplicated
by `sha256(source_name + url)`, so repeat runs won't create duplicates.

## Filtering & prioritization (Phase 2)

`filter` walks every stored item linked to a niche and sets its status in
`content_item_niches`:

* **filtered** — contains a blocklisted keyword, fails the relevance-keyword
  threshold, or is older than `max_age_days`.
* **duplicate** — title is a near-duplicate (Jaccard ≥ `dup_threshold`) of an
  already-accepted candidate, i.e. the same story reprinted elsewhere. The
  earliest-published copy is kept.
* **candidate** — survived everything; gets a `relevance_score`.

`queue` then orders the candidates by a weighted blend of recency (half-life
decay), engagement (log-scaled, normalized across the set), and how closely
sentiment matches the niche's `sentiment_target` (off unless configured).

Both are driven by per-niche config blocks:

```jsonc
"filters": {
  "blocklist": ["giveaway", "nsfw"],
  "relevance_keywords": ["ai", "open source", "model"],
  "relevance_threshold": 1,      // min keyword hits to be relevant
  "max_age_days": 7,
  "dup_threshold": 0.8           // 0..1 title similarity = duplicate
},
"prioritization": {
  "recency_weight": 0.5,
  "engagement_weight": 0.35,
  "sentiment_weight": 0.15,
  "half_life_hours": 24,
  "sentiment_target": null       // e.g. 1.0 to favor positive items
}
```

An empty `relevance_keywords` list means every (non-blocked, in-age) item is
relevant — useful for broad niches like `news`.

## Tests

```powershell
python -m pytest
```

`tests/test_filtering.py` covers blocklist/relevance/age, near-duplicate
detection, queue ordering, and sentiment matching against an in-memory DB.

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
    filtering.py  # Phase 2: filters, near-dup detection, prioritization
  sources/
    base.py       # Source ABC + registry, key/timestamp helpers
    rss.py        # generic RSS/Atom + reusable feed helpers
    <plugin>.py   # one module per source (see table above)
  cli.py          # `fetch`, `filter`, `queue`, `sources`
config/niches/
  *.json          # niche templates
tests/
  test_filtering.py
```

## Adding a source

Subclass `Source`, set `name` + `category`, implement `async def fetch()`
returning `ContentItem`s, and decorate with `@register`. Import it in
`sources/__init__.py`. Nothing else changes.
