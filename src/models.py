from dataclasses import dataclass
from typing import Optional


@dataclass
class Outcome:
    """
    A single outcome in a market (e.g., 'Lakers win').

    Construct with ANY one of odds_american / odds_decimal / implied_prob;
    the other two are derived automatically. Sportsbooks give American odds,
    Kalshi gives implied probability (price in cents) — both work.
    """
    name: str                              # Canonical name (normalized)
    odds_american: Optional[float] = None  # American odds (-110, +200)
    odds_decimal: Optional[float] = None   # Decimal odds (1.91, 2.50)
    implied_prob: Optional[float] = None   # Implied probability (0-1)

    def __post_init__(self):
        """Derive all three odds formats from whichever one was provided."""
        # First get decimal odds from whatever input we have
        if self.odds_decimal is None:
            if self.odds_american is not None:
                self.odds_decimal = self._american_to_decimal(self.odds_american)
            elif self.implied_prob is not None:
                self.odds_decimal = 1 / self.implied_prob
            else:
                raise ValueError(
                    f"Outcome '{self.name}' needs at least one of: "
                    f"odds_american, odds_decimal, implied_prob"
                )

        # Then derive the remaining two from decimal
        if self.implied_prob is None:
            self.implied_prob = 1 / self.odds_decimal
        if self.odds_american is None:
            self.odds_american = self._decimal_to_american(self.odds_decimal)

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
