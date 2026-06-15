# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
Searches the mock secondhand-listings dataset (`data/listings.json`, loaded via `load_listings()`) for items matching the user's request. It filters out anything over budget or in the wrong size, scores the rest by how well their text matches the user's keywords, and returns the matches best-first. This is a pure Python function — no LLM call.

**Input parameters:**
- `description` (str): Keywords describing what the user wants, e.g. `"vintage graphic tee"`. Matched (case-insensitive) against each listing's `title`, `description`, and `style_tags`.
- `size` (str | None): Size to filter by, e.g. `"M"`. Case-insensitive substring match against the listing's `size` field so `"m"` matches `"S/M"` and `"M (oversized)"`. `None` skips size filtering.
- `max_price` (float | None): Inclusive price ceiling. A listing passes if `listing["price"] <= max_price`. `None` skips price filtering.

**What it returns:**
A `list[dict]` of full listing dicts, sorted by relevance score (highest first). Each dict contains: `id, title, description, category, style_tags (list[str]), size, condition, price (float), colors (list[str]), brand (str | None), platform`. Listings whose keyword-overlap score is 0 are dropped before returning, so every dict in the list is an actual relevant match. Returns an empty list `[]` when nothing matches — it never raises.

**What happens if it fails or returns nothing:**
Returns `[]`. The planning loop detects the empty list, writes a helpful message into `session["error"]` (suggesting the user loosen the size, raise the budget, or use different keywords), and returns early. `suggest_outfit` and `create_fit_card` are **not** called.

---

### Tool 2: suggest_outfit

**What it does:**
Given the chosen listing and the user's wardrobe, asks the Groq LLM to propose 1–2 complete outfits built around the new item using pieces the user already owns. Returns styling guidance in natural language.

**Input parameters:**
- `new_item` (dict): The selected listing dict (top result from `search_listings`). The prompt uses its `title`, `category`, `colors`, `style_tags`, and `description`.
- `wardrobe` (dict): A wardrobe dict shaped like `wardrobe_schema.json` — a `"items"` key holding a list of item dicts, each with `id, name, category, colors, style_tags, notes`. May be empty (`{"items": []}`); the tool must handle that gracefully.

**What it returns:**
A non-empty `str` of outfit suggestions. When the wardrobe has items, the string names specific owned pieces (e.g. "pair with your wide-leg khaki trousers and chunky white sneakers") plus a styling tip. When the wardrobe is empty, it returns general styling advice for the item (what categories/colors pair well, what vibe it suits) instead of referencing nonexistent pieces.

**What happens if it fails or returns nothing:**
The empty-wardrobe case is handled inside the tool (general advice path), so it still returns a usable string rather than failing. If the LLM call raises or returns blank, the planning loop catches it, sets `session["error"]` to a message saying outfit generation failed and to try again, and returns early without calling `create_fit_card`.

---

### Tool 3: create_fit_card

**What it does:**
Turns the outfit suggestion and the item details into a short, casual, shareable social-media caption (Instagram/TikTok OOTD style) using the Groq LLM at a higher temperature so each card reads differently.

**Input parameters:**
- `outfit` (str): The outfit-suggestion string returned by `suggest_outfit`.
- `new_item` (dict): The selected listing dict — the prompt pulls its `title`, `price`, and `platform` so the caption can mention them naturally (once each).

**What it returns:**
A `str` of 2–4 sentences usable as a caption: casual/authentic voice, mentions the item name, price, and platform once each, captures the outfit's vibe in specific terms, and varies across runs.

**What happens if it fails or returns nothing:**
If `outfit` is empty or whitespace-only, the tool returns a descriptive error-message string (it does **not** raise). The planning loop treats a returned-but-empty `fit_card` as a soft failure: it still shows the listing and outfit to the user and notes the caption couldn't be generated.

---

### Additional Tools (if any)

None — FitFindr uses exactly the three required tools.

---

## Planning Loop

**How does your agent decide which tool to call next?**

`run_agent(query, wardrobe)` runs a fixed, conditional pipeline. The branches:

1. **Initialize** — `session = _new_session(query, wardrobe)`. All result fields start `None`/empty and `session["error"] = None`.

2. **Parse the query** — extract `description`, `size`, and `max_price` from the natural-language `query`. Approach: regex/string parsing. `max_price` comes from a pattern like `under $30` / `$30` (cast to `float`). `size` comes from matching tokens like `size M`, `XS`, `W30` against a known size vocabulary. `description` is the remaining keywords with the price/size phrases stripped out. Store the dict in `session["parsed"]`. If no price/size is found, those stay `None` (filters are skipped, not errored).

3. **Search** — call `search_listings(description, size, max_price)`; store the list in `session["search_results"]`.
   - **Branch A — `search_results == []`:** set `session["error"] = "No listings matched 'X'. Try a looser size, a higher budget, or different keywords."` and **`return session` immediately.** Do not proceed.
   - **Branch B — results found:** set `session["selected_item"] = session["search_results"][0]` (top-ranked) and continue.

4. **Suggest outfit** — call `suggest_outfit(session["selected_item"], session["wardrobe"])`; store in `session["outfit_suggestion"]`. If it returns falsy/raises, set `session["error"]` and `return session` early (don't build a fit card from nothing).

5. **Create fit card** — call `create_fit_card(session["outfit_suggestion"], session["selected_item"])`; store in `session["fit_card"]`.

6. **Done** — `return session`. The interaction is complete when `fit_card` is set (success) or as soon as `error` is set (early termination). The loop knows it's done because the pipeline is linear: there are no retries or re-planning steps; each successful stage unconditionally enables the next.

---

## State Management

**How does information from one tool get passed to the next?**

A single `session` dict (created by `_new_session`) is the one source of truth for the whole interaction. Tools don't talk to each other directly — the loop reads inputs from `session` and writes each tool's output back into it, so the next stage reads what the previous stage wrote.

| Session key | Written by | Read by |
|-------------|-----------|---------|
| `query` | `_new_session` (caller) | parse step |
| `parsed` (`description`, `size`, `max_price`) | parse step | `search_listings` |
| `search_results` (list) | `search_listings` | empty-check branch, item selection |
| `selected_item` (dict) | selection step (`search_results[0]`) | `suggest_outfit`, `create_fit_card` |
| `wardrobe` (dict) | `_new_session` (caller) | `suggest_outfit` |
| `outfit_suggestion` (str) | `suggest_outfit` | `create_fit_card` |
| `fit_card` (str) | `create_fit_card` | UI / final output |
| `error` (str \| None) | any stage on early exit | `app.py` / caller, checked first |

`app.py`'s `handle_query` calls `run_agent`, then checks `session["error"]` first: if set, it shows the error in panel 1 and blanks the other two; otherwise it formats `selected_item` into the listing panel and shows `outfit_suggestion` and `fit_card` in panels 2 and 3.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | Set `session["error"]` and return early before any LLM call. User sees: *"I couldn't find any listings matching 'designer ballgown' in size XXS under $5. Try raising your budget, removing the size filter, or using broader keywords like 'formal dress'."* No outfit/fit card is attempted. |
| suggest_outfit | Wardrobe is empty | Tool does **not** error — it returns general styling advice for the item (complementary categories/colors, the vibe it fits) so a new user with no closet still gets value. The loop continues to `create_fit_card` normally. |
| create_fit_card | Outfit input is missing or incomplete | Tool returns a descriptive string instead of raising. The loop still returns the listing and outfit to the user and the fit-card panel shows: *"Couldn't generate a caption this time — here's your outfit idea above; try resubmitting to get a fit card."* |

---

## Architecture

```
                          User query (text) + wardrobe choice
                                        │
                                        ▼
        ┌──────────────────────────  Planning Loop  (run_agent) ──────────────────────────┐
        │                                                                                  │
        │   parse query ──► Session.parsed = {description, size, max_price}                │
        │                                        │                                         │
        │                                        ▼                                         │
        │   search_listings(description, size, max_price)                                  │
        │        │                                                                         │
        │        │ results == []                                                           │
        │        ├───────────────► [ERROR] Session.error = "No listings found, try…" ──────┼──┐
        │        │                                                                         │  │
        │        │ results == [item, …]                                                    │  │
        │        ▼                                                                         │  │
        │   Session.search_results = [...]                                                 │  │
        │   Session.selected_item  = results[0]                                            │  │
        │        │                                                                         │  │
        │        ▼                                                                         │  │
        │   suggest_outfit(selected_item, wardrobe) ◄── Session.wardrobe                   │  │
        │        │           (empty wardrobe → general advice, no error)                   │  │
        │        ▼                                                                         │  │
        │   Session.outfit_suggestion = "..."                                              │  │
        │        │                                                                         │  │
        │        ▼                                                                         │  │
        │   create_fit_card(outfit_suggestion, selected_item)                              │  │
        │        │                                                                         │  │
        │        ▼                                                                         │  │
        │   Session.fit_card = "..."                                                       │  │
        │        │                                                                         │  │
        └────────┼─────────────────────────────────────────────────────◄── error path ───┼──┘
                 ▼                                                                         
            return Session  ──►  app.py handle_query()                                     
                 │                                                                         
                 ├─ error set?  → panel 1 shows error, panels 2 & 3 blank                  
                 └─ success     → panel 1 listing · panel 2 outfit · panel 3 fit card      
```

Component roles:
- **User** — submits a query string + picks Example/Empty wardrobe in the Gradio UI.
- **Planning Loop (`run_agent`)** — parses, orchestrates the three tools, owns all branching.
- **Tools** — `search_listings` (pure Python filter+score), `suggest_outfit` (Groq LLM), `create_fit_card` (Groq LLM).
- **Session state** — the shared dict every arrow reads from / writes to; the error branch terminates by writing `error` and returning the same dict.

---

## AI Tool Plan

**Milestone 3 — Individual tool implementations:**

- **search_listings:** I'll give Claude the *Tool 1* block above (all three params, the scoring/filter return value, and the empty-list failure mode) plus the `load_listings()` docstring from `utils/data_loader.py`. I expect a function that (1) loads listings, (2) filters by `max_price` and case-insensitive `size` substring, (3) scores remaining listings by keyword overlap across `title`/`description`/`style_tags`, (4) drops zero-score items, (5) returns sorted best-first. **Verify before trusting:** confirm it filters on *all three* params and returns `[]` (never raises) when nothing matches; then run the 5 `EXAMPLE_QUERIES` from `app.py` — including the deliberate no-results "designer ballgown size XXS under $5" — and eyeball that ranked results are sensible.
- **suggest_outfit:** Give Claude the *Tool 2* block + the `wardrobe_schema.json` example so it knows the `items` shape. Expect a function that branches on empty vs. non-empty wardrobe and calls the Groq client (`_get_groq_client`) with a prompt naming real wardrobe pieces. **Verify:** test once with `get_example_wardrobe()` (output must name actual items like "wide-leg khaki trousers") and once with `get_empty_wardrobe()` (output must give general advice, no invented pieces, non-empty string).
- **create_fit_card:** Give Claude the *Tool 3* block including the style guidelines (casual voice; item name, price, platform once each; higher temperature). Expect a caption generator with an empty-`outfit` guard. **Verify:** pass a real outfit string and check the caption mentions title/price/platform exactly once and reads like a post; pass `""` and confirm it returns an error string rather than raising.

**Milestone 4 — Planning loop and state management:**

- I'll give Claude the *Planning Loop*, *State Management*, and *Architecture* sections above plus the `_new_session` dict and `run_agent` TODO from `agent.py`. Expect an implementation that parses the query into `session["parsed"]`, calls the three tools in order, and **returns early with `session["error"]` set when `search_results` is empty**, matching the branch logic and the session-key table exactly. **Verify:** run `python agent.py` (it exercises a happy path and the no-results path) and confirm the happy path fills `selected_item`/`outfit_suggestion`/`fit_card` with `error=None`, and the no-results path sets `error` with the other fields left `None`. Then wire `app.py handle_query` and confirm the three panels map correctly for both cases.

---

## A Complete Interaction (Step by Step)

Write out what a full user interaction looks like from start to finish — tool call by tool call. Use a specific example query.

**What FitFindr needs to do:** FitFindr is a secondhand-fashion shopping agent that, given a user's request and their wardrobe, finds matching thrifted listings and helps them style what they buy. When the user describes an item they want, it calls `search_listings` to filter the dataset by description, size, and price; if results come back, it picks the top match and calls `suggest_outfit` to pair that item with pieces from the user's wardrobe, then `create_fit_card` to turn the look into a shareable social caption. If `search_listings` returns nothing, FitFindr stops, explains what to change (looser size, higher budget, different keywords), and does not call the downstream tools with empty input.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1 — Parse + Search:**
The loop parses the query into `session["parsed"] = {"description": "vintage graphic tee", "size": None, "max_price": 30.0}`, then calls `search_listings("vintage graphic tee", size=None, max_price=30.0)`. Listings are filtered to price ≤ $30 and scored on keyword overlap. Strong matches include `lst_006` "Graphic Tee — 2003 Tour Bootleg Style" ($24, depop) and `lst_015` "Vintage Graphic Hoodie — Faded Black" ($26). The function returns the list sorted best-first; the tee `lst_006` ranks top (matches "vintage", "graphic", "tee"). Stored in `session["search_results"]`.

**Step 2 — Select + Suggest outfit:**
Results are non-empty, so `session["selected_item"] = search_results[0]` (the $24 bootleg graphic tee). The loop calls `suggest_outfit(selected_item, wardrobe)` with the Example wardrobe. The LLM returns something like: *"Tuck this faded tee into your baggy straight-leg dark-wash jeans and finish with the chunky white sneakers for an easy streetwear fit. Layer the vintage black denim jacket over the top when it's cooler."* Stored in `session["outfit_suggestion"]`.

**Step 3 — Create fit card:**
The loop calls `create_fit_card(outfit_suggestion, selected_item)`. The LLM returns a caption like: *"found this faded bootleg graphic tee on depop for $24 and it's already my new go-to 🖤 throwing it on with baggy jeans + chunky sneakers, denim jacket on standby. thrift wins only."* Stored in `session["fit_card"]`. `session["error"]` stays `None`.

**Final output to user:**
`run_agent` returns the session. `app.py` shows three panels: **panel 1** the formatted listing ("Graphic Tee — 2003 Tour Bootleg Style — $24, depop, good condition"), **panel 2** the outfit idea from Step 2, and **panel 3** the fit-card caption from Step 3.

**Error-path variant:** For "designer ballgown size XXS under $5", `search_listings` returns `[]`. The loop sets `session["error"]` to a helpful message, returns early, and the UI shows that message in panel 1 with panels 2 and 3 blank — `suggest_outfit` and `create_fit_card` are never called.
