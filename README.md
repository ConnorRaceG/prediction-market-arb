# prediction-market-arb

Finds risk-free arbitrage between US sportsbooks, Kalshi, and Polymarket. It prices the same real-world outcome on two venues, includes the fees, and flags any time the two sides add up to less than $1.

I started this after noticing about a 20% gap on the Nathan's Hot Dog Eating Contest between Kalshi and DraftKings. Figured if it shows up once it shows up elsewhere, so I built something to find it automatically.

There's a Streamlit dashboard that shows each opportunity, the exact stakes to place, and how close every other game is to becoming an arb. You refresh it manually.

## What it does

- Pulls live odds from Kalshi and ~10 US sportsbooks (through The Odds API), one request each
- Matches the same game across venues and keeps the best line per outcome
- Includes the fees that kill most naive arbs: Kalshi's per-contract fee and the sportsbook's baked-in vig
- Sizes each side in whole Kalshi contracts, so the stake it shows is the number you actually enter
- Sorts by edge and shows the full price board on each card

A couple of things that took real work to get right: fees move the answer a lot (a +2.5% gross edge on one game dropped to +0.74% after Kalshi's fee, which is below the line to bet), and matching has to key on the game date as well as the teams, otherwise a two-game series with the same teams merges different days and invents arbs that aren't there.

## Architecture

Three separate tracks. They share the same fee and sizing math but match games differently.

| Track | Venues | Matching | Status |
|---|---|---|---|
| Deterministic | Kalshi x sportsbooks | per-sport team registry (exact, free) | core |
| Novelty | DraftKings novelty x Kalshi | semantic, via Claude (no team key exists) | working |
| Polymarket | Polymarket x Kalshi | semantic, via Claude (prediction vs prediction) | working |

The deterministic path never loads the LLM or browser dependencies. Those are imported lazily, only when you run a novelty or Polymarket scan.

```
src/
├── models.py                  # Canonical types: Market, Outcome
├── timeutil.py                # ET game-date helpers (timezone alignment)
├── adapters/                  # data sources -> normalized Markets
│   ├── kalshi.py              #   Kalshi API (RSA-PSS auth)
│   ├── odds_api.py            #   The Odds API (best line across US books)
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

1. Install dependencies
```bash
pip install -r requirements.txt
```

2. Get API credentials
- Kalshi: sign up at [kalshi.com](https://kalshi.com), create an API key under Account > API, download the `.pem`, save it to `.secrets/kalshi.pem`
- The Odds API: sign up at [the-odds-api.com](https://the-odds-api.com) and copy your key
- Anthropic (optional, only for the novelty and Polymarket matching): get a key at [console.anthropic.com](https://console.anthropic.com)

3. Configure environment
```bash
cp .env.example .env   # then fill in your keys
```
```
KALSHI_KEY_ID=your_key_id
ODDS_API_KEY=your_key
KALSHI_KEY_FILE=.secrets/kalshi.pem
ANTHROPIC_API_KEY=sk-ant-...     # optional
```

4. Validate and run
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

- Detection, not execution. Sportsbooks have no betting API, so you place the bets yourself. The tool shows the edge and the exact stakes. Kalshi/Polymarket is detection-only too, since Polymarket isn't tradeable from every US state yet.
- Top-of-book only. It uses the best available price and doesn't look at order-book depth.
- Personal project, built and run for myself.
