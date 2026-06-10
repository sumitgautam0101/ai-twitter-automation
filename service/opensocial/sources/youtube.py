"""YouTube source via the YouTube Data API v3 (+ optional transcripts).

    youtube:
      channel_ids: [UCxxxx, UCyyyy]   # one or both of channel_ids / query
      query: "ai news"
      limit: 10
      transcripts: true               # fetch transcript into `body`
      # api_key or env YOUTUBE_API_KEY

The Data API client is synchronous, so it runs in a worker thread.
"""

from __future__ import annotations

import asyncio

from opensocial.core.models import ContentItem
from opensocial.sources.base import Source, parse_iso8601, register, resolve_api_key


@register
class YouTubeSource(Source):
    name = "youtube"
    category = "video"

    async def fetch(self) -> list[ContentItem]:
        key = resolve_api_key(self.config, "YOUTUBE_API_KEY", source_name=self.name)
        return await asyncio.to_thread(self._fetch_sync, key)

    def _fetch_sync(self, key: str) -> list[ContentItem]:
        from googleapiclient.discovery import build

        youtube = build("youtube", "v3", developerKey=key, cache_discovery=False)

        channel_ids: list[str] = self.config.get("channel_ids", []) or []
        query = self.config.get("query")
        limit = int(self.config.get("limit", 10))
        want_transcripts = bool(self.config.get("transcripts", True))

        # Collect video ids + snippets via search (per channel, or one query).
        snippets: dict[str, dict] = {}
        order: list[str] = []
        targets = channel_ids or [None]
        for channel_id in targets:
            params = dict(
                part="snippet", type="video", order="date",
                maxResults=min(limit, 50),
            )
            if channel_id:
                params["channelId"] = channel_id
            if query:
                params["q"] = query
            res = youtube.search().list(**params).execute()
            for it in res.get("items", []):
                vid = it.get("id", {}).get("videoId")
                if vid and vid not in snippets:
                    snippets[vid] = it["snippet"]
                    order.append(vid)

        # Batch-fetch statistics (50 ids/request).
        stats: dict[str, dict] = {}
        for i in range(0, len(order), 50):
            chunk = order[i : i + 50]
            res = youtube.videos().list(
                part="statistics", id=",".join(chunk)
            ).execute()
            for it in res.get("items", []):
                stats[it["id"]] = it.get("statistics", {})

        items: list[ContentItem] = []
        for vid in order:
            sn = snippets[vid]
            st = stats.get(vid, {})
            thumb = (sn.get("thumbnails", {}).get("high") or {}).get("url")
            body = self._transcript(vid) if want_transcripts else None
            items.append(
                ContentItem(
                    source_name=self.name,
                    source_category=self.category,
                    title=sn.get("title", ""),
                    url=f"https://www.youtube.com/watch?v={vid}",
                    summary=sn.get("description"),
                    body=body,
                    author=sn.get("channelTitle"),
                    published_at=parse_iso8601(sn.get("publishedAt")),
                    media_urls=[thumb] if thumb else [],
                    engagement={
                        "views": _int(st.get("viewCount")),
                        "likes": _int(st.get("likeCount")),
                        "comments": _int(st.get("commentCount")),
                    },
                    raw_metadata={"snippet": sn, "statistics": st},
                )
            )
        return items

    @staticmethod
    def _transcript(video_id: str) -> str | None:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
        except ImportError:
            return None
        try:
            # API differs across versions: new instance .fetch() vs classmethod.
            try:
                segments = YouTubeTranscriptApi().fetch(video_id)
                parts = [getattr(s, "text", "") or s.get("text", "") for s in segments]
            except (AttributeError, TypeError):
                segments = YouTubeTranscriptApi.get_transcript(video_id)
                parts = [s["text"] for s in segments]
            return " ".join(p for p in parts if p) or None
        except Exception:
            return None


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
