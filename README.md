# Betting Market Arb Detector v2

A Python tool to detect arbitrage opportunities between prediction markets (Kalshi) and sportsbooks (via The Odds API).

## Architecture

```
src/
├── models.py              # Canonical data types (Market, Outcome)
├── adapters/              # Data source connectors → normalized Markets
│   ├── base.py            #   abstract base class
│   ├── kalshi.py          #   Kalshi API adapter
│   └── odds_api.py        #   The Odds API adapter (sportsbooks)
├── matching/
│   ├── normalize.py       # Event/outcome name normalization
│   └── matcher.py         # Group equivalent outcomes across sources
├── arb/
│   ├── odds.py            # Odds conversion utilities
│   ├── fees.py            # Fee models for each source
│   ├── detector.py        # Find arbs in matched groups
│   └── sizing.py          # Optimal bet sizing
├── pipeline.py            # Orchestrates fetch → match → detect
└── dashboard/app.py       # Streamlit UI
```

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Get API credentials

**Kalshi:**
- Sign up at https://kalshi.com
- Go to Account → API, create a key
- Download your private key (`.pem` file)
- Save it to `.secrets/kalshi.pem`

**The Odds API:**
- Sign up at https://the-odds-api.com
- Copy your API key from the dashboard

### 3. Configure environment

Copy `.env.example` to `.env` and fill in your credentials:
```bash
cp .env.example .env
```

Then edit `.env`:
```
KALSHI_KEY_ID=your_key_id_from_kalshi
ODDS_API_KEY=your_key_from_odds_api
KALSHI_KEY_FILE=.secrets/kalshi.pem
```

### 4. Validate setup
```bash
python config/settings.py
```

Should print `✓ All settings valid` if everything is configured correctly.

## Development Plan

### Phase 1: Core pipeline (proof of concept)
- [x] Project structure & config
- [ ] Kalshi adapter (fetch NBA moneylines from Kalshi)
- [ ] Odds API adapter (fetch NBA moneylines from DraftKings via The Odds API)
- [ ] Manual event matcher (map "Lakers vs Celtics" across both sources)
- [ ] Arb detection & sizing math
- [ ] Streamlit dashboard with Refresh button

### Phase 2: Robustness
- [ ] Fuzzy event name matching
- [ ] Historical arb tracking
- [ ] Add Polymarket as third source
- [ ] Spreads and player props

### Phase 3: Automation (optional)
- [ ] Optional auto-refresh on interval
- [ ] Notifications when arbs appear
- [ ] Live order book depth integration

## Decisions locked in

- **Sportsbook data**: The Odds API (reliable, documented, no scraping fragility)
- **First target**: Single-game NBA moneylines (binary outcomes, liquid, test-friendly)
- **v1 scope**: Kalshi + sportsbooks; Polymarket added in v2
- **Matching**: Start manual with `config/mappings.yaml`, automate later

## Terminology

- **Market**: A single betting event (e.g., "Lakers vs Celtics moneyline")
- **Outcome**: One side of a market (e.g., "Lakers win" at -110)
- **Arb**: A riskless profit across matched outcomes due to odds inefficiency
- **Vig**: The sportsbook's built-in margin (why moneylines sum to > 100% implied prob)
- **Kalshi fee**: Proportional to price and outcome probability; roughly 0.5% per side
