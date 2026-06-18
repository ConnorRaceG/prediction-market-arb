from dataclasses import dataclass
from typing import Optional
from enum import Enum


class OddsFormat(Enum):
    """Standard odds formats."""
    AMERICAN = "american"      # -110, +150, etc
    DECIMAL = "decimal"        # 1.91, 2.50, etc
    IMPLIED_PROB = "implied"   # 0.523, etc (0-1 scale)


@dataclass
class Outcome:
    """A single outcome in a market (e.g., 'Lakers win')."""
    name: str                  # Canonical name (normalized)
    odds_american: float       # American odds (-110, +200, etc)
    odds_decimal: Optional[float] = None
    implied_prob: Optional[float] = None

    def __post_init__(self):
        """Compute missing odds formats from whichever we have."""
        if self.odds_american is not None and self.odds_decimal is None:
            self.odds_decimal = self._american_to_decimal(self.odds_american)
        if self.odds_decimal is not None and self.implied_prob is None:
            self.implied_prob = 1 / self.odds_decimal


    @staticmethod
    def _american_to_decimal(american: float) -> float:
        """Convert American odds to decimal."""
        if american > 0:
            return 1 + (american / 100)
        else:
            return 1 + (100 / abs(american))

    @staticmethod
    def _decimal_to_american(decimal: float) -> float:
        """Convert decimal odds to American."""
        if decimal >= 2:
            return (decimal - 1) * 100
        else:
            return -100 / (decimal - 1)


@dataclass
class Market:
    """A full market (e.g., 'Lakers vs Celtics moneyline')."""
    source: str                # 'kalshi', 'odds_api', 'polymarket'
    market_id: str             # Unique ID in that source
    event_name: str            # Canonical event name (normalized)
    market_type: str           # 'moneyline', 'spread', 'over_under', 'futures'
    outcomes: list[Outcome]    # All possible outcomes
    timestamp: float           # When we fetched this (unix timestamp)
    url: Optional[str] = None  # Link to market on source website
    raw_data: Optional[dict] = None  # Raw JSON for debugging

    def __repr__(self):
        outcome_str = ", ".join([f"{o.name} @ {o.odds_american:+.0f}" for o in self.outcomes])
        return f"Market({self.source}/{self.market_type}: {self.event_name} | {outcome_str})"
