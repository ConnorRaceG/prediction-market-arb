"""
Main pipeline: fetch → match → detect arbs.
"""

import time
from dataclasses import dataclass

from src.adapters.kalshi import KalshiAdapter
from src.adapters.odds_api import OddsApiAdapter
from src.matching.matcher import match_markets
from src.arb.detector import detect_arbs, ArbResult


@dataclass
class PipelineResult:
    results: list[ArbResult]   # one per matched game, best edge first
    n_kalshi: int
    n_odds: int
    n_matched: int
    quota_remaining: str | None  # Odds API requests left this month
    timestamp: float

    @property
    def arbs(self) -> list[ArbResult]:
        return [r for r in self.results if r.is_arb]


def run_arb_detection(sport: str = "baseball_mlb", bankroll: float = 100.0) -> PipelineResult:
    """Run the full pipeline: fetch both sources, match games, evaluate arbs."""
    kalshi_markets = KalshiAdapter().fetch_markets(sport, "moneyline")

    odds_adapter = OddsApiAdapter("draftkings")
    odds_markets = odds_adapter.fetch_markets(sport, "moneyline")

    matched = match_markets(kalshi_markets + odds_markets, sport)
    results = detect_arbs(matched, sport, bankroll=bankroll)

    return PipelineResult(
        results=results,
        n_kalshi=len(kalshi_markets),
        n_odds=len(odds_markets),
        n_matched=len(matched),
        quota_remaining=odds_adapter.requests_remaining,
        timestamp=time.time(),
    )


if __name__ == "__main__":
    from config.settings import Settings

    Settings.validate()
    pr = run_arb_detection()
    print(f"Fetched {pr.n_kalshi} Kalshi + {pr.n_odds} DraftKings markets")
    print(f"Matched {pr.n_matched} games; {len(pr.arbs)} profitable arb(s)")
    print(f"Odds API quota remaining: {pr.quota_remaining}\n")
    for r in pr.results:
        print(r)
        if r.is_arb:
            print(f"      profit ${r.profit:.2f} on ${r.bankroll:.0f}; stakes:")
            for leg in r.legs:
                print(f"        ${leg.stake:6.2f} on {leg.team} @ {leg.source} ({leg.american:+.0f})")
