"""Generic RSS/Atom source — reused across most feed-based sources.

Configure with a list of feed URLs and the category to tag items with:

    rss:
      category: crypto
      feeds:
        - https://decrypt.co/feed
        - https://www.coindesk.com/arc/outboundfeeds/rss/
"""

from __future__ import annotations

import calendar
from datetime import datetime, timezone

import feedparser
import httpx

from opensocial.core.models import ContentItem
from opensocial.sources.base import DEFAULT_TIMEOUT, USER_AGENT, Source, register


def _struct_to_dt(struct_time) -> datetime | None:
    if not struct_time:
        return None
    return datetime.fromtimestamp(calendar.timegm(struct_time), tz=timezone.utc)


def _entry_media(entry) -> list[str]:
    urls: list[str] = []
    for media in getattr(entry, "media_content", []) or []:
        if media.get("url"):
            urls.append(media["url"])
    for enc in getattr(entry, "enclosures", []) or []:
        if enc.get("href"):
            urls.append(enc["href"])
    return urls


@register
class RSSSource(Source):
    name = "rss"
    category = "generic"

    async def fetch(self) -> list[ContentItem]:
        feeds: list[str] = self.config.get("feeds", []) or []
        category: str = self.config.get("category", self.category)

        items: list[ContentItem] = []
        async with httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as client:
            for feed_url in feeds:
                try:
                    resp = await client.get(feed_url)
                    resp.raise_for_status()
                except httpx.HTTPError:
                    continue
                parsed = feedparser.parse(resp.content)
                for entry in parsed.entries:
                    item = self._to_item(entry, category)
                    if item is not None:
                        items.append(item)
        return items

    def _to_item(self, entry, category: str) -> ContentItem | None:
        url = entry.get("link")
        title = entry.get("title")
        if not url or not title:
            return None

        published = _struct_to_dt(
            entry.get("published_parsed") or entry.get("updated_parsed")
        ) or datetime.now(timezone.utc)

        body = None
        contents = entry.get("content")
        if contents:
            body = contents[0].get("value")

        tags = [t.get("term") for t in entry.get("tags", []) if t.get("term")]

        return ContentItem(
            source_name=self.name,
            source_category=category,
            title=title,
            url=url,
            body=body,
            summary=entry.get("summary"),
            author=entry.get("author"),
            published_at=published,
            media_urls=_entry_media(entry),
            tags=tags,
            raw_metadata=dict(entry),
        )
