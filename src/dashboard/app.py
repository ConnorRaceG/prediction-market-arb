"""
Streamlit dashboard for arb detection.

Run with:  streamlit run src/dashboard/app.py

Shows the detection tracks in one edge-sorted grid: the deterministic sports
track (Kalshi vs US sportsbooks) always on, plus an optional LLM-matched
Polymarket track and the DK Predictions futures track. The futures track is read
from the cache the monitor writes — the dashboard can't scrape DraftKings itself
inside Streamlit, so "Update DK data" drives the monitor in a separate process.
Each track keeps its own pipeline; they're unified only as cards here
(see src/dashboard/cards.py).
"""

import os
import sys
import time
import subprocess
import streamlit as st

from src.pipeline import (
    run_arb_detection,
    run_polymarket_detection,
)
from src.dashboard.cards import (
    from_sports, from_polymarket,
)
from src.dashboard import cache
from config.settings import Settings, project_root

# The dashboard never scrapes DraftKings itself (Streamlit runs in a worker thread and
# Playwright can't launch a browser there on Windows). DK data is produced by the monitor
# in a separate process; the dashboard reads the cache it writes, and the "Update DK data"
# button shells out to that monitor. This window throttles how often that button will
# actually re-scrape, so repeated clicks can't hammer DraftKings. The cache timestamp is
# the shared "last DK pull" clock, so a recent scheduled monitor run counts too.
DK_COOLDOWN_SECS = 2.5 * 3600

# The scraper the "Update DK data" button runs (out-of-process). Covers the full catalog
# so matches line up correctly (a thin scan starves the Kalshi pool and mis-matches boards);
# that makes it a ~5-minute run, which is fine for an occasional, cooldown-gated button.
MONITOR_SCRIPT = os.path.join(project_root, "scripts", "monitor_futures.py")
UPDATE_BUDGET = 30


def _run_monitor(budget: int = UPDATE_BUDGET):
    """Run the futures monitor in its own process (where Playwright works), wait for it
    to write the cache, and return (status, message) with status in {ok, busy, error}.
    This is how the dashboard gets fresh DK data without launching a browser in Streamlit."""
    cmd = [sys.executable, MONITOR_SCRIPT, "--budget", str(budget)]
    try:
        r = subprocess.run(cmd, cwd=str(project_root), capture_output=True,
                           text=True, timeout=900)
    except subprocess.TimeoutExpired:
        return "error", "scraper timed out after 15 minutes"
    if r.returncode == 2:                 # monitor's "another scan is already running"
        return "busy", "another DK scan is already running"
    if r.returncode != 0:
        return "error", (r.stderr or r.stdout or "unknown error").strip()[-400:]
    # Surface the scan's own summary line on success.
    tail = [ln for ln in (r.stdout or "").splitlines() if "priced" in ln or "discovered" in ln]
    return "ok", (tail[-1] if tail else "done")

# Display label -> canonical sport key (same keys The Odds API uses)
SPORTS = {
    "MLB": "baseball_mlb",
    "WNBA": "basketball_wnba",
    "NFL": "americanfootball_nfl",
    "NBA": "basketball_nba",
    "NHL": "icehockey_nhl",
}
DEFAULT_SPORTS = ["MLB", "WNBA", "NFL"]  # in-season as of June 2026

# Edge meter range (fraction). 0% = break-even line; >0 = arbitrage.
EDGE_MIN, EDGE_MAX = -0.06, 0.03

CSS = """
<style>
.arb-wrap { display:grid; grid-template-columns:repeat(auto-fill,minmax(310px,1fr)); gap:12px; }
.arb-card { border:1px solid rgba(128,128,128,0.25); border-radius:12px; padding:14px 16px;
            background:rgba(128,128,128,0.06); }
.arb-card.arb { border-color:#16a34a; box-shadow:0 0 0 1px rgba(22,163,74,0.35); }
.card-head { display:flex; justify-content:space-between; align-items:center; }
.matchup { font-weight:700; font-size:1.05rem; }
.sport-tag { font-size:0.68rem; opacity:0.55; text-transform:uppercase; letter-spacing:0.05em; margin-left:7px; }
.sub { font-size:0.82rem; opacity:0.75; margin:3px 0 0; }
.intel { display:inline-block; font-size:0.62rem; font-weight:700; letter-spacing:0.04em;
         text-transform:uppercase; color:#f59e0b; border:1px solid rgba(245,158,11,0.45);
         border-radius:5px; padding:0 5px; margin-top:6px; }
.livewarn { font-size:0.72rem; color:#f59e0b; background:rgba(245,158,11,0.12);
            border:1px solid rgba(245,158,11,0.4); border-radius:6px; padding:5px 8px; margin-top:8px; }
.edge-pill { font-weight:700; font-size:0.92rem; padding:2px 10px; border-radius:999px; color:#fff; }
.edge-pill.arb { background:#16a34a; } .edge-pill.close { background:#f59e0b; } .edge-pill.none { background:#64748b; }
.meter { position:relative; height:8px; border-radius:999px; background:rgba(128,128,128,0.18); margin:11px 0 13px; }
.meter-zero { position:absolute; top:-3px; bottom:-3px; left:66.7%; width:2px; background:rgba(128,128,128,0.65); }
.meter-fill { position:absolute; top:0; bottom:0; border-radius:999px; }
.meter-fill.arb { background:#16a34a; } .meter-fill.close { background:#f59e0b; } .meter-fill.none { background:#94a3b8; }
.legs { display:flex; flex-direction:column; gap:6px; }
.leg { display:flex; align-items:center; gap:8px; font-size:0.9rem; }
.leg .team { font-weight:600; min-width:46px; }
.leg .src { font-size:0.7rem; padding:1px 7px; border-radius:6px; }
.leg .src.kalshi { background:rgba(124,58,237,0.22); color:#a78bfa; }
.leg .src.book { background:rgba(14,165,233,0.22); color:#38bdf8; }
.leg .odds { opacity:0.75; font-variant-numeric:tabular-nums; }
.leg .stake { margin-left:auto; font-weight:700; color:#16a34a; font-variant-numeric:tabular-nums; }
.leg .stake small { font-weight:500; opacity:0.7; }
.ribbon { font-size:0.7rem; font-weight:700; color:#16a34a; margin-top:8px; }
.when { font-size:0.74rem; opacity:0.7; margin:9px 0 2px; }
details.more { margin-top:9px; font-size:0.8rem; }
details.more summary { cursor:pointer; opacity:0.7; font-size:0.74rem; list-style:none; }
details.more summary:hover { opacity:1; }
details.more summary::-webkit-details-marker { display:none; }
details.more summary::before { content:'▸ '; }
details.more[open] summary::before { content:'▾ '; }
.det { margin-top:8px; padding-top:8px; border-top:1px dashed rgba(128,128,128,0.25); }
.det-row { margin:3px 0; opacity:0.85; }
.det-row b { opacity:0.6; font-weight:600; font-size:0.72rem; text-transform:uppercase; letter-spacing:0.04em; margin-right:6px; }
table.board { width:100%; border-collapse:collapse; margin-top:7px; font-variant-numeric:tabular-nums; }
table.board th { text-align:right; font-size:0.7rem; opacity:0.55; font-weight:600; padding:2px 6px; }
table.board th:first-child { text-align:left; }
table.board td { text-align:right; padding:2px 6px; font-size:0.82rem; }
table.board td:first-child { text-align:left; font-weight:600; }
table.board td.best { color:#16a34a; font-weight:700; }
table.cmp { width:100%; border-collapse:collapse; margin-top:9px; font-variant-numeric:tabular-nums; }
table.cmp th { font-size:0.66rem; opacity:0.55; font-weight:600; padding:2px 6px; text-align:right; }
table.cmp th:first-child { text-align:left; }
table.cmp td { padding:2px 6px; font-size:0.82rem; text-align:right; }
table.cmp td:first-child { text-align:left; font-weight:600; }
table.cmp tr.arb td { color:#16a34a; font-weight:700; }
table.cmp td.lock { opacity:0.7; }
</style>
"""


def _status(view):
    if view.is_arb:
        return "arb"
    return "close" if view.edge > -0.015 else "none"


def _meter(edge):
    span = EDGE_MAX - EDGE_MIN
    z = (0 - EDGE_MIN) / span
    pos = min(max((edge - EDGE_MIN) / span, 0.0), 1.0)
    left, width = (z, pos - z) if edge >= 0 else (pos, z - pos)
    return left * 100, max(width * 100, 0.0)


def _fmt_time(ts):
    """'Thu Jun 18, 7:36 PM' in the viewer's local timezone (cross-platform)."""
    if not ts:
        return "time TBD"
    lt = time.localtime(ts)
    hour = lt.tm_hour % 12 or 12
    ampm = "AM" if lt.tm_hour < 12 else "PM"
    return f"{time.strftime('%a %b', lt)} {lt.tm_mday}, {hour}:{lt.tm_min:02d} {ampm}"


def _relative(ts):
    """Human 'in 3h 12m' / 'live now' relative to now."""
    if not ts:
        return ""
    d = ts - time.time()
    if d < -3 * 3600:
        return "finished"
    if d < 0:
        return "live now"
    h, m = int(d // 3600), int((d % 3600) // 60)
    if h >= 24:
        return f"in {h // 24}d {h % 24}h"
    return f"in {h}h {m:02d}m" if h else f"in {m}m"


def _board(rows):
    """Two-column table per team: Kalshi vs the best book (named), winner green."""
    body = ""
    for row in rows:
        k_cls = " class='best'" if row.kalshi_best else ""
        k_cell = (f"<td{k_cls}>{row.kalshi_american:+.0f}</td>"
                  if row.kalshi_american is not None else "<td>—</td>")
        if row.book_american is not None:
            b_cls = " class='best'" if row.book_best else ""
            b_cell = (f"<td{b_cls}>{row.book_american:+.0f} "
                      f"<small>{row.book_label}</small></td>")
        else:
            b_cell = "<td>—</td>"
        body += f"<tr><td>{row.team}</td>{k_cell}{b_cell}</tr>"
    return (f"<table class='board'><tr><th></th><th>Kalshi</th>"
            f"<th>Best book</th></tr>{body}</table>")


def _details(view):
    """Expandable footer: a price board for sports, the LLM rationale otherwise."""
    if view.board is not None:
        body = (
            f"<div class='det-row'><b>Matchup</b>{view.title}</div>"
            f"<div class='det-row'><b>Starts</b>{_fmt_time(view.start_time)} "
            f"({_relative(view.start_time)})</div>"
            f"{_board(view.board)}"
        )
        summary = "Game details &amp; all prices"
    else:
        conf = f"{view.confidence:.0%}" if view.confidence is not None else "—"
        body = (
            f"<div class='det-row'><b>Match confidence</b>{conf}</div>"
            f"<div class='det-row'><b>Why matched</b>{view.note or '—'}</div>"
        )
        summary = "Match details"
    return (f"<details class='more'><summary>{summary}</summary>"
            f"<div class='det'>{body}</div></details>")


def _cents(p):
    return f"{p * 100:.0f}¢" if p is not None else "—"


def _comp_table(rows):
    """DK-vs-Kalshi per-candidate table for a futures board; arb rows in green."""
    body = ""
    for r in rows:
        cls = " class='arb'" if r.is_arb else ""
        body += (f"<tr{cls}><td>{r.name}</td><td>{_cents(r.dk_yes)}</td>"
                 f"<td>{_cents(r.kalshi_yes)}</td>"
                 f"<td class='lock'>{_cents(r.lock_cost)}</td></tr>")
    return ("<table class='cmp'><tr><th></th><th>DK</th><th>Kalshi</th>"
            f"<th>Lock</th></tr>{body}</table>")


def render_futures_card(view):
    """A DK-Predictions-vs-Kalshi board: a per-candidate comparison, not 2 legs."""
    status = _status(view)
    left, width = _meter(view.edge)
    rows = view.comparison or []
    arbs = [r for r in rows if r.is_arb]
    # Lead with arbs (or the cheapest locks); the rest go in an expander.
    lead = (arbs or rows)[:5]
    rest = [r for r in rows if r not in lead]
    ribbon = ""
    if arbs:
        names = ", ".join(r.name for r in arbs[:3])
        ribbon = f"<div class='ribbon'>✅ {len(arbs)} candidate arb(s): {names}</div>"
    more = (f"<details class='more'><summary>All {len(rows)} candidates</summary>"
            f"<div class='det'>{_comp_table(rows)}</div></details>" if rest else "")
    subtitle = f"<div class='sub'>{view.subtitle}</div>" if view.subtitle else ""
    if view.confidence is not None:  # LLM (semantic-title) match — show why
        why = f" · {view.note}" if view.note else ""
        subtitle += (f"<div class='sub'>🤖 matched by Claude · "
                     f"{view.confidence:.0%}{why}</div>")
    flag = "<div><span class='intel'>detection only</span></div>" if view.detection_only else ""
    return (
        f"<div class='arb-card {status}'>"
        f"<div class='card-head'><span class='matchup'>{view.title}"
        f"<span class='sport-tag'>{view.tag}</span></span>"
        f"<span class='edge-pill {status}'>{view.edge:+.2%}</span></div>"
        f"{subtitle}{flag}"
        f"<div class='meter'><div class='meter-zero'></div>"
        f"<div class='meter-fill {status}' style='left:{left:.1f}%; width:{width:.1f}%'></div></div>"
        f"{ribbon}{_comp_table(lead)}{more}</div>"
    )


def render_card(view):
    if view.comparison is not None:  # futures boards use the comparison-table card
        return render_futures_card(view)
    status = _status(view)
    left, width = _meter(view.edge)
    legs_html = ""
    for leg in view.legs:
        price = f"{leg.implied_prob * 100:.0f}¢" if leg.contracts else f"{leg.implied_prob:.0%}"
        if not view.is_arb:
            action = ""
        elif leg.contracts:  # Kalshi: whole-contract quantity is what you enter
            action = f"<span class='stake'>×{leg.contracts} <small>(${leg.stake:.0f})</small></span>"
        else:               # other venue: dollar stake (cents are fine here)
            action = f"<span class='stake'>${leg.stake:.2f}</span>"
        legs_html += (
            f"<div class='leg'><span class='team'>{leg.label}</span>"
            f"<span class='src {leg.venue_class}'>{leg.venue_label}</span>"
            f"<span class='odds'>{leg.american:+.0f} · {price}</span>{action}</div>"
        )
    ribbon = (
        f"<div class='ribbon'>✅ Lock ${view.profit:.2f} on ${view.staked:.0f} staked "
        f"({view.roi:+.1%})</div>" if view.is_arb else ""
    )
    # A live game's book odds move every play, so different books lag each other and a
    # small "arb" is usually a stale-line artifact that's gone before you can place both
    # legs. Flag it loudly rather than presenting it like a stable pre-game edge.
    live = view.start_time is not None and 0 <= (time.time() - view.start_time) < 4 * 3600
    live_warn = (
        "<div class='livewarn'>⚠ live game — odds move every play; this edge is likely "
        "a stale-line artifact. Verify both legs before betting.</div>"
        if (live and view.is_arb) else ""
    )
    subtitle = f"<div class='sub'>{view.subtitle}</div>" if view.subtitle else ""
    flag = "<div><span class='intel'>detection only</span></div>" if view.detection_only else ""
    when = (f"<div class='when'>🗓 {_fmt_time(view.start_time)} · {_relative(view.start_time)}</div>"
            if view.start_time else "")
    return (
        f"<div class='arb-card {status}'>"
        f"<div class='card-head'><span class='matchup'>{view.title}"
        f"<span class='sport-tag'>{view.tag}</span></span>"
        f"<span class='edge-pill {status}'>{view.edge:+.2%}</span></div>"
        f"{subtitle}{flag}{when}"
        f"<div class='meter'><div class='meter-zero'></div>"
        f"<div class='meter-fill {status}' style='left:{left:.1f}%; width:{width:.1f}%'></div></div>"
        f"<div class='legs'>{legs_html}</div>{ribbon}{live_warn}{_details(view)}</div>"
    )


def _humanize_secs(secs: float) -> str:
    secs = max(0, int(secs))
    if secs < 90:
        return "under a minute"
    if secs < 3600:
        return f"{secs // 60} min"
    h, m = divmod(secs // 60, 60)
    return f"{h}h {m:02d}m" if m else f"{h}h"


def scan(sport_labels, bankroll, include_poly, include_futures):
    """Run every enabled track and return their cards in one edge-sorted list.

    Sports and Polymarket are API-only and refresh live on every call. The DK Predictions
    futures track is read straight from the cache the monitor writes — the dashboard never
    scrapes DraftKings itself (it can't, inside Streamlit on Windows); the "Update DK data"
    button drives the monitor instead. Each track runs only when enabled, and a failure in
    one degrades to a warning instead of taking down the page.
    """
    cards, n_matched, n_arbs, quota, warnings = [], 0, 0, None, []
    steps = len(sport_labels) + int(include_poly) + int(include_futures)
    progress = st.progress(0.0, text="Scanning markets...")
    done = 0

    for label in sport_labels:
        pr = run_arb_detection(SPORTS[label], bankroll)
        cards.extend(from_sports(label, r) for r in pr.results)
        n_matched += pr.n_matched
        n_arbs += len(pr.arbs)
        quota = pr.quota_remaining or quota
        done += 1
        progress.progress(done / steps, text=f"Scanned {label}")

    if include_poly:
        progress.progress(done / steps, text="Scanning Polymarket × Kalshi...")
        live = None
        try:
            pmr = run_polymarket_detection(bankroll=bankroll)
            live = [from_polymarket(r) for r in pmr.results]
        except Exception:
            live = None
        if live is not None:
            cache.save_cards("polymarket", live)
            cards.extend(live)
            n_matched += len(live)
            n_arbs += sum(1 for c in live if c.is_arb)
        else:
            cached, ts = cache.load_cards("polymarket")
            if cached:
                cards.extend(cached)
                n_matched += len(cached)
                n_arbs += sum(1 for c in cached if c.is_arb)
                warnings.append(
                    "Polymarket live scan unavailable — showing the last successful scan "
                    f"from {cache.humanize_age(ts)}.")
        done += 1
        progress.progress(done / steps)

    if include_futures:
        # Cache-only: the monitor (a separate process) does the scraping; here we just
        # display its last scan. Use the "Update DK data" button to refresh it.
        cached, ts = cache.load_cards("futures")
        if cached:
            cards.extend(cached)
            n_matched += len(cached)
            n_arbs += sum(1 for c in cached if c.is_arb)
            warnings.append(
                f"DK Predictions futures × Kalshi: showing the scan from "
                f"{cache.humanize_age(ts)}. Use “Update DK data” in the sidebar to refresh.")
        else:
            warnings.append(
                "DK Predictions futures × Kalshi: no scan cached yet — click “Update DK "
                "data” in the sidebar (or run scripts/monitor_futures.py).")
        done += 1
        progress.progress(done / steps)

    progress.empty()
    cards.sort(key=lambda c: c.edge, reverse=True)
    return {"cards": cards, "n_matched": n_matched, "n_arbs": n_arbs,
            "quota": quota, "warnings": warnings, "ts": time.time()}


def main():
    st.set_page_config(page_title="Betting Market Arb Detector", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    st.title("🎯 Betting Market Arb Detector")
    st.caption("Kalshi vs US sportsbooks, LLM-matched Polymarket, and "
               "DK Predictions futures · cross-venue arbitrage · fees & vig included")

    try:
        Settings.validate()
    except (ValueError, FileNotFoundError) as e:
        st.error(f"⚠️ Configuration error: {e}")
        st.stop()

    st.sidebar.header("Controls")
    sport_labels = st.sidebar.multiselect("Sports", list(SPORTS.keys()), default=DEFAULT_SPORTS)
    bankroll = st.sidebar.number_input("Bankroll ($)", min_value=10.0, value=100.0, step=10.0)

    st.sidebar.markdown("**Extra tracks** · slower, run on refresh")
    have_key = bool(Settings.ANTHROPIC_API_KEY)
    include_poly = st.sidebar.checkbox(
        "Polymarket × Kalshi", value=False, disabled=not have_key)
    if not have_key:
        st.sidebar.caption("Set ANTHROPIC_API_KEY in .env to enable the Polymarket track.")
    include_futures = st.sidebar.checkbox(
        "DK Predictions futures × Kalshi", value=False)
    st.sidebar.caption("Futures is read from the last scan the monitor wrote. Use "
                       "“Update DK data” below to refresh it.")

    refresh = st.sidebar.button("🔄 Refresh", type="primary", use_container_width=True)
    st.sidebar.caption("Sports and Polymarket refresh live (1 Odds API request per sport).")

    # DK data updater. The dashboard can't scrape DraftKings itself (Playwright won't run
    # inside Streamlit on Windows), so this drives the monitor in a separate process.
    update_dk = force_dk = False
    if include_futures:
        st.sidebar.markdown("**DK data**")
        force_dk = st.sidebar.checkbox("Force update (ignore cooldown)", value=False)
        update_dk = st.sidebar.button("⟳ Update DK data (~5 min)", use_container_width=True)

    if not sport_labels and not (include_poly or include_futures):
        st.info("Pick at least one sport or enable a track in the sidebar.")
        return

    # "Update DK data" runs the scraper out-of-process, then rebuilds from the fresh cache.
    # The cooldown stops repeated clicks from hammering DraftKings (force overrides it).
    if update_dk:
        _, dk_ts = cache.load_cards("futures")
        on_cd, remaining = cache.cooldown_state(dk_ts, DK_COOLDOWN_SECS, force=force_dk)
        if on_cd:
            st.sidebar.warning(
                f"DK data is {cache.humanize_age(dk_ts)} old. Next update in "
                f"{_humanize_secs(remaining)}, or tick Force update.")
        else:
            with st.spinner("Running the DK scraper (~5 min, full board coverage). Runs in "
                            "the background; no browser window will open."):
                status, msg = _run_monitor()
            _, new_ts = cache.load_cards("futures")
            if status == "ok" and new_ts != dk_ts:
                st.sidebar.success(f"DK data updated ({msg}).")
                st.session_state.scan = scan(sport_labels, bankroll,
                                             include_poly, include_futures)
                st.session_state.hide_notices = False
            elif status == "busy":
                st.sidebar.info("Another DK scan is already running — try again shortly.")
            elif status == "ok":
                # Ran cleanly but the cache didn't move = nothing got priced (throttled).
                st.sidebar.warning("Scraper ran but priced no boards (likely DraftKings "
                                   "throttling). Showing the previous scan; try again later.")
            else:
                st.sidebar.error(f"DK scraper failed: {msg}")

    # Fetch on first load or when Refresh pressed (avoids burning API quota and
    # re-running the live tracks on every widget interaction).
    if refresh or "scan" not in st.session_state:
        st.session_state.scan = scan(sport_labels, bankroll,
                                     include_poly, include_futures)
        st.session_state.hide_notices = False  # new scan -> show its notices again
    data = st.session_state.scan

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Markets matched", data["n_matched"])
    c2.metric("Arbs found", data["n_arbs"])
    c3.metric("Odds API quota", data["quota"] or "—")
    c4.metric("Last refresh", time.strftime("%H:%M:%S", time.localtime(data["ts"])))

    # Notices are dismissible (handy for a clean screenshot). Dismissing reruns but
    # reuses the cached scan, so it never re-scrapes; a fresh Refresh shows them again.
    notices = data.get("warnings", [])
    if notices and not st.session_state.get("hide_notices", False):
        for w in notices:
            st.warning(f"⚠️ {w}")
        if st.button("✕ Dismiss notices"):
            st.session_state.hide_notices = True
            st.rerun()

    if data["n_arbs"]:
        st.success(f"💰 {data['n_arbs']} live arbitrage opportunity(ies) — green cards below, with stakes.")
    elif data["cards"]:
        st.info("No profitable arbs right now. Cards are sorted by edge — watch the ones nearing the center line.")

    if not data["cards"]:
        st.warning("No matched markets for the current selection (season off, none scheduled, or no overlap).")
        return

    cards = "".join(render_card(c) for c in data["cards"])
    st.markdown(f"<div class='arb-wrap'>{cards}</div>", unsafe_allow_html=True)
    st.caption(
        "Edge = 1 − (sum of effective costs incl. Kalshi fees + sportsbook vig). "
        "Sports cards show the best line across major US books; POLYMARKET cards are "
        "matched by Claude (open the card to see the match confidence and why); "
        "DK × KALSHI futures cards compare every candidate on a board, with a Yes+No "
        "lock cost (under $1 = arb). ×N = buy N whole Kalshi contracts at the ¢ limit "
        "price; other legs show a $ stake. All legs are placed manually — no betting API."
    )


if __name__ == "__main__":
    main()
