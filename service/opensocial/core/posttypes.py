"""Tone taxonomy: config parsing and shuffled-rotation selection.

Each niche's ``post_types`` block enables a subset of the seven **tones** — the
angle/voice a draft is written in (``news``, ``take``, a witty ``meme``, …) so a
niche's feed doesn't all sound like wire copy. The per-tone *intent* text lives
in :data:`opensocial.ai.prompts.POST_TYPE_TEMPLATES`; this module only decides
*which* tone each draft gets.

Selection is a shuffled rotation: deal a reshuffled deck of the enabled tones so
a batch of N drafts gets N distinct tones before any repeat. There are no daily
caps and no per-tone image rules — image attachment is governed entirely by the
niche-level ``image_source`` (see :func:`opensocial.ai.images.get_image_provider`).
"""

from __future__ import annotations

import random as _random
from dataclasses import dataclass

# Canonical tone set / order. Keys match POST_TYPE_TEMPLATES in ai/prompts.py.
ALL_TONES: list[str] = [
    "news", "spotlight", "insight", "take", "tip", "question", "meme",
]

# Tones that may be generated with no source content behind them (independent posts).
INDEPENDENT_ELIGIBLE = {"insight", "take", "tip", "question", "meme"}


@dataclass
class PostTypeRule:
    enabled: bool = True


@dataclass
class PostTypesConfig:
    rules: dict[str, PostTypeRule]

    @classmethod
    def from_niche(cls, raw: dict) -> "PostTypesConfig":
        block = (raw or {}).get("post_types") or {}
        rules: dict[str, PostTypeRule] = {}
        for ptype, spec in block.items():
            spec = spec or {}
            rules[ptype] = PostTypeRule(enabled=bool(spec.get("enabled", True)))
        return cls(rules=rules)

    def enabled_tones(self) -> list[str]:
        """Enabled tones in canonical order.

        With a ``post_types`` block, a tone is active only if it's declared and
        enabled. Falls back to :data:`ALL_TONES` when the niche enables none (or
        declares no block at all) so generation never stalls for lack of a tone —
        a bare niche simply gets the full, varied set.
        """
        if not self.rules:
            return list(ALL_TONES)
        enabled = [
            t for t in ALL_TONES
            if t in self.rules and self.rules[t].enabled
        ]
        return enabled or list(ALL_TONES)


def shuffled_deck(tones: list[str], rng: _random.Random | None = None) -> list[str]:
    """A reshuffled copy of ``tones`` to deal one-per-draft (pop from the end).

    The caller pops a tone per draft and refills with a fresh deck when empty,
    giving a rotation that exhausts every enabled tone before repeating.
    """
    deck = list(tones) or list(ALL_TONES)
    (rng or _random).shuffle(deck)
    return deck
