"""
Fee models.

The two sources charge very differently, and getting this right is what
separates real arbs from phantom ones:

  - Kalshi: a trading fee is added ON TOP of the contract price. Per their
    published general schedule, fee per $1 contract = 0.07 * P * (1-P),
    where P is the price in dollars. (Rounds up to the next cent per order;
    we use the continuous rate for sizing/EV.)

  - Sportsbooks (via The Odds API): the vig is already BAKED INTO the line, so
    the implied probability we read is already the true cost. No add-on.

NOTE: Verify the current Kalshi rate for your specific market — sports markets
can differ. It's a single constant below.
"""

KALSHI_FEE_RATE = 0.07  # general trading-fee coefficient; verify per market


def kalshi_fee_per_contract(price: float) -> float:
    """Kalshi trading fee per $1 contract bought at `price` (in dollars)."""
    return KALSHI_FEE_RATE * price * (1 - price)


def effective_cost(source: str, implied_prob: float) -> float:
    """
    Cost to lock in $1 of payout on an outcome, including fees.

    This is THE number the arb detector compares: if the effective costs of
    both sides of a game sum to < $1, there's a guaranteed profit.
    """
    if source == "kalshi":
        return implied_prob + kalshi_fee_per_contract(implied_prob)
    # Sportsbook: vig is already in the price
    return implied_prob
