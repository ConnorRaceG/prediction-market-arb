"""
View models for the dashboard.

The three detection tracks — sports (deterministic), novelty, and Polymarket —
each return their own result type from their own pipeline, and they stay separate
in the detection code on purpose. This module is the ONLY place they come
together: each `from_*` adapter maps one track's result into a neutral CardView
that the dashboard renders identically. No detector imports another; the tracks
are unified here, at the view layer, and nowhere else.

Adapters read result objects by attribute (duck-typed), so importing this module
never pulls in Playwright or the Anthropic SDK — the heavy deps stay behind the
lazy imports in the pipeline.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # type hints only — never imported at runtime
    from src.arb.detector import ArbResult
    from src.arb.novelty_detector import NoveltyArbResult
    from src.arb.polymarket_detector import PolymarketArbResult

# Display label per source/venue key. Sports book keys come from The Odds API;
# the novelty/Polymarket venues are the literal venue names.
SOURCE_LABEL = {
    "kalshi": "Kalshi", "odds_api": "Sportsbook",
    "draftkings": "DraftKings", "fanduel": "FanDuel", "betmgm": "BetMGM",
    "betrivers": "BetRivers", "williamhill_us": "Caesars", "caesars": "Caesars",
    "espnbet": "ESPN BET", "fanatics": "Fanatics", "ballybet": "Bally",
    "hardrockbet": "Hard Rock", "polymarket": "Polymarket",
}


def _venue_label(key: str) -> str:
    return SOURCE_LABEL.get(key, key)


def _venue_class(key: str) -> str:
    # Kalshi gets its own chip color; every other venue renders as a 'book' chip.
    return "kalshi" if key == "kalshi" else "book"


def _am_decimal(american: float) -> float:
    """Decimal payout for American odds — higher is the better line."""
    return 1 + (american / 100 if american > 0 else 100 / abs(american))


@dataclass
class CardLeg:
    label: str            # team abbrev (sports) or outcome name (novelty/poly)
    venue_label: str      # display name of the venue
    venue_class: str      # 'kalshi' or 'book' (drives the chip color)
    american: float
    implied_prob: float
    contracts: int | None  # whole Kalshi contracts (None for non-Kalshi legs)
    stake: float


@dataclass
class BoardRow:
    """One team's Kalshi-vs-best-book price row (sports cards only)."""
    team: str
    kalshi_american: float | None
    kalshi_best: bool
    book_american: float | None
    book_label: str | None
    book_best: bool


@dataclass
class CardView:
    track: str             # 'sports' | 'novelty' | 'polymarket'
    tag: str               # short label on the card (e.g. 'NFL', 'NOVELTY')
    title: str             # headline (matchup or event)
    edge: float
    is_arb: bool
    legs: list[CardLeg]
    profit: float
    staked: float
    roi: float
    subtitle: str | None = None       # secondary line (novelty market description)
    start_time: float | None = None   # sports only
    board: list[BoardRow] | None = None  # sports only (Kalshi vs best book)
    note: str | None = None           # novelty/poly: LLM match rationale
    confidence: float | None = None   # novelty/poly: LLM match confidence (0-1)
    detection_only: bool = False      # poly: flagged not tradeable from MA


def _outcome_legs(result) -> list[CardLeg]:
    """Legs for novelty/Polymarket results (outcome + venue fields)."""
    return [
        CardLeg(
            label=leg.outcome,
            venue_label=_venue_label(leg.venue),
            venue_class=_venue_class(leg.venue),
            american=leg.american,
            implied_prob=leg.implied_prob,
            contracts=leg.contracts,
            stake=leg.stake,
        )
        for leg in result.legs
    ]


def _build_board(r: "ArbResult") -> list[BoardRow]:
    """Per-team Kalshi vs best-book board, mirroring the deterministic detector."""
    by_team: dict[str, dict] = {}
    for q in (r.quotes or []):
        slot = by_team.setdefault(q.team, {})
        if q.source == "kalshi":
            slot["kalshi"] = q.american
        else:  # keep the best book line for the team
            cur = slot.get("book")
            if cur is None or _am_decimal(q.american) > _am_decimal(cur[0]):
                slot["book"] = (q.american, q.source)

    best_src = {leg.team: leg.source for leg in r.legs}
    rows = []
    for team, s in by_team.items():
        b = s.get("book")
        b_am, b_key = b if b else (None, None)
        rows.append(BoardRow(
            team=team,
            kalshi_american=s.get("kalshi"),
            kalshi_best=best_src.get(team) == "kalshi",
            book_american=b_am,
            book_label=_venue_label(b_key) if b_key else None,
            book_best=b_key is not None and best_src.get(team) == b_key,
        ))
    return rows


def from_sports(sport_label: str, r: "ArbResult") -> CardView:
    legs = [
        CardLeg(
            label=leg.team,
            venue_label=_venue_label(leg.source),
            venue_class=_venue_class(leg.source),
            american=leg.american,
            implied_prob=leg.implied_prob,
            contracts=leg.contracts,
            stake=leg.stake,
        )
        for leg in r.legs
    ]
    return CardView(
        track="sports",
        tag=sport_label,
        title=r.game,
        edge=r.edge,
        is_arb=r.is_arb,
        legs=legs,
        profit=r.profit,
        staked=r.staked,
        roi=r.roi,
        start_time=r.start_time,
        board=_build_board(r),
    )


def from_novelty(r: "NoveltyArbResult") -> CardView:
    return CardView(
        track="novelty",
        tag="NOVELTY",
        title=r.event,
        subtitle=r.market_desc,
        edge=r.edge,
        is_arb=r.is_arb,
        legs=_outcome_legs(r),
        profit=r.profit,
        staked=r.staked,
        roi=r.roi,
        note=r.note,
        confidence=r.confidence,
    )


def from_polymarket(r: "PolymarketArbResult") -> CardView:
    return CardView(
        track="polymarket",
        tag="POLYMARKET",
        title=r.event,
        edge=r.edge,
        is_arb=r.is_arb,
        legs=_outcome_legs(r),
        profit=r.profit,
        staked=r.staked,
        roi=r.roi,
        note=r.note,
        confidence=r.confidence,
        detection_only=True,
    )
