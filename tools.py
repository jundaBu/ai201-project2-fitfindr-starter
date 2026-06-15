"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()

# LLM model used by the two generative tools.
_MODEL = "llama-3.3-70b-versatile"


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    listings = load_listings()

    # Tokenize the description into lowercase keywords for overlap scoring.
    keywords = [w for w in re.findall(r"[a-z0-9]+", description.lower()) if w]

    size_filter = size.strip().lower() if size else None

    scored: list[tuple[int, dict]] = []
    for listing in listings:
        # --- price filter ---
        if max_price is not None and listing["price"] > max_price:
            continue

        # --- size filter (case-insensitive substring match) ---
        if size_filter is not None:
            if size_filter not in str(listing.get("size", "")).lower():
                continue

        # --- relevance score: keyword overlap across title, description, tags ---
        haystack = " ".join([
            listing.get("title", ""),
            listing.get("description", ""),
            " ".join(listing.get("style_tags", [])),
        ]).lower()

        score = sum(1 for kw in keywords if kw in haystack)
        if score == 0:
            continue  # no relevant match — drop it

        scored.append((score, listing))

    # Sort by score, highest first. Python's sort is stable, so listings with
    # equal scores keep their original dataset order.
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [listing for _, listing in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    client = _get_groq_client()

    # Describe the new item compactly for the prompt.
    item_desc = (
        f"{new_item.get('title', 'item')} "
        f"(category: {new_item.get('category', 'n/a')}, "
        f"colors: {', '.join(new_item.get('colors', [])) or 'n/a'}, "
        f"style: {', '.join(new_item.get('style_tags', [])) or 'n/a'})"
    )

    items = wardrobe.get("items", []) if wardrobe else []

    if not items:
        # Empty wardrobe — general styling advice, no invented pieces.
        prompt = (
            f"A shopper is considering buying this secondhand item:\n  {item_desc}\n\n"
            "They have not entered any wardrobe items yet. Suggest how to style this "
            "piece in general terms: what categories and colors of clothing pair well "
            "with it, and what overall vibe or occasion it suits. Give 1-2 concrete "
            "outfit ideas in 2-4 sentences. Do not invent specific items they own."
        )
    else:
        wardrobe_lines = "\n".join(
            f"  - {it.get('name', 'item')} "
            f"({it.get('category', 'n/a')}; {', '.join(it.get('colors', [])) or 'n/a'})"
            + (f" — {it['notes']}" if it.get("notes") else "")
            for it in items
        )
        prompt = (
            f"A shopper is considering buying this secondhand item:\n  {item_desc}\n\n"
            f"Here is their current wardrobe:\n{wardrobe_lines}\n\n"
            "Suggest 1-2 complete outfits that build around the new item using "
            "specific pieces from their wardrobe (refer to them by name). Add a brief "
            "styling tip (how to wear or layer it). Keep it to 2-4 sentences, casual "
            "and practical."
        )

    response = client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    # Guard against an empty / whitespace-only outfit — return a message, don't crash.
    if not outfit or not outfit.strip():
        return (
            "Couldn't generate a fit card — no outfit suggestion was provided. "
            "Try generating an outfit idea first."
        )

    client = _get_groq_client()

    title = new_item.get("title", "this piece")
    price = new_item.get("price")
    price_str = f"${price:g}" if isinstance(price, (int, float)) else "a steal"
    platform = new_item.get("platform", "secondhand")

    prompt = (
        "Write a short, casual Instagram/TikTok OOTD caption (2-4 sentences) for a "
        "thrifted fashion find. It should feel authentic — like a real person posting "
        "their outfit, not a product description.\n\n"
        f"Item: {title}\n"
        f"Price: {price_str}\n"
        f"Platform: {platform}\n"
        f"Outfit: {outfit}\n\n"
        f"Mention the item name, the price, and that it's from {platform} naturally "
        "(once each). Capture the outfit's vibe in specific terms. Emojis are welcome. "
        "Return only the caption text."
    )

    response = client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=1.0,  # high temperature so each card reads differently
    )
    return response.choices[0].message.content.strip()
