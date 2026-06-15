# FitFindr 🛍️

FitFindr is a secondhand-fashion shopping agent. You describe what you're looking for in
plain language ("a vintage graphic tee under $30, size M"); it searches a mock thrift
dataset, picks the best match, suggests an outfit built from your existing wardrobe, and
writes a shareable OOTD caption ("fit card") for the find.

It runs as a small Gradio web app and is powered by three tools orchestrated by a planning
loop. The interesting part isn't that it calls three tools — it's that it **decides** whether
to call them, branching on what the search returns.

---

## Setup

```bash
pip install -r requirements.txt
```

Set your Groq API key in a `.env` file in the project root (free key at
[console.groq.com](https://console.groq.com)):

```
GROQ_API_KEY=your_key_here
```

## Running it

```bash
python app.py
```

Open the URL printed in your terminal — usually `http://localhost:7860`, but **check the
output**: if that port is taken, Gradio falls back to 7861, 7862, etc. Type a query (or click
one of the example chips), pick *Example wardrobe* or *Empty wardrobe (new user)*, and hit
**Find it**. The three panels show the top listing, an outfit idea, and your fit card.

You can also drive the agent without the UI:

```bash
python agent.py        # runs a happy-path query and the no-results path
pytest tests/          # runs the tool unit tests
```

## Project layout

```
├── app.py              # Gradio UI + handle_query() (maps the session dict to 3 panels)
├── agent.py            # run_agent() planning loop + query parser + session state
├── tools.py            # the three tools: search_listings, suggest_outfit, create_fit_card
├── tests/test_tools.py # unit tests, one per tool + one per failure mode
├── data/
│   ├── listings.json          # 40 mock secondhand listings
│   └── wardrobe_schema.json   # wardrobe format + example/empty wardrobes
├── utils/data_loader.py       # load_listings(), get_example_wardrobe(), get_empty_wardrobe()
└── planning.md         # design doc: specs, planning loop, diagram, walkthrough
```

---

## Tool inventory

### 1. `search_listings(description, size, max_price) -> list[dict]`

**Purpose:** Find listings in the dataset that match the user's request. Pure Python — no LLM.

| Parameter | Type | Meaning |
|-----------|------|---------|
| `description` | `str` | Keywords describing the item, e.g. `"vintage graphic tee"`. Matched (case-insensitive) against each listing's `title`, `description`, and `style_tags`. |
| `size` | `str \| None` | Size to filter by, e.g. `"M"`. Case-insensitive **substring** match, so `"m"` matches `"S/M"` and `"M (oversized)"`. `None` skips size filtering. |
| `max_price` | `float \| None` | Inclusive price ceiling; a listing passes if `price <= max_price`. `None` skips price filtering. |

**Returns:** a `list[dict]` of full listing dicts (`id, title, description, category, style_tags,
size, condition, price, colors, brand, platform`), sorted by relevance (keyword-overlap score)
highest first. Listings scoring 0 are dropped, so every returned dict is a genuine match.
Returns `[]` when nothing matches — it never raises.

### 2. `suggest_outfit(new_item, wardrobe) -> str`

**Purpose:** Style the chosen item using the user's wardrobe. Calls the Groq LLM
(`llama-3.3-70b-versatile`, temperature 0.7).

| Parameter | Type | Meaning |
|-----------|------|---------|
| `new_item` | `dict` | The selected listing dict (top search result). |
| `wardrobe` | `dict` | A wardrobe shaped like `wardrobe_schema.json`: an `"items"` key holding item dicts (`id, name, category, colors, style_tags, notes`). May be empty. |

**Returns:** a non-empty `str`. With a populated wardrobe it names specific owned pieces plus a
styling tip. With an empty wardrobe it gives general styling advice for the item instead of
referencing pieces the user doesn't have.

### 3. `create_fit_card(outfit, new_item) -> str`

**Purpose:** Turn the outfit into a casual, shareable Instagram/TikTok caption. Calls the Groq
LLM at temperature 1.0 so each card reads differently.

| Parameter | Type | Meaning |
|-----------|------|---------|
| `outfit` | `str` | The outfit suggestion returned by `suggest_outfit`. |
| `new_item` | `dict` | The selected listing dict — the prompt pulls `title`, `price`, `platform`. |

**Returns:** a 2–4 sentence caption `str` that mentions the item name, price, and platform once
each. If `outfit` is empty/whitespace, it returns a descriptive error string instead of raising.

---

## How the planning loop works

`run_agent(query, wardrobe)` in [agent.py](agent.py) is a **linear pipeline with an early-exit
branch**. It does not call all three tools unconditionally — whether `suggest_outfit` and
`create_fit_card` run at all depends on what `search_listings` returns.

1. **Initialize** — build a fresh `session` dict (the single source of truth for the run).
2. **Parse the query** — `_parse_query()` uses regex to pull `description`, `size`, and
   `max_price` out of the natural-language query (e.g. `"vintage tee under $30, size M"` →
   `{description: "vintage tee", size: "M", max_price: 30.0}`). No LLM is used for parsing.
   Stored in `session["parsed"]`.
3. **Search** — call `search_listings(**parsed)`; store the list in `session["search_results"]`.
4. **The decision** — *is `search_results` empty?*
   - **Yes → stop.** Write a specific, actionable message into `session["error"]` and `return`
     immediately. `suggest_outfit` and `create_fit_card` are **never called** — the agent will
     not run the LLM on an empty selection.
   - **No → continue.** Set `session["selected_item"] = search_results[0]` (top-ranked).
5. **Suggest outfit** — call `suggest_outfit(selected_item, wardrobe)`; store in
   `session["outfit_suggestion"]`. If the LLM call raises or returns blank, set `error` and
   return early (don't build a card from nothing).
6. **Create fit card** — call `create_fit_card(outfit_suggestion, selected_item)`; store in
   `session["fit_card"]`. A failure here is *soft*: the listing and outfit are still returned.
7. **Return** the completed session.

The loop knows it's done when `fit_card` is set (success) or as soon as `error` is set (early
exit). There are no retries or re-planning steps — each successful stage unconditionally enables
the next, and the only fork is the empty-results check in step 4.

## State management

There is one `session` dict per interaction, created by `_new_session()`. Tools never talk to
each other directly: the loop reads each tool's input from `session` and writes its output back,
so the next stage reads exactly what the previous stage wrote. Nothing is re-prompted from the
user mid-run, and no intermediate values are hardcoded.

| Session key | Written by | Read by |
|-------------|-----------|---------|
| `query` | caller | parse step |
| `parsed` (`description`, `size`, `max_price`) | parse step | `search_listings` |
| `search_results` | `search_listings` | the empty-check branch + item selection |
| `selected_item` | selection step (`search_results[0]`) | `suggest_outfit`, `create_fit_card` |
| `wardrobe` | caller | `suggest_outfit` |
| `outfit_suggestion` | `suggest_outfit` | `create_fit_card` |
| `fit_card` | `create_fit_card` | UI |
| `error` | any stage on early exit | `app.py` (checked first) |

`app.py`'s `handle_query()` runs the agent, then checks `session["error"]` **first**: if set, it
shows the error in panel 1 and blanks panels 2–3; otherwise it formats `selected_item` into a
readable listing and shows `outfit_suggestion` and `fit_card` in the other two panels.

I verified state flows by reference rather than re-derivation: wrapping the tools to capture
their arguments showed that `session["selected_item"]` **is** the exact dict passed into both
`suggest_outfit` and `create_fit_card`, and `session["outfit_suggestion"]` **is** the exact
string passed into `create_fit_card` (Python `is` identity, not just equality).

## Error handling (per tool, with examples)

| Tool | Failure mode | What the agent does |
|------|-------------|---------------------|
| `search_listings` | No listing matches the query | Returns `[]` (no exception). The loop sets `error` and returns early, **without** calling the LLM tools. |
| `suggest_outfit` | Wardrobe is empty | Does *not* error — returns general styling advice so a brand-new user still gets value. The loop continues to the fit card. |
| `create_fit_card` | Outfit string is empty/whitespace | Returns a descriptive message string rather than raising; the listing and outfit still reach the user. |

Concrete examples from testing (Milestone 5):

- **No results** — `run_agent("designer ballgown size XXS under $5", ...)` returns:
  `error = "I couldn't find any listings matching 'designer ballgown', size XXS, under $5. Try
  raising your budget, removing the size filter, or using broader keywords."` and leaves
  `selected_item`, `outfit_suggestion`, and `fit_card` all `None`. Instrumenting the tools
  confirmed the downstream tools were called **zero** times on this path.
- **Empty wardrobe** — `suggest_outfit(<Y2K baby tee>, get_empty_wardrobe())` returned a full
  paragraph of general advice ("pairs well with bottoms in neutral colors like denim, black, or
  beige… style with high-waisted jeans and sneakers for a relaxed look") — non-empty, no crash.
- **Empty outfit** — `create_fit_card("", item)` returned `"Couldn't generate a fit card — no
  outfit suggestion was provided. Try generating an outfit idea first."` instead of raising.

---

## How AI was used

I used Claude (Claude Code) throughout, one tool/section at a time, and reviewed each output
against my `planning.md` spec before trusting it. Two specific instances:

**1. Implementing `search_listings`.** I gave Claude the *Tool 1* block from `planning.md` (the
three parameters, the scoring/sorting return contract, and the empty-list failure mode) plus the
`load_listings()` docstring. It produced a filter-then-score function. **What I checked/changed:**
I confirmed it filtered on all three parameters and returned `[]` rather than raising on no
match. I specifically verified the size filter used a **case-insensitive substring** match (so
`"m"` matches `"S/M"`), which my spec required, and that zero-score listings were dropped before
sorting. I then ran it against the 5 example queries — including the deliberate no-results
"designer ballgown size XXS under $5" — to confirm the ranking was sensible.

**2. Implementing the planning loop (`run_agent`).** I gave Claude the *Planning Loop*, *State
Management*, and *Architecture* (diagram) sections plus the `_new_session` dict and the numbered
TODO in `agent.py`. It produced the loop. **What I overrode:** the first version I wrote leaked
the size token into the description because it matched on the lowercased query but stripped from
the original (uppercase) text — so `"size XXS"` survived in the parsed description. I rewrote the
parser to blank out matched spans by character position so the description comes out clean
(`"designer ballgown"`). I also added explicit try/except guards around the two LLM calls so a
transient API failure degrades gracefully instead of crashing the loop, and confirmed by
instrumentation that the empty-results branch returns before any LLM call.

---

## Spec reflection

Writing `planning.md` first paid off most on the planning loop: because the empty-results branch
and the session-key ownership table were already written down, implementing `run_agent` was
mostly transcription, and the diagram doubled as the prompt for generating it. The spec also
caught a real design question early — what should happen when a new user has an empty wardrobe —
which I resolved as "general advice, not an error," and that decision flowed straight into both
the tool and its test.

What changed from the original spec: I added regex-span-based query parsing (the spec said
"regex/string parsing" but not the exact mechanism), and I made the fit-card failure a *soft*
failure (still return the listing + outfit) rather than a hard early-exit, because losing the
caption shouldn't throw away two good results. The core three-tool flow and the search-driven
branch matched the plan exactly.
