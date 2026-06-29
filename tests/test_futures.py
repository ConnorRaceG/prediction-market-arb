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
from src.matching.futures_matcher import (
    match_futures, normalize_name, FuturesMatch, period_sig, period_conflict)
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


def test_period_sig_and_conflict():
    assert period_sig("Fed decision in Jul 2026?") == ("2026", "jul")
    assert period_sig("Time's Person of the Year for 2026") == ("2026", None)
    assert period_sig("Recession this year?") == (None, None)
    assert period_conflict("Fed decision in Jul 2026", "Fed decision in Sep 2026")
    assert not period_conflict("Fed decision in Jul 2026", "Fed decision in Jul 2026")
    # lenient: a missing year/month on either side is not a conflict
    assert not period_conflict("US Recession in 2026?", "Recession this year?")
    print("  period_sig/conflict: month+year parsed; lenient on missing parts")


def test_match_rejects_other_month():
    # A board that recurs monthly repeats the same candidate names. The DK July board must
    # NOT match the Kalshi September one despite a perfect candidate overlap, and must take
    # the July counterpart when both are present.
    names = ["Alpha Co", "Bravo Co", "Charlie Co", "Delta Co"]
    dk = _names_market("dk_predictions", "dkJUL", "Top mover in Jul 2026", names)
    sep = _names_market("kalshi", "KXSEP", "Top mover in Sep 2026", names)
    assert match_futures([dk], [sep]) == []                       # cross-month rejected
    jul = _names_market("kalshi", "KXJUL", "Top mover in Jul 2026", names)
    m = match_futures([dk], [sep, jul])
    assert len(m) == 1 and m[0].kalshi_market_id == "KXJUL"       # right month picked
    print("  period_match: cross-month rejected, same-month chosen")


def test_overlap_gate_rejects_phantom():
    # Decade (10 names) shares only 3 with the 8 POTY names -> overlap 3/10 < 0.5 ->
    # no match, even though n_shared (3) clears min_shared. The phantom-match guard.
    dk = _names_market("dk_predictions", "dkPOTY", "TIME's Person of the Year 2026?", POTY)
    decade = _names_market("kalshi", "KXDECADE", "Time's Person of the Decade", DECADE)

    matches = match_futures([dk], [decade])
    assert matches == []
    print("  overlap_gate: weak 3/10 overlap rejected (no phantom Year<->Decade)")


def test_overlap_gate_rejects_subset():
    # The real bug: a TINY Kalshi board whose every name is inside the big DK board.
    # shared/min would be 3/3 = 1.0 (false match -> false arb); shared/max = 3/8 = 0.375
    # rejects it. Regression guard for the Person-of-the-Year vs Decade false arb.
    dk = _names_market("dk_predictions", "dkPOTY", "Person of the Year", POTY)  # 8 names
    subset = _names_market("kalshi", "KXSMALL", "Person of the Decade",
                           ["Elon Musk", "Taylor Swift", "Sam Altman"])  # all 3 in POTY
    assert match_futures([dk], [subset]) == []
    print("  subset_gate: tiny contained subset board rejected (no false arb)")


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


def test_both_fees_applied():
    # Each leg of the lock carries its venue's fee: Kalshi's proportional fee AND
    # DraftKings Predictions' flat per-contract fee. So the lock beats the naive sum.
    dk = _cand_market("dk_predictions", "dk", "E", [("A", 0.30, 0.74), ("B", 0.30, 0.74)])
    kalshi = _cand_market("kalshi", "k", "E", [("A", 0.40, 0.65), ("B", 0.40, 0.65)])
    comp = compare_futures(_match("dk", "k"), dk, kalshi)

    a = comp.candidates[0]  # cheapest lock: Yes@DK(0.30) + No@Kalshi(0.65)
    expected = effective_cost("dk_predictions", 0.30) + effective_cost("kalshi", 0.65)
    assert a.lock_cost > 0.30 + 0.65                       # both fees added on top of raw prices
    assert abs(a.lock_cost - expected) < 1e-9
    print(f"  both_fees: lock {a.lock_cost*100:.2f}c > naive 95c (DK + Kalshi fees)")


def test_dk_predictions_fee_tiers():
    from src.arb.fees import dk_predictions_fee_per_contract as f
    assert f(0.05) == 0.01 and f(0.19) == 0.01      # cheap -> 1c
    assert f(0.20) == 0.02 and f(0.50) == 0.02 and f(0.96) == 0.02  # middle -> 2c
    assert f(0.97) == 0.01 and f(0.99) == 0.01      # expensive -> 1c
    print("  dk_fee_tiers: 1c at 1-19c / 97-99c, 2c at 20-96c")


def test_threshold_buckets_not_crossed():
    # The real Fed false arb: DK 'Hike >25bps' (5c) got compared against Kalshi
    # 'Hike 25bps' (16c) -> phantom 8% lock. They are DIFFERENT outcomes (a >25bps
    # hike vs a 25bps hike), so the row must be dropped, even when the LLM's outcome_map
    # explicitly crosses them. Real numbers off the July 2026 Fed boards.
    dk = _cand_market("dk_predictions", "dk", "Fed Decision in Jul 2026",
                      [("Hike >25bps", 0.05, 0.95), ("0bps (Unchanged)", 0.85, 0.16),
                       ("Cut >25bps", 0.06, 0.95)])
    kalshi = _cand_market("kalshi", "k", "Fed decision in Jul 2026",
                          [("Hike >25bps", 0.01, None), ("Hike 25bps", 0.16, 0.86),
                           ("Fed maintains rate", 0.85, 0.16), ("Cut 25bps", 0.02, 0.99)])
    bad_map = {"Hike >25bps": "Hike 25bps",            # the off-by-one-bucket mismatch
               "0bps (Unchanged)": "Fed maintains rate",
               "Cut >25bps": "Cut 25bps"}
    comp = compare_futures(_match("dk", "k"), dk, kalshi, outcome_map=bad_map)

    names = {c.name for c in comp.candidates}
    assert comp.n_arbs == 0                         # phantom hike arb is gone
    assert "Hike >25bps" not in names               # mismatched-threshold row dropped
    assert "0bps (Unchanged)" in names              # the clean same-bucket row survives
    print("  threshold_guard: '>25bps' vs '25bps' refused (no phantom Fed arb)")


def test_threshold_buckets_same_bucket_compares():
    # The flip side: identical thresholds ('>25bps' vs '>25bps') must still compare,
    # so a genuine same-outcome price gap isn't thrown away with the phantom.
    dk = _cand_market("dk_predictions", "dk", "Fed", [("Hike >25bps", 0.05, 0.95)])
    kalshi = _cand_market("kalshi", "k", "Fed", [("Hike >25bps", 0.01, 0.98)])
    comp = compare_futures(_match("dk", "k"), dk, kalshi,
                           outcome_map={"Hike >25bps": "Hike >25bps"})
    assert len(comp.candidates) == 1
    row = comp.candidates[0]
    assert row.dk_yes == 0.05 and row.kalshi_yes == 0.01   # aligned to the right bucket
    print("  threshold_same: '>25bps' vs '>25bps' compared on the correct prices")


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
    test_period_sig_and_conflict()
    test_match_rejects_other_month()
    test_overlap_gate_rejects_phantom()
    test_overlap_gate_rejects_subset()
    test_candidate_arb_flagged()
    test_no_arb()
    test_both_fees_applied()
    test_dk_predictions_fee_tiers()
    test_threshold_buckets_not_crossed()
    test_threshold_buckets_same_bucket_compares()
    test_only_shared_candidates()
    print("\nAll futures tests passed.")
