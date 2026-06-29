"""
Persistent cache of the dashboard's last successful scan, per track.

The browser-scraped tracks (DK Predictions futures, novelty) fail when DraftKings
throttles repeated scrapes. Rather than show an error and nothing, the dashboard falls
back to the last successful scan saved on disk, with a note on how old it is. The daily
monitor writes the same cache, so the dashboard always has recent data to show even
between live refreshes (scraping and viewing are decoupled).

Cards are stored as plain JSON (dataclasses.asdict) under data/cache/<track>.json and
rebuilt into CardView objects on load. Importing this module pulls in no heavy deps.
"""

import os
import json
import time
import dataclasses

from src.dashboard.cards import CardView, CardLeg, BoardRow, ComparisonRow

_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "cache")


def _path(track: str) -> str:
    return os.path.join(_DIR, f"{track}.json")


def save_cards(track: str, cards: list) -> None:
    """Persist a track's cards as the new 'last successful scan' (atomic write)."""
    os.makedirs(_DIR, exist_ok=True)
    payload = {"ts": time.time(), "cards": [dataclasses.asdict(c) for c in cards]}
    tmp = _path(track) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, _path(track))


def load_cards(track: str):
    """Return (cards, timestamp) from the last saved scan, or ([], None) if none.

    Tolerant of schema drift: a card whose stored shape no longer matches the current
    CardView is skipped rather than crashing the dashboard (e.g. after a model change).
    """
    try:
        with open(_path(track), encoding="utf-8") as f:
            payload = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return [], None
    cards = []
    for d in payload.get("cards", []):
        try:
            cards.append(_from_dict(d))
        except Exception:
            continue
    return cards, payload.get("ts")


def _from_dict(d: dict) -> CardView:
    d = dict(d)
    d["legs"] = [CardLeg(**x) for x in (d.get("legs") or [])]
    d["board"] = [BoardRow(**x) for x in d["board"]] if d.get("board") else None
    d["comparison"] = [ComparisonRow(**x) for x in d["comparison"]] if d.get("comparison") else None
    return CardView(**d)


def cooldown_state(ts, cooldown_secs: float, force: bool = False, now=None):
    """Decide whether a DK-scraped track is still on cooldown.

    The cache timestamp doubles as the shared "last time anyone hit DraftKings" clock,
    so a recent monitor run counts too. Returns (on_cooldown, seconds_remaining); forcing
    or having no prior scan means not on cooldown (a live pull is allowed).
    """
    if force or ts is None:
        return False, 0.0
    now = now if now is not None else time.time()
    age = now - ts
    if age >= cooldown_secs:
        return False, 0.0
    return True, cooldown_secs - age


def humanize_age(ts) -> str:
    if not ts:
        return "unknown time"
    secs = max(0.0, time.time() - ts)
    if secs < 90:
        return "just now"
    if secs < 90 * 60:
        return f"{int(secs / 60)} min ago"
    if secs < 36 * 3600:
        return f"{int(secs / 3600)}h ago"
    return f"{int(secs / 86400)}d ago"
