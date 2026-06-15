"""
Tests for the three FitFindr tools.

Run with:
    pytest tests/

The search_listings tests are pure (no network). The suggest_outfit and
create_fit_card tests call the Groq LLM, so they need GROQ_API_KEY set in .env;
they are skipped automatically when no key is present.
"""

import os

import pytest

from tools import search_listings, suggest_outfit, create_fit_card
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

# Skip the LLM-backed tests when there's no API key (e.g. CI without secrets).
_HAS_KEY = bool(os.environ.get("GROQ_API_KEY"))
requires_llm = pytest.mark.skipif(not _HAS_KEY, reason="GROQ_API_KEY not set")


# ── search_listings (pure, no network) ─────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0
    # every result is a full listing dict
    assert all("title" in item and "price" in item for item in results)


def test_search_empty_results():
    # Nonsense keywords with an impossible size/price → no matches, empty list.
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []  # empty list, no exception


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=42)
    assert all(item["price"] <= 42 for item in results)


def test_search_size_filter_case_insensitive():
    # "m" should match sizes like "M", "S/M", "M/L" regardless of case.
    results = search_listings("vintage", size="m", max_price=None)
    assert all("m" in item["size"].lower() for item in results)


def test_search_sorted_by_relevance():
    # More overlapping keywords should rank at or above fewer.
    results = search_listings("vintage graphic tee", size=None, max_price=None)
    assert len(results) >= 2
    # Top result should mention at least one of the key terms in its text.
    top_text = (results[0]["title"] + results[0]["description"]).lower()
    assert any(kw in top_text for kw in ("graphic", "tee", "vintage"))


# ── suggest_outfit (LLM) ───────────────────────────────────────────────────────

@requires_llm
def test_suggest_outfit_with_wardrobe():
    new_item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    result = suggest_outfit(new_item, get_example_wardrobe())
    assert isinstance(result, str)
    assert result.strip() != ""


@requires_llm
def test_suggest_outfit_empty_wardrobe():
    # Empty wardrobe must not crash — it should still return styling advice.
    new_item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    result = suggest_outfit(new_item, get_empty_wardrobe())
    assert isinstance(result, str)
    assert result.strip() != ""


# ── create_fit_card (LLM) ──────────────────────────────────────────────────────

@requires_llm
def test_create_fit_card_returns_caption():
    new_item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    outfit = "Pair it with baggy jeans and chunky white sneakers."
    card = create_fit_card(outfit, new_item)
    assert isinstance(card, str)
    assert card.strip() != ""


def test_create_fit_card_empty_outfit():
    # Empty outfit → descriptive error string, NOT an exception. No LLM call needed.
    card = create_fit_card("", {"title": "Faded Band Tee", "price": 22, "platform": "depop"})
    assert isinstance(card, str)
    assert card.strip() != ""
    assert "couldn't" in card.lower() or "no outfit" in card.lower()


@requires_llm
def test_create_fit_card_varies():
    # Same input run twice should produce different captions (high temperature).
    new_item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    outfit = "Pair it with baggy jeans and chunky white sneakers."
    card_a = create_fit_card(outfit, new_item)
    card_b = create_fit_card(outfit, new_item)
    assert card_a != card_b
