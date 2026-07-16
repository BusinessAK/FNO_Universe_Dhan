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
            from src.config.sector_mapping import get_sector
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

        # News Catalysts (Decoupled & Always Present)
        _render_sidebar_catalysts()

        # 5. Database metadata tags
        st.markdown("---")
        st.markdown(f'<div style="font-size:10px;color:#4a5a8a;">'
                    f'DATABASE REGIME: EOD LONGITUDINAL<br>'
                    f'ACTIVE SESSION: {active_date}<br>'
                    f'TOTAL F&O SYMBOLS: {len(all_symbols)}</div>',
                    unsafe_allow_html=True)

    return view_mode, selected_symbol, selected_expiry, strike_pct, active_date, selected_sectors

def _render_sidebar_catalysts():
    st.markdown('<p class="term-header" style="margin-top:20px;">⚡ NEWS CATALYSTS</p>', unsafe_allow_html=True)

    import json as _json
    import os
    from src.ui.cards import render_html
    
    _catalyst_path = os.path.join("data", "compiled", "daily_catalysts.json")
    _catalyst_data: dict = {}
    if os.path.exists(_catalyst_path):
        try:
            with open(_catalyst_path, encoding="utf-8") as _f:
                _catalyst_data = _json.load(_f)
        except Exception:
            pass

    _catalysts = _catalyst_data.get("catalysts", [])

    if not _catalysts:
        st.info(
            "No catalyst data found for this session. "
            "Run `python3 briefing.py` after EOD compile to generate catalyst analysis. "
            "To enable AI-powered analysis: set `GEMINI_API_KEY` and `CATALYST_AI_MODE=true` in `.env`."
        )
    else:
        # 1. Gather all unique symbols for quick inspect selector
        _all_affected_syms = set()
        for _cat in _catalysts:
            for _s in _cat.get("affected_symbols", []):
                if _s:
                    _all_affected_syms.add(_s.strip().upper())
        _sorted_syms = sorted(list(_all_affected_syms))

        # 2. Filter Widgets (Sentiment & Search)
        _col1, _col2 = st.columns(2)
        with _col1:
            _sentiment_filter = st.selectbox(
                "Sentiment",
                options=["ALL", "BULLISH", "BEARISH", "MIXED"],
                key="cat_sentiment_filter",
                label_visibility="collapsed"
            )
        with _col2:
            _search_filter = st.text_input(
                "Search Symbol",
                key="cat_search_filter",
                label_visibility="collapsed",
                placeholder="Search..."
            ).strip().upper()

        # 3. Quick Inspect Ticker Dropdown
        if _sorted_syms:
            def _handle_inspect():
                val = st.session_state.cat_inspect_selector
                if val != "🔍 Quick Inspect...":
                    st.session_state.symbol_selector = val
                    st.session_state.selected_symbol = val
                    st.session_state.view_mode = "📊 SINGLE-STOCK / INDEX DEEP DIVE"
                    st.session_state.cat_inspect_selector = "🔍 Quick Inspect..."

            st.selectbox(
                "Quick Inspect",
                options=["🔍 Quick Inspect..."] + _sorted_syms,
                key="cat_inspect_selector",
                label_visibility="collapsed",
                on_change=_handle_inspect
            )

        # 4. Filter logic
        _filtered_catalysts = []
        for _cat in _catalysts:
            _impact = _cat.get("impact", "NEUTRAL").upper()
            _syms = [s.upper() for s in _cat.get("affected_symbols", [])]
            _secs = [s.upper() for s in _cat.get("affected_sectors", [])]
            _headline = _cat.get("headline", "").upper()

            if _sentiment_filter != "ALL" and _impact != _sentiment_filter:
                continue

            if _search_filter:
                _match = False
                if _search_filter in _headline:
                    _match = True
                for _s in _syms:
                    if _search_filter in _s:
                        _match = True
                for _sec in _secs:
                    if _search_filter in _sec:
                        _match = True
                if not _match:
                    continue

            _filtered_catalysts.append(_cat)

        _mode_label = _catalyst_data.get("mode", "RULES")
        _gen_ts     = _catalyst_data.get("generated", "—")
        _mode_color = "#8b5cf6" if _mode_label == "AI" else "#f59e0b"
        st.markdown(
            f'<div style="font-size:10px; color:#64748b; margin-top: 5px; margin-bottom:12px;">'
            f'Analysis: <span style="color:{_mode_color}; font-weight:bold;">{_mode_label}</span>'
            f'&nbsp;&nbsp;|&nbsp;&nbsp;{len(_filtered_catalysts)} matched</div>',
            unsafe_allow_html=True
        )

        if not _filtered_catalysts:
            st.info("No matching catalysts found.")
        else:
            _impact_cfg = {
                "BULLISH": ("#10b981", "rgba(16,185,129,0.1)", "▲"),
                "BEARISH": ("#ef4444", "rgba(239,68,68,0.1)",  "▼"),
                "MIXED":   ("#f59e0b", "rgba(245,158,11,0.1)", "◆"),
                "NEUTRAL": ("#64748b", "rgba(100,116,139,0.1)","○"),
            }

            _cat_html = ""
            for _cat in _filtered_catalysts:
                _impact  = _cat.get("impact", "NEUTRAL")
                _conf    = _cat.get("confidence", 0.0)
                _syms    = _cat.get("affected_symbols", [])
                _secs    = _cat.get("affected_sectors", [])
                _reason  = _cat.get("reason", "")
                _suggest = _cat.get("suggestion", "")
                _src     = _cat.get("source", "—")
                _pub     = _cat.get("published", "—")
                _headline = _cat.get("headline", "")

                _fc, _bg, _arrow = _impact_cfg.get(_impact, ("#64748b", "rgba(100,116,139,0.1)", "◆"))
                _conf_pct = f"{_conf:.0%}"

                _sym_pills = "".join(
                    f'<span style="background:rgba(255,255,255,0.07); color:#cbd5e1; '
                    f'border:1px solid #334155; padding:1px 5px; border-radius:3px; '
                    f'font-size:9px; font-family:\'JetBrains Mono\'; margin-right:3px; display:inline-block; margin-bottom:3px;">{s}</span>'
                    for s in _syms[:8]
                )
                _sec_pills = "".join(
                    f'<span style="background:rgba(139,92,246,0.1); color:#a78bfa; '
                    f'border:1px solid #4c1d95; padding:1px 5px; border-radius:3px; '
                    f'font-size:9px; margin-right:3px; display:inline-block; margin-bottom:3px;">{s}</span>'
                    for s in _secs[:3]
                )

                _cat_html += f"""
                <details style="background:#050512; border:1px solid #141435; border-left:3px solid {_fc};
                            border-radius:6px; padding:10px; margin-bottom:10px; font-family:'IBM Plex Sans', sans-serif;">
                  <summary style="cursor:pointer; outline:none; display:block; list-style:none;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                      <span style="background:{_bg}; color:{_fc}; border:1px solid {_fc};
                                   padding:1px 5px; border-radius:3px; font-size:9px;
                                   font-weight:bold; font-family:'JetBrains Mono';">
                        {_impact}
                      </span>
                      <span style="color:#64748b; font-size:9px; font-family:'JetBrains Mono';">
                        {_conf_pct} conf. &nbsp;▾
                      </span>
                    </div>
                    <div style="font-size:11px; color:#e2e8f0; font-weight:600; line-height:1.4;">
                      {_arrow} {_headline}
                    </div>
                  </summary>
                  <div style="margin-top:8px; border-top:1px dashed #141435; padding-top:8px;">
                    <div style="font-size:9px; color:#64748b; margin-bottom:6px;">
                      {_src} &nbsp;·&nbsp; {_pub}
                    </div>
                    <div style="margin-bottom:5px; line-height:1.2;">{_sym_pills}{_sec_pills}</div>
                    <div style="font-size:10px; color:#94a3b8; margin-bottom:4px; line-height:1.4;">
                      <strong style="color:#cbd5e1;">Reason:</strong> {_reason}
                    </div>
                    <div style="font-size:10px; color:#94a3b8; background:rgba(139,92,246,0.03);
                                border:1px dashed #221e50; border-radius:4px; padding:4px 6px; margin-top:4px; line-height:1.4;">
                      <strong style="color:#a78bfa;">Suggestion:</strong> {_suggest}
                    </div>
                  </div>
                </details>
                """

            render_html(_cat_html)
