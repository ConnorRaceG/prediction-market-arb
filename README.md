# prediction-market-arb

Detects **risk-free arbitrage** between [Kalshi](https://kalshi.com) (a regulated prediction market) and major US sportsbooks — and between Kalshi and [Polymarket](https://polymarket.com) — by pricing the *same real-world outcome* on two venues, fees included, and flagging when the two sides sum to less than $1.

> Born out of catching a ~20% spread on a novelty market — the Nathan's Hot Dog Eating Contest, of all things — between Kalshi and DraftKings. This is the systematic version of that hunch.

A manual-refresh Streamlit dashboard shows each opportunity, the exact stakes to place, and how close every other game is to crossing into arb territory.

## What it does

- Pulls live odds from **Kalshi** + **~10 major US sportsbooks** (via The Odds API), one request each
- Matches the same game across venues and keeps the **best line per outcome**
- Models the **fees that kill naive arbs** — Kalshi's per-contract fee and the sportsbook's baked-in vig
- Sizes each side to **whole Kalshi contracts**, so the displayed stake is actually placeable
- Sorts by edge; expandable cards show full prices, game time, and a side-by-side price board

## Why it's harder than it looks

This is where most "arb finders" quietly lose money:

- **Fees are decisive.** On a real game, a +2.5% *gross* edge collapsed to +0.74% *net* once Kalshi's fee was applied — below the threshold to bet. Ignore fees and you chase edges that aren't there. → [`src/arb/fees.py`](src/arb/fees.py)
- **Date-aware matching.** A two-game series shares the same pair of teams; keying on teams alone merges different days and invents arbs from mismatched odds. Markets are keyed on **(team-set, ET game date)**. → [`src/matching/matcher.py`](src/matching/matcher.py)
- **Whole-contract sizing.** Kalshi sells integer contracts, not dollar amounts. Sizing anchors to *N contracts* so the number you see is the number you actually enter. → [`src/arb/sizing.py`](src/arb/sizing.py)
- **Best line across books.** DraftKings only posts the imminent slate; pulling every major book in a single Odds API call roughly doubled matched games and tightened the edges.

## Architecture

Three independent tracks, sharing the same fee/sizing math but matched differently:

| Track | Venues | Matching | Status |
|---|---|---|---|
| **Deterministic** | Kalshi × sportsbooks | per-sport team registry (exact, free) | core |
| **Novelty** | DraftKings novelty × Kalshi | semantic, via Claude (no team key exists) | working |
| **Polymarket** | Polymarket × Kalshi | semantic, via Claude (prediction vs prediction) | working |

The deterministic path never loads the LLM or browser dependencies — they're imported lazily, only when you run a novelty or Polymarket scan.

```
src/
├── models.py                  # Canonical types: Market, Outcome
├── timeutil.py                # ET game-date helpers (timezone alignment)
├── adapters/                  # data sources -> normalized Markets
│   ├── kalshi.py              #   Kalshi API (RSA-PSS auth)
│   ├── odds_api.py            #   The Odds API (best line across major US books)
│   ├── dk_novelty.py          #   DraftKings novelty scraper (Playwright)
│   └── polymarket.py          #   Polymarket Gamma API
├── matching/
│   ├── normalize.py           #   per-sport team registry
│   ├── matcher.py             #   deterministic match by team-set + date
│   └── llm_matcher.py         #   semantic matcher (Claude) for novelty + Polymarket
├── arb/
│   ├── fees.py                #   Kalshi fee / sportsbook vig models
│   ├── sizing.py              #   whole-contract bet sizing
│   ├── detector.py            #   deterministic arb detection
│   ├── novelty_detector.py    #   DraftKings x Kalshi cross-venue arb
│   └── polymarket_detector.py #   Polymarket x Kalshi cross-venue arb
├── pipeline.py                # orchestration: fetch -> match -> detect
└── dashboard/app.py           # Streamlit UI
tests/                         # deterministic + novelty detector unit tests
```

## Setup

**1. Install dependencies**
```bash
pip install -r requirements.txt
```

**2. Get API credentials**
- **Kalshi** — sign up at [kalshi.com](https://kalshi.com), create an API key under Account → API, download the `.pem`, and save it to `.secrets/kalshi.pem`
- **The Odds API** — sign up at [the-odds-api.com](https://the-odds-api.com) and copy your key
- **Anthropic** *(optional)* — only needed for the novelty / Polymarket LLM matching; get a key at [console.anthropic.com](https://console.anthropic.com)

**3. Configure environment**
```bash
cp .env.example .env   # then fill in your keys
```
```
KALSHI_KEY_ID=your_key_id
ODDS_API_KEY=your_key
KALSHI_KEY_FILE=.secrets/kalshi.pem
ANTHROPIC_API_KEY=sk-ant-...     # optional
```

**4. Validate + run**
```bash
python config/settings.py            # prints [OK] when configured
streamlit run src/dashboard/app.py   # the dashboard
python -m src.pipeline               # or run the deterministic scan from the CLI
```

## Tests

```bash
python -m tests.test_detector            # deterministic: matching, dates, arb math
python -m tests.test_novelty_detector    # cross-venue Dutch-book sizing
```

## Scope

- **Detection, not execution.** Sportsbooks have no betting API, so bets are placed manually — the tool shows the edge and the exact stakes; you execute. (Kalshi↔Polymarket is detection-only too: Polymarket isn't tradeable from every US state yet.)
- **Top-of-book.** Uses the best available price; order-book depth is a known next step.
- Personal project — built and run for myself, cleaned up for sharing.

## What's next

- Order-book depth for honest sizing at scale
- Alerting when an arb appears (currently manual refresh)
- Filtering Polymarket by topic to surface live Kalshi↔Polymarket overlap

## Glossary

- **Arb** — a riskless profit from pricing the same outcome differently across venues
- **Vig** — a sportsbook's built-in margin (why moneylines imply >100% total probability)
- **Kalshi fee** — proportional to price and outcome probability; roughly 0.5% per side
