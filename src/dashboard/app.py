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

SOURCE_LABEL = {"kalshi": "Kalshi", "odds_api": "DraftKings"}
SOURCE_CLASS = {"kalshi": "kalshi", "odds_api": "book"}

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
.ribbon { font-size:0.7rem; font-weight:700; color:#16a34a; margin-top:8px; }
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


def render_card(sport_label, r):
    status = _status(r)
    left, width = _meter(r.edge)
    legs_html = ""
    for leg in r.legs:
        src_cls = SOURCE_CLASS.get(leg.source, "book")
        src_lbl = SOURCE_LABEL.get(leg.source, leg.source)
        stake = f"<span class='stake'>${leg.stake:.2f}</span>" if r.is_arb else ""
        legs_html += (
            f"<div class='leg'><span class='team'>{leg.team}</span>"
            f"<span class='src {src_cls}'>{src_lbl}</span>"
            f"<span class='odds'>{leg.american:+.0f} · {leg.implied_prob:.0%}</span>{stake}</div>"
        )
    ribbon = (
        f"<div class='ribbon'>✅ Lock ${r.profit:.2f} profit on ${r.bankroll:.0f} staked</div>"
        if r.is_arb else ""
    )
    return (
        f"<div class='arb-card {status}'>"
        f"<div class='card-head'><span class='matchup'>{r.game}"
        f"<span class='sport-tag'>{sport_label}</span></span>"
        f"<span class='edge-pill {status}'>{r.edge:+.2%}</span></div>"
        f"<div class='meter'><div class='meter-zero'></div>"
        f"<div class='meter-fill {status}' style='left:{left:.1f}%; width:{width:.1f}%'></div></div>"
        f"<div class='legs'>{legs_html}</div>{ribbon}</div>"
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
    st.caption("Kalshi vs DraftKings · live moneyline arbitrage · fees & vig included")

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
        "Edge = 1 − (sum of effective costs incl. Kalshi fees + DraftKings vig). "
        "Green meter crossing the center line = profitable arb. "
        "Sportsbook legs must be placed manually (no betting API)."
    )


if __name__ == "__main__":
    main()
