import streamlit as st
import pandas as pd

def render_sidebar(all_symbols: list, selected_date: str, session_history: dict, greeks_df: pd.DataFrame, trading_dates: list) -> tuple:
    """
    Renders Vanguard sidebar controllers and returns (view_mode, selected_symbol, selected_expiry, strike_pct, active_date).
    """
    with st.sidebar:
        st.markdown("## ⚡ VANGUARD")
        st.markdown("<p style='font-size:10px;color:#4a5a8a;margin-top:-10px;'>DEALER INVENTORY INTELLIGENCE</p>", unsafe_allow_html=True)
        st.markdown("---")

        # 1. Mode Selector
        view_mode = st.radio(
            "TERMINAL MODULE",
            ["⚡ VANGUARD SCREENER TERMINAL", "📊 SINGLE-STOCK / INDEX DEEP DIVE"],
            index=0,
            key="view_mode"
        )

        st.markdown("---")

        # 1.5. Dynamic EOD Trading Session Date Selector
        display_options = [pd.to_datetime(d).strftime('%d %b %Y') for d in reversed(trading_dates)]
        try:
            default_idx = trading_dates.index(selected_date)
            display_idx = len(trading_dates) - 1 - default_idx
        except Exception:
            display_idx = 0
            
        selected_display = st.selectbox(
            "ACTIVE SESSION DATE",
            options=display_options,
            index=display_idx,
            key="active_session_date_selector"
        )
        # Map back to raw ISO format string (YYYY-MM-DD)
        chosen_date_idx = len(trading_dates) - 1 - display_options.index(selected_display)
        active_date = trading_dates[chosen_date_idx]

        st.markdown("---")

        # 2. Selected symbol fallback/initialisation
        if "selected_symbol" not in st.session_state:
            st.session_state.selected_symbol = "NIFTY" if "NIFTY" in all_symbols else all_symbols[0]

        selected_symbol = st.selectbox(
            "ACTIVE SYMBOL",
            options=all_symbols,
            index=all_symbols.index(st.session_state.selected_symbol),
            key="symbol_selector"
        )
        st.session_state.selected_symbol = selected_symbol

        # 3. Dynamic Expiry Selector
        selected_expiry = "ALL EXPIRIES"
        if view_mode == "📊 SINGLE-STOCK / INDEX DEEP DIVE" and not greeks_df.empty:
            sym_greeks = greeks_df[greeks_df["SYMBOL"] == selected_symbol.upper()]
            if not sym_greeks.empty:
                unique_expiries = sorted(sym_greeks["EXPIRY_DT"].dropna().unique())
                expiry_options = ["ALL EXPIRIES"]
                expiry_map = {"ALL EXPIRIES": "ALL EXPIRIES"}
                for exp in unique_expiries:
                    try:
                        formatted_exp = pd.to_datetime(exp).strftime('%d %b %Y')
                    except Exception:
                        formatted_exp = str(exp)
                    expiry_options.append(formatted_exp)
                    expiry_map[formatted_exp] = exp

                st.markdown("---")
                selected_expiry_formatted = st.selectbox(
                    "ACTIVE EXPIRY",
                    options=expiry_options,
                    index=0,
                    key=f"expiry_selector_{selected_symbol}"
                )
                selected_expiry = expiry_map[selected_expiry_formatted]

        # 4. Strike percentage range adjustments
        st.markdown("---")
        strike_pct = st.slider("STRIKE RANGE (% ± CMP)", 5, 25, 12, 1)

        # 5. Database metadata tags
        st.markdown("---")
        st.markdown(f'<div style="font-size:10px;color:#4a5a8a;">'
                    f'DATABASE REGIME: EOD LONGITUDINAL<br>'
                    f'ACTIVE SESSION: {active_date}<br>'
                    f'TOTAL F&O SYMBOLS: {len(all_symbols)}</div>',
                    unsafe_allow_html=True)

    return view_mode, selected_symbol, selected_expiry, strike_pct, active_date
