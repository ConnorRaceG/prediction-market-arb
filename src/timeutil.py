"""
Time helpers for aligning game dates across sources.

The Odds API gives game start as a UTC ISO timestamp; Kalshi encodes the date
in its ticker. To match a Kalshi market to a sportsbook market we compare the
*official game date* in US/Eastern (how leagues schedule), which both sources
agree on. Keeping the timezone logic here keeps the adapters clean.
"""

from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover — missing tzdata
    _ET = timezone.utc  # fallback: dates may be off by a day for late games


def iso_to_unix(iso: str) -> float:
    """Parse an ISO8601 timestamp (possibly 'Z'-suffixed) to a unix timestamp."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def et_date(unix_utc: float) -> str:
    """ET calendar date 'YYYY-MM-DD' for a unix timestamp — the official game date."""
    return datetime.fromtimestamp(unix_utc, _ET).strftime("%Y-%m-%d")


def et_unix(year: int, month: int, day: int, hour: int, minute: int) -> float:
    """Unix timestamp for a wall-clock ET datetime (used to read Kalshi tickers)."""
    return datetime(year, month, day, hour, minute, tzinfo=_ET).timestamp()
