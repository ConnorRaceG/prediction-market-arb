"""
Streamlit dashboard for arb detection.

Run with: streamlit run src/dashboard/app.py
"""

import streamlit as st
from src.pipeline import run_arb_detection
from config.settings import Settings


def main():
    st.set_page_config(page_title="Betting Market Arb Detector", layout="wide")
    st.title("🎯 Betting Market Arb Detector")

    # Sidebar controls
    st.sidebar.header("Controls")
    if st.sidebar.button("🔄 Refresh Markets", key="refresh"):
        st.session_state.last_refresh = True

    # Validate settings
    try:
        Settings.validate()
    except (ValueError, FileNotFoundError) as e:
        st.error(f"⚠️ Configuration error: {e}")
        st.stop()

    # Fetch and display arbs
    st.write("Checking for arbitrage opportunities...")
    arbs = run_arb_detection()

    if arbs:
        st.success(f"✓ Found {len(arbs)} opportunities")
        for i, arb in enumerate(arbs, 1):
            with st.expander(f"Opportunity #{i}: {arb.description}", expanded=True):
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Profit Margin", f"{arb.profit_margin:.2%}")
                with col2:
                    st.write("**Markets:**")
                    for market in arb.markets:
                        st.write(f"  • {market}")
                with col3:
                    st.write("**Stakes:**")
                    for outcome, stake in arb.stakes.items():
                        st.write(f"  {outcome}: ${stake:.2f}")
    else:
        st.info("No profitable arbs found at the moment.")


if __name__ == "__main__":
    main()
