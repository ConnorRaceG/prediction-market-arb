import requests
from typing import Optional
from src.adapters.base import BaseAdapter
from src.models import Market, Outcome
from config.settings import Settings


class KalshiAdapter(BaseAdapter):
    """Kalshi prediction market adapter."""

    def __init__(self):
        super().__init__("kalshi")
        self.base_url = Settings.KALSHI_BASE_URL
        self.key_id = Settings.KALSHI_KEY_ID
        # TODO: RSA signing for authenticated requests
        # We'll need to load and sign with the private key from Settings.KALSHI_KEY_FILE

    def fetch_markets(self, sport: str, market_type: str = "moneyline") -> list[Market]:
        """
        Fetch live markets from Kalshi.

        For now, returns empty list. Implementation will:
        1. Authenticate with RSA-signed requests
        2. Query `/markets` endpoint for the given sport
        3. Filter to market_type (e.g. moneyline)
        4. Normalize outcomes and convert odds
        """
        # TODO: Implement
        return []

    def _get_authenticated_headers(self) -> dict:
        """Build Authorization header with RSA signature."""
        # TODO: Load private key from Settings.KALSHI_KEY_FILE
        # TODO: Create signature using cryptography.hazmat
        # See: https://docs.kalshi.com/docs/auth-guide
        raise NotImplementedError()
