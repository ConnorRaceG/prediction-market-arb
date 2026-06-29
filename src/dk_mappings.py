"""
Persistent pin of LLM-confirmed DK board -> Kalshi market mappings, in data/dk_mappings.json.

The deterministic matcher handles boards that share real candidate names (Person of the
Year, a Senate race priced party-vs-party) for free. The binary / political / economic
boards (a recession, the Fed decision, a race Kalshi names differently) need the LLM to
know they're the same market. Those boards recur and their mapping is stable, so once the
LLM has matched one at high confidence we PIN it here:
  ticker -> {kalshi, kalshi_title, outcome_map, confidence, note, ts}
and reuse the mapping on later scans instead of paying for the LLM every run. Prices are
still fetched live each scan; only the (which-event, how-outcomes-align) decision is pinned.

A pin re-confirms with the LLM after a week, and a pin that stops aligning (candidate names
changed) self-heals by falling back to the LLM that run. Pure data, no heavy imports.
"""

import os
import json
import time

from config.settings import project_root

_PATH = os.path.join(project_root, "data", "dk_mappings.json")

# Re-confirm a pinned mapping with the LLM at most this often (markets/wording can drift).
TTL_SECS = 7 * 24 * 3600


def load() -> dict:
    try:
        with open(_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save(mappings: dict) -> None:
    os.makedirs(os.path.dirname(_PATH), exist_ok=True)
    tmp = _PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(mappings, f)
    os.replace(tmp, _PATH)


def fresh(entry: dict | None) -> bool:
    """True if a pin exists and hasn't aged past the re-confirm window."""
    return bool(entry) and (time.time() - entry.get("ts", 0)) < TTL_SECS


def put(mappings: dict, dk_ticker: str, kalshi_ticker: str, kalshi_title: str,
        outcome_map, confidence: float, note: str) -> None:
    mappings[dk_ticker] = {
        "kalshi": kalshi_ticker,
        "kalshi_title": kalshi_title,
        "outcome_map": outcome_map,
        "confidence": confidence,
        "note": note,
        "ts": time.time(),
    }
