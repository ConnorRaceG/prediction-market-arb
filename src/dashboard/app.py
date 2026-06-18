"""
Streamlit dashboard for arb detection.

Run with:  streamlit run src/dashboard/app.py
"""

import time
import pandas as pd
import streamlit as st

from src.pipeline import run_arb_detection
from config.settings import Settings

SPORTS = {
    "MLB (Baseball)": "baseball_mlb",
    "NBA (Basketball)": "basketball_nba",
}


def main():
    st.set_page_config(page_title="Betting Market Arb Detector", layout="wide")
    st.title("🎯 Betting Market Arb Detector")
    st.caption("Kalshi vs DraftKings · live moneyline arbitrage (fees included)")

    # ---- Config check ----
    try:
        Settings.validate()
    except (ValueError, FileNotFoundError) as e:
        st.error(f"⚠️ Configuration error: {e}")
        st.stop()

    # ---- Sidebar controls ----
    st.sidebar.header("Controls")
    sport_label = st.sidebar.selectbox("Sport", list(SPORTS.keys()))
    bankroll = st.sidebar.number_input("Bankroll ($)", min_value=10.0, value=100.0, step=10.0)
    refresh = st.sidebar.button("🔄 Refresh Markets", type="primary", use_container_width=True)

    # Fetch on first load or when Refresh is pressed (avoids burning API quota)
    if refresh or "pr" not in st.session_state:
        with st.spinner("Fetching live odds from Kalshi & DraftKings..."):
            st.session_state.pr = run_arb_detection(SPORTS[sport_label], bankroll)
            st.session_state.sport_label = sport_label
            st.session_state.bankroll = bankroll

    pr = st.session_state.pr

    # ---- Status row ----
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Games matched", pr.n_matched)
    c2.metric("Arbs found", len(pr.arbs))
    c3.metric("Odds API quota left", pr.quota_remaining or "—")
    c4.metric("Last refresh", time.strftime("%H:%M:%S", time.localtime(pr.timestamp)))

    if pr.n_matched == 0:
        st.info(
            f"No games found for {st.session_state.get('sport_label', sport_label)} right now "
            "(the season may be off, or no games are scheduled today)."
        )
        return

    # ---- Arbs ----
    st.subheader("Arbitrage Opportunities")
    if pr.arbs:
        for r in pr.arbs:
            with st.expander(f"✅ {r.game} — {r.roi:+.2%} ROI (${r.profit:.2f} on ${r.bankroll:.0f})",
                             expanded=True):
                for leg in r.legs:
                    st.write(
                        f"**Bet ${leg.stake:.2f} on {leg.team}** at **{leg.source}** "
                        f"({leg.american:+.0f}, implied {leg.implied_prob:.1%}, "
                        f"effective cost {leg.effective_cost:.1%})"
                    )
    else:
        st.info("No profitable arbs right now. The closest games are below — watch the edge column.")

    # ---- All matched games table ----
    st.subheader("All Matched Games")
    rows = []
    for r in pr.results:
        row = {
            "Game": r.game,
            "Edge": f"{r.edge:+.2%}",
            "ROI": f"{r.roi:+.2%}",
            "Arb?": "✅" if r.is_arb else "",
        }
        for leg in r.legs:
            row[f"{leg.team}"] = f"{leg.source[:4]} {leg.american:+.0f}"
        rows.append(row)
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.caption(
        "Edge = 1 − (sum of effective costs incl. fees). Positive edge = arbitrage. "
        "Kalshi trading fees and DraftKings vig are both included. "
        "Sportsbook legs must be placed manually (no betting API exists)."
    )


if __name__ == "__main__":
    main()
