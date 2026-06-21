"""
Main pipeline: fetch → match → detect arbs.
"""

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.adapters.kalshi import KalshiAdapter
from src.adapters.odds_api import OddsApiAdapter
from src.matching.matcher import match_markets
from src.arb.detector import detect_arbs, ArbResult
from config.settings import Settings

if TYPE_CHECKING:  # novelty/polymarket/futures paths pull Playwright/Anthropic; keep lazy
    from src.arb.novelty_detector import NoveltyArbResult
    from src.arb.polymarket_detector import PolymarketArbResult
    from src.arb.futures_detector import FuturesComparison


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

    odds_adapter = OddsApiAdapter()  # best line across major US books
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


@dataclass
class NoveltyPipelineResult:
    results: list["NoveltyArbResult"]  # one per priced match, best edge first
    n_dk: int
    n_kalshi: int
    n_matched: int
    timestamp: float

    @property
    def arbs(self) -> list["NoveltyArbResult"]:
        return [r for r in self.results if r.is_arb]


def run_novelty_detection(
    bankroll: float = 100.0,
    headless: bool = False,
    categories: tuple[str, ...] = ("Entertainment",),
) -> NoveltyPipelineResult:
    """
    Novelty pipeline: scrape DraftKings novelty + fetch Kalshi entertainment,
    LLM-match them, then detect cross-venue arbs.

    Heavier than the sports path: the DraftKings scrape drives a real browser (a
    window opens unless headless=True) and the matcher calls the Anthropic API
    (needs ANTHROPIC_API_KEY). Imports are deferred so importing this module — and
    the sports pipeline — doesn't require Playwright or the Anthropic SDK.
    """
    from src.adapters.dk_novelty import DKNoveltyAdapter
    from src.matching.llm_matcher import match_novelty
    from src.arb.novelty_detector import detect_novelty_arbs

    dk_markets = DKNoveltyAdapter(headless=headless).fetch_markets()
    kalshi_markets = KalshiAdapter().fetch_novelty_markets(categories=categories)
    matches = match_novelty(dk_markets, kalshi_markets)
    results = detect_novelty_arbs(matches, dk_markets, kalshi_markets, bankroll=bankroll)

    return NoveltyPipelineResult(
        results=results,
        n_dk=len(dk_markets),
        n_kalshi=len(kalshi_markets),
        n_matched=len(matches),
        timestamp=time.time(),
    )


@dataclass
class PolymarketPipelineResult:
    results: list["PolymarketArbResult"]  # one per priced match, best edge first
    n_poly: int
    n_kalshi: int
    n_matched: int
    timestamp: float

    @property
    def arbs(self) -> list["PolymarketArbResult"]:
        return [r for r in self.results if r.is_arb]


def run_polymarket_detection(
    bankroll: float = 100.0,
    categories: tuple[str, ...] = ("Politics", "Elections"),
    min_liquidity: float = 1000.0,
    max_poly: int = 150,
) -> PolymarketPipelineResult:
    """
    Polymarket <-> Kalshi pipeline: fetch liquid Polymarket markets + Kalshi markets
    in the given categories, LLM-match them, then detect cross-venue arbs.

    No browser needed (Polymarket's Gamma API is a plain read), but the matcher calls
    the Anthropic API (needs ANTHROPIC_API_KEY). Detection only — Polymarket isn't
    tradeable from MA right now. Imports are deferred so the sports path stays light.
    """
    from src.adapters.polymarket import PolymarketAdapter
    from src.matching.llm_matcher import match_polymarket_kalshi
    from src.arb.polymarket_detector import detect_polymarket_arbs

    poly_markets = PolymarketAdapter(min_liquidity=min_liquidity).fetch_markets(max_markets=max_poly)
    kalshi_markets = KalshiAdapter().fetch_novelty_markets(categories=categories)
    matches = match_polymarket_kalshi(poly_markets, kalshi_markets)
    results = detect_polymarket_arbs(matches, poly_markets, kalshi_markets, bankroll=bankroll)

    return PolymarketPipelineResult(
        results=results,
        n_poly=len(poly_markets),
        n_kalshi=len(kalshi_markets),
        n_matched=len(matches),
        timestamp=time.time(),
    )


_TITLE_STOP = {"the", "of", "for", "a", "an", "to", "in", "on", "and", "will", "be",
               "who", "what", "2025", "2026", "2027", "2028"}


def _title_tokens(s: str) -> set[str]:
    """Significant words in a board title, for cheap title-to-title pre-matching."""
    from src.matching.futures_matcher import normalize_name
    return {t for t in normalize_name(s).split() if t not in _TITLE_STOP and len(t) > 1}


# Common words that don't distinguish one futures board from another — dropped when
# building the LLM matcher's candidate pool so it keys on the meaningful nouns.
_FUTURES_STOP = _TITLE_STOP | {
    "us", "party", "win", "control", "controls", "based", "results", "midterm",
    "midterms", "election", "elections", "winner", "date", "end", "next", "this", "year"}
MIN_FUTURES_LLM_CONF = 0.70


def _distinctive_tokens(s: str) -> set[str]:
    from src.matching.futures_matcher import normalize_name
    return {t for t in normalize_name(s).split() if t not in _FUTURES_STOP and len(t) > 2}


def _kalshi_pool(dk_markets, index, per_board: int = 15) -> list[tuple[str, str]]:
    """Kalshi events most likely to be a counterpart for the leftover DK boards: per
    board, the events sharing the most distinctive title words. Bounds the LLM input
    while keeping each board's real match in front of the model."""
    chosen: dict[str, str] = {}
    for dk in dk_markets:
        dts = _distinctive_tokens(dk.event_name)
        if not dts:
            continue
        scored = sorted(
            ((len(_distinctive_tokens(t) & dts), tk, t) for tk, t in index
             if _distinctive_tokens(t) & dts),
            reverse=True)
        for _, tk, t in scored[:per_board]:
            chosen[tk] = t
    return list(chosen.items())


@dataclass
class DKPredictionsPipelineResult:
    comparisons: list["FuturesComparison"]  # one per matched board, cheapest lock first
    unmatched: list[str]                    # DK board titles with no Kalshi counterpart
    n_dk: int
    n_kalshi: int
    n_matched: int
    timestamp: float

    @property
    def arbs(self) -> list["FuturesComparison"]:
        return [c for c in self.comparisons if c.n_arbs > 0]


def run_dk_predictions_detection(
    categories=("culture", "politics", "economics", "business"),
    max_groups_per_cat: int = 15,
    headless: bool = False,
    kalshi_categories=("Entertainment", "Politics", "Economics", "Financials",
                       "Elections", "Companies"),
    max_kalshi_fetch: int = 40,
    use_llm: bool = True,
) -> DKPredictionsPipelineResult:
    """
    DK Predictions <-> Kalshi futures scan (detection only).

    Scrape DK Predictions boards (prices read from DK's own API, not the screen) and
    match them to Kalshi two ways:
      1. deterministic candidate-name overlap, for distinctive multi-candidate boards
         (Person of the Year);
      2. for whatever is left, an LLM semantic title match, for the binary / political
         / economic boards whose meaning is in the title, not the candidates
         ('US Recession in 2026?' == Kalshi 'Recession this year?').
    Then compare prices per candidate to flag cross-venue Yes/No arbs.

    Imports are deferred so the sports path stays light; the DK scrape needs a browser,
    Kalshi needs its usual creds, and the LLM step needs ANTHROPIC_API_KEY (skipped if
    absent or use_llm is False).
    """
    from src.adapters.dk_predictions import DKPredictionsAdapter
    from src.matching.futures_matcher import match_futures, FuturesMatch
    from src.arb.futures_detector import compare_futures

    dk_markets = DKPredictionsAdapter(headless=headless).fetch_markets(
        categories=categories, max_groups_per_cat=max_groups_per_cat)

    kalshi = KalshiAdapter()
    index = kalshi.fetch_event_index(kalshi_categories)
    dk_by = {m.market_id: m for m in dk_markets}

    # 1) Deterministic: title pre-filter -> fetch full markets -> candidate-name overlap.
    # Rank by how many title words a Kalshi event shares with some DK board, so the real
    # counterpart (e.g. 'Person of the Year', 3 shared words) is fetched before weaker
    # 2-word matches get to the cap.
    dk_tokens = [_title_tokens(d.event_name) for d in dk_markets]

    def _relevance(title: str) -> int:
        return max((len(_title_tokens(title) & dt) for dt in dk_tokens), default=0)

    chosen = sorted(((r, tk, title) for tk, title in index if (r := _relevance(title)) >= 2),
                    reverse=True)
    k_by = {}
    for _, tk, title in chosen[:max_kalshi_fetch]:
        m = kalshi.fetch_event_market(tk, title)
        if m is not None:
            k_by[m.market_id] = m

    det_matches = match_futures(dk_markets, list(k_by.values()))
    comparisons = [compare_futures(mt, dk_by[mt.dk_market_id], k_by[mt.kalshi_market_id])
                   for mt in det_matches]
    matched_ids = {mt.dk_market_id for mt in det_matches}

    # 2) LLM semantic title match for the leftover boards (binary / political / economic).
    leftover = [m for m in dk_markets if m.market_id not in matched_ids]
    if use_llm and leftover and Settings.ANTHROPIC_API_KEY:
        try:
            from src.matching.llm_matcher import match_futures_llm
            pool = _kalshi_pool(leftover, index)
            pool_titles = dict(pool)
            for lm in match_futures_llm(leftover, pool):
                if lm.confidence < MIN_FUTURES_LLM_CONF or lm.dk_market_id in matched_ids:
                    continue
                km = k_by.get(lm.kalshi_ticker) or kalshi.fetch_event_market(
                    lm.kalshi_ticker, pool_titles.get(lm.kalshi_ticker, ""))
                if km is None:
                    continue
                k_by[km.market_id] = km
                dkm = dk_by[lm.dk_market_id]
                fm = FuturesMatch(dkm.market_id, km.market_id, dkm.event_name,
                                  km.event_name, [], 0, 1.0, 1.0)
                comparisons.append(compare_futures(fm, dkm, km,
                                                   confidence=lm.confidence, note=lm.note))
                matched_ids.add(lm.dk_market_id)
        except Exception:
            pass  # fail soft — keep the deterministic results

    comparisons.sort(key=lambda c: c.best_lock if c.best_lock is not None else 9)
    unmatched = [m.event_name for m in dk_markets if m.market_id not in matched_ids]

    return DKPredictionsPipelineResult(
        comparisons=comparisons,
        unmatched=unmatched,
        n_dk=len(dk_markets),
        n_kalshi=len(k_by),
        n_matched=len(matched_ids),
        timestamp=time.time(),
    )


if __name__ == "__main__":
    from config.settings import Settings

    Settings.validate()
    pr = run_arb_detection()
    print(f"Fetched {pr.n_kalshi} Kalshi + {pr.n_odds} sportsbook markets")
    print(f"Matched {pr.n_matched} games; {len(pr.arbs)} profitable arb(s)")
    print(f"Odds API quota remaining: {pr.quota_remaining}\n")
    for r in pr.results:
        print(r)
        if r.is_arb:
            print(f"      profit ${r.profit:.2f} on ${r.staked:.2f} staked ({r.roi:+.2%}):")
            for leg in r.legs:
                qty = f"x{leg.contracts:>4} contracts" if leg.contracts else f"${leg.stake:7.2f}     "
                print(f"        {qty} on {leg.team} @ {leg.source} ({leg.american:+.0f})")
