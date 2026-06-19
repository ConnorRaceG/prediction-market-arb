"""
Unit tests for the novelty arb detector (no network, no browser, no LLM).

Builds synthetic DraftKings + Kalshi markets and a hand-made match, then checks
the cross-venue Dutch-book math: cheapest venue per outcome, fee-aware, sized to
whole Kalshi contracts. Modeled on a Nathan's-Hot-Dog-style Over/Under.

Run:  python -m tests.test_novelty_detector   (or: pytest tests/)
"""

from dataclasses import dataclass

from src.models import Market, Outcome
from src.arb.novelty_detector import detect_novelty_arb, MIN_MATCH_CONFIDENCE


@dataclass
class _Match:  # stands in for llm_matcher.NoveltyMatch (keeps the test LLM-free)
    outcome_map: dict
    confidence: float = 0.95
    note: str = "test match"
    dk_market_id: str = "dk1"
    kalshi_market_id: str = "k1"


def _dk(over_american, under_american):
    return Market(
        source="dk_novelty", market_id="dk1",
        event_name="Nathan's Hot Dog Eating Contest",
        market_type="Total Hot Dogs Eaten by Joey Chestnut",
        outcomes=[Outcome(name="Over 76.5", odds_american=over_american),
                  Outcome(name="Under 76.5", odds_american=under_american)],
        timestamp=0.0,
    )


def _kalshi(over_prob, under_prob):
    return Market(
        source="kalshi", market_id="k1",
        event_name="Nathan's Hot Dog Eating Contest",
        market_type="novelty",
        outcomes=[Outcome(name="77 or more", implied_prob=over_prob),
                  Outcome(name="76 or fewer", implied_prob=under_prob)],
        timestamp=0.0,
    )


MAP = {"Over 76.5": "77 or more", "Under 76.5": "76 or fewer"}


def test_clear_arb():
    # Over cheaper on DK (+180 -> 0.357), Under far cheaper on Kalshi (0.33)
    dk = _dk(180, -250)            # implied 0.357 / 0.714
    kalshi = _kalshi(0.42, 0.33)
    r = detect_novelty_arb(_Match(MAP), dk, kalshi, bankroll=100.0)
    assert r is not None
    assert r.is_arb
    venues = {leg.outcome: leg.venue for leg in r.legs}
    assert venues["Over 76.5"] == "draftkings"
    assert venues["Under 76.5"] == "kalshi"
    # Kalshi leg carries an integer contract count; DK legs don't
    kleg = next(l for l in r.legs if l.venue == "kalshi")
    assert kleg.contracts and kleg.contracts > 0
    assert all(l.contracts is None for l in r.legs if l.venue == "draftkings")
    # T = 0.357 + (0.33 + 0.07*0.33*0.67) ~= 0.7026 -> edge ~= +0.30
    assert 0.25 < r.edge < 0.33
    assert r.profit > 0
    print(f"  clear_arb: edge {r.edge:+.2%}, profit ${r.profit:.2f} on ${r.staked:.2f}")


def test_priced_but_no_arb():
    # Kalshi undercuts on Under only, but not enough -> result returned, not an arb
    dk = _dk(180, -250)           # 0.357 / 0.714
    kalshi = _kalshi(0.40, 0.68)  # Under 0.68(+fee)~0.695 < 0.714, Over not cheaper
    r = detect_novelty_arb(_Match(MAP), dk, kalshi, bankroll=100.0)
    assert r is not None
    assert not r.is_arb
    assert r.edge < 0
    print(f"  priced_but_no_arb: edge {r.edge:+.2%}, is_arb={r.is_arb}")


def test_none_when_kalshi_never_cheaper():
    # Kalshi absurdly expensive on both sides -> no substitution -> None
    dk = _dk(-110, -110)          # ~0.524 each
    kalshi = _kalshi(0.95, 0.95)
    r = detect_novelty_arb(_Match(MAP), dk, kalshi, bankroll=100.0)
    assert r is None
    print("  none_when_kalshi_never_cheaper: correctly returned None")


def test_low_confidence_not_flagged():
    # Same fat edge as clear_arb, but a shaky match must NOT be flagged actionable
    dk = _dk(180, -250)
    kalshi = _kalshi(0.42, 0.33)
    r = detect_novelty_arb(_Match(MAP, confidence=0.5), dk, kalshi, bankroll=100.0)
    assert r is not None
    assert r.edge > 0          # math still shows an edge
    assert not r.is_arb        # but low confidence gates the flag
    assert 0.5 < MIN_MATCH_CONFIDENCE
    print(f"  low_confidence: edge {r.edge:+.2%} present but is_arb={r.is_arb}")


if __name__ == "__main__":
    test_clear_arb()
    test_priced_but_no_arb()
    test_none_when_kalshi_never_cheaper()
    test_low_confidence_not_flagged()
    print("\nAll novelty detector tests passed.")
