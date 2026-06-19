"""
End-to-end Polymarket <-> Kalshi arb scan (detection only).

Fetches liquid Polymarket markets + Kalshi markets in the chosen categories,
LLM-matches them, and prints any cross-venue arbs with sized legs. No browser
needed (Polymarket's Gamma API is a plain read); needs ANTHROPIC_API_KEY in .env.

NOTE: Polymarket isn't tradeable from MA as of 2026-06, so results are intel, not
executable right now.

Run:  python scripts/run_polymarket.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import Settings
from src.pipeline import run_polymarket_detection


def _leg_line(leg) -> str:
    if leg.venue == "kalshi":
        size = f"x{leg.contracts:>4} contracts @ {leg.implied_prob * 100:4.0f}c"
    else:
        size = f"${leg.stake:8.2f}        @ {leg.implied_prob:6.1%}"
    return f"        {leg.venue:11s} {size}  ->  {leg.outcome}"


def main():
    Settings.validate()
    print("Scanning Polymarket <-> Kalshi (no browser; Gamma API + Kalshi + LLM)...\n")
    pr = run_polymarket_detection(bankroll=100.0)

    print(f"Polymarket markets: {pr.n_poly}")
    print(f"Kalshi markets    : {pr.n_kalshi}")
    print(f"LLM matches       : {pr.n_matched};  {len(pr.arbs)} profitable arb(s)\n")

    if not pr.results:
        print("No priced cross-venue matches this scan.")
        return

    for r in pr.results:
        print(r)
        print(f"     match: {r.note}")
        if r.is_arb:
            print(f"     profit ${r.profit:.2f} on ${r.staked:.2f} staked ({r.roi:+.2%}):")
        for leg in r.legs:
            print(_leg_line(leg))
        print()


if __name__ == "__main__":
    main()
