"""
Cross-venue arb detection for matched futures boards (DK Predictions x Kalshi).

For each candidate present on both venues we have a YES ask and (usually) a NO ask
on each side. The classic single-candidate arb is a binary Dutch book: buy YES on the
cheaper venue and NO on the other; if the two legs cost under $1, exactly one resolves
YES and you lock the difference, whichever way it goes.

Fees: Kalshi legs pay Kalshi's trading fee (effective_cost); DK Predictions' ask
already includes its spread, so DK legs take no extra fee (same treatment as the
sportsbook / Polymarket legs in the other tracks).

This module returns a full per-candidate comparison (so the user can eyeball every
board even when there's no edge), with the profitable candidates flagged. Detection
only — the Kalshi leg is API-executable, the DK leg is placed manually.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.models import Market
from src.arb.fees import effective_cost
from src.matching.futures_matcher import normalize_name
from config.settings import Settings

if TYPE_CHECKING:
    from src.matching.futures_matcher import FuturesMatch


@dataclass
class FuturesCandidate:
    name: str
    dk_yes: float | None      # cost to buy YES on DK (implied prob)
    kalshi_yes: float | None  # cost to buy YES on Kalshi (implied prob)
    lock_cost: float | None   # cheapest cross-venue Yes+No lock, fees included
    lock_desc: str            # which legs make that lock
    is_arb: bool


@dataclass
class FuturesComparison:
    dk_event: str
    kalshi_event: str
    dk_market_id: str
    kalshi_market_id: str
    candidates: list[FuturesCandidate]  # one row per shared candidate, best lock first
    n_shared: int
    n_arbs: int
    best_lock: float | None             # min lock cost across candidates (<1 = arb)
    confidence: float | None = None     # LLM match confidence (None = deterministic match)
    note: str = ""                      # LLM rationale for the match (if any)


def _candidates(market: Market) -> dict[str, dict]:
    return {normalize_name(c["name"]): c
            for c in (market.raw_data or {}).get("candidates", [])}


def compare_futures(match: "FuturesMatch", dk: Market, kalshi: Market,
                    min_margin_pct: float | None = None,
                    confidence: float | None = None, note: str = "",
                    outcome_map: dict[str, str] | None = None) -> FuturesComparison:
    """Build the per-candidate DK-vs-Kalshi comparison and flag binary arbs.

    Candidates are aligned across venues by `outcome_map` (DK name -> Kalshi name) when
    given — that's how LLM matches line up sides the two venues name differently
    ('Republicans' vs 'Republican Party'). Without a map (deterministic matches) sides
    align by identical normalized name. `confidence`/`note` are set for LLM matches.
    """
    threshold = (Settings.MIN_ARB_MARGIN if min_margin_pct is None else min_margin_pct) / 100.0
    dk_c, k_c = _candidates(dk), _candidates(kalshi)

    if outcome_map:
        pairs = [(normalize_name(d), normalize_name(k)) for d, k in outcome_map.items()]
    else:
        pairs = [(key, key) for key in set(dk_c) & set(k_c)]

    rows: list[FuturesCandidate] = []
    n_arbs = 0
    best_lock = None
    seen: set[str] = set()
    for dk_key, k_key in pairs:
        d, k = dk_c.get(dk_key), k_c.get(k_key)
        if d is None or k is None or dk_key in seen:
            continue
        seen.add(dk_key)
        dk_yes, dk_no = d.get("yes"), d.get("no")
        k_yes, k_no = k.get("yes"), k.get("no")

        # Two ways to lock the binary; the Kalshi leg pays Kalshi's fee.
        opt_a = (dk_yes + effective_cost("kalshi", k_no)) \
            if (dk_yes is not None and k_no is not None) else None   # Yes@DK + No@Kalshi
        opt_b = (effective_cost("kalshi", k_yes) + dk_no) \
            if (k_yes is not None and dk_no is not None) else None   # Yes@Kalshi + No@DK
        options = [(opt_a, "Yes@DK + No@Kalshi"), (opt_b, "Yes@Kalshi + No@DK")]
        valid = [(c, desc) for c, desc in options if c is not None]
        lock, desc = min(valid, default=(None, ""))

        is_arb = lock is not None and lock < 1.0 - threshold
        if is_arb:
            n_arbs += 1
        if lock is not None and (best_lock is None or lock < best_lock):
            best_lock = lock
        rows.append(FuturesCandidate(d["name"], dk_yes, k_yes, lock, desc, is_arb))

    # Arbs first, then by cheapest lock so the most interesting rows sit on top.
    rows.sort(key=lambda r: (not r.is_arb, r.lock_cost if r.lock_cost is not None else 9))
    return FuturesComparison(
        dk_event=match.dk_event,
        kalshi_event=match.kalshi_event,
        dk_market_id=match.dk_market_id,
        kalshi_market_id=match.kalshi_market_id,
        candidates=rows,
        n_shared=len(rows),
        n_arbs=n_arbs,
        best_lock=best_lock,
        confidence=confidence,
        note=note,
    )
