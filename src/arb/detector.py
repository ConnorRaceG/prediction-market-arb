"""
Detect arbitrage opportunities in matched market groups.

TODO: Implement arb math including fees, vig, and profit calculation.
"""

from dataclasses import dataclass
from src.models import Market


@dataclass
class ArbOpportunity:
    """A detected arbitrage opportunity."""
    markets: list[Market]  # The markets involved
    outcomes: list[str]    # Which outcomes to bet on
    profit_margin: float   # Profit % after fees
    stakes: dict           # How much to bet on each outcome {outcome_name: amount}
    description: str       # Human-readable summary


def detect_arbs(market_groups: list[list[Market]]) -> list[ArbOpportunity]:
    """
    Find arbitrage opportunities in matched market groups.

    Args:
        market_groups: Groups of equivalent markets from match_markets()

    Returns:
        List of detected arbs that meet the MIN_ARB_MARGIN threshold
    """
    # TODO: Implement
    # 1. For each group of matched markets
    # 2. Check all possible bet combinations
    # 3. Account for fees and sportsbook vig
    # 4. Calculate required stakes for each outcome to guarantee profit
    # 5. Return arbs where profit margin > MIN_ARB_MARGIN
    return []
