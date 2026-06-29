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

# Cover the whole catalog (currently ~23 boards). Matching quality depends on coverage:
# pricing only a few boards starves the Kalshi candidate pool and the LLM ends up matching
# a board to the wrong Kalshi variant. The dashboard no longer scrapes on its own, so this
# infrequent, jittered, warm-profile run can afford full coverage without tripping throttling.
PRICE_BUDGET = 30

# A single-scan lock so the scheduled run and a dashboard-triggered run can't scrape
# DraftKings (and write the cache) at the same time. A lock older than this is treated
# as stale (a previous run crashed) and reclaimed; a real scan finishes well under it.
LOCK = os.path.join(DATA_DIR, "monitor.lock")
LOCK_STALE_SECS = 20 * 60


def _acquire_lock() -> bool:
    """Take the exclusive scan lock. False if another fresh scan already holds it."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(LOCK) and (time.time() - os.path.getmtime(LOCK)) < LOCK_STALE_SECS:
        return False
    try:
        if os.path.exists(LOCK):
            os.remove(LOCK)  # stale -> reclaim
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except (FileExistsError, OSError):
        return False  # lost the race to another scan
    with os.fdopen(fd, "w") as f:
        f.write(f"{os.getpid()} {datetime.now().isoformat(timespec='seconds')}")
    return True


def _release_lock() -> None:
    try:
        os.remove(LOCK)
    except OSError:
        pass


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
    """Run one scan, log it, alert on any arb. Returns the number of boards with an arb,
    or -1 if another scan is already running (this one skips to avoid a double-scrape)."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if not _acquire_lock():
        print("another scan is already running; skipping this one.")
        return -1
    try:
        return _scan_once_locked(budget)
    finally:
        _release_lock()


def _scan_once_locked(budget: int) -> int:
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
        # Exit 2 signals "skipped, another scan is running" so a caller (the dashboard)
        # can tell that apart from a real failure.
        sys.exit(2 if scan_once(a.budget) == -1 else 0)


if __name__ == "__main__":
    main()
