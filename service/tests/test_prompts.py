"""Per-niche persona controls — the General-tab style / length / instructions
must actually reach the generation prompt (and a legacy free-text voice/tone
must still work as a fallback)."""

from __future__ import annotations

from opensocial.ai.prompts import (
    LENGTH_PROMPTS,
    STYLE_PROMPTS,
    DEFAULT_VOICE,
    build_messages,
)


def _system(config):
    system, _ = build_messages(config=config, post_type="take", subject="A topic")
    return system


def test_style_choice_drives_the_voice():
    system = _system({"persona": {"style": "funny"}})
    assert STYLE_PROMPTS["funny"] in system


def test_length_choice_adds_length_instruction():
    system = _system({"persona": {"length": "very_short"}})
    assert LENGTH_PROMPTS["very_short"] in system


def test_custom_instructions_are_appended():
    system = _system({"persona": {"instructions": "Always cite a number."}})
    assert "Additional instructions: Always cite a number." in system


def test_all_three_controls_compose():
    system = _system(
        {"persona": {"style": "professional", "length": "long", "instructions": "Be concrete."}}
    )
    assert STYLE_PROMPTS["professional"] in system
    assert LENGTH_PROMPTS["long"] in system
    assert "Additional instructions: Be concrete." in system


def test_legacy_voice_tone_still_honored_when_no_style():
    system = _system({"persona": {"voice": "You are a wry critic.", "tone": "dry"}})
    assert "You are a wry critic." in system
    assert "Tone: dry" in system


def test_style_overrides_legacy_voice():
    # When a style is set it wins; the legacy free-text voice is ignored.
    system = _system({"persona": {"style": "casual", "voice": "Ignore me."}})
    assert STYLE_PROMPTS["casual"] in system
    assert "Ignore me." not in system


def test_default_voice_when_persona_empty():
    system = _system({})
    assert DEFAULT_VOICE in system


def test_unknown_style_falls_back():
    # A bogus style value isn't a STYLE_PROMPTS key → fall back to voice/default.
    system = _system({"persona": {"style": "zany"}})
    assert DEFAULT_VOICE in system
