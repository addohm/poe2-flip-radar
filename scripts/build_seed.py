#!/usr/bin/env python3
"""
Build a seed docs/data.json from already-fetched sample API responses, WITHOUT
hitting the network. Also serves as an offline test of the transform functions
in fetch_data.py. The GitHub Action replaces this seed with a full daily pull.
"""
import json, os, sys, glob, re
from datetime import datetime, timezone

import fetch_data as fd

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.normpath(os.path.join(HERE, "..", "docs"))
os.makedirs(os.path.join(DOCS, "history"), exist_ok=True)


def load_json_body(path):
    """Files have a small header then a JSON body; may be truncated."""
    t = open(path, encoding="utf-8", errors="replace").read()
    i = t.find('{"CurrentPage')
    if i < 0:
        i = t.find("{")
    return t[i:]


def parse_items(body):
    """Tolerantly extract complete top-level objects from an Items:[...] array."""
    j = body.find('"Items":[')
    if j < 0:
        return []
    k = body.find("[", j)
    items, depth, start, instr, esc = [], 0, None, False, False
    for pos in range(k + 1, len(body)):
        ch = body[pos]
        if instr:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                instr = False
            continue
        if ch == '"':
            instr = True
        elif ch == "{":
            if depth == 0:
                start = pos
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                chunk = body[start:pos + 1]
                try:
                    items.append(json.loads(chunk))
                except Exception:
                    pass
                start = None
        elif ch == "]" and depth == 0:
            break
    return items


def find_file(sub):
    root = "/sessions/sweet-epic-dijkstra/mnt/.claude/projects"
    hits = glob.glob(f"{root}/**/{sub}", recursive=True)
    return hits[0] if hits else None


# ---- sample files (currency & essences complete; accessory/weapon truncated) ----
SAMPLES = {
    "currency": "mcp-workspace-web_fetch-1784018849528.txt",
    "essences": "mcp-workspace-web_fetch-1784018916578.txt",
    "weapon":   "mcp-workspace-web_fetch-1784018921465.txt",
    "accessory":"mcp-workspace-web_fetch-1784021936663.txt",
}

raw = {}
for k, fn in SAMPLES.items():
    p = find_file(fn)
    raw[k] = parse_items(load_json_body(p)) if p else []
    print(f"{k}: {len(raw[k])} items", file=sys.stderr)

uniques_by_cat = {
    "accessory": [r for r in (fd.norm_unique(x) for x in raw["accessory"]) if r.get("price")],
    "weapon":    [r for r in (fd.norm_unique(x) for x in raw["weapon"]) if r.get("price")],
}
currency_by_cat = {
    "currency": [r for r in (fd.norm_currency(x) for x in raw["currency"]) if r.get("price")],
    "essences": [r for r in (fd.norm_currency(x) for x in raw["essences"]) if r.get("price")],
}
all_uniques = uniques_by_cat["accessory"] + uniques_by_cat["weapon"]
all_currency = currency_by_cat["currency"] + currency_by_cat["essences"]

def find_cur(api_id):
    for r in all_currency:
        if r.get("apiId") == api_id:
            return r.get("price")
    return None

divine_ex = find_cur("divine") or 464.0
chance_ex = find_cur("chance") or 4.34
chancing = fd.build_chancing(all_uniques, chance_ex, divine_ex)
sugg = fd.suggestions(all_uniques, currency_by_cat["currency"], currency_by_cat["essences"], chancing)

payload = {
    "generated": datetime.now(timezone.utc).isoformat(),
    "league": "Runes of Aldur",
    "seed": True,
    "divine_ex": round(divine_ex, 1),
    "chance_ex": round(chance_ex, 2),
    "category_labels": {"accessory": "Accessories", "weapon": "Weapons",
                        "currency": "Currency", "essences": "Essences"},
    "uniques_by_cat": uniques_by_cat,
    "currency_by_cat": currency_by_cat,
    "chancing": chancing,
    "suggestions": sugg,
    "counts": {"uniques": len(all_uniques), "currency": len(all_currency),
               "chancing_bases": len(chancing)},
}

out = os.path.join(DOCS, "data.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(payload, f, separators=(",", ":"))
print("wrote", out, payload["counts"], file=sys.stderr)
# sanity print
print("divine_ex", divine_ex, "chance_ex", chance_ex, file=sys.stderr)
print("chancing sample:", json.dumps(chancing[:3], indent=1)[:800], file=sys.stderr)
