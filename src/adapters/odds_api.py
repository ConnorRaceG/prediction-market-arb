import requests
from src.adapters.base import BaseAdapter
from src.models import Market, Outcome
from config.settings import Settings


class OddsApiAdapter(BaseAdapter):
    """The Odds API adapter (sportsbook aggregator)."""

    def __init__(self):
        super().__init__("odds_api")
        self.base_url = Settings.ODDS_API_BASE_URL
        self.api_key = Settings.ODDS_API_KEY

    def fetch_markets(self, sport: str, market_type: str = "moneyline") -> list[Market]:
        """
        Fetch sportsbook odds from The Odds API.

        For now, returns empty list. Implementation will:
        1. Query `/sports/{sport}/odds` endpoint
        2. Filter to market_type (e.g. 'h2h' for moneyline)
        3. Parse bookmaker odds (typically from 'DraftKings', 'FanDuel', etc.)
        4. Normalize to Outcome objects and convert American → decimal
        """
        # TODO: Implement
        return []
