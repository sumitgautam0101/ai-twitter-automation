# OpenSocial — service

The Python automation engine for OpenSocial. See [../project.md](../project.md)
for the full architecture. This is **Phase 1 (Sources)**: the `ContentItem`
model, SQLite storage, the source plugin framework, three real plugins
(generic RSS, Hacker News, GDELT), and a CLI to fetch & store de-duplicated
content.

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

## Layout

```
opensocial/
  core/
    models.py     # ContentItem — the normalized content format
    db.py         # SQLAlchemy models + idempotent storage
    config.py     # niche YAML loading
  sources/
    base.py       # Source ABC + registry (@register)
    rss.py        # generic RSS/Atom (reused across feed sources)
    hackernews.py # Algolia HN Search API
    gdelt.py      # GDELT DOC 2.0 API
  cli.py          # `fetch`, `sources`
config/niches/
  crypto.yaml     # one simplified Phase 1 niche
```

## Adding a source

Subclass `Source`, set `name` + `category`, implement `async def fetch()`
returning `ContentItem`s, and decorate with `@register`. Import it in
`sources/__init__.py`. Nothing else changes.
