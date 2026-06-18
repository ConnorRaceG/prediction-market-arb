from abc import ABC, abstractmethod
from typing import Optional
import time
from src.models import Market


class BaseAdapter(ABC):
    """Abstract base for all data source adapters."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def fetch_markets(self, sport: str, market_type: str = "moneyline") -> list[Market]:
        """
        Fetch markets from this source.

        Args:
            sport: e.g. 'basketball_nba', 'american_football_nfl'
            market_type: e.g. 'moneyline', 'spread', 'over_under'

        Returns:
            List of Market objects, normalized and timestamped.
        """
        pass

    def _create_market(
        self,
        market_id: str,
        event_name: str,
        market_type: str,
        outcomes: list,
        url: Optional[str] = None,
        raw_data: Optional[dict] = None,
    ) -> Market:
        """Helper to create a normalized Market object."""
        return Market(
            source=self.name,
            market_id=market_id,
            event_name=event_name,
            market_type=market_type,
            outcomes=outcomes,
            timestamp=time.time(),
            url=url,
            raw_data=raw_data,
        )
