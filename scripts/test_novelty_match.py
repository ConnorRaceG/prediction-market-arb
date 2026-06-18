"""
End-to-end novelty test: scrape DK novelty + fetch Kalshi entertainment, then
LLM-match them. Needs ANTHROPIC_API_KEY in .env.

Run:  python scripts/test_novelty_match.py
"""

from src.adapters.dk_novelty import DKNoveltyAdapter
from src.adapters.kalshi import KalshiAdapter
from src.matching.llm_matcher import match_novelty
from config.settings import Settings


def main():
    Settings.validate()

    print("Fetching Kalshi entertainment markets...")
    kalshi = KalshiAdapter().fetch_novelty_markets()
    print(f"  Kalshi: {len(kalshi)} markets")

    print("Scraping DraftKings novelty (a browser window will open)...")
    dk = DKNoveltyAdapter(headless=False).fetch_markets()
    print(f"  DraftKings: {len(dk)} markets")

    print(f"\nMatching via {Settings.MATCHER_MODEL}...")
    matches = match_novelty(dk, kalshi)

    print(f"\n{len(matches)} match(es):")
    for m in matches:
        print(f"  DK {m.dk_market_id} <-> Kalshi {m.kalshi_market_id}  (confidence {m.confidence:.0%})")
        print(f"     {m.note}")
        for dko, ko in m.outcome_map.items():
            print(f"     {dko!r}  =  {ko!r}")


if __name__ == "__main__":
    main()
