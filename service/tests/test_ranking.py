"""Tests for the LLM comparative importance reranker.

These run without any model: a tiny fake provider stands in for a real
:class:`TextProvider`, and the offline ``TemplateProvider`` path is asserted to
be a pure no-op.
"""

from __future__ import annotations

from types import SimpleNamespace

from opensocial.ai.ranking import rerank_by_importance
from opensocial.ai.text import TemplateProvider


def _cand(title: str):
    """A stand-in RankedCandidate: the reranker only reads ``.row`` fields."""
    return SimpleNamespace(
        row=SimpleNamespace(title=title, summary="", body=""),
        priority_score=0.0,
    )


class _FakeProvider:
    """Returns a canned reply, recording the prompts it was handed."""

    name = "fake-model"

    def __init__(self, reply: str):
        self.reply = reply
        self.calls = []

    def generate(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.reply


class _BoomProvider:
    name = "boom"

    def generate(self, system: str, user: str) -> str:
        raise RuntimeError("model down")


def _titles(cands):
    return [c.row.title for c in cands]


def test_template_provider_is_noop():
    cands = [_cand("a"), _cand("b"), _cand("c")]
    out = rerank_by_importance(cands, {}, text_provider=TemplateProvider())
    assert out is cands  # untouched, same object


def test_single_candidate_is_noop():
    cands = [_cand("only")]
    out = rerank_by_importance(cands, {}, text_provider=_FakeProvider("1"))
    assert out is cands


def test_reorders_by_model_reply():
    cands = [_cand("a"), _cand("b"), _cand("c")]
    out = rerank_by_importance(cands, {}, text_provider=_FakeProvider("3, 1, 2"))
    assert _titles(out) == ["c", "a", "b"]


def test_omitted_indices_appended_in_original_order():
    cands = [_cand("a"), _cand("b"), _cand("c"), _cand("d")]
    # Model only ranks the 3rd item; the rest keep their deterministic order.
    out = rerank_by_importance(cands, {}, text_provider=_FakeProvider("3"))
    assert _titles(out) == ["c", "a", "b", "d"]


def test_malformed_reply_falls_back_to_input():
    cands = [_cand("a"), _cand("b")]
    out = rerank_by_importance(cands, {}, text_provider=_FakeProvider("no numbers here"))
    assert out is cands


def test_provider_exception_falls_back_to_input():
    cands = [_cand("a"), _cand("b")]
    out = rerank_by_importance(cands, {}, text_provider=_BoomProvider())
    assert out is cands


def test_top_k_limits_the_head_but_keeps_the_tail():
    cands = [_cand(str(i)) for i in range(5)]
    # Only the first 3 are sent; reply reverses them. Indices 4,5 (titles 3,4)
    # are the untouched tail and stay last in order.
    out = rerank_by_importance(
        cands, {}, text_provider=_FakeProvider("3,2,1"), top_k=3
    )
    assert _titles(out) == ["2", "1", "0", "3", "4"]


def test_out_of_range_indices_are_ignored():
    cands = [_cand("a"), _cand("b")]
    # 9 is out of range and dropped; 2 then 1 → b, a.
    out = rerank_by_importance(cands, {}, text_provider=_FakeProvider("9, 2, 1"))
    assert _titles(out) == ["b", "a"]
