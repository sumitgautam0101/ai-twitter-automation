"""X (Twitter) publisher via Tweepy.

``tweepy`` is imported lazily so the package and tests load without it. Posting
is text-only by default per the cost strategy; media upload uses the v1.1 API
(required for media) while the tweet itself goes through v2.
"""

from __future__ import annotations

from opensocial.publish.base import Publisher, PublishResult


class XPublisher(Publisher):
    platform = "x"

    def __init__(self, credentials: dict) -> None:
        self.credentials = credentials
        self.dry_run = False
        self._client = None

    def _connect(self):
        if self._client is not None:
            return self._client
        import tweepy

        c = self.credentials
        self._client = tweepy.Client(
            consumer_key=c["api_key"],
            consumer_secret=c["api_secret"],
            access_token=c["access_token"],
            access_token_secret=c["access_token_secret"],
        )
        return self._client

    def _upload_media(self, media_url: str) -> str | None:
        """Download the image and upload via v1.1, returning a media id."""
        import httpx
        import tweepy

        c = self.credentials
        auth = tweepy.OAuth1UserHandler(
            c["api_key"], c["api_secret"], c["access_token"], c["access_token_secret"]
        )
        api = tweepy.API(auth)
        with httpx.Client(timeout=30.0) as http:
            resp = http.get(media_url)
            resp.raise_for_status()
        import io

        media = api.media_upload(filename="image.png", file=io.BytesIO(resp.content))
        return media.media_id_string

    def publish(self, *, text: str, media_url: str | None = None) -> PublishResult:
        try:
            client = self._connect()
            media_ids = None
            if media_url:
                mid = self._upload_media(media_url)
                if mid:
                    media_ids = [mid]
            resp = client.create_tweet(text=text, media_ids=media_ids)
            tweet_id = str(resp.data["id"])
            return PublishResult(
                ok=True,
                platform_post_id=tweet_id,
                platform_post_url=f"https://x.com/i/web/status/{tweet_id}",
            )
        except Exception as exc:
            return PublishResult(ok=False, error=str(exc))
