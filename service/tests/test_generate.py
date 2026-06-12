"""Phase 3 tests — post-type selection, text post-processing, and the
fetch → filter → generate path, all with a mocked AI provider (no network,
no model)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from opensocial.ai.images import NoneProvider
from opensocial.ai.text import TemplateProvider, TextProvider
from opensocial.core.db import (
    Base,
    GeneratedPost,
    make_engine,
    store_items,
)
from opensocial.core.filtering import filter_niche
from opensocial.core.generate import (
    effective_length,
    generate_for_niche,
    generate_independent,
    html_to_text,
    sanitize_formatting,
    strip_preamble,
    strip_wrapping_quotes,
)
from opensocial.core.models import ContentItem
from opensocial.core.posttypes import ALL_TONES, PostTypesConfig, shuffled_deck

NICHE = "tech"


@pytest.fixture()
def session_factory(tmp_path):
    engine = make_engine(tmp_path / "test.db")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _item(title, **kw):
    now = datetime.now(timezone.utc)
    return ContentItem(
        source_name=kw.get("source_name", "hackernews"),
        source_category="tech",
        title=title,
        url=kw.get("url", f"https://example.com/{abs(hash(title))}"),
        body=kw.get("body", ""),
        summary=kw.get("summary", ""),
        published_at=kw.get("published", now),
        engagement=kw.get("engagement"),
        media_urls=kw.get("media_urls", []),
    )


class _FixedProvider(TextProvider):
    """Returns a canned string regardless of prompt (for post-processing tests)."""

    name = "fixed"

    def __init__(self, text):
        self._text = text

    def generate(self, system, user):
        return self._text


_CONFIG = {
    "slug": "tech",
    "display_name": "Tech & Dev",
    "ai": {"text": {"provider": "template"}, "image": {"provider": "pollinations"}},
    "filters": {"relevance_keywords": []},
    "prioritization": {"recency_weight": 1.0, "engagement_weight": 0.0},
    "post_types": {
        "news": {"enabled": True},
        "spotlight": {"enabled": True},
        "take": {"enabled": True},
    },
    "independent_take": {"enabled": True, "per_day": 1, "types": ["take"], "image": "none"},
}


# --- unit: post-processing ------------------------------------------------


def test_strip_wrapping_quotes():
    assert strip_wrapping_quotes('"hello world"') == "hello world"
    assert strip_wrapping_quotes("`code take`") == "code take"
    assert strip_wrapping_quotes("no quotes here") == "no quotes here"


def test_html_to_text_strips_tags_entities_and_whitespace():
    raw = '<p>Hello &amp; <a href="http://x">welcome</a></p>\n\n  to it'
    assert html_to_text(raw) == "Hello & welcome to it"
    assert html_to_text(None) == ""
    assert html_to_text("") == ""


def test_strip_preamble_drops_known_scaffolding():
    assert (
        strip_preamble("Okay, let's do this. Here's the post: Markets are wild")
        == "Markets are wild"
    )
    assert strip_preamble("Sure. Prediction markets win") == "Prediction markets win"
    # No scaffolding → untouched, even when it starts with a bare 'this'.
    assert strip_preamble("This take stands alone") == "This take stands alone"
    # Never empties the post: a post that *is* only the filler is left as-is.
    assert strip_preamble("Here's the post:") == "Here's the post:"


def test_sanitize_formatting_strips_markdown_and_dashes():
    # Markdown emphasis/code is unwrapped to its inner text.
    assert sanitize_formatting("**bold** and `code`") == "bold and code"
    assert sanitize_formatting("a *witty* take") == "a witty take"
    # Em/en dashes and spaced hyphens become commas.
    assert sanitize_formatting("markets are wild — really wild") == (
        "markets are wild, really wild"
    )
    assert sanitize_formatting("a play - or a gamble") == "a play, or a gamble"
    # Less common dash codepoints models emit (horizontal bar, minus sign,
    # figure/two-em dash, fullwidth hyphen) are all normalized too.
    for dash in ("―", "−", "‒", "⸺", "－", "﹘"):
        assert sanitize_formatting(f"check {dash} either") == "check, either"
    assert sanitize_formatting("check—either") == "check, either"  # no spaces
    # Intra-word hyphens in names/numbers are preserved.
    assert sanitize_formatting("GPT-4 powers e-commerce") == "GPT-4 powers e-commerce"


def test_choose_post_type_picks_named_tone():
    from types import SimpleNamespace

    from opensocial.ai.ranking import choose_post_type

    cand = SimpleNamespace(row=_item("Some headline"))
    choices = ["news", "take", "insight"]
    # The model names a tone → that tone is chosen.
    picked = choose_post_type(
        cand, _CONFIG, text_provider=_FixedProvider("take"),
        choices=choices, niche_name="Tech",
    )
    assert picked == "take"
    # An unparseable reply → None, so the caller falls back to its deck.
    assert (
        choose_post_type(
            cand, _CONFIG, text_provider=_FixedProvider("no idea"),
            choices=choices, niche_name="Tech",
        )
        is None
    )


def test_choose_post_type_is_noop_offline():
    from types import SimpleNamespace

    from opensocial.ai.ranking import choose_post_type

    cand = SimpleNamespace(row=_item("Some headline"))
    # Offline TemplateProvider can't classify → None (deck rotation takes over).
    assert (
        choose_post_type(
            cand, _CONFIG, text_provider=TemplateProvider(),
            choices=["news", "take"], niche_name="Tech",
        )
        is None
    )


def test_effective_length_counts_urls_as_23():
    url = "https://example.com/a/very/long/path/that/is/way/more/than/23/chars"
    text = f"check this {url}"
    # "check this " == 11 chars, + 23 for the URL.
    assert effective_length(text) == 11 + 23


# --- unit: tone selection -------------------------------------------------


def test_enabled_tones_returns_declared_enabled_in_order():
    cfg = PostTypesConfig.from_niche(_CONFIG)
    # _CONFIG enables news, spotlight, take — returned in canonical order.
    assert cfg.enabled_tones() == ["news", "spotlight", "take"]


def test_enabled_tones_falls_back_to_all_when_none_enabled():
    # No block → all tones; block that disables everything → all tones too.
    assert PostTypesConfig.from_niche({}).enabled_tones() == ALL_TONES
    all_off = {"post_types": {t: {"enabled": False} for t in ALL_TONES}}
    assert PostTypesConfig.from_niche(all_off).enabled_tones() == ALL_TONES


def test_shuffled_deck_deals_every_tone_before_repeating():
    tones = ["news", "spotlight", "take"]
    deck = shuffled_deck(tones)
    assert sorted(deck) == sorted(tones)  # a permutation, no dupes/drops


# --- unit: rewrite-to-fit -------------------------------------------------


def test_rewrite_to_fit_trims_overlong_draft(session_factory):
    long_text = "x" * 500
    provider = _FixedProvider(long_text)
    items = [_item("A subject", url="https://a.com/1")]
    with session_factory() as session:
        store_items(session, items, NICHE)
        filter_niche(session, NICHE, _CONFIG)
        drafts = generate_for_niche(
            session, NICHE, _CONFIG, text_provider=provider,
            image_provider=NoneProvider(),
        )
    # _FixedProvider ignores the shorten instruction, so the hard-trim guard
    # must bring it under the 280 limit.
    assert drafts
    assert effective_length(drafts[0].text) <= 280


# --- integration: fetch(stored) → filter → generate -----------------------


def test_generate_end_to_end_persists_drafts(session_factory):
    items = [
        _item("Open source AI model ships", url="https://a.com/1", media_urls=["https://img/1.png"]),
        _item("New dev framework released", url="https://b.com/2"),
        _item("GitHub release notes", url="https://c.com/3", source_name="github_releases"),
    ]
    with session_factory() as session:
        store_items(session, items, NICHE)
        filter_niche(session, NICHE, _CONFIG)
        drafts = generate_for_niche(
            session, NICHE, _CONFIG,
            text_provider=TemplateProvider(), image_provider=NoneProvider(),
        )

        rows = session.query(GeneratedPost).all()
        assert len(rows) == len(drafts) == 3
        # Shuffled rotation deals each enabled tone once before repeating, so the
        # three drafts cover exactly the niche's three enabled tones.
        assert {r.post_type for r in rows} == {"news", "spotlight", "take"}
        # every draft is a standalone, link-free post under the limit
        for r in rows:
            assert r.text and effective_length(r.text) <= 280
            assert "http" not in r.text
            assert r.status == "draft"
            assert r.ai_text_provider == "template"


def test_generate_skips_already_drafted(session_factory):
    items = [_item("Only story", url="https://a.com/1")]
    with session_factory() as session:
        store_items(session, items, NICHE)
        filter_niche(session, NICHE, _CONFIG)
        first = generate_for_niche(
            session, NICHE, _CONFIG, text_provider=TemplateProvider(),
            image_provider=NoneProvider(),
        )
        second = generate_for_niche(
            session, NICHE, _CONFIG, text_provider=TemplateProvider(),
            image_provider=NoneProvider(),
        )
    assert len(first) == 1
    assert second == []  # nothing new to draft


# --- no silent fallback ----------------------------------------------------


def test_no_fallback_raises_when_litellm_unavailable(monkeypatch):
    # A real provider with litellm missing must RAISE, not quietly degrade to the
    # title-echoing template provider.
    import sys

    from opensocial.ai.text import TextProviderError, get_text_provider

    monkeypatch.setitem(sys.modules, "litellm", None)  # `import litellm` → ImportError
    with pytest.raises(TextProviderError):
        get_text_provider({"ai": {"text": {"provider": "claude"}}})


def test_template_provider_only_when_explicitly_chosen():
    # provider: template is still honored (offline/tests) — it's a deliberate pick.
    from opensocial.ai.text import TemplateProvider, get_text_provider

    p = get_text_provider({"ai": {"text": {"provider": "template"}}})
    assert isinstance(p, TemplateProvider)


def test_empty_model_output_fails_generation(session_factory):
    # If the model returns nothing usable, fail loudly rather than store an
    # empty draft or fall back.
    from opensocial.ai.text import TextProviderError

    items = [_item("A subject", url="https://a.com/1")]
    with session_factory() as session:
        store_items(session, items, NICHE)
        filter_niche(session, NICHE, _CONFIG)
        with pytest.raises(TextProviderError):
            generate_for_niche(
                session, NICHE, _CONFIG, text_provider=_FixedProvider(""),
                image_provider=NoneProvider(),
            )


# --- integration: independent (daily Take) --------------------------------


def test_independent_take_creates_post_with_no_content_item(session_factory):
    with session_factory() as session:
        drafts = generate_independent(
            session, NICHE, _CONFIG, text_provider=TemplateProvider(),
            image_provider=NoneProvider(),
        )
        assert len(drafts) == 1
        assert drafts[0].independent is True
        row = session.query(GeneratedPost).filter_by(content_item_id=None).one()
        assert row.post_type == "take"
        assert row.media_url is None  # image: none in config


def test_independent_take_idempotent_per_day(session_factory):
    with session_factory() as session:
        generate_independent(
            session, NICHE, _CONFIG, text_provider=TemplateProvider(),
            image_provider=NoneProvider(),
        )
        again = generate_independent(
            session, NICHE, _CONFIG, text_provider=TemplateProvider(),
            image_provider=NoneProvider(),
        )
        # per_day is 1 and one already exists today → second run adds nothing.
        assert again == []
        assert session.query(GeneratedPost).filter_by(content_item_id=None).count() == 1
