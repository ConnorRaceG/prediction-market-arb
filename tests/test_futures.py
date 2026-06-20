"""
Unit tests for the DK Predictions futures track (no network, no browser, no LLM).

Two halves:
  - the deterministic name-overlap MATCHER (futures_matcher), especially the
    overlap-coefficient gate that stops the Person-of-the-Year vs Person-of-the-
    Decade phantom match;
  - the cross-venue DETECTOR (futures_detector) binary-lock math: buy YES on the
    cheaper venue + NO on the other, Kalshi leg pays the Kalshi fee.

Run:  python -m tests.test_futures   (or: pytest tests/)
"""

from src.models import Market, Outcome
from src.arb.fees import effective_cost
from src.matching.futures_matcher import match_futures, normalize_name, FuturesMatch
from src.arb.futures_detector import compare_futures


def _names_market(source, mid, event, names):
    """A board with just candidate names (prices irrelevant to matching)."""
    return Market(
        source=source, market_id=mid, event_name=event, market_type="futures",
        outcomes=[Outcome(name=n, implied_prob=0.1) for n in names], timestamp=0.0,
    )


def _cand_market(source, mid, event, cands):
    """A board carrying per-candidate yes/no asks; cands = [(name, yes, no), ...]."""
    return Market(
        source=source, market_id=mid, event_name=event, market_type="futures",
        outcomes=[Outcome(name=n, implied_prob=y) for n, y, _ in cands if y],
        timestamp=0.0,
        raw_data={"candidates": [{"name": n, "yes": y, "no": no} for n, y, no in cands]},
    )


def _match(dk_id, k_id):
    return FuturesMatch(dk_id, k_id, "DK Event", "Kalshi Event", [], 0, 1.0, 1.0)


POTY = ["Donald Trump", "Zohran Mamdani", "Pope Leo XIV", "Elon Musk",
        "Taylor Swift", "Sam Altman", "Dario Amodei", "Marco Rubio"]
DECADE = ["Elon Musk", "Taylor Swift", "Sam Altman",      # 3 shared with POTY
          "Greta Thunberg", "Xi Jinping", "Joe Biden",
          "Volodymyr Zelensky", "Lionel Messi", "Beyonce", "Barack Obama"]


# ---- matcher ----

def test_normalize_name():
    assert normalize_name("Péter Magyar") == "peter magyar"
    assert normalize_name("Mohammad-Bagher Ghalibaf") == "mohammad bagher ghalibaf"
    assert normalize_name("Pope Leo XIV") == "pope leo xiv"
    print("  normalize_name: accents/punctuation folded")


def test_match_picks_correct_counterpart():
    # When both Year and Decade are present, the DK Year board must take Year.
    dk = _names_market("dk_predictions", "dkPOTY", "TIME's Person of the Year 2026?", POTY)
    year = _names_market("kalshi", "KXTIME-26", "Time's Person of the Year for 2026", POTY)
    decade = _names_market("kalshi", "KXDECADE", "Time's Person of the Decade", DECADE)

    matches = match_futures([dk], [year, decade])
    assert len(matches) == 1
    assert matches[0].kalshi_market_id == "KXTIME-26"   # Year, not Decade
    assert matches[0].n_shared == 8 and matches[0].overlap == 1.0
    print(f"  match_correct: -> {matches[0].kalshi_market_id} "
          f"({matches[0].n_shared} shared, overlap {matches[0].overlap:.2f})")


def test_overlap_gate_rejects_phantom():
    # Decade alone shares only 3 of the 8 POTY names -> overlap 0.375 < 0.5 -> no match,
    # even though n_shared (3) clears min_shared. This is the phantom-match guard.
    dk = _names_market("dk_predictions", "dkPOTY", "TIME's Person of the Year 2026?", POTY)
    decade = _names_market("kalshi", "KXDECADE", "Time's Person of the Decade", DECADE)

    matches = match_futures([dk], [decade])
    assert matches == []
    print("  overlap_gate: weak 3/8 overlap rejected (no phantom Year<->Decade)")


# ---- detector ----

def test_candidate_arb_flagged():
    # Cand A: Yes@DK 0.30 + No@Kalshi 0.65(+fee) ~= 0.966 < 0.99 -> arb.
    dk = _cand_market("dk_predictions", "dk", "E", [("Cand A", 0.30, 0.74), ("Cand B", 0.50, 0.55)])
    kalshi = _cand_market("kalshi", "k", "E", [("Cand A", 0.40, 0.65), ("Cand B", 0.52, 0.53)])
    comp = compare_futures(_match("dk", "k"), dk, kalshi)

    a = next(c for c in comp.candidates if c.name == "Cand A")
    assert a.is_arb and a.lock_cost is not None and a.lock_cost < 1.0
    assert a.lock_desc == "Yes@DK + No@Kalshi"
    assert comp.n_arbs == 1
    assert comp.best_lock is not None and comp.best_lock < 1.0
    # the cheapest lock (the arb) sorts to the top
    assert comp.candidates[0].name == "Cand A"
    print(f"  candidate_arb: Cand A lock {a.lock_cost*100:.1f}c flagged; n_arbs={comp.n_arbs}")


def test_no_arb():
    dk = _cand_market("dk_predictions", "dk", "E", [("A", 0.50, 0.55), ("B", 0.60, 0.45)])
    kalshi = _cand_market("kalshi", "k", "E", [("A", 0.52, 0.53), ("B", 0.58, 0.47)])
    comp = compare_futures(_match("dk", "k"), dk, kalshi)

    assert comp.n_arbs == 0
    assert all(not c.is_arb for c in comp.candidates)
    assert comp.best_lock is not None and comp.best_lock >= 1.0
    print(f"  no_arb: best lock {comp.best_lock*100:.1f}c, 0 arbs")


def test_kalshi_fee_applied():
    # The Kalshi leg of the lock must carry Kalshi's fee, so the lock beats the naive sum.
    dk = _cand_market("dk_predictions", "dk", "E", [("A", 0.30, 0.74), ("B", 0.30, 0.74)])
    kalshi = _cand_market("kalshi", "k", "E", [("A", 0.40, 0.65), ("B", 0.40, 0.65)])
    comp = compare_futures(_match("dk", "k"), dk, kalshi)

    a = comp.candidates[0]
    assert a.lock_cost > 0.30 + 0.65                       # fee added on top of raw prices
    assert abs(a.lock_cost - (0.30 + effective_cost("kalshi", 0.65))) < 1e-9
    print(f"  kalshi_fee: lock {a.lock_cost*100:.2f}c > naive 95c (fee on No@Kalshi)")


def test_only_shared_candidates():
    # Candidates present on just one venue are dropped; only the intersection is compared.
    dk = _cand_market("dk_predictions", "dk", "E", [("A", 0.30, 0.70), ("DK Only", 0.20, 0.80)])
    kalshi = _cand_market("kalshi", "k", "E", [("A", 0.40, 0.60), ("Kalshi Only", 0.10, 0.90)])
    comp = compare_futures(_match("dk", "k"), dk, kalshi)

    assert {c.name for c in comp.candidates} == {"A"}
    assert comp.n_shared == 1
    print("  only_shared: one-venue candidates dropped")


if __name__ == "__main__":
    test_normalize_name()
    test_match_picks_correct_counterpart()
    test_overlap_gate_rejects_phantom()
    test_candidate_arb_flagged()
    test_no_arb()
    test_kalshi_fee_applied()
    test_only_shared_candidates()
    print("\nAll futures tests passed.")
