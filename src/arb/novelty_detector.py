"""
Detect arbitrage in LLM-matched novelty markets.

Unlike the sports detector, novelty markets can't be matched by a team registry
— the LLM matcher (src/matching/llm_matcher.py) hands us an explicit alignment of
DraftKings outcomes to their economically-equivalent Kalshi outcomes. This module
turns that alignment into a cross-venue Dutch book: for every outcome of the event
we take whichever venue prices it cheaper (fees included), and if the cheapest
costs sum to under $1 there's a guaranteed profit.

The DraftKings market supplies the complete, mutually-exclusive set of outcomes
(a sportsbook market always covers the whole event), so we treat it as the base
partition and substitute a Kalshi price into an outcome only where the matcher
aligned one AND it undercuts DraftKings — partial Kalshi coverage is fine. We
require at least one Kalshi substitution (otherwise there's nothing cross-venue to
arb) and gate the is_arb flag on the matcher's confidence, because a wrong
alignment loses real money.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.models import Market
from src.arb.fees import effective_cost
from src.arb.sizing import compute_sizing
from config.settings import Settings

if TYPE_CHECKING:  # avoid importing the Anthropic SDK just to run the math
    from src.matching.llm_matcher import NoveltyMatch

# A low-confidence alignment can produce a phantom edge; don't flag those as
# actionable arbs even if the math says so. The result is still returned (so you
# can eyeball it), just with is_arb=False.
MIN_MATCH_CONFIDENCE = 0.80


@dataclass
class NoveltyArbLeg:
    outcome: str           # the logical outcome (DraftKings' label)
    venue: str             # "draftkings" or "kalshi" — where to place this leg
    american: float
    implied_prob: float
    effective_cost: float  # implied prob incl. fees (what we compare)
    stake: float = 0.0     # dollar outlay, filled once sizing is computed
    contracts: int | None = None  # whole Kalshi contracts (None for DraftKings)


@dataclass
class NoveltyArbResult:
    event: str             # e.g. "Nathan's Hot Dog Eating Contest"
    market_desc: str       # e.g. "Total Hot Dogs Eaten by Joey Chestnut"
    legs: list[NoveltyArbLeg]
    total_cost: float      # T = sum of cheapest effective costs
    edge: float            # 1 - T (positive = arb)
    roi: float
    profit: float
    bankroll: float
    staked: float
    is_arb: bool
    confidence: float      # LLM match confidence (0-1)
    note: str              # LLM's rationale for the match
    dk_market_id: str
    kalshi_market_id: str

    def __repr__(self):
        flag = "[ARB]" if self.is_arb else "  -  "
        return (f"{flag} {self.event} — {self.market_desc}: edge={self.edge:+.2%} "
                f"roi={self.roi:+.2%} (match conf {self.confidence:.0%})")


def detect_novelty_arb(
    match: "NoveltyMatch",
    dk: Market,
    kalshi: Market,
    bankroll: float = 100.0,
    min_roi_pct: float | None = None,
) -> NoveltyArbResult | None:
    """
    Evaluate one matched novelty market for a cross-venue arb.

    Returns a result for any market where at least one outcome is cheaper on
    Kalshi (so there's a genuine cross-venue comparison); None otherwise.
    """
    threshold = (Settings.MIN_ARB_MARGIN if min_roi_pct is None else min_roi_pct) / 100.0
    kalshi_by_name = {o.name: o for o in kalshi.outcomes}

    best: dict[str, NoveltyArbLeg] = {}
    for dk_o in dk.outcomes:
        # DraftKings always prices every outcome (its market is the full partition)
        dk_cost = effective_cost(dk.source, dk_o.implied_prob)
        leg = NoveltyArbLeg(dk_o.name, "draftkings", dk_o.odds_american,
                            dk_o.implied_prob, dk_cost)
        # Substitute Kalshi where the matcher aligned it AND it's cheaper
        kalshi_name = match.outcome_map.get(dk_o.name)
        kalshi_o = kalshi_by_name.get(kalshi_name) if kalshi_name else None
        if kalshi_o is not None:
            kalshi_cost = effective_cost("kalshi", kalshi_o.implied_prob)
            if kalshi_cost < dk_cost:
                leg = NoveltyArbLeg(dk_o.name, "kalshi", kalshi_o.odds_american,
                                    kalshi_o.implied_prob, kalshi_cost)
        best[dk_o.name] = leg

    # Nothing to arb if no outcome is cheaper on Kalshi than on DraftKings
    if not any(leg.venue == "kalshi" for leg in best.values()):
        return None

    costs = {name: leg.effective_cost for name, leg in best.items()}
    sizing = compute_sizing(costs, bankroll)
    for name, leg in best.items():
        leg.stake = sizing.stakes[name]
        if leg.venue == "kalshi":
            leg.contracts = sizing.contracts  # integer quantity to enter

    edge = 1 - sizing.total_cost
    is_arb = sizing.roi >= threshold and match.confidence >= MIN_MATCH_CONFIDENCE
    return NoveltyArbResult(
        event=dk.event_name,
        market_desc=dk.market_type,
        legs=list(best.values()),
        total_cost=sizing.total_cost,
        edge=edge,
        roi=sizing.roi,
        profit=sizing.profit,
        bankroll=bankroll,
        staked=sizing.total_staked,
        is_arb=is_arb,
        confidence=match.confidence,
        note=match.note,
        dk_market_id=match.dk_market_id,
        kalshi_market_id=match.kalshi_market_id,
    )


def detect_novelty_arbs(
    matches: list["NoveltyMatch"],
    dk_markets: list[Market],
    kalshi_markets: list[Market],
    bankroll: float = 100.0,
    min_roi_pct: float | None = None,
) -> list[NoveltyArbResult]:
    """Evaluate every LLM match; return results sorted best-edge-first."""
    dk_by_id = {m.market_id: m for m in dk_markets}
    kalshi_by_id = {m.market_id: m for m in kalshi_markets}

    results = []
    for match in matches:
        dk = dk_by_id.get(match.dk_market_id)
        kalshi = kalshi_by_id.get(match.kalshi_market_id)
        if dk is None or kalshi is None:
            continue
        result = detect_novelty_arb(match, dk, kalshi, bankroll, min_roi_pct)
        if result is not None:
            results.append(result)

    results.sort(key=lambda r: r.edge, reverse=True)
    return results
