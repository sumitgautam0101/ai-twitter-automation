"""Finnhub source via the Finnhub REST API (free key required).

    finnhub:
      category: crypto       # general | forex | crypto | merger (market news)
      # or company news for specific tickers:
      symbols: [AAPL, TSLA]
      limit: 30
      # api_key or env FINNHUB_API_KEY
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import httpx

from opensocial.core.models import ContentItem
from opensocial.sources.base import (
    DEFAULT_TIMEOUT,
    USER_AGENT,
    Source,
    register,
    resolve_api_key,
)

BASE = "https://finnhub.io/api/v1"


@register
class FinnhubSource(Source):
    name = "finnhub"
    category = "finance"

    async def fetch(self) -> list[ContentItem]:
        key = resolve_api_key(self.config, "FINNHUB_API_KEY", source_name=self.name)
        symbols: list[str] = self.config.get("symbols", []) or []
        category: str = self.config.get("category", "general")
        limit: int = int(self.config.get("limit", 30))

        items: list[ContentItem] = []
        async with httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT, headers={"User-Agent": USER_AGENT}
        ) as client:
            if symbols:
                today = date.today()
                frm = today - timedelta(days=7)
                for symbol in symbols:
                    resp = await client.get(
                        f"{BASE}/company-news",
                        params={
                            "symbol": symbol,
                            "from": frm.isoformat(),
                            "to": today.isoformat(),
                            "token": key,
                        },
                    )
                    if resp.status_code == 200:
                        for art in resp.json()[:limit]:
                            items.append(self._to_item(art))
            else:
                resp = await client.get(
                    f"{BASE}/news", params={"category": category, "token": key}
                )
                resp.raise_for_status()
                for art in resp.json()[:limit]:
                    items.append(self._to_item(art))
        return items

    def _to_item(self, art: dict) -> ContentItem:
        ts = art.get("datetime")
        published = (
            datetime.fromtimestamp(ts, tz=timezone.utc)
            if ts
            else datetime.now(timezone.utc)
        )
        image = art.get("image")
        return ContentItem(
            source_name=self.name,
            source_category=self.category,
            title=art.get("headline", ""),
            url=art.get("url", ""),
            summary=art.get("summary") or None,
            author=art.get("source"),
            published_at=published,
            media_urls=[image] if image else [],
            tags=[art["category"]] if art.get("category") else [],
            raw_metadata=art,
        )
