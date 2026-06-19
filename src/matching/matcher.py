"""
Match equivalent markets across sources.

Each market is keyed by the frozenset of canonical team abbreviations in its
outcomes. Markets from different sources sharing the same key are the same game.
"""

from dataclasses import dataclass, field
from src.models import Market
from src.matching.normalize import normalize_team


@dataclass
class MatchedMarket:
    """A single real-world game, with the equivalent markets from each source."""
    teams: frozenset            # canonical team abbreviations, e.g. {'BOS', 'SEA'}
    slate_date: str | None = None  # ET game date, distinguishes series games
    markets: list[Market] = field(default_factory=list)

    @property
    def sources(self) -> set:
        return {m.source for m in self.markets}

    def __repr__(self):
        date = f"@{self.slate_date}" if self.slate_date else ""
        return f"MatchedMarket({'/'.join(sorted(self.teams))}{date}: {sorted(self.sources)})"


def market_key(market: Market, sport: str) -> tuple | None:
    """
    Hashable identity for a market: (team-set, game date). The date keeps the
    games of a multi-day series (same two teams) from collapsing into one. None
    if any team can't be normalized.
    """
    abbrs = [normalize_team(o.name, sport) for o in market.outcomes]
    if any(a is None for a in abbrs):
        return None
    return (frozenset(abbrs), market.slate_date)


def match_markets(markets: list[Market], sport: str) -> list[MatchedMarket]:
    """
    Group markets that represent the same game across sources.

    Returns only groups that appear in 2+ sources (i.e. arb candidates).
    """
    groups: dict[tuple, MatchedMarket] = {}
    unmatched = []

    for m in markets:
        key = market_key(m, sport)
        if key is None:
            unmatched.append(m)
            continue
        teams, slate_date = key
        if key not in groups:
            groups[key] = MatchedMarket(teams=teams, slate_date=slate_date)
        groups[key].markets.append(m)

    if unmatched:
        names = {o.name for m in unmatched for o in m.outcomes}
        print(f"[matcher] {len(unmatched)} markets had unrecognized teams: {sorted(names)}")

    # Only keep games present in more than one source
    return [g for g in groups.values() if len(g.sources) >= 2]
