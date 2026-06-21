# prediction-market-arb

Finds risk-free arbitrage across prediction markets and sportsbooks: Kalshi, DraftKings Predictions, Polymarket, and ~10 major US books. It prices the same real-world outcome on two venues, includes the fees, and flags any time the two sides add up to less than $1.

I started this after noticing about a 20% gap on the Nathan's Hot Dog Eating Contest between Kalshi and DraftKings. The lesson stuck: the edge isn't in sports moneylines, which are efficient and picked over by sharp money. It lives in the low-volume prediction-market boards nobody polices closely, like Time's Person of the Year, individual Senate races, or whether there's a recession, where DraftKings Predictions and Kalshi quietly disagree.

So the main piece is the futures scanner: it pulls every board off DraftKings Predictions, finds the matching Kalshi market, and compares them candidate by candidate. A Streamlit dashboard shows that alongside the original sports and Polymarket tracks in one grid, and a daily monitor pings me when a real arb actually opens. That last part matters because these gaps are intermittent, so a one-off scan usually shows nothing.

## What it does

- Scans DraftKings Predictions futures boards (culture, politics, economics, business) and compares each to its Kalshi counterpart, candidate by candidate
- Pulls live odds from Kalshi, ~10 US sportsbooks (via The Odds API), and Polymarket
- Prices everything with fees included: Kalshi's per-contract fee and the sportsbook's baked-in vig
- Sizes each side in whole Kalshi contracts, so the stake it shows is the number you actually enter
- Shows it all in one edge-sorted dashboard, and the daily monitor logs a history so you can watch a board drift toward an arb

## How the matching works

The hard part is knowing two boards are actually the same market. The tool uses three approaches, picked by how distinctive the board is:

- Sports: exact team-registry match, keyed on the set of teams and the game date (free, deterministic). The date keying stops a two-game series from collapsing into one phantom match.
- Distinctive futures like Person of the Year: match by shared candidate names. A "who wins" board has real people on it, so name overlap is a reliable signal. It's guarded so a small board contained inside a big one can't masquerade as a match (Person of the Decade is not Person of the Year).
- Binary and political boards like recession or a Senate race: the meaning is in the title, not the candidates, so Claude matches them semantically and aligns the outcomes across venues (DK "Yes" to Kalshi "Starts", "Republicans" to the Republican candidate). It's gated at high confidence and told that a different institution, place, or office is never a match, so it won't pair the ECB with the Fed.

## Architecture

Separate tracks. They share the same fee and sizing math but match markets differently, and only come together as cards in the dashboard.

| Track | Venues | Matching |
|---|---|---|
| Sports | Kalshi x ~10 US sportsbooks | per-sport team registry (exact, free) |
| Futures | DraftKings Predictions x Kalshi | candidate-name overlap, plus Claude for binary/political boards |
| Novelty | DraftKings sportsbook x Kalshi | Claude (semantic) |
| Polymarket | Polymarket x Kalshi | Claude (semantic) |

The sports path never loads the LLM or browser dependencies. Those are imported lazily, only when you enable a track that needs them.

```
src/
├── models.py                  # Canonical types: Market, Outcome
├── timeutil.py                # ET game-date helpers (timezone alignment)
├── adapters/                  # data sources -> normalized Markets
│   ├── kalshi.py              #   Kalshi API (RSA-PSS auth)
│   ├── odds_api.py            #   The Odds API (best line across US books)
│   ├── dk_novelty.py          #   DraftKings sportsbook novelty scraper
│   ├── dk_predictions.py      #   DraftKings Predictions futures scraper (exact cents from its API)
│   └── polymarket.py          #   Polymarket Gamma API
├── matching/
│   ├── normalize.py           #   per-sport team registry
│   ├── matcher.py             #   deterministic sports match by team-set + date
│   ├── futures_matcher.py     #   candidate-name overlap for futures boards
│   └── llm_matcher.py         #   semantic matching (Claude): novelty, Polymarket, futures
├── arb/
│   ├── fees.py                #   Kalshi fee / sportsbook vig models
│   ├── sizing.py              #   whole-contract bet sizing
│   ├── detector.py            #   deterministic sports arb detection
│   ├── novelty_detector.py    #   DraftKings sportsbook x Kalshi cross-venue arb
│   ├── polymarket_detector.py #   Polymarket x Kalshi cross-venue arb
│   └── futures_detector.py    #   per-candidate DK Predictions x Kalshi comparison
├── pipeline.py                # orchestration: fetch -> match -> detect
└── dashboard/
    ├── app.py                 #   Streamlit UI (one edge-sorted grid, all tracks)
    └── cards.py               #   view-model: maps each track's result to a card
scripts/
├── run_dk_predictions.py      # one-off futures scan vs Kalshi, printed to the terminal
└── monitor_futures.py         # daily scan + history log + arb alert
tests/                         # deterministic, novelty, and futures unit tests
```

## Setup

1. Install dependencies
```bash
pip install -r requirements.txt
```

2. Get API credentials
- Kalshi: sign up at [kalshi.com](https://kalshi.com), create an API key under Account > API, download the `.pem`, save it to `.secrets/kalshi.pem`
- The Odds API: sign up at [the-odds-api.com](https://the-odds-api.com) and copy your key
- Anthropic: get a key at [console.anthropic.com](https://console.anthropic.com). Needed for the futures (binary/political boards), novelty, and Polymarket matching; the sports track runs without it.

3. Configure environment
```bash
cp .env.example .env   # then fill in your keys
```
```
KALSHI_KEY_ID=your_key_id
ODDS_API_KEY=your_key
KALSHI_KEY_FILE=.secrets/kalshi.pem
ANTHROPIC_API_KEY=sk-ant-...
```

4. Validate and run
```bash
python config/settings.py            # prints [OK] when configured
streamlit run src/dashboard/app.py   # the dashboard (all tracks in one grid)
python scripts/run_dk_predictions.py # one-off futures scan vs Kalshi
python -m src.pipeline               # or the deterministic sports scan from the CLI
```

## Daily monitor

The futures gaps are intermittent, so the useful mode is to scan once a day and only hear about it when there's something to act on.

```bash
python scripts/monitor_futures.py            # one scan; logs to data/, alerts on a real arb
python scripts/monitor_futures.py --loop 24  # or keep scanning every 24h
```

Every run appends to `data/monitor_history.jsonl` (each board's best lock over time). When a board crosses into arb territory it writes `data/arbs_found.log`, prints a banner, and pops a desktop alert. On Windows you can run it daily with Task Scheduler.

## Tests

```bash
python -m tests.test_detector            # deterministic sports: matching, dates, arb math
python -m tests.test_novelty_detector    # cross-venue Dutch-book sizing
python -m tests.test_futures             # futures matcher overlap gate + comparison math
```

## Scope

- Detection, not execution. Sportsbooks and DraftKings Predictions have no betting API, so you place those bets yourself; the tool shows the edge and the exact stakes. Kalshi does have a trading API, which is the path to auto-placing the Kalshi leg later.
- Top-of-book only. It uses the best available price and doesn't look at order-book depth.
- Personal project, built and run for myself.
