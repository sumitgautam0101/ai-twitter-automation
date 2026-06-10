"""GDELT DOC 2.0 source — global news/trend feed (no key required).

    gdelt:
      query: cryptocurrency
      limit: 30

GDELT's ``ArtList`` mode returns article metadata (title, url, domain,
seendate, socialimage, language). Per-article tone is not exposed by this
mode, so ``sentiment`` is left null here until a richer mode is wired in.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from opensocial.core.models import ContentItem
from opensocial.sources.base import DEFAULT_TIMEOUT, USER_AGENT, Source, register

API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


def _parse_seendate(value: str | None) -> datetime:
    # GDELT seendate format: "20240115T123000Z"
    if value:
        try:
            return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            pass
    return datetime.now(timezone.utc)


@register
class GDELTSource(Source):
    name = "gdelt"
    category = "news"

    async def fetch(self) -> list[ContentItem]:
        query: str = self.config.get("query", "")
        limit: int = int(self.config.get("limit", 30))

        params = {
            "query": query,
            "mode": "ArtList",
            "format": "json",
            "maxrecords": limit,
            "sort": "DateDesc",
        }
        async with httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT, headers={"User-Agent": USER_AGENT}
        ) as client:
            resp = await client.get(API_URL, params=params)
            resp.raise_for_status()
            try:
                data = resp.json()
            except ValueError:
                # GDELT returns plain-text errors (e.g. rate limiting) non-JSON
                return []

        items: list[ContentItem] = []
        for art in data.get("articles", []) or []:
            url = art.get("url")
            title = art.get("title")
            if not url or not title:
                continue

            social_image = art.get("socialimage")
            items.append(
                ContentItem(
                    source_name=self.name,
                    source_category=self.category,
                    title=title,
                    url=url,
                    author=art.get("domain"),
                    published_at=_parse_seendate(art.get("seendate")),
                    media_urls=[social_image] if social_image else [],
                    language=art.get("language", "en") or "en",
                    raw_metadata=art,
                )
            )
        return items
