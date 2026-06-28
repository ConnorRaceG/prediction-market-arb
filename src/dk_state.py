"""
Small persistent memory of the DraftKings Predictions board universe.

Two things get remembered between scans, in data/dk_state.json:
  - `seen`:   ticker -> first time we ever saw the board. Lets us flag a board as NEW
              the first scan it appears (new boards are where loose pricing lives).
  - `priced`: ticker -> last time we actually priced it. Lets us rotate the sweep so
              boards we haven't looked at in a while come up before ones we just did.

This is what makes "open mind, small footprint" work: we discover the whole catalog
every scan (cheap) but only pay to price a budget of boards, and this state decides
which ones. Pure data + ordering logic, no heavy imports.
"""

import os
import json
import time

from config.settings import project_root

_PATH = os.path.join(project_root, "data", "dk_state.json")

# Forget boards we haven't seen or priced in this long, so the file can't grow forever
# (a board that later reappears just looks new again, which is fine).
_TTL_SECS = 30 * 24 * 3600


def load_state() -> dict:
    try:
        with open(_PATH, encoding="utf-8") as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"seen": {}, "priced": {}}
    state.setdefault("seen", {})
    state.setdefault("priced", {})
    return state


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(_PATH), exist_ok=True)
    tmp = _PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(tmp, _PATH)


def new_tickers(specs, state: dict) -> set:
    """Tickers in this discovery we've never seen before."""
    seen = state.get("seen", {})
    return {s.ticker for s in specs if s.ticker not in seen}


def prioritize(specs, matchable: set, state: dict, budget: int) -> list:
    """Order discovered boards by how likely they are to surface an arb, then cap to the
    pricing budget. Tiers, in order:
      1. NEW boards that also match a Kalshi market   (highest-edge moment)
      2. known boards that match a Kalshi market        (where arbs can exist at all)
      3. NEW boards with no obvious Kalshi match yet     (open mind: still worth a look)
      4. everything else, least-recently-priced first    (slow rotation over the catalog)
    """
    seen = state.get("seen", {})
    priced = state.get("priced", {})
    new_match, known_match, new_other, rest = [], [], [], []
    for s in specs:
        is_new = s.ticker not in seen
        is_match = s.ticker in matchable
        if is_new and is_match:
            new_match.append(s)
        elif is_match:
            known_match.append(s)
        elif is_new:
            new_other.append(s)
        else:
            rest.append(s)
    rest.sort(key=lambda s: priced.get(s.ticker, 0.0))  # oldest / never-priced first
    return (new_match + known_match + new_other + rest)[:budget]


def record(state: dict, discovered, priced_tickers, now: float | None = None) -> dict:
    """Mark every discovered board as seen (keeping the first-seen time) and stamp the
    boards we just priced. Prunes anything past the TTL so the file stays bounded."""
    now = now or time.time()
    seen = state.setdefault("seen", {})
    pr = state.setdefault("priced", {})
    for s in discovered:
        seen.setdefault(s.ticker, now)
    for tk in priced_tickers:
        pr[tk] = now
    cutoff = now - _TTL_SECS
    live = {s.ticker for s in discovered}
    state["seen"] = {t: ts for t, ts in seen.items() if ts >= cutoff or t in live}
    state["priced"] = {t: ts for t, ts in pr.items() if ts >= cutoff or t in live}
    return state
