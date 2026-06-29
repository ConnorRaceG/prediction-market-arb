"""
Deterministic name-overlap matcher for futures boards.

DK Predictions and Kalshi list the SAME real candidates on a "who wins X" board
(Donald Trump, Zohran Mamdani, Pope Leo XIV, ...). So we don't need an LLM to know
two boards are the same market: we match them by how many candidate names they
share. This keeps the futures track deterministic and free; the LLM matcher stays
available for the genuinely ambiguous novelty/Polymarket cases elsewhere.
"""

import re
import unicodedata
from dataclasses import dataclass

from src.models import Market

_MONTHS = ("january", "february", "march", "april", "may", "june", "july",
           "august", "september", "october", "november", "december")
_MONTH_RE = re.compile(r"\b(" + "|".join(_MONTHS + tuple(m[:3] for m in _MONTHS)) + r")\b")
_YEAR_RE = re.compile(r"\b(20\d\d)\b")


def period_sig(title: str) -> tuple[str | None, str | None]:
    """(year, 3-letter month) named in a board title, e.g. 'Fed decision in Jul 2026?'
    -> ('2026', 'jul'). Either part may be None when the title doesn't say."""
    t = (title or "").lower()
    y = _YEAR_RE.search(t)
    m = _MONTH_RE.search(t)
    return (y.group(1) if y else None, m.group(1)[:3] if m else None)


def period_conflict(a_title: str, b_title: str) -> bool:
    """True if two titles name a period that disagrees (different year or month).

    Stops a board matching the SAME recurring board for a different period — the July
    Fed decision vs the September one share identical candidate names and would otherwise
    match and cross-price. Lenient on purpose: a missing year/month on either side is not
    a conflict (e.g. 'Recession this year?' carries no year, so it can still match)."""
    (ay, am), (by, bm) = period_sig(a_title), period_sig(b_title)
    return bool((ay and by and ay != by) or (am and bm and am != bm))


@dataclass
class FuturesMatch:
    dk_market_id: str
    kalshi_market_id: str
    dk_event: str
    kalshi_event: str
    shared: list[str]   # candidate names present on both boards (DK spelling)
    n_shared: int
    overlap: float      # |shared| / |larger candidate set| (the match gate)
    jaccard: float      # |shared| / |union of candidate names| (for reference)


def normalize_name(s: str) -> str:
    """Lowercase, strip accents and punctuation, collapse whitespace."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = "".join(ch if ch.isalnum() else " " for ch in s)
    return " ".join(s.split())


def _name_set(market: Market) -> set[str]:
    return {n for o in market.outcomes if (n := normalize_name(o.name))}


def match_futures(dk_markets: list[Market], kalshi_markets: list[Market],
                  min_shared: int = 3, min_overlap: float = 0.5) -> list[FuturesMatch]:
    """
    Match each DK board to the Kalshi event it shares the most candidates with.

    A match needs BOTH at least `min_shared` shared candidate names AND an overlap
    coefficient (shared / LARGER candidate set) of at least `min_overlap`. Dividing by
    the larger board is what stops phantom matches: "Person of the Year" (20 names) and
    "Person of the Decade" (a few names, all also in Year) overlap on Musk / Swift /
    Altman, but that's a small fraction of the 20-name board, so it's rejected. A genuine
    same-market pair shares most of BOTH boards. Anything borderline falls through to the
    LLM matcher. Each DK board takes its single best Kalshi event.
    """
    kalshi_named = [(m, _name_set(m)) for m in kalshi_markets]
    matches: list[FuturesMatch] = []

    for dk in dk_markets:
        dk_names = _name_set(dk)
        if not dk_names:
            continue
        best = None  # (kalshi_market, shared_set, overlap, jaccard)
        for km, kn in kalshi_named:
            # Recurring boards (e.g. the Fed decision each month) repeat the same candidate
            # names; a different-period Kalshi board must not be matched on that overlap.
            if period_conflict(dk.event_name, km.event_name):
                continue
            shared = dk_names & kn
            if len(shared) < 2:
                continue
            overlap = len(shared) / max(len(dk_names), len(kn))
            jac = len(shared) / len(dk_names | kn)
            if best is None or len(shared) > len(best[1]) or (
                len(shared) == len(best[1]) and overlap > best[2]):
                best = (km, shared, overlap, jac)
        if best and len(best[1]) >= min_shared and best[2] >= min_overlap:
            km, shared, overlap, jac = best
            matches.append(FuturesMatch(
                dk_market_id=dk.market_id,
                kalshi_market_id=km.market_id,
                dk_event=dk.event_name,
                kalshi_event=km.event_name,
                shared=sorted(shared),
                n_shared=len(shared),
                overlap=overlap,
                jaccard=jac,
            ))
    return matches
