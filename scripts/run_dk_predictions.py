"""
Scan DraftKings Predictions futures boards and compare them to Kalshi.

Opens a browser to load DK Predictions (prices read from DK's own API, not the
screen), pulls the matching Kalshi events, matches boards by shared candidates
(deterministic, no LLM), and prints a per-candidate price comparison with any
cross-venue Yes/No arbs flagged.

Run:  python scripts/run_dk_predictions.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import Settings
from src.pipeline import run_dk_predictions_detection


def _c(p):
    return f"{p * 100:4.0f}c" if p is not None else "  - "


def main():
    Settings.validate()
    print("Scanning DK Predictions (a browser window opens) + Kalshi...\n")
    pr = run_dk_predictions_detection(headless=False)

    print(f"DK boards: {pr.n_dk} | Kalshi events fetched: {pr.n_kalshi} | "
          f"matched boards: {pr.n_matched} | boards with an arb: {len(pr.arbs)}\n")

    for comp in pr.comparisons:
        bl = f"{comp.best_lock * 100:.0f}c" if comp.best_lock is not None else "-"
        flag = f"   *** {comp.n_arbs} ARB(S) ***" if comp.n_arbs else ""
        print(f"== {comp.dk_event}  <->  {comp.kalshi_event}  "
              f"({comp.n_shared} shared, best lock {bl}){flag}")
        for c in comp.candidates:
            tag = "  <== ARB" if c.is_arb else ""
            print(f"    {c.name:24s} DK {_c(c.dk_yes)}  Kalshi {_c(c.kalshi_yes)}   "
                  f"lock {_c(c.lock_cost)} ({c.lock_desc}){tag}")
        print()

    if pr.unmatched:
        print(f"DK boards with no Kalshi counterpart ({len(pr.unmatched)}):")
        for title in pr.unmatched:
            print(f"   - {title}")


if __name__ == "__main__":
    main()
