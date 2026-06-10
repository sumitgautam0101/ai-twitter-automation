# OpenSocial — Architecture Plan

## Context

OpenSocial is an open-source, plugin-based tool for automated, AI-driven posting to **X (Twitter)**. Any "niche" (crypto, tech, finance, etc.) can be configured with its own content sources, AI persona/prompts, posting schedule with anti-bot randomness, optional Telegram approval workflow, and a dashboard for full configuration.



## Tech Stack

| Concern | Choice | Why |
|---|---|---|
| Language/runtime | Python 3.12, asyncio | Every library needed (X API, AI, Telegram) is Python-first; runs on a cheap VPS or Raspberry Pi |
| HTTP client | httpx (async) | Concurrent fetching across all sources |
| Reddit | asyncpraw | Official async fork of PRAW |
| RSS/Atom | feedparser | Universal parser for the generic RSS plugin |
| YouTube | google-api-python-client + youtube-transcript-api | Channel data + transcripts |
| Scheduler | APScheduler (async, DB-backed job store) | Persists jobs in the same SQLite database, no Redis/Celery needed |
| Database | SQLite | Single file, zero-config, shared directly with the separate dashboard project |
| AI text | LiteLLM | One interface across OpenAI/Anthropic/Gemini/Ollama — fully swappable providers |
| AI images | Pollinations.ai (free, default) + Replicate/DALL-E as paid options | Zero-cost default image generation |
| Stock images | Pixabay (default), Unsplash, Pexels | Free, no attribution required for Pixabay |
| X posting | Tweepy | Covers posting + media upload |
| Telegram | python-telegram-bot (async) | Notifications + approval queue with inline buttons | 
| Secrets | Encrypted at rest (Fernet) | API keys and platform credentials stored encrypted, key from an environment variable |

---

## High-Level Structure

The system is organized as a set of plugin packages built around a shared "content item" format:

- **Sources** — one plugin per content source (or a generic RSS plugin reused across many feeds). Each plugin fetches and normalizes content into a common format. Adding a new source means adding a new plugin, with no changes elsewhere.
- **AI (text)** — generates post text from a content item and a niche's persona/prompt, via a swappable AI provider (Ollama by default — no API key required).
- **AI (images)** — supplies an image for a post, either AI-generated or from a stock photo provider, behind a single interface.
- **Publisher** — posts to X (via Tweepy), built behind a publisher interface so other platforms could be added later as additional plugins.
- **Scheduler** — decides when posts go out, with randomized timing/jitter to avoid bot-like patterns, and enforces daily post limits.
- **Telegram bot** — sends notifications and, optionally, an approval queue (approve/edit/regenerate/reject) before anything is posted.
- **Core** — shared data models, the SQLite database layer, and the pipeline that ties fetch → filter → generate → schedule → publish together.

---

## Project Structure

OpenSocial is split into two independently-deployable projects sharing one SQLite database:

- **service** (Python) — everything described above in High-Level Structure: source plugins, filtering/dedup, AI text & image generation, the X publisher, scheduler, Telegram bot, and CLI. It's the only component that writes to `content_items`, `generated_posts`, and `post_history`, and it reads the configuration tables to know what to do.
- **ui** (React/Next.js, separate project) — the dashboard described later in this plan. It writes only to the configuration tables (niche profiles, source settings, secrets, platform accounts, Telegram chats) and reads everything for display (queue, history, cost tracking, live config). It contains no automation logic.

This split keeps automation and configuration cleanly separated: `service` owns *what happens*, `ui` owns *what's configured* and *what's shown*.

---

## Core Data Model

Every source plugin returns content normalized into a common "content item" shape, which is the only thing the rest of the pipeline understands. It includes: a stable ID (used for de-duplication), the source name/category, title, body/summary text, URL, author, published/fetched timestamps, any media URLs, tags, language, an optional sentiment score, optional engagement stats (e.g. score/comments), and the raw original data for reference.

AI generation always works from this normalized item — it never needs to know which source it came from.

**Field availability varies by source.** Full `body` text is available from Reddit, YouTube (via transcript), Medium/Decrypt/The Block/YC Blog (via `content:encoded`), Dev.to, GitHub Releases, and the Guardian; the rest (GDELT, CoinDesk, Reuters/MarketWatch, WHO, Nature/PhysOrg/Futurism, HBR, ArXiv, Finnhub, yfinance, ProductHunt, NASA) only provide a `summary`/excerpt — so the standard fallback is `content_for_ai = item.body or item.summary or item.title`. `sentiment` is natively populated only by GDELT (`tone` score, normalized to -1..1); every other source leaves it null. `engagement` is a flexible JSON dict whose shape differs per source (Reddit: score/comments/upvote_ratio; YouTube: views/likes/comments; Hacker News: score/comments; Dev.to: reactions/comments/reading_time; ProductHunt: votes/comments; GitHub Releases: downloads) — most RSS-based sources leave it null. `language` is rarely provided per item (GDELT and the Guardian are exceptions) and otherwise defaults to `en`.

---

## Content Sources (24)

**Universal**
- GDELT DOC 2.0 API — global news/trend feed with sentiment scoring (replaces Google News RSS)
- Reddit (PRAW)
- YouTube Data API (with transcripts)
- Generic RSS parser (reused for most RSS-based sources below)
- Medium RSS (by tag)

**Tech & Dev**
- Hacker News API
- Dev.to API
- GitHub Releases (via GitHub REST API)
- ProductHunt API (requires applying for API access)
- ArXiv API

**Crypto**
- Decrypt RSS
- CoinDesk RSS
- The Block RSS

**Finance**
- Finnhub API
- Yahoo Finance / yfinance (unofficial, falls back to Finnhub)
- Reuters / MarketWatch RSS

**News & Politics**
- The Guardian API

**Health & Science**
- WHO RSS
- NASA API
- Nature / PhysOrg / Futurism RSS

**Business & Startups**
- ProductHunt API (shared with Tech & Dev)
- Indie Hackers RSS
- Y Combinator Blog RSS
- HBR RSS

---

## Niche Profiles

Each niche (e.g. "crypto", "tech") is a configuration profile that defines:

- **Persona** — voice/tone and the prompt template used to turn a content item into a post (instructed to write standalone text, not assuming a link will be attached).
- **AI settings** — which text provider/model to use, and how images are sourced (AI-generated, stock photo, or none).
- **Filters** — keyword blocklist, relevance keywords/threshold, and age limits for content.
- **Sources** — which of the 24 sources are enabled for this niche, with source-specific settings (subreddits, channel IDs, feed URLs, search queries, poll intervals).
- **Schedule** — posting time windows, posts-per-day range, minimum gap between posts, and random jitter.
- **Approval** — whether posts require Telegram approval before publishing, and what happens on timeout.
- **Posting** — whether the post includes the source link (off by default, to keep X cost at $0.015/post).

The dashboard lets users create new niches from starter templates (crypto, tech, finance, science, news, business) and edit every one of these settings.

---

## Pipeline / Data Flow

1. **Fetch** — each enabled source is polled on its own schedule; new items are de-duplicated and stored, then linked to whichever niches they're relevant to.
2. **Filter** — each niche applies its blocklist/keyword/age filters and a near-duplicate check against recently seen content, marking items as candidates, filtered, or duplicates.
3. **Generate** — for each niche, the highest-priority candidates (by recency, engagement, sentiment match) are turned into draft post text via the niche's persona/prompt, and an image is attached if configured.
4. **Schedule** — each niche gets a random number of posts for the day (within its configured range), placed at random times within its posting windows, respecting minimum gaps and jitter.
5. **Publish** — when a scheduled slot fires, if approval is required the post is sent to Telegram for review; otherwise (or once approved) it's posted to X, with the source link included or omitted per the niche's setting, and the result (success/failure, cost) is recorded.

A global daily post cap acts as a cross-niche safety net on top of each niche's own posting limits.

---

## Database Schema

SQLite tables (SQLAlchemy models + Alembic migrations). JSON columns are stored as serialized text. Each table is tagged with the build phase that introduces it.

```sql
-- Phase 1
content_items (
  id              TEXT PRIMARY KEY,   -- sha256(source_name + url)
  source_name     TEXT NOT NULL,
  source_category TEXT NOT NULL,
  title           TEXT NOT NULL,
  body            TEXT,               -- full text/transcript/abstract, when the source provides it
  summary         TEXT,
  url             TEXT NOT NULL,
  author          TEXT,
  published_at    DATETIME NOT NULL,
  fetched_at      DATETIME NOT NULL,
  media_urls      JSON,               -- list[str]
  tags            JSON,               -- list[str]
  language        TEXT DEFAULT 'en',
  sentiment       REAL,               -- -1..1; populated only by GDELT today
  engagement      JSON,               -- shape varies per source, e.g. {"score":, "comments":}
  raw_metadata    JSON NOT NULL       -- full original API/feed item, for forward-compat
)

content_item_niches (
  content_item_id TEXT NOT NULL REFERENCES content_items(id),
  niche_slug      TEXT NOT NULL,
  status          TEXT NOT NULL,      -- candidate | filtered | duplicate
  relevance_score REAL,
  PRIMARY KEY (content_item_id, niche_slug)
)

niche_profiles (
  slug          TEXT PRIMARY KEY,
  display_name  TEXT NOT NULL,
  enabled       BOOLEAN NOT NULL DEFAULT 1,
  config_yaml   TEXT NOT NULL,        -- full niche config (source of truth, also mirrored on disk)
  updated_at    DATETIME NOT NULL
)

source_configs (
  source_name       TEXT PRIMARY KEY,
  enabled_globally  BOOLEAN NOT NULL DEFAULT 1,
  last_fetch_at     DATETIME,
  last_fetch_status TEXT,
  extra_config      JSON
)

-- Phase 3
generated_posts (
  id                TEXT PRIMARY KEY,
  content_item_id   TEXT REFERENCES content_items(id),
  niche_slug        TEXT NOT NULL,
  text              TEXT NOT NULL,
  media_path        TEXT,
  media_url         TEXT,
  media_attribution TEXT,
  ai_text_provider  TEXT NOT NULL,
  ai_image_provider TEXT,
  status            TEXT NOT NULL,    -- draft | scheduled | pending_approval | approved | rejected | published | failed
  scheduled_at      DATETIME,
  created_at        DATETIME NOT NULL,
  updated_at        DATETIME NOT NULL
)

-- Phase 4
platform_accounts (
  id                    TEXT PRIMARY KEY,
  platform              TEXT NOT NULL DEFAULT 'x',
  account_label         TEXT NOT NULL,
  credentials_encrypted BLOB NOT NULL,
  daily_post_cap        INTEGER
)

post_history (
  id                    TEXT PRIMARY KEY,
  generated_post_id     TEXT NOT NULL REFERENCES generated_posts(id),
  platform              TEXT NOT NULL DEFAULT 'x',
  platform_account_id   TEXT NOT NULL REFERENCES platform_accounts(id),
  platform_post_id      TEXT,
  platform_post_url     TEXT,
  status                TEXT NOT NULL,  -- success | failed
  error_message         TEXT,
  attempted_at          DATETIME NOT NULL,
  included_source_link  BOOLEAN NOT NULL,
  cost_estimate         REAL NOT NULL
)

api_keys (
  key_name        TEXT PRIMARY KEY,
  value_encrypted BLOB NOT NULL,
  updated_at      DATETIME NOT NULL
)

-- Phase 5
telegram_chats (
  chat_id       TEXT PRIMARY KEY,
  role          TEXT NOT NULL,  -- notifications | approval | both
  registered_at DATETIME NOT NULL
)
```

---

## Telegram Bot

Provides status commands (active niches, upcoming posts, pending approvals) and pause/resume per niche.

When approval is required, each draft post is sent as a card with the generated text, image, and source attribution, with buttons to approve, edit (reply with new text), regenerate (re-run AI generation), or reject. Unapproved posts can either auto-publish or be discarded after a configurable timeout.

---

## Dashboard (Separate Project)

The web dashboard (niche configuration, source management, schedule/queue view, post history, cost tracking, secrets) will be built as a **separate React/Next.js project**. It reads from and writes to the same SQLite database as the automation engine directly — no separate API layer initially. Detailed dashboard design is out of scope for this plan.

---

## Cost Tracking

Cost per post is recorded in `post_history.cost_estimate` as $0.015 (text-only) or $0.20 (with link), plus $0.001 per analytics read. The dashboard sums these for spend tracking and shows the cost difference live when toggling whether a post includes the source link.

---

## Build Phasing

**Phase 1 — Sources**
Core data models (`ContentItem`) and database tables for `content_items` and `content_item_niches`; the source plugin framework (`Source` ABC + registry) and the generic RSS plugin; a first set of real plugins covering each source category (e.g. generic RSS, Hacker News, GDELT, Reddit, YouTube) to prove the pattern across both API- and feed-based sources; one simplified niche profile (with the user-selected subreddits/YouTube channels and category-based source toggles); and a CLI command to fetch and store content, de-duplicated across repeat runs.

**Phase 2 — Data Extraction & Prioritization**
Filtering (keyword blocklist, relevance keywords/threshold, age limits) and near-duplicate detection against recently seen content, marking each item as candidate, filtered, or duplicate; candidate prioritization by recency, engagement, and sentiment match, producing an ordered queue of candidates per niche.

**Phase 3 — Post Creation**
AI text generation via LiteLLM (Ollama by default, no API key needed) that turns prioritized candidates into standalone, no-link draft posts via the niche's persona/prompt; AI/stock image attachment; the `generated_posts` table; and CLI commands to generate drafts and preview (dry-run) what would be published.

**Phase 4 — Automation**
The X publisher (Tweepy, text-only by default per the cost strategy); the scheduler (APScheduler) with randomized posting windows, jitter, and per-niche/global frequency caps; the `post_history` table and cost tracking; remaining source plugins and niche templates (crypto, finance, science, news, business) so every content category is fully populated.

**Phase 5 — Telegram**
Telegram bot notifications, then the full approval queue (approve/edit/regenerate/reject) with timeout handling. At this point the pipeline runs unattended end-to-end with optional human-in-the-loop review.

The `ui` dashboard (separate React/Next.js project — see "Project Structure") is developed in parallel once the database schema stabilizes after Phase 3; it has no dependency on the automation/Telegram work since it only reads and writes configuration tables.

---

## Verification

- **Phase 1**: Fetching a niche pulls content from its enabled sources, normalizes it to `ContentItem`, and stores it without creating duplicates on repeat runs.
- **Phase 2**: Filtering and de-duplication correctly mark items as candidate/filtered/duplicate, and the resulting candidate queue is ordered by recency, engagement, and sentiment match.
- **Phase 3**: Generating posts for a niche produces draft text via the AI provider that reads as a standalone post (no dangling "read more"/link references), confirming the no-link-by-default design; a dry-run publish step prints what would be posted without calling the real X API; an automated test covers fetch → filter → generate end-to-end using a mocked AI response.
- **Phase 4**: A scheduled post fires at a randomized time within its niche's posting window, respects the minimum gap/jitter and daily caps, and records a `post_history` row with the correct cost estimate.
- **Phase 5**: A draft requiring approval is sent to Telegram with working approve/edit/regenerate/reject buttons, and the configured timeout behavior (auto-post or discard) fires correctly.
