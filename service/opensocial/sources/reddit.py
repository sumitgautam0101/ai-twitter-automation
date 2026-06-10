"""Reddit source via asyncpraw (read-only; app credentials required).

    reddit:
      subreddits: [cryptocurrency, bitcoin]
      sort: hot              # hot | new | top | rising
      limit: 25
      # client_id / client_secret (or env REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET)
      # user_agent: optional override
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from opensocial.core.models import ContentItem
from opensocial.sources.base import USER_AGENT, Source, register

_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp")


@register
class RedditSource(Source):
    name = "reddit"
    category = "social"

    async def fetch(self) -> list[ContentItem]:
        client_id = self.config.get("client_id") or os.environ.get("REDDIT_CLIENT_ID")
        client_secret = self.config.get("client_secret") or os.environ.get(
            "REDDIT_CLIENT_SECRET"
        )
        if not (client_id and client_secret):
            raise RuntimeError(
                "reddit requires client_id/client_secret (config or env "
                "REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET)"
            )

        subreddits: list[str] = self.config.get("subreddits", []) or []
        sort: str = self.config.get("sort", "hot")
        limit: int = int(self.config.get("limit", 25))
        user_agent: str = self.config.get("user_agent", USER_AGENT)

        import asyncpraw

        items: list[ContentItem] = []
        reddit = asyncpraw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
        )
        try:
            reddit.read_only = True
            for name in subreddits:
                subreddit = await reddit.subreddit(name)
                lister = getattr(subreddit, sort, subreddit.hot)
                async for sub in lister(limit=limit):
                    items.append(self._to_item(sub, name))
        finally:
            await reddit.close()
        return items

    def _to_item(self, sub, subreddit: str) -> ContentItem:
        permalink = f"https://www.reddit.com{sub.permalink}"
        external = getattr(sub, "url", "") or ""
        media = [external] if external.lower().endswith(_IMAGE_EXTS) else []
        return ContentItem(
            source_name=self.name,
            source_category=self.category,
            title=sub.title,
            url=permalink,
            body=(sub.selftext or None),
            author=str(sub.author) if sub.author else None,
            published_at=datetime.fromtimestamp(sub.created_utc, tz=timezone.utc),
            media_urls=media,
            tags=[subreddit],
            engagement={
                "score": sub.score,
                "comments": sub.num_comments,
                "upvote_ratio": getattr(sub, "upvote_ratio", None),
            },
            raw_metadata={
                "id": sub.id,
                "subreddit": subreddit,
                "permalink": sub.permalink,
                "external_url": external,
                "over_18": getattr(sub, "over_18", None),
            },
        )
