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
            ["⚡ VANGUARD SCREENER TERMINAL", "📊 SINGLE-STOCK / INDEX DEEP DIVE", "🔮 WATCHLIST BRIEFING"],
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

        # 2. Selected symbol fallback/initialisation & selector rendering
        if "selected_symbol" not in st.session_state:
            st.session_state.selected_symbol = "NIFTY" if "NIFTY" in all_symbols else all_symbols[0]

        # Sync key from active widget if it exists in session state
        if "symbol_selector" in st.session_state:
            st.session_state.selected_symbol = st.session_state.symbol_selector

        selected_symbol = st.session_state.selected_symbol
        selected_expiry = "ALL EXPIRIES"

        if view_mode == "📊 SINGLE-STOCK / INDEX DEEP DIVE":
            # Restore selectbox state from persistent shadow variable before rendering
            st.session_state.symbol_selector = st.session_state.selected_symbol
            selected_symbol = st.selectbox(
                "ACTIVE SYMBOL",
                options=all_symbols,
                key="symbol_selector"
            )
            st.session_state.selected_symbol = selected_symbol

            # 3. Dynamic Expiry Selector
            if not greeks_df.empty:
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

        # 4. Strike percentage range adjustments (Only for Single Stock Deep Dive)
        if "selected_strike_pct" not in st.session_state:
            st.session_state.selected_strike_pct = 12

        if "sidebar_strike_pct_slider" in st.session_state:
            st.session_state.selected_strike_pct = st.session_state.sidebar_strike_pct_slider

        strike_pct = st.session_state.selected_strike_pct
        if view_mode == "📊 SINGLE-STOCK / INDEX DEEP DIVE":
            st.markdown("---")
            st.session_state.sidebar_strike_pct_slider = st.session_state.selected_strike_pct
            strike_pct = st.slider(
                "STRIKE RANGE (% ± CMP)",
                5, 25,
                value=st.session_state.selected_strike_pct,
                step=1,
                key="sidebar_strike_pct_slider"
            )
            st.session_state.selected_strike_pct = strike_pct

        # 4.5. Sector filter (Only for Screener Terminal)
        if "selected_sector" not in st.session_state:
            st.session_state.selected_sector = "ALL"

        if "sidebar_sector_filter" in st.session_state:
            st.session_state.selected_sector = st.session_state.sidebar_sector_filter

        selected_sectors = [st.session_state.selected_sector]
        if view_mode == "⚡ VANGUARD SCREENER TERMINAL":
            unique_sectors = set()
            from vanguard.config.sector_mapping import get_sector
            for sym in all_symbols:
                sec = get_sector(sym)
                if sec and sec != "Other" and sec != "Index":
                    unique_sectors.add(sec)
            sorted_sectors = sorted(list(unique_sectors))
            
            try:
                sec_index = (["ALL"] + sorted_sectors).index(st.session_state.selected_sector)
            except Exception:
                sec_index = 0

            st.markdown("---")
            st.session_state.sidebar_sector_filter = st.session_state.selected_sector
            chosen_sector = st.selectbox(
                "FILTER SECTOR",
                options=["ALL"] + sorted_sectors,
                index=sec_index,
                key="sidebar_sector_filter"
            )
            st.session_state.selected_sector = chosen_sector
            selected_sectors = [chosen_sector]

        # 5. Database metadata tags
        st.markdown("---")
        st.markdown(f'<div style="font-size:10px;color:#4a5a8a;">'
                    f'DATABASE REGIME: EOD LONGITUDINAL<br>'
                    f'ACTIVE SESSION: {active_date}<br>'
                    f'TOTAL F&O SYMBOLS: {len(all_symbols)}</div>',
                    unsafe_allow_html=True)

    return view_mode, selected_symbol, selected_expiry, strike_pct, active_date, selected_sectors
