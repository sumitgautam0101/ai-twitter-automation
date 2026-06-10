"""NASA source via the Astronomy Picture of the Day (APOD) API.

    nasa:
      count: 5            # number of random recent APOD entries
      # optional: api_key or env NASA_API_KEY (falls back to DEMO_KEY)
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from opensocial.core.models import ContentItem
from opensocial.sources.base import (
    DEFAULT_TIMEOUT,
    USER_AGENT,
    Source,
    register,
    resolve_api_key,
)

API_URL = "https://api.nasa.gov/planetary/apod"


def _parse_date(value: str | None) -> datetime:
    if value:
        try:
            return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


@register
class NasaSource(Source):
    name = "nasa"
    category = "science"

    async def fetch(self) -> list[ContentItem]:
        key = resolve_api_key(
            self.config, "NASA_API_KEY", required=False, source_name=self.name
        ) or "DEMO_KEY"
        count = int(self.config.get("count", self.config.get("limit", 5)))

        async with httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT, headers={"User-Agent": USER_AGENT}
        ) as client:
            resp = await client.get(API_URL, params={"api_key": key, "count": count})
            resp.raise_for_status()
            data = resp.json()

        # A single-date request returns a dict; count/date-range returns a list.
        entries = data if isinstance(data, list) else [data]
        items: list[ContentItem] = []
        for apod in entries:
            title = apod.get("title")
            media = apod.get("hdurl") or apod.get("url")
            if not title or not media:
                continue
            items.append(
                ContentItem(
                    source_name=self.name,
                    source_category=self.category,
                    title=title,
                    url=media,
                    summary=apod.get("explanation"),
                    body=apod.get("explanation"),
                    author=apod.get("copyright"),
                    published_at=_parse_date(apod.get("date")),
                    media_urls=[apod["url"]] if apod.get("url") else [],
                    tags=[apod.get("media_type")] if apod.get("media_type") else [],
                    raw_metadata=apod,
                )
            )
        return items
