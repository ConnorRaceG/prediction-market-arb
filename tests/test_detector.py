"""
Unit tests for the DETERMINISTIC sports path (no network).

Covers the core the tool actually relies on: team-registry matching across
sources (Kalshi vs Odds API), the date-aware key that stops a multi-day series
from collapsing, and the fee-aware arb + whole-contract sizing in the detector.

Run:  python -m tests.test_detector   (or: pytest tests/)
"""

from src.models import Market, Outcome
from src.matching.matcher import match_markets
from src.arb.detector import detect_arbs


def _kalshi(date, bos_prob, sea_prob):
    return Market(
        source="kalshi", market_id="K1", event_name="Red Sox vs Mariners",
        market_type="moneyline",
        outcomes=[Outcome(name="Boston Red Sox", implied_prob=bos_prob),
                  Outcome(name="Seattle Mariners", implied_prob=sea_prob)],
        timestamp=0.0, slate_date=date,
    )


def _book(date, bos_american, sea_american, bos_book="fanduel", sea_book="betmgm"):
    return Market(
        source="odds_api", market_id="O1",
        event_name="Boston Red Sox @ Seattle Mariners", market_type="moneyline",
        outcomes=[Outcome(name="Boston Red Sox", odds_american=bos_american, book=bos_book),
                  Outcome(name="Seattle Mariners", odds_american=sea_american, book=sea_book)],
        timestamp=0.0, slate_date=date,
    )


def test_match_and_arb():
    # Kalshi cheap on Boston, the book cheap on Seattle -> cross-source arb
    k = _kalshi("2026-06-18", 0.36, 0.70)
    b = _book("2026-06-18", -150, 130)
    matched = match_markets([k, b], "baseball_mlb")
    assert len(matched) == 1
    assert matched[0].sources == {"kalshi", "odds_api"}

    results = detect_arbs(matched, "baseball_mlb", bankroll=100.0)
    assert len(results) == 1
    r = results[0]
    assert r.is_arb
    assert 0.15 < r.edge < 0.22
    by_team = {leg.team: leg for leg in r.legs}
    # cheapest side per team, with the right source + sizing style
    assert by_team["BOS"].source == "kalshi" and (by_team["BOS"].contracts or 0) > 0
    assert by_team["SEA"].source == "betmgm" and by_team["SEA"].contracts is None
    assert r.profit > 0
    print(f"  match_and_arb: edge {r.edge:+.2%}, BOS@kalshi x{by_team['BOS'].contracts}, "
          f"profit ${r.profit:.2f}")


def test_date_separation():
    # Same two teams, different game dates -> must NOT collapse into one match
    # (this is what prevents phantom arbs from comparing different days' odds)
    k = _kalshi("2026-06-18", 0.36, 0.70)
    b = _book("2026-06-19", -150, 130)
    matched = match_markets([k, b], "baseball_mlb")
    assert matched == []
    print("  date_separation: same teams, different dates -> no match")


def test_no_arb():
    # Efficient prices: a result is still returned (for the dashboard), not an arb
    k = _kalshi("2026-06-18", 0.55, 0.52)
    b = _book("2026-06-18", -120, 100)
    matched = match_markets([k, b], "baseball_mlb")
    results = detect_arbs(matched, "baseball_mlb", bankroll=100.0)
    assert len(results) == 1 and not results[0].is_arb
    print(f"  no_arb: edge {results[0].edge:+.2%}, is_arb={results[0].is_arb}")


if __name__ == "__main__":
    test_match_and_arb()
    test_date_separation()
    test_no_arb()
    print("\nAll deterministic detector tests passed.")
