"""
Streamlit dashboard for arb detection.

Run with:  streamlit run src/dashboard/app.py
"""

import time
import streamlit as st

from src.pipeline import run_arb_detection
from config.settings import Settings

# Display label -> canonical sport key (same keys The Odds API uses)
SPORTS = {
    "MLB": "baseball_mlb",
    "WNBA": "basketball_wnba",
    "NFL": "americanfootball_nfl",
    "NBA": "basketball_nba",
    "NHL": "icehockey_nhl",
}
DEFAULT_SPORTS = ["MLB", "WNBA", "NFL"]  # in-season as of June 2026

SOURCE_LABEL = {
    "kalshi": "Kalshi", "odds_api": "Sportsbook",
    "draftkings": "DraftKings", "fanduel": "FanDuel", "betmgm": "BetMGM",
    "betrivers": "BetRivers", "williamhill_us": "Caesars", "caesars": "Caesars",
    "espnbet": "ESPN BET", "fanatics": "Fanatics", "ballybet": "Bally",
    "hardrockbet": "Hard Rock",
}
SOURCE_CLASS = {"kalshi": "kalshi"}  # everything else renders as a 'book' chip

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
</style>
"""


def _status(r):
    if r.is_arb:
        return "arb"
    return "close" if r.edge > -0.015 else "none"


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


def _am_decimal(american):
    """Decimal payout for American odds — higher is the better line."""
    return 1 + (american / 100 if american > 0 else 100 / abs(american))


def _board(r):
    """Two-column table per team: Kalshi vs the best book (named), winner green."""
    by_team = {}  # team -> {'kalshi': american, 'book': (american, book_key)}
    for q in (r.quotes or []):
        slot = by_team.setdefault(q.team, {})
        if q.source == "kalshi":
            slot["kalshi"] = q.american
        else:  # keep the best book line for the team
            cur = slot.get("book")
            if cur is None or _am_decimal(q.american) > _am_decimal(cur[0]):
                slot["book"] = (q.american, q.source)
    best_src = {leg.team: leg.source for leg in r.legs}
    rows = ""
    for team, s in by_team.items():
        k = s.get("kalshi")
        k_cls = " class='best'" if best_src.get(team) == "kalshi" else ""
        k_cell = f"<td{k_cls}>{k:+.0f}</td>" if k is not None else "<td>—</td>"
        b = s.get("book")
        if b:
            b_am, b_key = b
            b_cls = " class='best'" if best_src.get(team) == b_key else ""
            b_cell = (f"<td{b_cls}>{b_am:+.0f} "
                      f"<small>{SOURCE_LABEL.get(b_key, b_key)}</small></td>")
        else:
            b_cell = "<td>—</td>"
        rows += f"<tr><td>{team}</td>{k_cell}{b_cell}</tr>"
    return (f"<table class='board'><tr><th></th><th>Kalshi</th>"
            f"<th>Best book</th></tr>{rows}</table>")


def render_card(sport_label, r):
    status = _status(r)
    left, width = _meter(r.edge)
    legs_html = ""
    for leg in r.legs:
        src_cls = SOURCE_CLASS.get(leg.source, "book")
        src_lbl = SOURCE_LABEL.get(leg.source, leg.source)
        price = f"{leg.implied_prob * 100:.0f}¢" if leg.contracts else f"{leg.implied_prob:.0%}"
        if not r.is_arb:
            action = ""
        elif leg.contracts:  # Kalshi: whole-contract quantity is what you enter
            action = f"<span class='stake'>×{leg.contracts} <small>(${leg.stake:.0f})</small></span>"
        else:               # Sportsbook: dollar stake (cents are fine here)
            action = f"<span class='stake'>${leg.stake:.2f}</span>"
        legs_html += (
            f"<div class='leg'><span class='team'>{leg.team}</span>"
            f"<span class='src {src_cls}'>{src_lbl}</span>"
            f"<span class='odds'>{leg.american:+.0f} · {price}</span>{action}</div>"
        )
    ribbon = (
        f"<div class='ribbon'>✅ Lock ${r.profit:.2f} on ${r.staked:.0f} staked "
        f"({r.roi:+.1%})</div>" if r.is_arb else ""
    )
    when = f"<div class='when'>🗓 {_fmt_time(r.start_time)} · {_relative(r.start_time)}</div>"
    details = (
        "<details class='more'><summary>Game details &amp; all prices</summary>"
        "<div class='det'>"
        f"<div class='det-row'><b>Matchup</b>{r.matchup_full or r.game}</div>"
        f"<div class='det-row'><b>Starts</b>{_fmt_time(r.start_time)} ({_relative(r.start_time)})</div>"
        f"{_board(r)}</div></details>"
    )
    return (
        f"<div class='arb-card {status}'>"
        f"<div class='card-head'><span class='matchup'>{r.game}"
        f"<span class='sport-tag'>{sport_label}</span></span>"
        f"<span class='edge-pill {status}'>{r.edge:+.2%}</span></div>"
        f"{when}"
        f"<div class='meter'><div class='meter-zero'></div>"
        f"<div class='meter-fill {status}' style='left:{left:.1f}%; width:{width:.1f}%'></div></div>"
        f"<div class='legs'>{legs_html}</div>{ribbon}{details}</div>"
    )


def scan(sport_labels, bankroll):
    items, n_games, n_arbs, quota = [], 0, 0, None
    progress = st.progress(0.0, text="Fetching live odds...")
    for i, label in enumerate(sport_labels):
        pr = run_arb_detection(SPORTS[label], bankroll)
        items.extend((label, r) for r in pr.results)
        n_games += pr.n_matched
        n_arbs += len(pr.arbs)
        quota = pr.quota_remaining or quota
        progress.progress((i + 1) / len(sport_labels), text=f"Scanned {label}")
    progress.empty()
    items.sort(key=lambda x: x[1].edge, reverse=True)
    return {"items": items, "n_games": n_games, "n_arbs": n_arbs,
            "quota": quota, "ts": time.time()}


def main():
    st.set_page_config(page_title="Betting Market Arb Detector", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    st.title("🎯 Betting Market Arb Detector")
    st.caption("Kalshi vs major US sportsbooks · live moneyline arbitrage · fees & vig included")

    try:
        Settings.validate()
    except (ValueError, FileNotFoundError) as e:
        st.error(f"⚠️ Configuration error: {e}")
        st.stop()

    st.sidebar.header("Controls")
    sport_labels = st.sidebar.multiselect("Sports", list(SPORTS.keys()), default=DEFAULT_SPORTS)
    bankroll = st.sidebar.number_input("Bankroll ($)", min_value=10.0, value=100.0, step=10.0)
    refresh = st.sidebar.button("🔄 Refresh", type="primary", use_container_width=True)
    st.sidebar.caption("Each sport = 1 Odds API request per refresh.")

    if not sport_labels:
        st.info("Pick at least one sport in the sidebar.")
        return

    # Fetch on first load or when Refresh pressed (avoids burning API quota)
    if refresh or "scan" not in st.session_state:
        st.session_state.scan = scan(sport_labels, bankroll)
    data = st.session_state.scan

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Games matched", data["n_games"])
    c2.metric("Arbs found", data["n_arbs"])
    c3.metric("Odds API quota", data["quota"] or "—")
    c4.metric("Last refresh", time.strftime("%H:%M:%S", time.localtime(data["ts"])))

    if data["n_arbs"]:
        st.success(f"💰 {data['n_arbs']} live arbitrage opportunity(ies) — green cards below, with stakes.")
    elif data["items"]:
        st.info("No profitable arbs right now. Cards are sorted by edge — watch the ones nearing the center line.")

    if not data["items"]:
        st.warning("No matched games for the selected sports (season off or none scheduled).")
        return

    cards = "".join(render_card(label, r) for label, r in data["items"])
    st.markdown(f"<div class='arb-wrap'>{cards}</div>", unsafe_allow_html=True)
    st.caption(
        "Edge = 1 − (sum of effective costs incl. Kalshi fees + sportsbook vig). "
        "Each book leg shows the **best line across major US books** (named on the card). "
        "Green meter crossing the center line = profitable arb. "
        "**×N = buy N whole Kalshi contracts** at the ¢ limit price (that's the "
        "number you enter in the app); sportsbook legs show a $ stake. "
        "All legs are placed manually — no betting API."
    )


if __name__ == "__main__":
    main()
