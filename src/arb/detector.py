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
    stake: float = 0.0     # dollar outlay, filled once sizing is computed
    contracts: int | None = None  # whole Kalshi contracts to buy (None for books)


@dataclass
class Quote:
    """One source's price on one outcome — the full board, for side-by-side view."""
    team: str
    source: str
    american: float
    implied_prob: float


@dataclass
class ArbResult:
    game: str              # e.g. "BOS vs TOR"
    legs: list[ArbLeg]
    total_cost: float      # T = sum of effective costs
    edge: float            # 1 - T (positive = arb)
    roi: float             # profit / amount staked
    profit: float          # dollars, on the actual staked amount
    bankroll: float        # the requested bankroll
    staked: float          # actual cash out (whole-contract rounded)
    is_arb: bool
    quotes: list[Quote] = None       # every source's price on every outcome
    start_time: float | None = None  # game start (unix UTC)
    matchup_full: str | None = None  # "Away Team @ Home Team" (full names)
    slate_date: str | None = None    # ET game date

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
        # Best (cheapest effective cost) source for each team, plus the full board
        best: dict[str, ArbLeg] = {}
        quotes: list[Quote] = []
        for market in mm.markets:
            for outcome in market.outcomes:
                team = normalize_team(outcome.name, sport)
                if team is None:
                    continue
                # Display source is the specific book (e.g. 'fanduel'); fee model
                # still keys off the real source ('odds_api' vs 'kalshi').
                disp = outcome.book or market.source
                quotes.append(Quote(team, disp, outcome.odds_american,
                                    outcome.implied_prob))
                cost = effective_cost(market.source, outcome.implied_prob)
                if team not in best or cost < best[team].effective_cost:
                    best[team] = ArbLeg(
                        team=team,
                        source=disp,
                        american=outcome.odds_american,
                        implied_prob=outcome.implied_prob,
                        effective_cost=cost,
                    )

        # Need every team in the game priced by at least one source
        if set(best.keys()) != set(mm.teams):
            continue

        costs = {team: leg.effective_cost for team, leg in best.items()}
        sizing = compute_sizing(costs, bankroll)
        for team, leg in best.items():
            leg.stake = sizing.stakes[team]
            if leg.source == "kalshi":
                leg.contracts = sizing.contracts  # integer quantity to enter

        # Prefer the sportsbook market for game time + full team names
        book = next((m for m in mm.markets if m.source == "odds_api"), None)
        anchor = book or next((m for m in mm.markets if m.start_time), None)

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
                staked=sizing.total_staked,
                is_arb=sizing.roi >= threshold,
                quotes=quotes,
                start_time=anchor.start_time if anchor else None,
                matchup_full=book.event_name if book else None,
                slate_date=mm.slate_date,
            )
        )

    results.sort(key=lambda r: r.edge, reverse=True)
    return results
