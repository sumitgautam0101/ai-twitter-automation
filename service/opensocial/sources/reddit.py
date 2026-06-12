"""Reddit source via the public Atom feeds (no key required).

Reddit blocks unauthenticated access to the ``.json`` listing endpoints with a
403 anti-bot page, but the equivalent ``.rss`` (Atom) feeds remain open. We
fetch ``/r/<sub>/<sort>/.rss`` per subreddit and parse it with feedparser.

Tradeoff vs. the OAuth API: Atom feeds carry the title, link, author, timestamp
and post body, but **not** the score / comment counts, so ``engagement`` is
left empty (prioritization simply treats those signals as absent).

    reddit:
      subreddits: [cryptocurrency, bitcoin]
      sort: hot              # hot | new | top | rising
      limit: 25
      time: day             # only for sort=top: hour | day | week | month | year | all

Reddit rejects the default httpx/library User-Agent, so we send a browser-like
one. Stay within ~10 subreddits per fetch to avoid the unauthenticated 429.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import feedparser
import httpx

from opensocial.core.models import ContentItem
from opensocial.sources.base import DEFAULT_TIMEOUT, Source, register
from opensocial.sources.rss import struct_to_dt

_SORTS = {"hot", "new", "top", "rising"}
# Reddit serves an anti-bot block page to library User-Agents; a browser UA
# (plus the .rss path) is accepted for unauthenticated reads.
_REDDIT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_IMG_RE = re.compile(r'<img[^>]+src="([^"]+)"', re.I)


@register
class RedditSource(Source):
    name = "reddit"
    category = "social"

    async def fetch(self) -> list[ContentItem]:
        subreddits: list[str] = self.config.get("subreddits", []) or []
        sort: str = self.config.get("sort", "hot")
        if sort not in _SORTS:
            sort = "hot"
        limit: int = int(self.config.get("limit", 25))
        time_filter: str = self.config.get("time", "day")

        params: dict[str, str | int] = {"limit": limit}
        if sort == "top":
            params["t"] = time_filter

        items: list[ContentItem] = []
        async with httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            headers={"User-Agent": _REDDIT_UA},
            follow_redirects=True,
        ) as client:
            for name in subreddits:
                url = f"https://www.reddit.com/r/{name}/{sort}/.rss"
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                parsed = feedparser.parse(resp.content)
                for entry in parsed.entries:
                    item = self._to_item(entry, name)
                    if item is not None:
                        items.append(item)
        return items

    def _to_item(self, entry, subreddit: str) -> ContentItem | None:
        url = entry.get("link")
        title = entry.get("title")
        if not url or not title:
            return None

        body = None
        contents = entry.get("content")
        if contents:
            body = contents[0].get("value")

        media: list[str] = []
        if body:
            m = _IMG_RE.search(body)
            if m and m.group(1).startswith("http"):
                media.append(m.group(1))

        author = entry.get("author")  # e.g. "/u/someone"
        published = struct_to_dt(
            entry.get("published_parsed") or entry.get("updated_parsed")
        ) or datetime.now(timezone.utc)

        return ContentItem(
            source_name=self.name,
            source_category=self.category,
            title=title,
            url=url,
            body=body,
            author=author,
            published_at=published,
            media_urls=media,
            tags=[subreddit],
            engagement={},  # Atom feeds don't expose score / comment counts
            raw_metadata={
                "id": entry.get("id"),
                "subreddit": subreddit,
                "permalink": url,
            },
        )
