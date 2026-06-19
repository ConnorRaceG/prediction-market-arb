"""
Optimal bet sizing for a two-(or more)-way arbitrage.

Given the effective cost of each outcome (cost to lock $1 of payout, fees
included), we split the bankroll so the return is identical no matter which
outcome wins — that's what makes the profit risk-free.
"""

from dataclasses import dataclass


@dataclass
class Sizing:
    stakes: dict          # {team: dollars to outlay on that outcome}
    contracts: int        # whole-contract anchor N (Kalshi quantity is an integer)
    total_cost: float     # T = sum of effective costs (the "price" of $1 payout)
    total_staked: float   # actual cash out = N * T (≈ bankroll)
    guaranteed_return: float  # = N: each side returns $N if it wins
    profit: float         # guaranteed_return - total_staked
    roi: float            # profit / total_staked


def compute_sizing(costs: dict[str, float], bankroll: float) -> Sizing:
    """
    Allocate the bankroll across outcomes to equalize payout, anchored to a
    WHOLE number of contracts.

    On Kalshi you buy an integer quantity of $1-payout contracts; you can't bet
    a dollar amount with cents. So we pick N = round(bankroll / T) contracts —
    each winning side returns exactly $N — and every leg's outlay is N * c_i
    (for a Kalshi leg, c_i is price+fee, so the integer quantity is exactly N).
        T = sum(c_i);  stake_i = N * c_i;  each side returns N.
    """
    T = sum(costs.values())
    contracts = max(1, round(bankroll / T))
    stakes = {team: contracts * c for team, c in costs.items()}
    total_staked = contracts * T
    guaranteed_return = float(contracts)
    profit = guaranteed_return - total_staked
    return Sizing(
        stakes=stakes,
        contracts=contracts,
        total_cost=T,
        total_staked=total_staked,
        guaranteed_return=guaranteed_return,
        profit=profit,
        roi=profit / total_staked,
    )
