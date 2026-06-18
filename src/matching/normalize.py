"""
Team name normalization.

Different sources name teams differently:
  - The Odds API:  "Los Angeles Angels", "Boston Red Sox"  (City + Nickname)
  - Kalshi:        "Los Angeles A",      "Boston"           (City, letter-disambiguated)

We map every known alias to a canonical abbreviation so games can be matched
by their *set of teams* rather than fragile string comparison.
"""

import re

# Canonical abbreviation -> list of known aliases (any source, any format).
# Ambiguous cities (LA, NY, Chicago) include the Kalshi single-letter style.
MLB_TEAMS = {
    "ARI": ["Arizona", "Arizona Diamondbacks", "Diamondbacks", "D-backs"],
    "ATL": ["Atlanta", "Atlanta Braves", "Braves"],
    "BAL": ["Baltimore", "Baltimore Orioles", "Orioles"],
    "BOS": ["Boston", "Boston Red Sox", "Red Sox"],
    "CHC": ["Chicago Cubs", "Cubs", "Chicago C"],
    "CWS": ["Chicago White Sox", "White Sox", "Chicago W"],
    "CIN": ["Cincinnati", "Cincinnati Reds", "Reds"],
    "CLE": ["Cleveland", "Cleveland Guardians", "Guardians"],
    "COL": ["Colorado", "Colorado Rockies", "Rockies"],
    "DET": ["Detroit", "Detroit Tigers", "Tigers"],
    "HOU": ["Houston", "Houston Astros", "Astros"],
    "KC": ["Kansas City", "Kansas City Royals", "Royals"],
    "LAA": ["Los Angeles Angels", "LA Angels", "Angels", "Los Angeles A", "Anaheim"],
    "LAD": ["Los Angeles Dodgers", "LA Dodgers", "Dodgers", "Los Angeles D"],
    "MIA": ["Miami", "Miami Marlins", "Marlins"],
    "MIL": ["Milwaukee", "Milwaukee Brewers", "Brewers"],
    "MIN": ["Minnesota", "Minnesota Twins", "Twins"],
    "NYM": ["New York Mets", "Mets", "New York M"],
    "NYY": ["New York Yankees", "Yankees", "New York Y"],
    "ATH": ["Athletics", "A's", "Oakland", "Oakland Athletics", "Las Vegas"],
    "PHI": ["Philadelphia", "Philadelphia Phillies", "Phillies"],
    "PIT": ["Pittsburgh", "Pittsburgh Pirates", "Pirates"],
    "SD": ["San Diego", "San Diego Padres", "Padres"],
    "SF": ["San Francisco", "San Francisco Giants", "Giants"],
    "SEA": ["Seattle", "Seattle Mariners", "Mariners"],
    "STL": ["St. Louis", "St Louis", "St. Louis Cardinals", "Cardinals"],
    "TB": ["Tampa Bay", "Tampa Bay Rays", "Rays"],
    "TEX": ["Texas", "Texas Rangers", "Rangers"],
    "TOR": ["Toronto", "Toronto Blue Jays", "Blue Jays"],
    "WSH": ["Washington", "Washington Nationals", "Nationals"],
}


def _norm(s: str) -> str:
    """Lowercase and strip punctuation so 'A's' -> 'as', 'St. Louis' -> 'st louis'."""
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


# Reverse index: normalized alias -> canonical abbreviation
_ALIAS_INDEX: dict[str, str] = {}
for _abbr, _aliases in MLB_TEAMS.items():
    for _alias in _aliases:
        _ALIAS_INDEX[_norm(_alias)] = _abbr


def normalize_team(raw_name: str) -> str | None:
    """
    Return the canonical abbreviation for a raw team name, or None if unknown.

    Tries exact alias match first, then a safe substring fallback that only
    resolves when exactly one team matches (avoids 'Los Angeles' ambiguity).
    """
    n = _norm(raw_name)
    if not n:
        return None
    if n in _ALIAS_INDEX:
        return _ALIAS_INDEX[n]

    # Fallback: unique substring match (one team only, else give up)
    hits = {abbr for alias, abbr in _ALIAS_INDEX.items() if alias in n or n in alias}
    return hits.pop() if len(hits) == 1 else None
