import requests
from src.adapters.base import BaseAdapter
from src.models import Market, Outcome
from config.settings import Settings

# Map our canonical market_type names to The Odds API market keys
MARKET_TYPE_MAP = {
    "moneyline": "h2h",
    "spread": "spreads",
    "over_under": "totals",
}


class OddsApiAdapter(BaseAdapter):
    """The Odds API adapter (sportsbook aggregator)."""

    def __init__(self, bookmaker: str = "draftkings"):
        super().__init__("odds_api")
        self.base_url = Settings.ODDS_API_BASE_URL
        self.api_key = Settings.ODDS_API_KEY
        self.bookmaker = bookmaker  # which sportsbook to extract odds from
        self.requests_remaining = None  # updated after each call
        self._session = requests.Session()

    def fetch_markets(self, sport: str, market_type: str = "moneyline") -> list[Market]:
        """
        Fetch sportsbook odds from The Odds API.

        Args:
            sport: e.g. 'basketball_nba'
            market_type: 'moneyline', 'spread', or 'over_under'

        Returns:
            List of normalized Market objects for the configured bookmaker.
        """
        api_market = MARKET_TYPE_MAP.get(market_type, "h2h")
        url = f"{self.base_url}/sports/{sport}/odds"
        params = {
            "apiKey": self.api_key,
            "regions": "us",
            "markets": api_market,
            "oddsFormat": "american",
        }

        resp = self._session.get(url, params=params, timeout=15)
        # Track remaining quota (The Odds API returns this header)
        self.requests_remaining = resp.headers.get("x-requests-remaining")
        resp.raise_for_status()

        events = resp.json()
        markets = []
        for event in events:
            market = self._parse_event(event, market_type, api_market)
            if market:
                markets.append(market)
        return markets

    def _parse_event(self, event: dict, market_type: str, api_market: str) -> Market | None:
        """Extract the configured bookmaker's odds from one event."""
        # Find our target bookmaker
        bookmaker = next(
            (bm for bm in event.get("bookmakers", []) if bm["key"] == self.bookmaker),
            None,
        )
        if not bookmaker:
            return None

        # Find the requested market within that bookmaker
        market_data = next(
            (m for m in bookmaker.get("markets", []) if m["key"] == api_market),
            None,
        )
        if not market_data:
            return None

        outcomes = [
            Outcome(name=o["name"], odds_american=float(o["price"]))
            for o in market_data["outcomes"]
        ]

        event_name = f"{event['away_team']} @ {event['home_team']}"
        return self._create_market(
            market_id=f"{event['id']}_{self.bookmaker}",
            event_name=event_name,
            market_type=market_type,
            outcomes=outcomes,
            url=None,
            raw_data=event,
        )


if __name__ == "__main__":
    # Quick live test
    adapter = OddsApiAdapter(bookmaker="draftkings")
    markets = adapter.fetch_markets("basketball_nba", "moneyline")
    print(f"Requests remaining this month: {adapter.requests_remaining}")
    print(f"Fetched {len(markets)} DraftKings NBA moneyline markets\n")
    for m in markets[:5]:
        print(m)
