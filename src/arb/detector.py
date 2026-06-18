"""
Detect arbitrage in matched market groups.

For each game we pick, per outcome, the source offering the cheapest effective
cost (best odds, fees included). If the two sides sum to under $1, it's an arb.
We return a result for EVERY matched game (even non-arbs) so the dashboard can
show how close each one is, flagging the profitable ones.
"""

from dataclasses import dataclass
from src.matching.matcher import MatchedMarket
from src.matching.normalize import normalize_team
from src.arb.fees import effective_cost
from src.arb.sizing import compute_sizing
from config.settings import Settings


@dataclass
class ArbLeg:
    team: str
    source: str
    american: float        # raw American odds shown by the source
    implied_prob: float    # raw implied probability
    effective_cost: float  # implied prob incl. fees (what we actually compare)
    stake: float = 0.0     # filled in once sizing is computed
    url: str | None = None


@dataclass
class ArbResult:
    game: str              # e.g. "BOS vs TOR"
    legs: list[ArbLeg]
    total_cost: float      # T = sum of effective costs
    edge: float            # 1 - T (positive = arb)
    roi: float             # profit / amount staked
    profit: float          # dollars, on the configured bankroll
    bankroll: float
    is_arb: bool

    def __repr__(self):
        flag = "[ARB]" if self.is_arb else "  -  "
        legs = " | ".join(f"{l.team} on {l.source} ({l.american:+.0f})" for l in self.legs)
        return f"{flag} {self.game}: edge={self.edge:+.2%} roi={self.roi:+.2%} [{legs}]"


def detect_arbs(
    matched: list[MatchedMarket],
    sport: str,
    bankroll: float = 100.0,
    min_roi_pct: float | None = None,
) -> list[ArbResult]:
    """Evaluate each matched game for arbitrage. Returns results sorted best-first."""
    threshold = (Settings.MIN_ARB_MARGIN if min_roi_pct is None else min_roi_pct) / 100.0
    results = []

    for mm in matched:
        # Best (cheapest effective cost) source for each team
        best: dict[str, ArbLeg] = {}
        for market in mm.markets:
            for outcome in market.outcomes:
                team = normalize_team(outcome.name, sport)
                if team is None:
                    continue
                cost = effective_cost(market.source, outcome.implied_prob)
                if team not in best or cost < best[team].effective_cost:
                    best[team] = ArbLeg(
                        team=team,
                        source=market.source,
                        american=outcome.odds_american,
                        implied_prob=outcome.implied_prob,
                        effective_cost=cost,
                        url=market.url,
                    )

        # Need every team in the game priced by at least one source
        if set(best.keys()) != set(mm.teams):
            continue

        costs = {team: leg.effective_cost for team, leg in best.items()}
        sizing = compute_sizing(costs, bankroll)
        for team, leg in best.items():
            leg.stake = sizing.stakes[team]

        edge = 1 - sizing.total_cost
        results.append(
            ArbResult(
                game=" vs ".join(sorted(mm.teams)),
                legs=list(best.values()),
                total_cost=sizing.total_cost,
                edge=edge,
                roi=sizing.roi,
                profit=sizing.profit,
                bankroll=bankroll,
                is_arb=sizing.roi >= threshold,
            )
        )

    results.sort(key=lambda r: r.edge, reverse=True)
    return results
