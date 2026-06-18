"""
Team name normalization, per sport.

Sources name teams differently:
  - The Odds API:  "Los Angeles Lakers", "New York Jets"   (City + Nickname)
  - Kalshi:        "Los Angeles L",      "New York J"        (City, letter-disambiguated)

Each sport has its own registry (canonical abbreviation -> aliases) so games
can be matched by their *set of teams* rather than fragile string comparison.
Registries are namespaced by sport, so "Panthers" (NHL Florida) and "Panthers"
(NFL Carolina) never collide.

For ambiguous cities (LA, NY, Chicago) we include Kalshi's single-letter style.
"""

import re

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

NBA_TEAMS = {
    "ATL": ["Atlanta", "Atlanta Hawks", "Hawks"],
    "BOS": ["Boston", "Boston Celtics", "Celtics"],
    "BKN": ["Brooklyn", "Brooklyn Nets", "Nets"],
    "CHA": ["Charlotte", "Charlotte Hornets", "Hornets"],
    "CHI": ["Chicago", "Chicago Bulls", "Bulls"],
    "CLE": ["Cleveland", "Cleveland Cavaliers", "Cavaliers", "Cavs"],
    "DAL": ["Dallas", "Dallas Mavericks", "Mavericks", "Mavs"],
    "DEN": ["Denver", "Denver Nuggets", "Nuggets"],
    "DET": ["Detroit", "Detroit Pistons", "Pistons"],
    "GSW": ["Golden State", "Golden State Warriors", "Warriors"],
    "HOU": ["Houston", "Houston Rockets", "Rockets"],
    "IND": ["Indiana", "Indiana Pacers", "Pacers"],
    "LAC": ["Los Angeles Clippers", "LA Clippers", "Clippers", "Los Angeles C"],
    "LAL": ["Los Angeles Lakers", "LA Lakers", "Lakers", "Los Angeles L"],
    "MEM": ["Memphis", "Memphis Grizzlies", "Grizzlies"],
    "MIA": ["Miami", "Miami Heat", "Heat"],
    "MIL": ["Milwaukee", "Milwaukee Bucks", "Bucks"],
    "MIN": ["Minnesota", "Minnesota Timberwolves", "Timberwolves", "Wolves"],
    "NOP": ["New Orleans", "New Orleans Pelicans", "Pelicans"],
    "NYK": ["New York", "New York Knicks", "Knicks"],
    "OKC": ["Oklahoma City", "Oklahoma City Thunder", "Thunder"],
    "ORL": ["Orlando", "Orlando Magic", "Magic"],
    "PHI": ["Philadelphia", "Philadelphia 76ers", "76ers", "Sixers"],
    "PHX": ["Phoenix", "Phoenix Suns", "Suns"],
    "POR": ["Portland", "Portland Trail Blazers", "Trail Blazers", "Blazers"],
    "SAC": ["Sacramento", "Sacramento Kings", "Kings"],
    "SAS": ["San Antonio", "San Antonio Spurs", "Spurs"],
    "TOR": ["Toronto", "Toronto Raptors", "Raptors"],
    "UTA": ["Utah", "Utah Jazz", "Jazz"],
    "WAS": ["Washington", "Washington Wizards", "Wizards"],
}

NFL_TEAMS = {
    "ARI": ["Arizona", "Arizona Cardinals", "Cardinals"],
    "ATL": ["Atlanta", "Atlanta Falcons", "Falcons"],
    "BAL": ["Baltimore", "Baltimore Ravens", "Ravens"],
    "BUF": ["Buffalo", "Buffalo Bills", "Bills"],
    "CAR": ["Carolina", "Carolina Panthers", "Panthers"],
    "CHI": ["Chicago", "Chicago Bears", "Bears"],
    "CIN": ["Cincinnati", "Cincinnati Bengals", "Bengals"],
    "CLE": ["Cleveland", "Cleveland Browns", "Browns"],
    "DAL": ["Dallas", "Dallas Cowboys", "Cowboys"],
    "DEN": ["Denver", "Denver Broncos", "Broncos"],
    "DET": ["Detroit", "Detroit Lions", "Lions"],
    "GB": ["Green Bay", "Green Bay Packers", "Packers"],
    "HOU": ["Houston", "Houston Texans", "Texans"],
    "IND": ["Indianapolis", "Indianapolis Colts", "Colts"],
    "JAX": ["Jacksonville", "Jacksonville Jaguars", "Jaguars"],
    "KC": ["Kansas City", "Kansas City Chiefs", "Chiefs"],
    "LV": ["Las Vegas", "Las Vegas Raiders", "Raiders"],
    "LAC": ["Los Angeles Chargers", "LA Chargers", "Chargers", "Los Angeles C"],
    "LAR": ["Los Angeles Rams", "LA Rams", "Rams", "Los Angeles R"],
    "MIA": ["Miami", "Miami Dolphins", "Dolphins"],
    "MIN": ["Minnesota", "Minnesota Vikings", "Vikings"],
    "NE": ["New England", "New England Patriots", "Patriots"],
    "NO": ["New Orleans", "New Orleans Saints", "Saints"],
    "NYG": ["New York Giants", "Giants", "New York G"],
    "NYJ": ["New York Jets", "Jets", "New York J"],
    "PHI": ["Philadelphia", "Philadelphia Eagles", "Eagles"],
    "PIT": ["Pittsburgh", "Pittsburgh Steelers", "Steelers"],
    "SF": ["San Francisco", "San Francisco 49ers", "49ers", "Niners"],
    "SEA": ["Seattle", "Seattle Seahawks", "Seahawks"],
    "TB": ["Tampa Bay", "Tampa Bay Buccaneers", "Buccaneers", "Bucs"],
    "TEN": ["Tennessee", "Tennessee Titans", "Titans"],
    "WAS": ["Washington", "Washington Commanders", "Commanders"],
}

NHL_TEAMS = {
    "ANA": ["Anaheim", "Anaheim Ducks", "Ducks"],
    "BOS": ["Boston", "Boston Bruins", "Bruins"],
    "BUF": ["Buffalo", "Buffalo Sabres", "Sabres"],
    "CGY": ["Calgary", "Calgary Flames", "Flames"],
    "CAR": ["Carolina", "Carolina Hurricanes", "Hurricanes", "Canes"],
    "CHI": ["Chicago", "Chicago Blackhawks", "Blackhawks"],
    "COL": ["Colorado", "Colorado Avalanche", "Avalanche", "Avs"],
    "CBJ": ["Columbus", "Columbus Blue Jackets", "Blue Jackets"],
    "DAL": ["Dallas", "Dallas Stars", "Stars"],
    "DET": ["Detroit", "Detroit Red Wings", "Red Wings"],
    "EDM": ["Edmonton", "Edmonton Oilers", "Oilers"],
    "FLA": ["Florida", "Florida Panthers", "Panthers"],
    "LAK": ["Los Angeles", "Los Angeles Kings", "LA Kings", "Kings"],
    "MIN": ["Minnesota", "Minnesota Wild", "Wild"],
    "MTL": ["Montreal", "Montreal Canadiens", "Canadiens", "Habs"],
    "NSH": ["Nashville", "Nashville Predators", "Predators", "Preds"],
    "NJD": ["New Jersey", "New Jersey Devils", "Devils"],
    "NYI": ["New York Islanders", "Islanders", "New York I"],
    "NYR": ["New York Rangers", "Rangers", "New York R"],
    "OTT": ["Ottawa", "Ottawa Senators", "Senators", "Sens"],
    "PHI": ["Philadelphia", "Philadelphia Flyers", "Flyers"],
    "PIT": ["Pittsburgh", "Pittsburgh Penguins", "Penguins", "Pens"],
    "SJS": ["San Jose", "San Jose Sharks", "Sharks"],
    "SEA": ["Seattle", "Seattle Kraken", "Kraken"],
    "STL": ["St. Louis", "St Louis", "St. Louis Blues", "Blues"],
    "TBL": ["Tampa Bay", "Tampa Bay Lightning", "Lightning", "Bolts"],
    "TOR": ["Toronto", "Toronto Maple Leafs", "Maple Leafs", "Leafs"],
    "VAN": ["Vancouver", "Vancouver Canucks", "Canucks"],
    "VGK": ["Vegas", "Vegas Golden Knights", "Golden Knights", "Knights"],
    "WSH": ["Washington", "Washington Capitals", "Capitals", "Caps"],
    "WPG": ["Winnipeg", "Winnipeg Jets", "Jets"],
    "UTA": ["Utah", "Utah Hockey Club", "Utah Mammoth", "Mammoth"],
}

WNBA_TEAMS = {
    "ATL": ["Atlanta", "Atlanta Dream", "Dream"],
    "CHI": ["Chicago", "Chicago Sky", "Sky"],
    "CONN": ["Connecticut", "Connecticut Sun", "Sun"],
    "DAL": ["Dallas", "Dallas Wings", "Wings"],
    "GS": ["Golden State", "Golden State Valkyries", "Valkyries"],
    "IND": ["Indiana", "Indiana Fever", "Fever"],
    "LV": ["Las Vegas", "Las Vegas Aces", "Aces"],
    "LA": ["Los Angeles", "Los Angeles Sparks", "Sparks"],
    "MIN": ["Minnesota", "Minnesota Lynx", "Lynx"],
    "NY": ["New York", "New York Liberty", "Liberty"],
    "PHX": ["Phoenix", "Phoenix Mercury", "Mercury"],
    "SEA": ["Seattle", "Seattle Storm", "Storm"],
    "WAS": ["Washington", "Washington Mystics", "Mystics"],
    "TOR": ["Toronto", "Toronto Tempo", "Tempo"],       # 2026 expansion
    "POR": ["Portland", "Portland Fire", "Fire"],       # 2026 expansion
}

# Canonical sport key (matches The Odds API keys) -> team registry
SPORT_TEAMS = {
    "baseball_mlb": MLB_TEAMS,
    "basketball_nba": NBA_TEAMS,
    "basketball_wnba": WNBA_TEAMS,
    "americanfootball_nfl": NFL_TEAMS,
    "icehockey_nhl": NHL_TEAMS,
}


def _norm(s: str) -> str:
    """Lowercase and strip punctuation so 'A's' -> 'as', 'St. Louis' -> 'st louis'."""
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


# Lazily-built reverse indexes: sport -> {normalized alias: abbreviation}
_INDEXES: dict[str, dict[str, str]] = {}


def _index_for(sport: str) -> dict[str, str]:
    if sport not in _INDEXES:
        idx: dict[str, str] = {}
        for abbr, aliases in SPORT_TEAMS.get(sport, {}).items():
            for alias in aliases:
                idx[_norm(alias)] = abbr
        _INDEXES[sport] = idx
    return _INDEXES[sport]


def normalize_team(raw_name: str, sport: str) -> str | None:
    """
    Canonical abbreviation for a raw team name within a sport, or None if unknown.

    Exact alias match first, then a safe substring fallback that only resolves
    when exactly one team matches (avoids 'Los Angeles' ambiguity).
    """
    idx = _index_for(sport)
    n = _norm(raw_name)
    if not n:
        return None
    if n in idx:
        return idx[n]
    hits = {abbr for alias, abbr in idx.items() if alias in n or n in alias}
    return hits.pop() if len(hits) == 1 else None
