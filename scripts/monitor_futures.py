"""
Daily monitor for DK Predictions <-> Kalshi futures arbs.

These low-volume boards are efficient most of the time; the edge is intermittent, so
the point of the tool is to catch the moment a cross-venue lock drops under $1. This
runs one futures scan, appends a summary to data/monitor_history.jsonl (so you can see
how each board's best lock moves over time), and ONLY when a real arb appears it records
it to data/arbs_found.log, prints a loud banner, and pops a Windows alert.

Run once (e.g. from Task Scheduler, once a day):
    python scripts/monitor_futures.py
Or keep it looping in-process (scan every N hours):
    python scripts/monitor_futures.py --loop 24
"""

import os
import sys
import json
import time
import subprocess
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import Settings
from src.pipeline import run_dk_predictions_detection

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(_ROOT, "data")
HISTORY = os.path.join(DATA_DIR, "monitor_history.jsonl")
ALERTS = os.path.join(DATA_DIR, "arbs_found.log")
# Same warm browser profile the dashboard uses, so both share Akamai's trust cookies
# (whichever runs while the other holds it falls back to an ephemeral context).
DK_PROFILE = os.path.join(DATA_DIR, "dk_profile")

# The scheduled monitor can afford a deeper sweep than an interactive dashboard pull,
# so it prices a bigger budget of the prioritized boards each run.
PRICE_BUDGET = 18


def _record(ts: str, pr) -> dict:
    """One history row: counts + every matched board's best lock (for trend-watching)."""
    return {
        "ts": ts,
        "n_discovered": pr.n_discovered,
        "n_dk": pr.n_dk,
        "n_matched": pr.n_matched,
        "n_arbs": len(pr.arbs),
        "new_boards": pr.new_boards,
        "boards": [
            {"dk": c.dk_event, "kalshi": c.kalshi_event, "best_lock": c.best_lock,
             "n_arbs": c.n_arbs, "confidence": c.confidence}
            for c in pr.comparisons
        ],
    }


def _arb_banner(ts: str, arbs: list) -> str:
    """Human-readable alert text for the boards that crossed into arb territory."""
    lines = [f"[{ts}] {len(arbs)} ARB(S) FOUND"]
    for c in arbs:
        best = next((x for x in c.candidates if x.is_arb), None)
        detail = f" - {best.name} via {best.lock_desc}" if best else ""
        lock = f"{c.best_lock * 100:.0f}c" if c.best_lock is not None else "?"
        lines.append(f"  {c.dk_event}  <->  {c.kalshi_event}: "
                     f"{c.n_arbs} candidate arb(s), best lock {lock}{detail}")
    return "\n".join(lines)


def _windows_alert(title: str, message: str) -> None:
    """Best-effort desktop popup; never fails the scan."""
    try:
        subprocess.run(["msg", "*", f"{title}: {message}"], timeout=10, check=False)
    except Exception:
        pass


def scan_once(budget: int = PRICE_BUDGET) -> int:
    """Run one scan, log it, alert on any arb. Returns the number of boards with an arb."""
    os.makedirs(DATA_DIR, exist_ok=True)
    Settings.validate()
    ts = datetime.now().isoformat(timespec="seconds")
    print(f"[{ts}] scanning DK Predictions x Kalshi futures...")

    pr = run_dk_predictions_detection(
        headless=True, profile_dir=DK_PROFILE, price_budget=budget, verbose=True)
    with open(HISTORY, "a", encoding="utf-8") as f:
        f.write(json.dumps(_record(ts, pr)) + "\n")

    # Feed the dashboard's cache so it can show this scan even when a live refresh is
    # throttled (the monitor maintains the memory; the dashboard just displays it).
    if pr.n_dk > 0:
        try:
            from src.dashboard.cards import from_futures
            from src.dashboard import cache
            cache.save_cards("futures", [from_futures(c) for c in pr.comparisons])
        except Exception:
            pass

    arbs = pr.arbs
    print(f"[{ts}] {pr.n_discovered} boards discovered, {pr.n_dk} priced, "
          f"{pr.n_matched} matched, {len(arbs)} with an arb.")
    if pr.new_boards:
        print(f"[{ts}] new boards this scan: {', '.join(pr.new_boards)}")

    if arbs:
        banner = _arb_banner(ts, arbs)
        print("\n" + "=" * 64 + "\n" + banner + "\n" + "=" * 64)
        with open(ALERTS, "a", encoding="utf-8") as f:
            f.write(banner + "\n")
        first = arbs[0]
        lock = f"{first.best_lock * 100:.0f}c" if first.best_lock is not None else "?"
        _windows_alert("Arb found",
                       f"{first.dk_event} vs {first.kalshi_event} (lock {lock}). "
                       f"See data/arbs_found.log.")
    return len(arbs)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="DK Predictions x Kalshi futures monitor")
    ap.add_argument("--loop", type=float, metavar="HOURS", nargs="?", const=24.0,
                    default=None, help="scan every HOURS hours (default 24) instead of once")
    ap.add_argument("--budget", type=int, default=PRICE_BUDGET,
                    help=f"boards to price per scan (default {PRICE_BUDGET}); "
                         "the dashboard triggers a lighter run")
    a = ap.parse_args()
    if a.loop is not None:
        print(f"monitor loop: scanning every {a.loop}h (Ctrl+C to stop)")
        while True:
            try:
                scan_once(a.budget)
            except Exception as e:
                print(f"scan failed: {e}")
            time.sleep(a.loop * 3600)
    else:
        scan_once(a.budget)


if __name__ == "__main__":
    main()
