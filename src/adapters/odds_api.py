import requests
from src.adapters.base import BaseAdapter
from src.models import Market, Outcome
from src.timeutil import iso_to_unix, et_date
from config.settings import Settings

# Map our canonical market_type names to The Odds API market keys
MARKET_TYPE_MAP = {
    "moneyline": "h2h",
    "spread": "spreads",
    "over_under": "totals",
}

# Regulated US sportsbooks the user can actually place at. The Odds API returns
# all of them in one request, so we keep the best line per outcome across the
# set (an arb only needs SOME book to beat Kalshi). Caesars = 'williamhill_us'.
MAJOR_US_BOOKS = (
    "draftkings", "fanduel", "betmgm", "betrivers", "williamhill_us",
    "caesars", "espnbet", "fanatics", "ballybet", "hardrockbet",
)


def _decimal(american: float) -> float:
    """Decimal payout for American odds — higher is better for the bettor."""
    return 1 + (american / 100 if american > 0 else 100 / abs(american))


class OddsApiAdapter(BaseAdapter):
    """The Odds API adapter — best line per outcome across major US books."""

    def __init__(self, books: tuple[str, ...] = MAJOR_US_BOOKS):
        super().__init__("odds_api")
        self.base_url = Settings.ODDS_API_BASE_URL
        self.api_key = Settings.ODDS_API_KEY
        self.books = set(books)         # which sportsbooks to consider
        self.requests_remaining = None  # updated after each call
        self._session = requests.Session()

    def fetch_markets(self, sport: str, market_type: str = "moneyline") -> list[Market]:
        """
        Fetch sportsbook odds from The Odds API.

        Args:
            sport: e.g. 'basketball_nba'
            market_type: 'moneyline', 'spread', or 'over_under'

        Returns:
            One Market per game, each outcome priced at the best book line.
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
        """Best line per outcome across our books, tagged with the winning book."""
        # outcome name -> (american, book_key) keeping the most favorable price
        best: dict[str, tuple[float, str]] = {}
        for bm in event.get("bookmakers", []):
            if bm["key"] not in self.books:
                continue
            md = next((m for m in bm.get("markets", []) if m["key"] == api_market), None)
            if not md:
                continue
            for o in md["outcomes"]:
                am = float(o["price"])
                cur = best.get(o["name"])
                if cur is None or _decimal(am) > _decimal(cur[0]):
                    best[o["name"]] = (am, bm["key"])

        if len(best) < 2:
            return None  # need both sides priced by at least one book

        outcomes = [
            Outcome(name=name, odds_american=am, book=book)
            for name, (am, book) in best.items()
        ]
        commence = event.get("commence_time")
        start_time = iso_to_unix(commence) if commence else None
        event_name = f"{event['away_team']} @ {event['home_team']}"
        return self._create_market(
            market_id=event["id"],
            event_name=event_name,
            market_type=market_type,
            outcomes=outcomes,
            url=None,
            raw_data=event,
            start_time=start_time,
            slate_date=et_date(start_time) if start_time else None,
        )


if __name__ == "__main__":
    # Quick live test
    adapter = OddsApiAdapter()
    markets = adapter.fetch_markets("baseball_mlb", "moneyline")
    print(f"Requests remaining this month: {adapter.requests_remaining}")
    print(f"Fetched {len(markets)} MLB games (best line across {len(adapter.books)} books)\n")
    for m in markets[:5]:
        print(m, "| books:", [o.book for o in m.outcomes])
