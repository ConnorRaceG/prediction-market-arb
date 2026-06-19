"""
Kalshi market discovery — find which events/categories a keyword lives under.

Novelty markets are scattered across Kalshi categories (Entertainment, Sports,
Politics, ...), so before wiring a category into KalshiAdapter.fetch_novelty_markets
use this to see where a given contest actually sits (and whether it's open yet).

Run:  python scripts/explore_kalshi.py "hot dog" nathan chestnut eating
"""

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.adapters.kalshi import KalshiAdapter


def main(keywords):
    kw = [k.lower() for k in keywords] or ["hot dog", "nathan", "chestnut", "eating"]
    adapter = KalshiAdapter()

    cats: Counter = Counter()
    hits = []
    cursor = None
    for _ in range(15):  # up to ~3000 open events
        params = {"status": "open", "limit": 200}
        if cursor:
            params["cursor"] = cursor
        data = adapter._get("/events", params)
        for e in data.get("events", []):
            cats[e.get("category", "?")] += 1
            title = e.get("title") or ""
            if any(k in title.lower() for k in kw):
                hits.append((e.get("category", "?"), e["event_ticker"], title))
        cursor = data.get("cursor")
        if not cursor:
            break

    print("Open-event categories seen:")
    for c, n in cats.most_common():
        print(f"  {n:5d}  {c}")

    print(f"\nMatches for {kw}:")
    if not hits:
        print("  (none found in open events)")
    for cat, ticker, title in hits:
        print(f"  [{cat}] {ticker}  {title}")


if __name__ == "__main__":
    main(sys.argv[1:])
