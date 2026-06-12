"""Google News source tests — URL construction and offline feed parsing.

No network: the search-URL builder is a pure function, and the parse path is
exercised by feeding a saved Google News RSS fixture straight to ``feedparser``
+ the reused ``entry_to_item`` helper.
"""

from __future__ import annotations

import feedparser

from opensocial.sources import get_source
from opensocial.sources.googlenews import (
    GoogleNewsSource,
    build_feed_url,
)
from opensocial.sources.rss import entry_to_item

# A trimmed but structurally faithful Google News search-RSS response.
FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>"video games" - Google News</title>
  <item>
    <title>Big studio announces new console game - GameOutlet</title>
    <link>https://news.google.com/rss/articles/CBMiABC123?oc=5</link>
    <guid isPermaLink="false">CBMiABC123</guid>
    <pubDate>Tue, 10 Jun 2025 12:00:00 GMT</pubDate>
    <description>&lt;a href="https://news.google.com/..."&gt;Big studio announces&lt;/a&gt;</description>
    <source url="https://www.gameoutlet.com">GameOutlet</source>
  </item>
  <item>
    <title>Indie hit tops the charts this week - PlayDaily</title>
    <link>https://news.google.com/rss/articles/CBMiDEF456?oc=5</link>
    <guid isPermaLink="false">CBMiDEF456</guid>
    <pubDate>Tue, 10 Jun 2025 09:30:00 GMT</pubDate>
    <description>&lt;a href="https://news.google.com/..."&gt;Indie hit&lt;/a&gt;</description>
    <source url="https://www.playdaily.com">PlayDaily</source>
  </item>
</channel>
</rss>
"""


def test_registered():
    assert get_source("googlenews") is GoogleNewsSource
    assert GoogleNewsSource.name == "googlenews"
    assert GoogleNewsSource.category == "news"


def test_build_feed_url_with_query():
    url = build_feed_url("video games")
    assert url.startswith("https://news.google.com/rss/search?q=")
    # spaces are escaped, locale params are appended
    assert "q=video+games" in url
    assert "hl=en-US" in url and "gl=US" in url and "ceid=US%3Aen" in url


def test_build_feed_url_empty_query_is_top_stories():
    url = build_feed_url("")
    assert url.startswith("https://news.google.com/rss?")
    assert "search" not in url


def test_build_feed_url_locale_override():
    url = build_feed_url("cricket", hl="en-IN", gl="IN", ceid="IN:en")
    assert "hl=en-IN" in url and "gl=IN" in url and "ceid=IN%3Aen" in url


def test_fixture_parses_into_content_items():
    parsed = feedparser.parse(FIXTURE)
    items = [
        entry_to_item(e, "googlenews", "news") for e in parsed.entries
    ]
    items = [i for i in items if i is not None]

    assert len(items) == 2
    first = items[0]
    assert first.title == "Big studio announces new console game - GameOutlet"
    assert first.url.startswith("https://news.google.com/rss/articles/")
    assert first.source_name == "googlenews"
    assert first.source_category == "news"
    # pubDate parsed into a real timestamp (year from the fixture)
    assert first.published_at.year == 2025
    # stable de-dup id derives from source + url
    assert first.id == first.make_id("googlenews", first.url)
