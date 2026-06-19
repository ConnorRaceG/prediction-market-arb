"""
End-to-end novelty arb scan.

Scrapes DraftKings novelty (a browser window opens), fetches Kalshi entertainment
markets, LLM-matches the two, and prints any cross-venue arbs with sized legs.

Needs ANTHROPIC_API_KEY in .env (for the matcher) plus the usual Kalshi creds.
Run:  python scripts/run_novelty.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import Settings
from src.pipeline import run_novelty_detection


def _leg_line(leg) -> str:
    if leg.venue == "kalshi":
        size = f"x{leg.contracts:>4} contracts @ {leg.implied_prob * 100:4.0f}c"
    else:
        size = f"${leg.stake:8.2f}        @ {leg.american:+5.0f}"
    return f"        {leg.venue:11s} {size}  ->  {leg.outcome}"


def main():
    Settings.validate()
    print("Scanning novelty markets (a DraftKings browser window will open)...\n")
    pr = run_novelty_detection(bankroll=100.0, headless=False)

    print(f"DraftKings novelty  : {pr.n_dk} markets")
    print(f"Kalshi entertainment: {pr.n_kalshi} markets")
    print(f"LLM matches         : {pr.n_matched};  {len(pr.arbs)} profitable arb(s)\n")

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
