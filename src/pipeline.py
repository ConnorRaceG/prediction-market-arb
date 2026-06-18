"""
Main pipeline: fetch → match → detect arbs.
"""

from src.adapters.kalshi import KalshiAdapter
from src.adapters.odds_api import OddsApiAdapter
from src.matching.matcher import match_markets
from src.arb.detector import detect_arbs, ArbOpportunity


def run_arb_detection(sport: str = "basketball_nba") -> list[ArbOpportunity]:
    """
    Run the full pipeline: fetch data, match events, detect arbs.

    Args:
        sport: e.g. 'basketball_nba'

    Returns:
        List of detected arbitrage opportunities
    """
    # Fetch markets from both sources
    kalshi_adapter = KalshiAdapter()
    odds_adapter = OddsApiAdapter()

    kalshi_markets = kalshi_adapter.fetch_markets(sport, "moneyline")
    odds_markets = odds_adapter.fetch_markets(sport, "moneyline")

    print(f"Fetched {len(kalshi_markets)} Kalshi markets")
    print(f"Fetched {len(odds_markets)} sportsbook markets")

    all_markets = kalshi_markets + odds_markets

    # Match equivalent events across sources
    matched_groups = match_markets(all_markets)
    print(f"Matched into {len(matched_groups)} groups")

    # Detect arbs in each group
    arbs = detect_arbs(matched_groups)
    print(f"Found {len(arbs)} opportunities")

    return arbs


if __name__ == "__main__":
    # For testing: validate config and run pipeline
    from config.settings import Settings

    try:
        Settings.validate()
        arbs = run_arb_detection()
        for arb in arbs:
            print(f"\n{arb.description}")
            print(f"  Profit margin: {arb.profit_margin:.2%}")
            print(f"  Stakes: {arb.stakes}")
    except (ValueError, FileNotFoundError) as e:
        print(f"Error: {e}")
