"""
Detect arbitrage in LLM-matched Polymarket <-> Kalshi markets.

A sibling of novelty_detector for the Polymarket track (kept separate on purpose).
The LLM matcher (match_polymarket_kalshi) hands us an outcome_map (Polymarket
outcome -> equivalent Kalshi outcome). Polymarket binary Yes/No markets always
price the complete event, so Polymarket is the base partition; a Kalshi price is
substituted into an outcome only where the matcher aligned one AND it's cheaper
after fees. Cheapest-per-outcome costs summing under $1 => a cross-venue Dutch book.

Both venues are prediction markets: Kalshi adds its trading fee (effective_cost),
Polymarket doesn't, and only Kalshi legs take an integer contract count. We require
at least one Kalshi substitution and gate is_arb on the matcher's confidence.

NOTE: detection only — Polymarket isn't tradeable from MA as of 2026-06, so these
are intel, not executable for the user right now.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.models import Market
from src.arb.fees import effective_cost
from src.arb.sizing import compute_sizing
from config.settings import Settings

if TYPE_CHECKING:  # avoid importing the Anthropic SDK just to run the math
    from src.matching.llm_matcher import PolymarketMatch

MIN_MATCH_CONFIDENCE = 0.80


@dataclass
class PolymarketArbLeg:
    outcome: str
    venue: str             # 'polymarket' or 'kalshi' — where to place this leg
    american: float
    implied_prob: float
    effective_cost: float
    stake: float = 0.0
    contracts: int | None = None  # whole Kalshi contracts (None for Polymarket)


@dataclass
class PolymarketArbResult:
    event: str
    legs: list[PolymarketArbLeg]
    total_cost: float
    edge: float
    roi: float
    profit: float
    bankroll: float
    staked: float
    is_arb: bool
    confidence: float
    note: str
    poly_id: str
    kalshi_id: str

    def __repr__(self):
        flag = "[ARB]" if self.is_arb else "  -  "
        return (f"{flag} {self.event}: edge={self.edge:+.2%} roi={self.roi:+.2%} "
                f"(match conf {self.confidence:.0%})")


def detect_polymarket_arb(
    match: "PolymarketMatch",
    poly: Market,
    kalshi: Market,
    bankroll: float = 100.0,
    min_roi_pct: float | None = None,
) -> PolymarketArbResult | None:
    """Evaluate one matched Polymarket<->Kalshi pair; None if nothing is cheaper on Kalshi."""
    threshold = (Settings.MIN_ARB_MARGIN if min_roi_pct is None else min_roi_pct) / 100.0
    kalshi_by_name = {o.name: o for o in kalshi.outcomes}

    best: dict[str, PolymarketArbLeg] = {}
    for p_o in poly.outcomes:
        # Polymarket prices the full Yes/No partition; Kalshi is substituted where cheaper
        p_cost = effective_cost(poly.source, p_o.implied_prob)
        leg = PolymarketArbLeg(p_o.name, "polymarket", p_o.odds_american,
                               p_o.implied_prob, p_cost)
        k_name = match.outcome_map.get(p_o.name)
        k_o = kalshi_by_name.get(k_name) if k_name else None
        if k_o is not None:
            k_cost = effective_cost("kalshi", k_o.implied_prob)
            if k_cost < p_cost:
                leg = PolymarketArbLeg(p_o.name, "kalshi", k_o.odds_american,
                                       k_o.implied_prob, k_cost)
        best[p_o.name] = leg

    if not any(leg.venue == "kalshi" for leg in best.values()):
        return None

    costs = {name: leg.effective_cost for name, leg in best.items()}
    sizing = compute_sizing(costs, bankroll)
    for name, leg in best.items():
        leg.stake = sizing.stakes[name]
        if leg.venue == "kalshi":
            leg.contracts = sizing.contracts

    edge = 1 - sizing.total_cost
    is_arb = sizing.roi >= threshold and match.confidence >= MIN_MATCH_CONFIDENCE
    return PolymarketArbResult(
        event=poly.event_name,
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
        poly_id=match.poly_id,
        kalshi_id=match.kalshi_id,
    )


def detect_polymarket_arbs(
    matches: list["PolymarketMatch"],
    poly_markets: list[Market],
    kalshi_markets: list[Market],
    bankroll: float = 100.0,
    min_roi_pct: float | None = None,
) -> list[PolymarketArbResult]:
    """Evaluate every match; return results sorted best-edge-first."""
    poly_by_id = {m.market_id: m for m in poly_markets}
    kalshi_by_id = {m.market_id: m for m in kalshi_markets}

    results = []
    for match in matches:
        poly = poly_by_id.get(match.poly_id)
        kalshi = kalshi_by_id.get(match.kalshi_id)
        if poly is None or kalshi is None:
            continue
        result = detect_polymarket_arb(match, poly, kalshi, bankroll, min_roi_pct)
        if result is not None:
            results.append(result)

    results.sort(key=lambda r: r.edge, reverse=True)
    return results
