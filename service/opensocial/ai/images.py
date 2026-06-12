"""Image providers behind one tiny interface.

``ImageProvider.image_for(prompt)`` returns an :class:`ImageResult` (or
``None`` for the no-image provider). Phase 3 only needs the image *reference*
(a URL + attribution); actually downloading bytes for media upload is a Phase 4
publish concern.

AI image *generation* (Pollinations/DALL·E) was removed — Pollinations moved to a
paid, rate-limited model and DALL·E needs paid API access — so images now come
only from real sources:

* :class:`UnsplashProvider` — real stock photos via the Unsplash API (needs
  ``UNSPLASH_ACCESS_KEY``); degrades to no image when the key is absent, a
  request fails, or nothing matches (it broadens the query and retries first).
* :class:`SourceMediaProvider` — a marker provider for the "Content" image
  source: it never fetches; :func:`generate._attach_image` uses the source
  item's own media instead.
* :class:`NoneProvider` — supplies no image (for ``never`` visual rules, when a
  niche disables images, or by default).

``get_image_provider(config)`` picks one from the **per-niche** ``image_source``
field (``unsplash`` | ``content`` | ``none``; default ``none``).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ImageResult:
    url: str
    provider: str
    attribution: str | None = None
    path: str | None = None  # filled at publish time when bytes are downloaded


class ImageProvider(ABC):
    name: str

    @abstractmethod
    def image_for(self, prompt: str) -> ImageResult | None:
        raise NotImplementedError


class UnsplashProvider(ImageProvider):
    """Real stock photos via the Unsplash API. Needs ``UNSPLASH_ACCESS_KEY``.

    The URL only exists after a real API call, so this hits the network. It
    degrades gracefully: with no key (or any request error) it returns ``None``
    rather than failing the generation run. Because Unsplash matches keywords
    literally and 404s when nothing matches, it broadens the query and retries
    so a niche+headline that doesn't match still yields a relevant photo.
    """

    name = "unsplash"
    _API = "https://api.unsplash.com/photos/random"

    def __init__(self, width: int = 1024, height: int = 1024) -> None:
        # Unsplash serves its own sizes; width/height are kept for interface
        # parity (and a squarish crop hint) but don't force exact dimensions.
        self.width = int(width)
        self.height = int(height)

    def image_for(self, prompt: str) -> ImageResult | None:
        text = (prompt or "").strip()
        if not text:
            return None
        import os

        key = os.environ.get("UNSPLASH_ACCESS_KEY")
        if not key:
            return None

        # Try the full query, then progressively broader fallbacks (the leading
        # niche word is kept first by ``unsplash_query``) so a no-match degrades
        # to a relevant on-topic photo instead of dropping the image entirely.
        for query in self._query_attempts(text):
            result = self._fetch(query, key)
            if result is not None:
                return result
        return None

    @staticmethod
    def _query_attempts(text: str) -> list[str]:
        words = text.split()
        attempts = [text]
        if len(words) > 3:
            attempts.append(" ".join(words[:3]))
        if len(words) > 1:
            attempts.append(words[0])  # the niche name on its own
        # De-dupe while preserving order.
        seen: set[str] = set()
        return [q for q in attempts if not (q in seen or seen.add(q))]

    def _fetch(self, query: str, key: str) -> ImageResult | None:
        try:
            import json as _json
            from urllib.parse import urlencode
            from urllib.request import Request, urlopen

            orientation = "squarish" if self.width == self.height else (
                "landscape" if self.width > self.height else "portrait"
            )
            params = urlencode(
                {"query": query, "orientation": orientation, "content_filter": "high"}
            )
            req = Request(
                f"{self._API}?{params}",
                headers={"Authorization": f"Client-ID {key}", "Accept-Version": "v1"},
            )
            with urlopen(req, timeout=10) as resp:  # noqa: S310 (trusted host)
                data = _json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

        url = (data.get("urls") or {}).get("regular")
        if not url:
            return None
        author = (data.get("user") or {}).get("name")
        attribution = f"Photo by {author} on Unsplash" if author else "Unsplash"
        return ImageResult(url=url, provider=self.name, attribution=attribution)


class SourceMediaProvider(ImageProvider):
    """Marker for the "Content" image source — use the source item's own media.

    It never fetches an image itself; :func:`generate._attach_image` keys off
    ``name == "content"`` to attach the fetched item's media instead.
    """

    name = "content"

    def image_for(self, prompt: str) -> ImageResult | None:
        return None


class NoneProvider(ImageProvider):
    name = "none"

    def image_for(self, prompt: str) -> ImageResult | None:
        return None


def get_image_provider(config: dict | None) -> ImageProvider:
    """Build the image provider for a niche from its ``image_source`` field.

    * ``unsplash`` — stock photos (:class:`UnsplashProvider`).
    * ``content`` — use the fetched item's own media (:class:`SourceMediaProvider`).
    * ``none`` (default) — no images. Legacy ``ai`` also maps here, since AI
      image generation was removed.
    """
    source = ((config or {}).get("image_source") or "none").strip().lower()
    if source == "unsplash":
        return UnsplashProvider()
    if source == "content":
        return SourceMediaProvider()
    return NoneProvider()
