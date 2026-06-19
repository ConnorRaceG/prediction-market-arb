import base64
import re
import time
import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from src.adapters.base import BaseAdapter
from src.models import Market, Outcome
from src.timeutil import et_date, et_unix
from config.settings import Settings, project_root

_MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
     "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], start=1)}

# Game tickers look like KXMLBGAME-26JUN211435SDTEX (YY MON DD HHMM teams) or,
# for some sports, KXWNBAGAME-26JUN20SEAPHX (no time) — so HHMM is optional.
_TICKER_TIME = re.compile(r"-(\d{2})([A-Z]{3})(\d{2})(\d{4})?")

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
        self._session = requests.Session()  # reuse TCP/TLS across the many calls

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
        resp = self._session.get(self.base_url + endpoint, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    # ---- Market fetching ----

    @staticmethod
    def _outcome_from_leg(leg: dict) -> Outcome | None:
        """Build an Outcome from a Kalshi market leg, or None if no executable ask price."""
        yes_ask = float(leg.get("yes_ask_dollars", 0) or 0)
        if not (0 < yes_ask < 1):
            return None
        name = leg.get("yes_sub_title") or leg.get("ticker", "").split("-")[-1]
        return Outcome(name=name, implied_prob=yes_ask)

    @staticmethod
    def _ticker_time(event_ticker: str) -> tuple[float | None, str | None]:
        """(start_unix, ET game-date) parsed from a game ticker's embedded date/time."""
        m = _TICKER_TIME.search(event_ticker or "")
        if not m:
            return None, None
        yy, mon, dd, hhmm = m.groups()
        month = _MONTHS.get(mon)
        if not month:
            return None, None
        hour, minute = (int(hhmm[:2]), int(hhmm[2:])) if hhmm else (12, 0)
        start = et_unix(2000 + int(yy), month, int(dd), hour, minute)
        # When the ticker carries no time (e.g. WNBA), start_time is just a noon
        # placeholder; the date is exact and the sportsbook supplies the real time.
        return (start if hhmm else None), et_date(start)

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
            outcomes = [o for leg in legs if (o := self._outcome_from_leg(leg))]
            if len(outcomes) < 2:
                continue  # need both sides to be tradeable

            start_time, slate_date = self._ticker_time(event_ticker)
            markets.append(
                self._create_market(
                    market_id=event_ticker,
                    event_name=legs[0].get("title", event_ticker),
                    market_type=market_type,
                    outcomes=outcomes,
                    url="https://kalshi.com/markets",
                    raw_data={"event_ticker": event_ticker, "legs": legs},
                    start_time=start_time,
                    slate_date=slate_date,
                )
            )
        return markets


    def fetch_event_index(self, categories, max_pages: int = 25) -> list[tuple[str, str]]:
        """
        Cheap listing of (event_ticker, title) for open events in the given
        categories — no per-event market calls. Lets a caller decide which events
        are worth pulling in full (e.g. only the ones a DK board might match).

        Pages through all open events; the default cap is high enough to reach the
        long tail (Kalshi has a few thousand open events across all categories).
        """
        out: list[tuple[str, str]] = []
        cursor = None
        for _ in range(max_pages):
            params = {"status": "open", "limit": 200}
            if cursor:
                params["cursor"] = cursor
            data = self._get("/events", params)
            for e in data.get("events", []):
                if e.get("category") in categories:
                    out.append((e["event_ticker"], e.get("title", e["event_ticker"])))
            cursor = data.get("cursor")
            if not cursor:
                break
        return out

    def fetch_event_market(self, event_ticker: str, title: str = "") -> Market | None:
        """
        Pull one event's open markets as a single multi-outcome Market. Outcomes
        come from each candidate's yes_ask; raw_data carries per-candidate yes/no
        asks (the No side is needed for the futures cross-venue Yes/No arb).
        """
        data = self._get("/markets", {"event_ticker": event_ticker, "status": "open", "limit": 100})
        legs = data.get("markets", [])
        outcomes = [o for leg in legs if (o := self._outcome_from_leg(leg))]
        if not outcomes:
            return None
        candidates = []
        for leg in legs:
            name = leg.get("yes_sub_title") or leg.get("ticker", "").split("-")[-1]
            ya = float(leg.get("yes_ask_dollars") or 0)
            na = float(leg.get("no_ask_dollars") or 0)
            candidates.append({
                "name": name,
                "yes": ya if 0 < ya < 1 else None,
                "no": na if 0 < na < 1 else None,
            })
        return self._create_market(
            market_id=event_ticker,
            event_name=title or event_ticker,
            market_type="novelty",
            outcomes=outcomes,
            url="https://kalshi.com/markets",
            raw_data={"event_ticker": event_ticker, "candidates": candidates},
        )

    def fetch_novelty_markets(self, categories=("Entertainment",), max_events: int = 25) -> list[Market]:
        """
        Fetch open non-sports markets (awards, entertainment, etc.) for novelty arb.
        One Market per event (outcomes = candidate sub-markets priced at yes_ask),
        capped to keep both the API calls and the LLM matcher input bounded.
        """
        index = self.fetch_event_index(categories)[:max_events]
        markets = []
        for event_ticker, title in index:
            m = self.fetch_event_market(event_ticker, title)
            if m is not None:
                markets.append(m)
        return markets


if __name__ == "__main__":
    adapter = KalshiAdapter()
    status = adapter._get("/exchange/status")
    print(f"Exchange active: {status.get('exchange_active')}\n")

    markets = adapter.fetch_markets("baseball_mlb", "moneyline")
    print(f"Fetched {len(markets)} Kalshi MLB game markets\n")
    for m in markets[:5]:
        print(m)
