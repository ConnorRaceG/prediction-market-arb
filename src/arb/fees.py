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


def dk_predictions_fee_per_contract(price: float) -> float:
    """
    DraftKings Predictions fee per $1 contract bought at `price` (per side).

    Unlike Kalshi's proportional fee, DK charges a FLAT per-contract amount tiered
    by price (its published schedule, DK fee + exchange fee combined): 1c for cheap
    or expensive contracts (1-19c or 97-99c), 2c for the 20-96c middle. Around 2c per
    leg on most prices, which is enough to sink a thin lock. Re-verify at:
    https://myaccount.draftkings.com/documents/fee-disclosure?product=predict
    """
    cents = round(price * 100)
    return 0.01 if (cents <= 19 or cents >= 97) else 0.02


def effective_cost(source: str, implied_prob: float) -> float:
    """
    Cost to lock in $1 of payout on an outcome, including fees.

    This is THE number the arb detector compares: if the effective costs of
    both sides of a game sum to < $1, there's a guaranteed profit.
    """
    if source == "kalshi":
        return implied_prob + kalshi_fee_per_contract(implied_prob)
    if source == "dk_predictions":
        return implied_prob + dk_predictions_fee_per_contract(implied_prob)
    # Sportsbook / Polymarket: vig is already in the price
    return implied_prob
