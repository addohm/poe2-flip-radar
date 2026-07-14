# PoE2 Flip Radar

A simple, static website that shows **the best ways to invest and flip in Path of Exile 2**,
with suggestions generated from price history. Four categories:

- 💰 **Currency arbitrage** — the most liquid orbs to buy low / sell high
- 📈 **Unique flips** — liquid, rising uniques worth buying underpriced and relisting
- 🧪 **Essence flips** — in-demand essences trending up
- 🎰 **Chancing** — for each white base, the priciest unique you could hit (your "jackpot"),
  with honest break-even odds

Data comes from the free [poe2scout.com](https://poe2scout.com) API and refreshes **once a day**
via a GitHub Action. The site itself is plain HTML/JS — no build step, no server.

## How it works

```
scripts/fetch_data.py   -> pulls the API, computes analytics, writes docs/data.json
docs/index.html         -> the website; reads data.json and renders it
.github/workflows/update.yml -> runs the script daily and commits the fresh data.json
docs/history/*.json     -> a small dated snapshot each day (divine rate + counts)
```

Everything the visitor needs is in `docs/`. GitHub Pages serves that folder.

## Setup (about 5 minutes, one time)

1. **Create a repo** on GitHub (e.g. `poe2-flip-radar`) and upload these files
   (keep the folder structure). Via the command line:
   ```bash
   git init
   git add .
   git commit -m "PoE2 Flip Radar"
   git branch -M main
   git remote add origin https://github.com/<you>/poe2-flip-radar.git
   git push -u origin main
   ```
2. **Turn on Pages:** repo **Settings → Pages → Build and deployment → Source: "Deploy from a
   branch"**, Branch = `main`, Folder = **`/docs`**, Save.
   Your site appears at `https://<you>.github.io/poe2-flip-radar/`.
3. **Turn on the daily updater:** repo **Settings → Actions → General → Workflow permissions →
   "Read and write permissions"**, Save. (This lets the Action commit the new `data.json`.)
4. **First run:** open the **Actions** tab → *Update PoE2 economy data* → **Run workflow**.
   After it finishes (~1–2 min) your page shows live data. It then runs itself every day.

The repo already ships with a **seed `data.json`** so the page works immediately, even before the
first Action run. (It's a partial sample; the daily run replaces it with the full economy.)

## Change how often it refreshes

Edit the `cron` line in `.github/workflows/update.yml`:

- Daily 06:15 UTC (default): `"15 6 * * *"`
- Twice daily: add a second line `- cron: "15 18 * * *"`
- Weekly (Mondays): `"15 6 * * 1"`

## Tuning the suggestions

All the logic is in `scripts/fetch_data.py`, near the top of each function:

- `flip_score()` — weights for liquidity / momentum / value
- `build_chancing()` — the `< divine_ex` cutoff decides which bases are "worth" showing
- `suggestions()` — the min-stock / min-price thresholds for each category

No external libraries — it's pure Python standard library, so nothing to install.

## A word on chancing

Chancing turns a **white base into a random unique of that same base — or destroys it.** The odds
are a hidden rarity tier GGG never publishes, and they're brutal for chase items (community testing
suggests ~1 in 1,000–2,000 for the rarest). The dashboard shows the **break-even hit-rate** so you
can see how much of a lottery each base is. The only zero-variance profit from a Chance Orb is to
**sell it.** Treat the chancing tab as "fun money," not a plan.

*Not affiliated with Grinding Gear Games. Prices move constantly — verify before big trades.*
