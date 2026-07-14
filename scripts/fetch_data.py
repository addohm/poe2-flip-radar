#!/usr/bin/env python3
"""
PoE2 Flip Radar - data fetcher.

Pulls the poe2scout.com public API for the current softcore trade league,
computes flip/arbitrage/chancing analytics, and writes docs/data.json.

Runs on a schedule via GitHub Actions. Standard library only (no pip installs).
"""

import json
import os
import sys
import time
import math
import urllib.request
import urllib.parse
from datetime import datetime, timezone

API = "https://poe2scout.com/api"
REALM = "poe2"
USER_AGENT = "poe2-flip-radar (github pages dashboard)"

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.normpath(os.path.join(HERE, "..", "docs"))
OUT = os.path.join(DOCS, "data.json")
HIST_DIR = os.path.join(DOCS, "history")

# Which item base types can actually be turned into a unique with an Orb of Chance.
# The poe2scout `IsChanceable` flag is unreliable (see HANDOFF gotcha #3), so we use a
# curated allowlist derived from poe2db.tw (which reads the game's own data files).
# Loaded from scripts/chanceable_bases.json so the list can be refreshed without touching code.
CHANCEABLE_PATH = os.path.join(HERE, "chanceable_bases.json")


def load_chanceable():
    """Return (chanceable_base_set, not_chanceable_unique_set), both normalized lower/stripped.

    File shape: {"chanceable_bases": [...], "not_chanceable_notable": [{"unique": ...}, ...]}
    Missing file -> empty sets -> nothing is flagged chanceable (safe: no false jackpots).
    """
    try:
        with open(CHANCEABLE_PATH, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        print("  ! chanceable_bases.json missing/invalid; chancing list will be empty",
              file=sys.stderr)
        return frozenset(), frozenset()
    bases = frozenset(norm_name(b) for b in doc.get("chanceable_bases", []))
    deny = frozenset(norm_name(u.get("unique", "")) for u in doc.get("not_chanceable_notable", []))
    return bases, deny


def norm_name(s):
    # normalize curly apostrophes/quotes to straight so poe2db-derived names match poe2scout
    return (s or "").strip().lower().replace("’", "'").replace("‘", "'")


# Loaded once at import from chanceable_bases.json (norm_name is defined above).
CHANCEABLE_BASES, NOT_CHANCEABLE = load_chanceable()

# poe2scout categories that count as "gear" for the chanceable-gear view.
GEAR_CATS = {"armour", "weapon", "accessory"}


def is_chanceable(base, name):
    """A unique is chanceable if its base is in the allowlist and it isn't a
    known boss-only/unobtainable exception."""
    return norm_name(base) in CHANCEABLE_BASES and norm_name(name) not in NOT_CHANCEABLE


def get_url(url, retries=4):
    """GET a full JSON URL with basic retry/backoff."""
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (attempt + 1))
    print(f"  ! failed: {url} ({last})", file=sys.stderr)
    return None


def get(path, params=None, retries=4):
    """GET a poe2scout JSON endpoint with basic retry/backoff."""
    url = f"{API}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return get_url(url, retries)


# poe.ninja economy: gives per-unique `listingCount`, a demand/popularity signal the
# poe2scout board doesn't expose. Categories map poe2scout cat -> poe.ninja type.
NINJA = "https://poe.ninja/poe2/api/economy/stash/current/item/overview"
NINJA_TYPES = {"UniqueArmours", "UniqueWeapons", "UniqueAccessories",
               "UniqueJewels", "UniqueFlasks"}


def fetch_ninja_popularity(league):
    """Return {normalized unique name -> total listingCount across base variants}.

    Best-effort: if poe.ninja is unreachable we return {} and fall back to poe2scout
    quantities, so the site still builds.
    """
    pop = {}
    for ntype in sorted(NINJA_TYPES):
        url = NINJA + "?" + urllib.parse.urlencode({"league": league, "type": ntype})
        data = get_url(url)
        lines = (data or {}).get("lines") or []
        for it in lines:
            nm = norm_name(it.get("name"))
            if nm:
                pop[nm] = pop.get(nm, 0) + (it.get("listingCount") or 0)
        print(f"  ninja/{ntype}: {len(lines)}")
        time.sleep(0.4)
    return pop


def pick_league(leagues):
    """Current softcore trade league = IsCurrent and not a Hardcore variant."""
    current = [l for l in leagues if l.get("IsCurrent")]
    sc = [l for l in current if not l.get("Value", "").upper().startswith("HC")
          and "Hardcore" not in l.get("Value", "")]
    return (sc or current or leagues)[0]


def pct(new, old):
    if old in (None, 0) or new is None:
        return None
    return round((new / old - 1.0) * 100.0, 1)


def trend_from_logs(current, logs):
    """PriceLogs are newest-first; entries may be null. Return (chg1d, chg7d)."""
    clean = [e for e in (logs or []) if e and e.get("Price")]
    if not clean:
        return None, None
    return pct(current, clean[0]["Price"]), pct(current, clean[-1]["Price"])


def sig(v, n=4):
    """Round to n significant figures; keeps the JSON small and the shape intact."""
    if v is None or v == 0:
        return v
    return round(v, -int(math.floor(math.log10(abs(v)))) + (n - 1))


def spark_from_logs(current, logs):
    """Compact price series oldest->newest (ending at current) for a sparkline.

    PriceLogs are newest-first and may contain nulls; we drop nulls, reverse to
    chronological order, and append the current price as the final point.
    Returns None when there's not enough signal to draw a line.
    """
    clean = [e["Price"] for e in (logs or []) if e and e.get("Price")]
    series = list(reversed(clean))
    if current:
        series.append(current)
    series = [sig(p) for p in series if p]
    return series if len(series) >= 2 else None


def paginate(kind, league, cat):
    endpoint = "Uniques/ByCategory" if kind == "u" else "Currencies/ByCategory"
    items, page = [], 1
    while True:
        data = get(f"{REALM}/Leagues/{urllib.parse.quote(league)}/{endpoint}",
                   {"Category": cat, "Page": page, "PerPage": 250, "DataPoints": 8})
        if not data or not data.get("Items"):
            break
        items.extend(data["Items"])
        if page >= data.get("Pages", 1):
            break
        page += 1
        time.sleep(0.4)
    return items


def norm_unique(it):
    meta = it.get("ItemMetadata") or {}
    price = it.get("CurrentPrice")
    c1, c7 = trend_from_logs(price, it.get("PriceLogs"))
    name = it.get("Name") or it.get("Text")
    base = meta.get("base_type") or it.get("Type")
    return {"name": name, "base": base,
            "type": it.get("Type"), "cat": it.get("CategoryApiId"),
            "price": price, "qty": it.get("CurrentQuantity"),
            "chg1d": c1, "chg7d": c7, "spark": spark_from_logs(price, it.get("PriceLogs")),
            "chanceable": is_chanceable(base, name),
            "mods": tooltip_mods(meta),
            "icon": it.get("IconUrl")}


def tooltip_mods(meta):
    """Compact mod bundle for a hover tooltip. Keys kept short to limit JSON size:
    i=implicit mods, e=explicit mods, f=flavour text, lvl=level requirement."""
    impl = meta.get("implicit_mods") or []
    expl = meta.get("explicit_mods") or []
    flav = meta.get("flavor_text")
    lvl = (meta.get("requirements") or {}).get("Level")
    if not (impl or expl or flav):
        return None
    out = {}
    if impl:
        out["i"] = impl
    if expl:
        out["e"] = expl
    if flav:
        out["f"] = flav
    if lvl:
        out["lvl"] = lvl
    return out


def norm_currency(it):
    meta = it.get("ItemMetadata") or {}
    price = it.get("CurrentPrice")
    c1, c7 = trend_from_logs(price, it.get("PriceLogs"))
    return {"name": it.get("Text") or it.get("ApiId"), "apiId": it.get("ApiId"),
            "price": price, "qty": it.get("CurrentQuantity"),
            "chg1d": c1, "chg7d": c7, "spark": spark_from_logs(price, it.get("PriceLogs")),
            "mods": currency_mods(meta, it),
            "icon": it.get("IconUrl")}


def currency_mods(meta, it):
    """Tooltip bundle for currency/essences: what the item does. Reuses the unique
    tooltip shape (e=effect lines shown as mods, f=description shown as flavour)."""
    effect = meta.get("effect") or it.get("effect")
    desc = meta.get("description") or it.get("description")
    lines = effect if isinstance(effect, list) else ([effect] if effect else [])
    lines = [s for s in lines if s]
    if not (lines or desc):
        return None
    out = {}
    if lines:
        out["e"] = lines
    if desc:
        out["f"] = desc
    return out


def flip_score(row):
    """Explainable 0-100 flippability: liquidity + momentum + meaningful value."""
    price, qty, chg7 = row.get("price") or 0, row.get("qty") or 0, row.get("chg7d")
    if price <= 0 or qty <= 0:
        return 0
    liq = min(1.0, math.log10(qty + 1) / 4.0)
    mom = 0.5 if chg7 is None else max(0.0, min(1.0, (chg7 + 30) / 60.0))
    val = min(1.0, math.log10(price + 1) / 5.0)
    return round(100 * (0.45 * liq + 0.35 * mom + 0.20 * val), 1)


def build_chancing(uniques, chance_ex, divine_ex):
    """
    Chancing yields a unique on the SAME base type only. For each base the
    'jackpot' is the priciest unique; cheaper ones are consolations. Odds are
    hidden, so we report the break-even hit-rate rather than a fabricated EV.
    """
    by_base = {}
    for u in uniques:
        b = u.get("base")
        if b and u.get("price") and u.get("chanceable"):
            by_base.setdefault(b, []).append(u)

    opps = []
    for base, us in by_base.items():
        us = sorted(us, key=lambda x: -(x["price"] or 0))
        jack = us[0]
        jack_ex = jack["price"] or 0
        if jack_ex < (divine_ex or 400):   # ignore bases whose best hit is under ~1 div
            continue
        invest_ex = (chance_ex or 5) * 3
        opps.append({
            "base": base, "jackpot": jack["name"],
            "jackpot_ex": round(jack_ex, 1),
            "jackpot_div": round(jack_ex / divine_ex, 2) if divine_ex else None,
            "consolations": [{"name": c["name"], "ex": round(c["price"], 1),
                              "div": round(c["price"] / divine_ex, 2) if divine_ex else None}
                             for c in us[1:5]],
            "num_uniques": len(us),
            "invest_ex": round(invest_ex, 1),
            "invest_div": round(invest_ex / divine_ex, 3) if divine_ex else None,
            "ratio": round(jack_ex / invest_ex, 1) if invest_ex else None,
            "breakeven_pct": round(invest_ex / jack_ex * 100, 3) if jack_ex else None,
        })
    opps.sort(key=lambda o: -(o["jackpot_ex"] or 0))
    return opps


def suggestions(uniques, currency, essences, chancing):
    def top(rows, key, n):
        return sorted(rows, key=key, reverse=True)[:n]
    uni = [u for u in uniques if (u.get("qty") or 0) >= 200 and (u.get("price") or 0) >= 50]
    for u in uni:
        u["score"] = flip_score(u)
    cur = [c for c in currency if (c.get("qty") or 0) >= 1000 and (c.get("price") or 0) >= 5
           and (c.get("chg7d") is None or c["chg7d"] >= -15)]
    ess = [e for e in essences if (e.get("qty") or 0) >= 100 and (e.get("chg7d") or 0) > 0]
    return {"uniques": top(uni, lambda r: r["score"], 8),
            "currency": top(cur, lambda r: (r.get("qty") or 0), 8),
            "essences": top(ess, lambda r: (r.get("chg7d") or 0), 8),
            "chancing": chancing[:10]}


def main():
    os.makedirs(DOCS, exist_ok=True)
    os.makedirs(HIST_DIR, exist_ok=True)

    leagues = get(f"{REALM}/Leagues") or []
    if not leagues:
        print("Could not load leagues; aborting.", file=sys.stderr)
        sys.exit(1)
    league = pick_league(leagues)["Value"]
    print(f"League: {league}")

    cats = get(f"{REALM}/Leagues/{urllib.parse.quote(league)}/Items/Categories") or {}
    uni_cats = [c["ApiId"] for c in cats.get("UniqueCategories", [])]
    cur_cats = [c["ApiId"] for c in cats.get("CurrencyCategories", [])]

    all_uniques, uniques_by_cat = [], {}
    for c in uni_cats:
        rows = [r for r in (norm_unique(x) for x in paginate("u", league, c)) if r.get("price")]
        uniques_by_cat[c] = rows
        all_uniques.extend(rows)
        print(f"  uniques/{c}: {len(rows)}")

    # Enrich uniques with poe.ninja listing counts (a "how many players use it" proxy).
    ninja_pop = fetch_ninja_popularity(league)
    for u in all_uniques:
        u["listings"] = ninja_pop.get(norm_name(u["name"]))
    print(f"  matched poe.ninja listings for "
          f"{sum(1 for u in all_uniques if u.get('listings') is not None)}/{len(all_uniques)} uniques")

    all_currency, currency_by_cat = [], {}
    for c in cur_cats:
        rows = [r for r in (norm_currency(x) for x in paginate("c", league, c)) if r.get("price")]
        currency_by_cat[c] = rows
        all_currency.extend(rows)
        print(f"  currency/{c}: {len(rows)}")

    def find_cur(api_id):
        for r in all_currency:
            if r.get("apiId") == api_id:
                return r.get("price")
        return None

    divine_ex = find_cur("divine") or 400.0
    chance_ex = find_cur("chance") or 5.0
    chaos_ex = find_cur("chaos") or 50.0
    essences = currency_by_cat.get("essences", [])
    chancing = build_chancing(all_uniques, chance_ex, divine_ex)
    sugg = suggestions(all_uniques, currency_by_cat.get("currency", []), essences, chancing)

    payload = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "league": league,
        "divine_ex": round(divine_ex, 1),
        "chance_ex": round(chance_ex, 2),
        "chaos_ex": round(chaos_ex, 2),
        "category_labels": {c["ApiId"]: c["Label"] for c in
                            cats.get("UniqueCategories", []) + cats.get("CurrencyCategories", [])},
        "uniques_by_cat": uniques_by_cat,
        "currency_by_cat": currency_by_cat,
        "chancing": chancing,
        "suggestions": sugg,
        "counts": {"uniques": len(all_uniques), "currency": len(all_currency),
                   "chancing_bases": len(chancing),
                   "chanceable_uniques": sum(1 for u in all_uniques if u.get("chanceable"))},
    }

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    snap = os.path.join(HIST_DIR, datetime.now(timezone.utc).strftime("%Y-%m-%d") + ".json")
    with open(snap, "w", encoding="utf-8") as f:
        json.dump({"generated": payload["generated"], "divine_ex": payload["divine_ex"],
                   "counts": payload["counts"]}, f)
    print(f"Wrote {OUT} ({payload['counts']})")


if __name__ == "__main__":
    main()
