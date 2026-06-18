import base64
import time
import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from src.adapters.base import BaseAdapter
from src.models import Market, Outcome
from config.settings import Settings, project_root

# Maps our canonical sport keys (same keys The Odds API uses) to Kalshi game
# series tickers. Pattern is KX{LEAGUE}GAME. Verified live where in-season;
# NBA/NHL confirmed by pattern (0 open games off-season as of June 2026).
SPORT_SERIES = {
    "baseball_mlb": "KXMLBGAME",
    "basketball_nba": "KXNBAGAME",
    "basketball_wnba": "KXWNBAGAME",
    "americanfootball_nfl": "KXNFLGAME",
    "icehockey_nhl": "KXNHLGAME",
}


class KalshiAdapter(BaseAdapter):
    """Kalshi prediction market adapter (RSA-PSS authenticated)."""

    PATH_PREFIX = "/trade-api/v2"

    def __init__(self):
        super().__init__("kalshi")
        self.base_url = Settings.KALSHI_BASE_URL
        self.key_id = Settings.KALSHI_KEY_ID
        self._private_key = self._load_private_key()

    # ---- Auth ----

    def _load_private_key(self):
        key_path = project_root / Settings.KALSHI_KEY_FILE
        with open(key_path, "rb") as f:
            return serialization.load_pem_private_key(f.read(), password=None)

    def _sign(self, timestamp_ms: str, method: str, path: str) -> str:
        """RSA-PSS sign `timestamp + METHOD + path` per Kalshi auth spec."""
        message = f"{timestamp_ms}{method}{path}".encode("utf-8")
        signature = self._private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode("utf-8")

    def _auth_headers(self, method: str, signed_path: str) -> dict:
        timestamp_ms = str(int(time.time() * 1000))
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
            "KALSHI-ACCESS-SIGNATURE": self._sign(timestamp_ms, method, signed_path),
        }

    def _get(self, endpoint: str, params: dict = None) -> dict:
        """Authenticated GET. `endpoint` like '/markets' (no prefix, no query)."""
        signed_path = self.PATH_PREFIX + endpoint  # signature excludes query string
        headers = self._auth_headers("GET", signed_path)
        resp = requests.get(self.base_url + endpoint, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    # ---- Market fetching ----

    def fetch_markets(self, sport: str, market_type: str = "moneyline") -> list[Market]:
        """
        Fetch open Kalshi game markets for a sport.

        Kalshi lists one binary market per team per game. We group those by
        event_ticker and build a single two-outcome Market per game, using each
        team's yes_ask (the price to buy that team to win) as its implied prob.
        """
        series = SPORT_SERIES.get(sport)
        if not series:
            return []

        data = self._get(
            "/markets",
            {"series_ticker": series, "status": "open", "limit": 200},
        )

        # Group the per-team binary markets by their shared event (game)
        events: dict[str, list[dict]] = {}
        for rm in data.get("markets", []):
            events.setdefault(rm["event_ticker"], []).append(rm)

        markets = []
        for event_ticker, legs in events.items():
            outcomes = []
            for leg in legs:
                yes_ask = float(leg.get("yes_ask_dollars", 0) or 0)
                if not (0 < yes_ask < 1):
                    continue  # no executable ask price right now
                team = leg.get("yes_sub_title") or leg["ticker"].split("-")[-1]
                outcomes.append(Outcome(name=team, implied_prob=yes_ask))

            if len(outcomes) < 2:
                continue  # need both sides to be tradeable

            markets.append(
                self._create_market(
                    market_id=event_ticker,
                    event_name=legs[0].get("title", event_ticker),
                    market_type=market_type,
                    outcomes=outcomes,
                    url="https://kalshi.com/markets",
                    raw_data={"event_ticker": event_ticker, "legs": legs},
                )
            )
        return markets


    def fetch_novelty_markets(self, categories=("Entertainment",), max_events: int = 25) -> list[Market]:
        """
        Fetch open non-sports markets (awards, entertainment, etc.) for novelty arb.

        Each Kalshi event becomes one Market whose outcomes are its candidate
        sub-markets (yes_sub_title) priced at yes_ask. Capped to keep both the
        API calls and the LLM matcher input bounded.
        """
        tickers: list[tuple[str, str]] = []
        cursor = None
        for _ in range(8):
            params = {"status": "open", "limit": 200}
            if cursor:
                params["cursor"] = cursor
            data = self._get("/events", params)
            for e in data.get("events", []):
                if e.get("category") in categories:
                    tickers.append((e["event_ticker"], e.get("title", e["event_ticker"])))
            cursor = data.get("cursor")
            if not cursor or len(tickers) >= max_events:
                break
        tickers = tickers[:max_events]

        markets = []
        for event_ticker, title in tickers:
            data = self._get("/markets", {"event_ticker": event_ticker, "status": "open", "limit": 100})
            outcomes = []
            for leg in data.get("markets", []):
                yes_ask = float(leg.get("yes_ask_dollars", 0) or 0)
                if not (0 < yes_ask < 1):
                    continue
                name = leg.get("yes_sub_title") or leg.get("ticker", "")
                outcomes.append(Outcome(name=name, implied_prob=yes_ask))
            if outcomes:
                markets.append(self._create_market(
                    market_id=event_ticker,
                    event_name=title,
                    market_type="novelty",
                    outcomes=outcomes,
                    url="https://kalshi.com/markets",
                    raw_data={"event_ticker": event_ticker},
                ))
        return markets


if __name__ == "__main__":
    adapter = KalshiAdapter()
    status = adapter._get("/exchange/status")
    print(f"Exchange active: {status.get('exchange_active')}\n")

    markets = adapter.fetch_markets("baseball_mlb", "moneyline")
    print(f"Fetched {len(markets)} Kalshi MLB game markets\n")
    for m in markets[:5]:
        print(m)
