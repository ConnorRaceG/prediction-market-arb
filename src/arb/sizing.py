"""
Optimal bet sizing for a two-(or more)-way arbitrage.

Given the effective cost of each outcome (cost to lock $1 of payout, fees
included), we split the bankroll so the return is identical no matter which
outcome wins — that's what makes the profit risk-free.
"""

from dataclasses import dataclass


@dataclass
class Sizing:
    stakes: dict          # {team: dollars to bet on that outcome}
    total_cost: float     # T = sum of effective costs (the "price" of $1 payout)
    total_staked: float   # equals bankroll
    guaranteed_return: float
    profit: float         # guaranteed_return - total_staked
    roi: float            # profit / total_staked


def compute_sizing(costs: dict[str, float], bankroll: float) -> Sizing:
    """
    Allocate `bankroll` across outcomes to equalize payout.

    For each outcome with effective cost c_i (decimal odds = 1/c_i):
        stake_i = bankroll * c_i / T,   where T = sum(c_i)
    Each outcome then returns bankroll / T regardless of result.
    """
    T = sum(costs.values())
    stakes = {team: bankroll * c / T for team, c in costs.items()}
    guaranteed_return = bankroll / T
    profit = guaranteed_return - bankroll
    return Sizing(
        stakes=stakes,
        total_cost=T,
        total_staked=bankroll,
        guaranteed_return=guaranteed_return,
        profit=profit,
        roi=profit / bankroll,
    )
