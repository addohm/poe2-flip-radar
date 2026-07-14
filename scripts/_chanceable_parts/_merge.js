// Merge the per-category chanceable classifications (from the poe2db scrape agents)
// into scripts/chanceable_bases.json. Run: node scripts/_chanceable_parts/_merge.js
const fs = require("fs");
const path = require("path");
const dir = __dirname;
const parts = fs.readdirSync(dir).filter(f => f.endsWith(".json"));

const bases = new Set();
const deny = new Map(); // unique name -> {unique, base, reason}
for (const f of parts) {
  const doc = JSON.parse(fs.readFileSync(path.join(dir, f), "utf8"));
  (doc.chanceable_bases || []).forEach(b => bases.add(b.trim()));
  (doc.not_chanceable || []).forEach(x => {
    if (x && x.unique) deny.set(x.unique.trim().toLowerCase(), {
      unique: x.unique.trim(), base: x.base || "", reason: x.reason || "boss-locked / not in chance pool"
    });
  });
}

const out = {
  _comment: "Which item base types can be turned into a unique with an Orb of Chance, and which " +
    "notable uniques are excluded (boss-locked etc). Built from poe2db.tw (game-data extraction) by " +
    "verifying each unique's drop source per category. A base qualifies when it has >=1 globally-" +
    "droppable unique, is a plain base tier (not Advanced/Expert/Runemastered), and is released. " +
    "Regenerate with scripts/_chanceable_parts/_merge.js. See HANDOFF gotcha #3.",
  patch: "0.5.x Runes of Aldur",
  source: "https://poe2db.tw/us/ (per-unique drop data)",
  updated: "2026-07-14",
  chanceable_bases: [...bases].sort((a, b) => a.localeCompare(b)),
  not_chanceable_notable: [...deny.values()].sort((a, b) => a.unique.localeCompare(b.unique)),
};

const target = path.join(dir, "..", "chanceable_bases.json");
fs.writeFileSync(target, JSON.stringify(out, null, 2) + "\n");
console.log(`merged ${parts.length} parts -> ${out.chanceable_bases.length} bases, ` +
  `${out.not_chanceable_notable.length} denied uniques`);
console.log("parts:", parts.join(", "));
