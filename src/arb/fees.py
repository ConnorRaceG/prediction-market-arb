"""
Fee models for each source.

Kalshi charges proportional trading fees, sportsbooks bake vig into the line.
"""

from config.settings import Settings


def get_kalshi_fee(price: float) -> float:
    """
    Calculate Kalshi trading fee.

    Kalshi charges ~0.5% maker/taker on both sides, proportional to price.
    This is a simplified model; check Kalshi docs for exact formula.

    Args:
        price: The share price (0.01 to 0.99)

    Returns:
        Fee as a decimal (e.g., 0.005 = 0.5%)
    """
    # TODO: Verify exact Kalshi fee structure
    return 0.005


def get_sportsbook_vig(prob_1: float, prob_2: float) -> float:
    """
    Calculate implied vig from overround.

    If two outcomes have implied probs that sum to >100%,
    the difference is the sportsbook's vig.

    Args:
        prob_1: Implied probability of outcome 1 (0-1)
        prob_2: Implied probability of outcome 2 (0-1)

    Returns:
        Vig as a decimal (e.g., 0.04 = 4%)
    """
    overround = prob_1 + prob_2
    if overround > 1:
        return overround - 1
    return 0
