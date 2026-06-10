"""GitHub Releases source via the GitHub REST API.

    github_releases:
      repos:
        - python/cpython
        - openai/openai-python
      limit: 5
      # optional: api_key or env GITHUB_TOKEN to raise the rate limit

Works unauthenticated (60 req/hr); a token raises that to 5000 req/hr.
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


@register
class GitHubReleasesSource(Source):
    name = "github_releases"
    category = "tech"

    async def fetch(self) -> list[ContentItem]:
        repos: list[str] = self.config.get("repos", []) or []
        limit: int = int(self.config.get("limit", 10))
        token = resolve_api_key(
            self.config, "GITHUB_TOKEN", required=False, source_name=self.name
        )

        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        items: list[ContentItem] = []
        async with httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT, headers=headers
        ) as client:
            for repo in repos:
                resp = await client.get(
                    f"https://api.github.com/repos/{repo}/releases",
                    params={"per_page": limit},
                )
                if resp.status_code != 200:
                    continue
                for rel in resp.json():
                    downloads = sum(
                        a.get("download_count", 0) for a in rel.get("assets", [])
                    )
                    items.append(
                        ContentItem(
                            source_name=self.name,
                            source_category=self.category,
                            title=rel.get("name") or rel.get("tag_name") or repo,
                            url=rel.get("html_url"),
                            body=rel.get("body") or None,
                            author=repo,
                            published_at=parse_iso8601(
                                rel.get("published_at") or rel.get("created_at")
                            ),
                            tags=[repo, rel.get("tag_name")] if rel.get("tag_name") else [repo],
                            engagement={"downloads": downloads},
                            raw_metadata=rel,
                        )
                    )
        return items
