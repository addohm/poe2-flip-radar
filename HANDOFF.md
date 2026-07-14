# HANDOFF — PoE2 Flip Radar

> Read this first. It's the full context for continuing this project.
> You can rename this file to `CLAUDE.md` if you want it auto-loaded in Claude Code.

## What this project is

A **static website on GitHub Pages** that helps a Path of Exile 2 trade-league player
find ways to invest and flip currency/items. It shows plain-language suggestions for four
categories — **currency arbitrage, unique flips, essence flips, and chancing** — generated
from price history pulled off the free [poe2scout.com](https://poe2scout.com) API.

Design intent (from the owner, verbatim goals):
- "Simple website with categories of ways to invest and flip, suggestions made based on history."
- "Something simple for simple-minded people." → favor plain-language cards over dense tables.
- Must be **expandable beyond a few items per category** → full searchable tables under each category.
- Refresh **daily** (they were fine with daily; weekly optional).
- Chancing is a first-class category. The mental model they gave: *"a 1-div wand, ~2 div of
  currency investment, with a chance at a 200-div return."* → the chancing view models
  "invest cheap → shot at a big jackpot unique on the same base."

Owner's bankroll context: ~50+ Divine, softcore PC trade, wants unique flips + currency arbitrage.
There's a companion strategy doc (`poe2-flipping-playbook.md`) that lives outside this repo; the
site is the automated version of that thinking.

## Current status: WORKING / deployable

- `scripts/fetch_data.py` — compiles, runs the full pull, writes `docs/data.json`. **Not yet run
  against the live API from CI** — it was validated offline (see Testing). Expect it to work but
  watch the first Action run.
- `docs/index.html` — complete dashboard, JS syntax-checked. Renders from `data.json`.
- `docs/data.json` — a **seed** built from partial sample data (marked `"seed": true`). The daily
  Action overwrites it with the full economy.
- `.github/workflows/update.yml` — daily cron (06:15 UTC) + manual dispatch; commits data.
- Not yet pushed to GitHub or deployed to Pages. Setup steps are in `README.md`.

## Architecture / file map

```
scripts/fetch_data.py   THE fetcher+analytics. stdlib only (urllib, json, math). Writes docs/data.json.
scripts/build_seed.py   Offline seed/test builder. Parses saved sample responses, reuses fetch_data's
                        transform functions, writes a partial data.json. Safe to delete once live.
docs/index.html         Single-file dashboard (vanilla JS, no deps, inline CSS). Reads data.json.
docs/data.json          Generated data the site reads. Committed so the page works pre-first-run.
docs/history/*.json     One tiny dated snapshot per day (divine rate + counts) for future trend work.
docs/.nojekyll          Stops GitHub Pages/Jekyll from ignoring the history folder.
.github/workflows/update.yml  Daily cron -> run script -> commit data.json.
README.md               End-user setup + deploy instructions.
```

Data flow: **GitHub Action → `fetch_data.py` → `docs/data.json` → `index.html`.** No server, no
build step, no client-side API calls (visitors read the committed JSON, not the API).

## The poe2scout API — what we learned (important)

Base URL `https://poe2scout.com/api`. OpenAPI at `/api/openapi.json` (Swagger UI at `/api/swagger`).
Realm segment is `poe2`. **All prices are in Exalted Orbs (Ex)** — Exalted is the base unit, not Chaos.

Endpoints we use:
- `GET /poe2/Leagues` → list; pick `IsCurrent==true` and not a `HC`/Hardcore variant.
  Current league at build time: **"Runes of Aldur"** (patch 0.5.x).
- `GET /poe2/Leagues/{League}/Items/Categories` → unique + currency category ApiIds.
- `GET /poe2/Leagues/{League}/Uniques/ByCategory?Category=..&Page=..&PerPage=..&DataPoints=..`
- `GET /poe2/Leagues/{League}/Currencies/ByCategory?Category=..&...`

Unique categories: `accessory, armour, flask, jewel, map, weapon, sanctum`.
Currency categories: `currency, fragments, runes, essences, ultimatum (Soul Cores), expedition,
ritual, vaultkeys, breach, abyss, uncutgems, lineagesupportgems, delirium, incursion, idol, ...`.

**Gotchas discovered (save yourself the pain):**
1. **`PriceLogs` are newest-first**, and entries can be `null`. `PriceLogs[0]` ≈ yesterday,
   last non-null ≈ ~7 days ago. `trend_from_logs()` handles this.
2. **`CurrentPrice` / `CurrentQuantity` can be null** on thin items — always filter/guard.
3. **`IsChanceable` on unique items is unreliable** — it returned `false` for Headhunter and
   Mageblood, which ARE chanceable. **Do not trust it.** We instead group uniques by
   `ItemMetadata.base_type` (chancing only yields a unique of the same base). Boss-only uniques
   and Advanced/Expert bases aren't truly chanceable, but the API doesn't flag that cleanly —
   a known imperfection in the chancing list. If you want accuracy, cross-reference a
   community "chanceable bases" list.
4. **Divine price is inconsistent between endpoints.** `/Leagues` reported DivinePrice ≈ 695 Ex
   while the `currency` category's "Divine Orb" `CurrentPrice` ≈ 464 Ex. We use the **currency
   board value** (`apiId == "divine"`) as the source of truth for Ex↔Div conversion.
   Chance Orb is `apiId == "chance"`.
5. **Odd/empty responses**: some `PerPage`/`DataPoints` combos returned an empty body via one
   fetch client; the paginated `Page=1&PerPage=250` form is reliable. The `Search` query param
   appeared to return `Total:0` for names that exist — **don't rely on `Search`**, filter client-side.
6. **CORS is untested.** We deliberately do server-side (Action) fetching so it doesn't matter.
   If someone later wants live client-side fetching, verify CORS headers first; if absent, keep
   the Action approach.
7. Be polite: the fetcher sleeps 0.4s between pages and retries with backoff. Keep it that way.

## Key design decisions (and why)

- **Action-generated JSON, not client-side fetch** — avoids CORS/rate-limit issues, lets us build
  history, and keeps the page instant for visitors.
- **stdlib-only Python** — zero `pip install`, so CI is trivial and can't break on deps.
- **Chancing shows break-even hit-rate, not "expected value"** — real chancing odds are a hidden
  GGG rarity tier and are NOT public. Presenting a computed EV would be dishonest. We show
  `breakeven_pct` = investment/jackpot, surfaced in the UI as "profit only if you hit better than
  1-in-N," with a prominent warning. **Keep this honesty; don't fabricate odds.**
- **`flip_score()`** is a deliberately simple, explainable 0–100 blend (liquidity 45% / momentum
  35% / value 20%). It's a heuristic, not gospel — tune weights freely.
- Single-file HTML, inline everything — matches "simple," no toolchain.

## Testing / how it was validated

- `python3 -m py_compile` on both scripts — pass.
- `node --check` on the extracted `<script>` — pass.
- `data.json` validated for all keys the HTML reads; `build_seed.py` produced sensible output
  (e.g. Utility Belt → Mageblood jackpot with Ingenuity consolation, break-even ~0.007%).
- **Not yet done:** a real end-to-end run of `fetch_data.py` against the live API (blocked from the
  build environment). First CI run is the real integration test — check the Action log.

There are no automated tests. If you add CI beyond the data job, a lightweight check would be:
run `fetch_data.py`, assert `data.json` parses and `counts.uniques > 0`.

## Deploy (summary — full version in README.md)

1. Push repo to GitHub. 2. Settings → Pages → deploy from branch `main`, folder `/docs`.
3. Settings → Actions → General → Workflow permissions → **Read and write**.
4. Actions tab → *Update PoE2 economy data* → **Run workflow** once. Self-updates daily after.

## Suggested next steps (roughly prioritized)

1. **Run the Action once and verify** the full `data.json` (all categories populate; divine/chance
   prices sane). This is the main open item.
2. **Per-item price-history charts.** `docs/history/` already saves daily snapshots but only the
   divine rate + counts. To chart individual items, extend the snapshot to store per-item prices
   (careful with repo size — consider keeping only tracked items, or a rolling 30-day window).
   Chart.js from CDN is the easy path (allowed on Pages).
3. **Week-over-week movers.** Compare today's `data.json` to a ~7-day-old snapshot and flag the
   biggest risers/fallers per category. Needs richer history than #2's current snapshot.
4. **Refine the chancing list** by intersecting `base_type` with a real chanceable-bases list so
   boss-only/Advanced/Expert bases stop appearing as false jackpots (see API gotcha #3).
5. **Currency Exchange spread data.** The API has `ExchangeSnapshot` / `SnapshotPairs` endpoints
   (see openapi.json) — could compute real bid/ask spreads for the arbitrage tab instead of just
   ranking by market depth.
6. **HC / league toggle.** `pick_league()` currently forces softcore; the data exists for HC and
   other leagues. Could fetch multiple and add a dropdown.
7. Minor UX: remember last tab (localStorage), mobile table polish, copy-to-clipboard trade search
   links (deep-link to pathofexile.com/trade2 with the item name).

## Conventions / notes for whoever continues

- Keep `fetch_data.py` dependency-free. If you must add a lib, add `requirements.txt` and a pip
  step in the workflow — but prefer not to.
- Prices are Ex everywhere internally; convert to Div only for display using `divine_ex`.
- Don't reintroduce trust in `IsChanceable`. Don't invent chancing odds.
- The owner values **simplicity and honesty** over feature density. New features should keep the
  "Start Here" page skimmable.
- `build_seed.py` and its sample-file paths are throwaway scaffolding tied to the original build
  session — once the live Action runs, you can delete `build_seed.py`.

*Not affiliated with Grinding Gear Games.*
