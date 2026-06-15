"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import re

from tools import search_listings, suggest_outfit, create_fit_card


# ── query parsing ─────────────────────────────────────────────────────────────

# Letter sizes (longest first so "XXL" matches before "XL"/"L").
_LETTER_SIZES = ["xxs", "xxl", "xs", "xl", "s", "m", "l"]


def _parse_query(query: str) -> dict:
    """
    Extract {description, size, max_price} from a natural-language query.

    Uses regex/string matching (no LLM):
      - max_price: a number after "under"/"below"/"<"/"$" → float, else None.
      - size: "size 8", "W30", or a standalone letter size token → str, else None.
      - description: the query with the matched price/size phrases stripped out.
    """
    text = query.strip()
    lowered = text.lower()

    # --- price: "under $30", "below 30", "$30", "< 40" ---
    max_price = None
    price_match = re.search(
        r"(?:under|below|less than|<|\$)\s*\$?\s*(\d+(?:\.\d+)?)", lowered
    )
    if price_match:
        max_price = float(price_match.group(1))

    # --- size: explicit "size X", waist "W30", or a standalone letter size ---
    size = None
    size_match = re.search(r"\bsize\s+([a-z0-9/]+)\b", lowered)
    if size_match:
        size = size_match.group(1).upper()
    else:
        waist_match = re.search(r"\b(w\d{2}(?:\s*l\d{2})?)\b", lowered)
        if waist_match:
            size = waist_match.group(1).upper()
        else:
            for token in re.findall(r"\b[a-z]+\b", lowered):
                if token in _LETTER_SIZES:
                    size = token.upper()
                    break

    # --- description: blank out the spans we already consumed (matched on the
    # lowered text, but spans map 1:1 onto the original since case-folding keeps
    # length), then collapse leftover punctuation/whitespace. ---
    chars = list(text)
    for m in (price_match, size_match):
        if m:
            for i in range(*m.span()):
                chars[i] = " "
    description = "".join(chars)
    description = re.sub(r"[,\.]", " ", description)
    description = re.sub(r"\s+", " ", description).strip()

    return {"description": description, "size": size, "max_price": max_price}


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
    }


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    TODO — implement this function using the planning loop you designed in planning.md:

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the user's query to extract a description, size, and
                max_price. You can use regex, string splitting, or ask the LLM
                to parse it — document your choice in planning.md.
                Store the result in session["parsed"].

        Step 3: Call search_listings() with the parsed parameters.
                Store results in session["search_results"].
                If no results: set session["error"] to a helpful message and
                return the session early. Do NOT proceed to suggest_outfit
                with empty input.

        Step 4: Select the item to use (e.g., the top result).
                Store it in session["selected_item"].

        Step 5: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 6: Call create_fit_card() with the outfit suggestion and selected item.
                Store the result in session["fit_card"].

        Step 7: Return the session.

    Before writing code, complete the Planning Loop and State Management sections
    of planning.md — your implementation should match what you described there.
    """
    # Step 1: Initialize the session.
    session = _new_session(query, wardrobe)

    # Step 2: Parse the query into description / size / max_price.
    session["parsed"] = _parse_query(query)
    parsed = session["parsed"]

    # Step 3: Search.
    session["search_results"] = search_listings(
        parsed["description"],
        size=parsed["size"],
        max_price=parsed["max_price"],
    )

    # Branch A — no matches: set an error and return early. Do NOT call the
    # downstream tools with empty input.
    if not session["search_results"]:
        bits = [f"'{parsed['description']}'"]
        if parsed["size"]:
            bits.append(f"size {parsed['size']}")
        if parsed["max_price"] is not None:
            bits.append(f"under ${parsed['max_price']:g}")
        session["error"] = (
            f"I couldn't find any listings matching {', '.join(bits)}. "
            "Try raising your budget, removing the size filter, or using broader keywords."
        )
        return session

    # Step 4: Select the top-ranked result.
    session["selected_item"] = session["search_results"][0]

    # Step 5: Suggest an outfit from the selected item + wardrobe.
    try:
        session["outfit_suggestion"] = suggest_outfit(
            session["selected_item"], session["wardrobe"]
        )
    except Exception as exc:  # LLM/network failure — fail gracefully, no fit card.
        session["error"] = f"Couldn't generate an outfit idea right now ({exc}). Please try again."
        return session

    if not session["outfit_suggestion"] or not session["outfit_suggestion"].strip():
        session["error"] = "Couldn't generate an outfit idea right now. Please try again."
        return session

    # Step 6: Create the fit card from the outfit + selected item.
    try:
        session["fit_card"] = create_fit_card(
            session["outfit_suggestion"], session["selected_item"]
        )
    except Exception as exc:
        # Soft failure: keep the listing + outfit, just note the card couldn't be made.
        session["fit_card"] = (
            f"(Couldn't generate a caption this time — {exc}. Your outfit idea is above.)"
        )

    # Step 7: Return the completed session.
    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
