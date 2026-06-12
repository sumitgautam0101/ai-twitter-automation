"""Per-niche image source — the General-tab Image source dropdown
(``image_source``) selects Unsplash / Content / None. AI image generation was
removed, so there is no AI/Pollinations/DALL·E path."""

from __future__ import annotations

from opensocial.ai.images import (
    NoneProvider,
    SourceMediaProvider,
    UnsplashProvider,
    get_image_provider,
)
from opensocial.core.generate import _attach_image


def _cfg(source):
    cfg = {"slug": "tech"}
    if source is not None:
        cfg["image_source"] = source
    return cfg


def test_source_none_disables_images():
    assert isinstance(get_image_provider(_cfg("none")), NoneProvider)


def test_source_content_uses_source_media_provider():
    assert isinstance(get_image_provider(_cfg("content")), SourceMediaProvider)


def test_source_unsplash():
    assert isinstance(get_image_provider(_cfg("unsplash")), UnsplashProvider)


def test_default_when_image_source_unset_is_none():
    # AI generation removed → the default (and legacy "ai") is no image.
    assert isinstance(get_image_provider(_cfg(None)), NoneProvider)
    assert isinstance(get_image_provider(_cfg("ai")), NoneProvider)


def test_content_provider_attaches_item_media():
    provider = SourceMediaProvider()
    # Content image source uses the item's own media…
    url, attr, prov = _attach_image(
        provider, niche_name="Tech", subject="x",
        item_media=["https://img/1.png"],
    )
    assert (url, attr, prov) == ("https://img/1.png", "source", "source")
    # …and yields no image when the item has none.
    assert _attach_image(
        provider, niche_name="Tech", subject="x", item_media=[],
    ) == (None, None, None)


def test_none_provider_yields_no_image():
    assert _attach_image(
        NoneProvider(), niche_name="Tech", subject="x", item_media=None,
    ) == (None, None, None)


def test_unsplash_degrades_to_none_without_key(monkeypatch):
    monkeypatch.delenv("UNSPLASH_ACCESS_KEY", raising=False)
    assert UnsplashProvider().image_for("a sunset over mountains") is None


def test_unsplash_broadens_query_on_no_match(monkeypatch):
    # First (specific) query finds nothing; the broadened fallback succeeds —
    # so we degrade to a relevant photo instead of dropping the image.
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "k")
    from opensocial.ai.images import ImageResult

    tried: list[str] = []

    def fake_fetch(self, query, key):
        tried.append(query)
        # Only the broadest single-word attempt returns a photo.
        if " " in query:
            return None
        return ImageResult(url="https://img/photo.jpg", provider="unsplash")

    monkeypatch.setattr(UnsplashProvider, "_fetch", fake_fetch)
    res = UnsplashProvider().image_for("AI steroid Olympics sparked debate performance")
    assert res is not None and res.url == "https://img/photo.jpg"
    assert tried[0] == "AI steroid Olympics sparked debate performance"
    assert tried[-1] == "AI"


class _RecordingUnsplash(UnsplashProvider):
    """Captures the query string instead of hitting the network."""

    def image_for(self, prompt):
        self.seen = prompt
        return None


def test_attach_image_feeds_unsplash_the_clean_query():
    prov = _RecordingUnsplash()
    _attach_image(
        prov, niche_name="Crypto",
        subject="BlackRock files to list its bitcoin income ETF", item_media=None,
    )
    # Routed through unsplash_query — a tight niche anchor + the most salient
    # subject word, not the raw headline or an AI-illustration prompt.
    assert "illustration" not in prov.seen
    assert prov.seen == "Crypto BlackRock"
