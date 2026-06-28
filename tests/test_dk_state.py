"""
Unit tests for the DK Predictions discovery/priority plumbing (no network, no browser).

Covers the two pure pieces that decide how the "open mind, small footprint" scan
behaves:
  - src/dk_state.py: which discovered boards are new, and the priority order that
    spends a limited pricing budget (new + Kalshi-matchable first, slow rotation for
    the rest), plus seen/last-priced bookkeeping with TTL pruning;
  - src/dashboard/cache.py: the shared-cooldown decision that lets the dashboard
    refresh button serve cache instantly instead of re-hitting DraftKings.

Run:  python -m tests.test_dk_state   (or: pytest tests/)
"""

from src import dk_state
from src.adapters.dk_predictions import BoardSpec
from src.dashboard import cache


def _spec(ticker, title=""):
    return BoardSpec(ticker=ticker, title=title or ticker, url=f"/g/{ticker}", category="x")


# A:new+match  B:known+match  C:new+other  D:known+other(old)  E:known+other(new)
A, B, C, D, E = (_spec("A"), _spec("B"), _spec("C"), _spec("D"), _spec("E"))
SPECS = [A, B, C, D, E]
MATCHABLE = {"A", "B"}


def _state():
    return {"seen": {"B": 1.0, "D": 1.0, "E": 1.0},
            "priced": {"D": 100.0, "E": 200.0}}


# ---- new-board detection ----

def test_new_tickers():
    assert dk_state.new_tickers(SPECS, _state()) == {"A", "C"}
    assert dk_state.new_tickers(SPECS, {"seen": {}}) == {"A", "B", "C", "D", "E"}
    print("  new_tickers: unseen tickers flagged as new")


# ---- priority ordering ----

def test_prioritize_tiers():
    order = [s.ticker for s in dk_state.prioritize(SPECS, MATCHABLE, _state(), budget=10)]
    # new+match, then known+match, then new+other, then rotation oldest-priced first.
    assert order == ["A", "B", "C", "D", "E"]
    print(f"  prioritize_tiers: {order}")


def test_prioritize_budget_caps():
    picked = dk_state.prioritize(SPECS, MATCHABLE, _state(), budget=3)
    assert [s.ticker for s in picked] == ["A", "B", "C"]
    print("  prioritize_budget: capped to the budget, highest-edge tiers kept")


def test_prioritize_rotation_oldest_first():
    # With nothing matchable and nothing new, pure rotation: least-recently-priced first.
    st = {"seen": {"D": 1.0, "E": 1.0}, "priced": {"D": 200.0, "E": 100.0}}
    order = [s.ticker for s in dk_state.prioritize([D, E], set(), st, budget=10)]
    assert order == ["E", "D"]   # E priced longer ago -> comes first
    print("  prioritize_rotation: oldest-priced board surfaces first")


# ---- bookkeeping ----

def test_record_marks_seen_and_priced():
    st = {"seen": {}, "priced": {}}
    dk_state.record(st, SPECS, ["A", "C"], now=1000.0)
    assert set(st["seen"]) == {"A", "B", "C", "D", "E"}
    assert st["priced"] == {"A": 1000.0, "C": 1000.0}
    # first-seen time is preserved, not overwritten, on a later scan
    dk_state.record(st, SPECS, ["B"], now=2000.0)
    assert st["seen"]["A"] == 1000.0 and st["priced"]["B"] == 2000.0
    print("  record: marks seen (first time kept) + last-priced")


def test_record_prunes_stale():
    old = 1000.0
    st = {"seen": {"GONE": old}, "priced": {"GONE": old}}
    now = old + dk_state._TTL_SECS + 1     # GONE is past the TTL and not re-discovered
    dk_state.record(st, [A], ["A"], now=now)
    assert "GONE" not in st["seen"] and "GONE" not in st["priced"]
    assert "A" in st["seen"]
    print("  record_prune: boards past the TTL drop out of state")


# ---- shared cooldown ----

def test_cooldown_state():
    cd = 9000.0
    assert cache.cooldown_state(None, cd) == (False, 0.0)            # no prior scan
    assert cache.cooldown_state(1000.0, cd, force=True) == (False, 0.0)  # forced
    on, rem = cache.cooldown_state(now0 := 5000.0, cd, now=now0 + 1000.0)
    assert on and abs(rem - 8000.0) < 1e-6                           # mid-window
    on, rem = cache.cooldown_state(5000.0, cd, now=5000.0 + cd + 1)
    assert not on and rem == 0.0                                     # window elapsed
    print("  cooldown_state: None/forced/elapsed allow live; mid-window blocks")


if __name__ == "__main__":
    test_new_tickers()
    test_prioritize_tiers()
    test_prioritize_budget_caps()
    test_prioritize_rotation_oldest_first()
    test_record_marks_seen_and_priced()
    test_record_prunes_stale()
    test_cooldown_state()
    print("\nAll dk_state tests passed.")
