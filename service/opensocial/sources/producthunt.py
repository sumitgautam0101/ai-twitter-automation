"""ProductHunt source via the API v2 GraphQL endpoint (token required).

    producthunt:
      limit: 20
      # api_key or env PRODUCTHUNT_TOKEN (developer token from
      # https://www.producthunt.com/v2/oauth/applications)
"""

from __future__ import annotations

import httpx

from opensocial.core.models import ContentItem
from opensocial.sources.base import (
    DEFAULT_TIMEOUT,
    USER_AGENT,
    Source,
    parse_iso8601,
    register,
    resolve_api_key,
)

API_URL = "https://api.producthunt.com/v2/api/graphql"

_QUERY = """
query ($n: Int!) {
  posts(first: $n, order: RANKING) {
    edges {
      node {
        id name tagline description url votesCount commentsCount createdAt
        thumbnail { url }
        topics(first: 5) { edges { node { name } } }
      }
    }
  }
}
"""


@register
class ProductHuntSource(Source):
    name = "producthunt"
    category = "business"

    async def fetch(self) -> list[ContentItem]:
        token = resolve_api_key(
            self.config, "PRODUCTHUNT_TOKEN", source_name=self.name
        )
        limit = int(self.config.get("limit", 20))

        async with httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT, headers={"User-Agent": USER_AGENT}
        ) as client:
            resp = await client.post(
                API_URL,
                json={"query": _QUERY, "variables": {"n": limit}},
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            data = resp.json()

        items: list[ContentItem] = []
        edges = (
            data.get("data", {}).get("posts", {}).get("edges", [])
            if data.get("data")
            else []
        )
        for edge in edges:
            node = edge.get("node", {})
            thumb = (node.get("thumbnail") or {}).get("url")
            topics = [
                t["node"]["name"]
                for t in node.get("topics", {}).get("edges", [])
                if t.get("node")
            ]
            items.append(
                ContentItem(
                    source_name=self.name,
                    source_category=self.category,
                    title=node.get("name", ""),
                    url=node.get("url", ""),
                    summary=node.get("tagline"),
                    body=node.get("description"),
                    published_at=parse_iso8601(node.get("createdAt")),
                    media_urls=[thumb] if thumb else [],
                    tags=topics,
                    engagement={
                        "votes": node.get("votesCount"),
                        "comments": node.get("commentsCount"),
                    },
                    raw_metadata=node,
                )
            )
        return items
