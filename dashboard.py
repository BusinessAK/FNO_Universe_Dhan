"""
Vanguard Institutional EOD Terminal - Main Streamlit Orchestration
"""
import streamlit as st
import pandas as pd
import numpy as np
import json
import os, sys

# Setup package paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
sys.path.insert(0, os.path.dirname(__file__))

# Import Centralized Abstractions & Services Layer
from src.services.database_service import DatabaseService
from src.services.session_cache import SessionCache
from src.services.ui_state import UIStateService
from src.core.market_structure_engine import MarketStructureEngine
from src.core.historical_engine import HistoricalSessionResolver

# Import UI components and logic modules
from src.ui.styling import inject_styles
from src.ui.sidebar import render_sidebar
from src.ui.matrix import render_inventory_matrix
from src.ui.setups_grid import render_setups_grid
from src.ui.cards import (
    render_metric_row, render_alerts, render_intelligence_panel, 
    render_greeks_ledger, sig_colors, render_market_breadth_panel,
    render_daily_changes_panel, render_playbook_card
)
from src.charts import (
    render_wall_migration_chart, render_cumulative_oi_chart,
    render_gex_profile_chart, render_oi_concentration_chart,
    render_iv_skew_chart
)

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Vanguard Institutional EOD Terminal",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Inject modern premium stylesheet
inject_styles()

# Initialize Core Services & Engines
db_service = DatabaseService()
session_cache = SessionCache()
market_engine = MarketStructureEngine()

# ─────────────────────────────────────────────────────────────────────────────
# WIDGET STATE MUTATION CALLBACK
# ─────────────────────────────────────────────────────────────────────────────
def select_stock(symbol):
    """Callback triggered on setup card selection to route to Single Stock Deep Dive."""
    st.session_state.selected_symbol = symbol
    st.session_state.symbol_selector = symbol
    st.session_state.view_mode = "📊 SINGLE-STOCK / INDEX DEEP DIVE"

# ─────────────────────────────────────────────────────────────────────────────
# DATA SEEDING & DEFAULTS LOADERS
# ─────────────────────────────────────────────────────────────────────────────
def load_session_history():
    path = "data/compiled/session_history.json"
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception as e:
            st.error(f"Error parsing session history JSON: {e}")
    return {}

def load_base_signals():
    try:
        signals = pd.read_csv("data/processed/signals.csv")
        greeks  = pd.read_csv("data/processed/greeks.csv")
        return signals, greeks
    except Exception:
        return pd.DataFrame(), pd.DataFrame()

# Seeding state data
session_history = load_session_history()
signals_df, greeks_df = load_base_signals()

if not session_history:
    st.error("⚠ Vanguard EOD Database compiled index (`session_history.json`) is missing. Run `python3 daily_compiler.py` first.")
    st.stop()

# Identify all symbols and trading dates chronologically
all_symbols = sorted(list(session_history.keys()))
trading_dates = []
if all_symbols:
    # Union dates across ALL symbols — avoids silent gaps if any leading symbol
    # was absent from a particular bhav (lot expiry, delisting, etc.)
    all_date_set = set()
    for sym in all_symbols:
        all_date_set.update(session_history[sym].keys())
    trading_dates = sorted(list(all_date_set))

if not trading_dates:
    st.error("⚠ No compiled dates found in session history database.")
    st.stop()

# Instantiate Centralized UI State Manager
ui_state = UIStateService(trading_dates, all_symbols)
ui_state.initialize_defaults()

# Instantiate Historical Session Resolver
resolver = HistoricalSessionResolver(trading_dates[-1] if trading_dates else "")

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR CONTROLLER DECK
# ─────────────────────────────────────────────────────────────────────────────
view_mode, selected_symbol, selected_expiry, strike_pct, active_date = render_sidebar(
    all_symbols, ui_state.selected_date, session_history, greeks_df, trading_dates
)
ui_state.selected_date = active_date
ui_state.selected_symbol = selected_symbol
ui_state.view_mode = view_mode
latest_date = active_date

# ─────────────────────────────────────────────────────────────────────────────
# MODULE 1: VANGUARD SCREENER TERMINAL (Flagship View)
# ─────────────────────────────────────────────────────────────────────────────
if view_mode == "⚡ VANGUARD SCREENER TERMINAL":
    # Screener Header
    st.markdown(f"""
    <div class="title-bar">
      <span style="font-size:24px;color:#fbbf24;">⚡</span>
      <h1>VANGUARD INSTITUTIONAL EOD TERMINAL</h1>
      <span class="sig-badge" style="background:#091c15;color:#10b981;border:1px solid #064e3b;margin-left:15px;">DECISION LAYER ACTIVE</span>
      <span class="ts">DATA REGIME: CHRONOLOGICAL F&O HEATMAP</span>
    </div>
    """, unsafe_allow_html=True)
    
    # ── Global market breadth and alerts loading from DatabaseService ──
    latest_breadth = db_service.get_market_breadth(latest_date)
    if not latest_breadth:
        latest_breadth = {
            "bullish_pct": 50.0, "bearish_pct": 50.0,
            "compression_pct": 0.0, "expansion_pct": 0.0,
            "transition_pct": 0.0, "mean_rev_pct": 100.0,
            "total_symbols": len(all_symbols)
        }
        
    today_changes = db_service.get_daily_changes(latest_date)
    
    # Render premium daily global breadth panels
    render_market_breadth_panel(latest_breadth)
    render_daily_changes_panel(today_changes)
    
    # ── Weekly Expiry Rollover Banner ─────────────────────────────────────────
    # Check if today's session had an index weekly expiry filtered out.
    # We read from any index symbol present in session_history.
    _index_syms = [s for s in ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"] if s in session_history]
    _expiry_filtered = False
    _dropped_dates = ""
    for _isym in _index_syms:
        _m = session_history.get(_isym, {}).get(latest_date, {})
        if _m.get("expiry_filtered", False):
            _expiry_filtered = True
            _dropped_dates = _m.get("dropped_expiry_dates", "")
            break

    if _expiry_filtered:
        _dropped_label = f" ({_dropped_dates})" if _dropped_dates else ""
        st.markdown(f"""
        <div style="
            background: linear-gradient(90deg, rgba(120,80,0,0.25), rgba(251,191,36,0.08));
            border: 1px solid rgba(251,191,36,0.35);
            border-left: 4px solid #fbbf24;
            border-radius: 6px;
            padding: 10px 16px;
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            gap: 12px;
            font-family: 'IBM Plex Sans', sans-serif;
        ">
            <span style="font-size:18px;">🔄</span>
            <div>
                <span style="font-weight:700;color:#fbbf24;font-size:12px;letter-spacing:0.5px;">
                    WEEKLY INDEX EXPIRY ROLLOVER
                </span>
                <span style="color:#a0a0c0;font-size:11px;margin-left:10px;">
                    Expired series stripped from T-1 before delta computation{_dropped_label}
                </span>
                <br>
                <span style="color:#6b7a99;font-size:10px;">
                    ✅ Stock signals unaffected &nbsp;|&nbsp;
                    ✅ Index IFS computed on surviving series only &nbsp;|&nbsp;
                    ✅ Persistence counters preserved
                </span>
            </div>
        </div>
        """, unsafe_allow_html=True)
    # ──────────────────────────────────────────────────────────────────────────

    # Section A - flagships matrix
    st.markdown('<p class="term-header">SECTION A — INSTITUTIONAL INVENTORY MATRIX</p>', unsafe_allow_html=True)
    render_inventory_matrix(all_symbols, session_history, latest_date, trading_dates)

    
    # Section B - setups scanner loading direct from DatabaseService
    categorized_setups = {
        "GAMMA_SQUEEZE": [], "VOLATILITY_COIL": [], "PINCH_ZONE": [], "FLOOR_BOUNCE": [],
        "DEALER_DEFENSE": [], "REGIME_SHIFT": [], "INVENTORY_MIGRATION": [],
        "IV_SPIKE": [], "IV_CRUSH": [], "IV_SKEW_ACCUMULATION": []
    }
    
    setups_df = db_service.get_setups(latest_date)
    for _, r in setups_df.iterrows():
        s_sym = r["symbol"]
        s_type = r["setup_type"]
        s_m = session_history.get(s_sym, {}).get(latest_date, {})
        if s_m and s_type in categorized_setups:
             categorized_setups[s_type].append((s_sym, s_m))
             
    # Sort setups: Volatility Coils and Pinch Zones sorted by Priority Score (Pty) descending; all others sorted by absolute IFS score descending
    for s_type in categorized_setups:
        if s_type in ["VOLATILITY_COIL", "PINCH_ZONE", "IV_SKEW_ACCUMULATION"]:
            categorized_setups[s_type] = sorted(
                categorized_setups[s_type],
                key=lambda x: float(x[1].get("priority_score") or 0.0),
                reverse=True
            )
        else:
            categorized_setups[s_type] = sorted(
                categorized_setups[s_type],
                key=lambda x: abs(float(x[1].get("ifs_score") or 0.0)),
                reverse=True
            )
            
    render_setups_grid(categorized_setups, select_stock, selected_symbol)

# ─────────────────────────────────────────────────────────────────────────────
# MODULE 2: SINGLE-STOCK / INDEX DEEP DIVE (Detailed Chronology)
# ─────────────────────────────────────────────────────────────────────────────
elif view_mode == "📊 SINGLE-STOCK / INDEX DEEP DIVE":
    sym_sessions = session_history.get(selected_symbol, {})
    latest_metrics = sym_sessions.get(latest_date, {})
    ifs_score = float(latest_metrics.get("ifs_score") or 0.0)
    
    # Header badges styling
    _bg, _fc, _bc = sig_colors("bull" if ifs_score > 15 else "bear" if ifs_score < -15 else "neut")
    ring_html = f'<span class="score-ring" style="border-color:{_fc};color:{_fc};">{ifs_score:+.0f}</span>'
    badge_html = f'<span class="sig-badge" style="background:{_bg};color:{_fc};border:1px solid {_bc};">{latest_metrics.get("gamma_regime", "ROTATION")}</span>'
    
    # Format active date and expiry for display
    try:
        active_date_formatted = pd.to_datetime(latest_date).strftime('%d %b %Y')
    except Exception:
        active_date_formatted = str(latest_date)
        
    if selected_expiry != "ALL EXPIRIES":
        try:
            expiry_formatted = pd.to_datetime(selected_expiry).strftime('%d %b %Y')
        except Exception:
            expiry_formatted = str(selected_expiry)
    else:
        expiry_formatted = "ALL EXPIRIES"

    st.markdown(f"""
    <div class="title-bar">
      <span style="font-size:22px;color:#a78bfa;">📊</span>
      <h1>{selected_symbol} DEEP DIVE</h1>
      {ring_html}&nbsp;{badge_html}
      <span class="sig-badge" style="background:#091c15;color:#fbbf24;border:1px solid #78350f;margin-left:10px;">📅 {active_date_formatted}</span>
      <span class="sig-badge" style="background:#091c15;color:#a78bfa;border:1px solid #2e1065;margin-left:5px;">⏳ EXPIRY: {expiry_formatted}</span>
      <span class="ts">VANGUARD INVENTORY CHRONOLOGY LEDGER</span>
    </div>
    """, unsafe_allow_html=True)
    
    col_left, col_right = st.columns([7, 3])
    
    # Check if we are viewing a historical session date. If so, fall back directly to the compiled database values!
    is_historical = resolver.is_historical(latest_date)
    
    # Fetch options chain slice from Session Cache Service
    greeks_slice = session_cache.get_filtered_greeks(greeks_df, selected_symbol)
    if not greeks_slice.empty and selected_expiry != "ALL EXPIRIES":
        greeks_slice = greeks_slice[greeks_slice["EXPIRY_DT"] == selected_expiry].copy()
        
    # Get Decoupled Computed Market Structure State Object
    market_state = market_engine.compute_structure(
        selected_symbol, latest_date, 
        greeks_slice if not is_historical else pd.DataFrame(), 
        latest_metrics
    )
    
    # ── Left Cockpit Panel (Bloomberg cards, Playbook and detailed longitudinal charts) ──
    col_left.markdown('<p class="term-header">KEY MARKET STRUCTURE LEVELS (LATEST CLOSE)</p>', unsafe_allow_html=True)
    render_metric_row(
        market_state.spot, float(latest_metrics.get('spot_change_pct') or 0.0), 
        market_state.call_wall, market_state.put_wall, market_state.gamma_flip, 
        market_state.gex, market_state.pcr, container=col_left
    )
    
    # Actionable Tactical Playbook Sheet (NEW)
    render_playbook_card(latest_metrics.get("playbook", {}), container=col_left)
    
    render_alerts(
        market_state.spot, market_state.call_wall, market_state.put_wall, market_state.gamma_flip, 
        latest_metrics.get("pe_interp", "Neutral"), latest_metrics.get("ce_interp", "Neutral"), 
        latest_metrics.get("suggested_strategy", "Wait for Setup"), latest_metrics=latest_metrics, container=col_left
    )
    
    # Right-hand intelligence panel
    render_intelligence_panel(selected_symbol, latest_metrics, sym_sessions, container=col_right)
    
    # Render longitudinal tabs
    col_left.markdown('<p class="term-header">DETAILED LONGITUDINAL ANALYSIS PANEL</p>', unsafe_allow_html=True)
    tab_chrono, tab_gex, tab_oi, tab_skew, tab_table = col_left.tabs([
        "📅  MONTHLY CHRONOLOGY", "📊  GEX PROFILE", 
        "📈  OI CONCENTRATION", "🌡  IV SKEW", 
        "🔢  GREEKS LEDGER"
    ])
    
    # Monthly Chronology Charts
    with tab_chrono:
        fig_walls = render_wall_migration_chart(sym_sessions)
        fig_cum_oi = render_cumulative_oi_chart(sym_sessions)
        st.plotly_chart(fig_walls, use_container_width=True)
        st.plotly_chart(fig_cum_oi, use_container_width=True)
        
    # GEX Profile Chart
    with tab_gex:
        if not resolver.can_render_chain_charts(latest_date):
            st.warning(resolver.get_session_warning(latest_date))
        else:
            fig_gex = render_gex_profile_chart(greeks_df, selected_symbol, selected_expiry, market_state.spot, market_state.gamma_flip, market_state.call_wall, market_state.put_wall, strike_pct)
            if fig_gex is None:
                st.warning("No GEX data available in system processed files for this symbol.")
            else:
                st.plotly_chart(fig_gex, use_container_width=True)
            
    # OI Concentration Chart
    with tab_oi:
        if not resolver.can_render_chain_charts(latest_date):
            st.warning(resolver.get_session_warning(latest_date))
        else:
            fig_oi = render_oi_concentration_chart(greeks_df, selected_symbol, selected_expiry, market_state.spot, market_state.gamma_flip, market_state.call_wall, market_state.put_wall, strike_pct)
            if fig_oi is None:
                st.warning("No option chain data available for this symbol.")
            else:
                st.plotly_chart(fig_oi, use_container_width=True)
            
    # IV Skew Chart
    with tab_skew:
        if not resolver.can_render_chain_charts(latest_date):
            st.warning(resolver.get_session_warning(latest_date))
        else:
            fig_iv = render_iv_skew_chart(greeks_df, selected_symbol, selected_expiry, market_state.spot, market_state.gamma_flip, market_state.call_wall, market_state.put_wall, strike_pct)
            if fig_iv is None:
                st.warning("IV data unavailable for this symbol.")
            else:
                st.plotly_chart(fig_iv, use_container_width=True)
            
    # Greeks Ledger Table
    with tab_table:
        if not resolver.can_render_greeks_ledger(latest_date):
            st.warning(resolver.get_session_warning(latest_date))
        else:
            st_greeks_filtered = session_cache.get_filtered_greeks(greeks_df, selected_symbol)
            if selected_expiry != "ALL EXPIRIES":
                st_greeks_filtered = st_greeks_filtered[st_greeks_filtered["EXPIRY_DT"] == selected_expiry].copy()
                
            if st_greeks_filtered.empty:
                st.warning("No Greeks record compiled for this ticker.")
            else:
                lo_strike = market_state.spot * (1 - strike_pct / 100)
                hi_strike = market_state.spot * (1 + strike_pct / 100)
                st_greeks_filtered["STRIKE_PR"] = pd.to_numeric(st_greeks_filtered["STRIKE_PR"], errors="coerce")
                st_greeks_filtered = st_greeks_filtered[
                    (st_greeks_filtered["STRIKE_PR"] >= lo_strike) & 
                    (st_greeks_filtered["STRIKE_PR"] <= hi_strike)
                ].sort_values(["STRIKE_PR", "OPTION_TYP"])
                
                render_greeks_ledger(st_greeks_filtered, market_state.spot)

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("""
<hr>
<p style="font-size:10px;color:#2a3a5a;text-align:center;letter-spacing:1px;font-family:'IBM Plex Sans';">
  VANGUARD INSTITUTIONAL TERMINAL · dealer positioning & inventory intelligence · EOD system
</p>
""", unsafe_allow_html=True)
