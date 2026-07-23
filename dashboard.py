"""
Vanguard Institutional EOD Terminal - Main Streamlit Orchestration
"""
import streamlit as st
import pandas as pd
import json
import os, sys
from typing import Any

# Setup package paths

sys.path.insert(0, os.path.dirname(__file__))

# Import Centralized Abstractions & Services Layer
from vanguard.services.database_service import DatabaseService
from vanguard.services.session_cache import SessionCache
from vanguard.services.ui_state import UIStateService
from vanguard.core.market_structure_engine import MarketStructureEngine
from vanguard.core.historical_engine import HistoricalSessionResolver
from vanguard.core.config import INDEX_SYMBOLS
from vanguard.core.setups import categorize_and_sort

def format_date_safe(value: Any, fmt: str = '%d %b %Y') -> str:
    """Safely format a date or return it as string if parsing fails."""
    try:
        return pd.to_datetime(value).strftime(fmt)
    except Exception:
        return str(value)

# Import UI components and logic modules
from vanguard.ui.styling import inject_styles
from vanguard.ui.sidebar import render_sidebar
from vanguard.ui.matrix import render_inventory_matrix
from vanguard.ui.setups_grid import render_setups_grid, render_structure_flip_watch
from vanguard.ui.cards import (
    render_html, render_metric_row, render_alerts, render_intelligence_panel,
    render_greeks_ledger, sig_colors,
    render_daily_changes_panel, render_playbook_card,
    render_cm_breadth_panel, render_market_breadth_panel
)
from vanguard.ui.watchlist import render_watchlist_briefing
from vanguard.charts import (
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
if "session_cache" not in st.session_state:
    st.session_state.session_cache = SessionCache()
session_cache = st.session_state.session_cache
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
@st.cache_data(show_spinner=False)
def load_session_history(mtime):
    path = "data/compiled/session_history.json"
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None

@st.cache_data(show_spinner=False)
def load_base_signals(signals_mtime, greeks_mtime):
    try:
        signals = pd.read_csv("data/processed/signals.csv")
        greeks  = pd.read_csv("data/processed/greeks.csv")
        return signals, greeks
    except Exception:
        return pd.DataFrame(), pd.DataFrame()

# Seeding state data
session_history_path = "data/compiled/session_history.json"
session_history_mtime = os.path.getmtime(session_history_path) if os.path.exists(session_history_path) else 0
session_history = load_session_history(session_history_mtime)

signals_path = "data/processed/signals.csv"
greeks_path = "data/processed/greeks.csv"
signals_mtime = os.path.getmtime(signals_path) if os.path.exists(signals_path) else 0
greeks_mtime = os.path.getmtime(greeks_path) if os.path.exists(greeks_path) else 0
signals_df, greeks_df = load_base_signals(signals_mtime, greeks_mtime)

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
view_mode, selected_symbol, selected_expiry, strike_pct, active_date, selected_sectors = render_sidebar(
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
    try:
        latest_breadth = db_service.get_market_breadth(latest_date)
    except Exception:
        latest_breadth = {}

    if not latest_breadth:
        latest_breadth = {
            "bullish_pct": 50.0, "bearish_pct": 50.0,
            "compression_pct": 0.0, "expansion_pct": 0.0,
            "transition_pct": 0.0, "mean_rev_pct": 100.0,
            "total_symbols": len(all_symbols)
        }
        
    today_changes = db_service.get_daily_changes(latest_date)

    # Load CM price breadth (full NSE EQ universe)
    try:
        latest_cm_breadth = db_service.get_cm_breadth(latest_date)
    except Exception:
        latest_cm_breadth = {}

    # Render F&O structural change alerts
    render_daily_changes_panel(today_changes)

    # Render F&O structural breadth register
    render_market_breadth_panel(latest_breadth)

    # Render Cash Market Price Breadth (separate from F&O breadth)
    render_cm_breadth_panel(latest_cm_breadth, anchor_date=db_service.get_cm_first_date())
    
    # ── Weekly Expiry Rollover Banner ─────────────────────────────────────────
    # Check if today's session had an index weekly expiry filtered out.
    # We read from any index symbol present in session_history.
    _index_syms = [s for s in INDEX_SYMBOLS if s in session_history]
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

    tab_setups, tab_matrix = st.tabs(["🚀 HIGH CONVICTION SETUPS", "📊 FULL INVENTORY MATRIX"])
    
    with tab_setups:
        st.markdown('<p class="term-header">CONFLUENCE-FILTERED ACTIONABLE SIGNALS</p>', unsafe_allow_html=True)
        # Load filtered setups scanner loading direct from DatabaseService
        setups_df = db_service.get_setups(latest_date)
        
        if setups_df.empty:
            st.info("No high-conviction setups found for today that pass the strict confluence filter (Momentum + Breadth + GEX Alignment).")
        else:
            categorized_setups = categorize_and_sort(setups_df, session_history, latest_date)
            render_setups_grid(categorized_setups, select_stock, selected_symbol, selected_sectors, active_date=latest_date, session_history=session_history)
            
    with tab_matrix:
        st.markdown('<p class="term-header">INSTITUTIONAL INVENTORY MATRIX (F&O UNIVERSE)</p>', unsafe_allow_html=True)
        render_inventory_matrix(all_symbols, session_history, latest_date, trading_dates, selected_sectors)


# ─────────────────────────────────────────────────────────────────────────────
# MODULE 2: SINGLE-STOCK / INDEX DEEP DIVE (Detailed Chronology)
# ─────────────────────────────────────────────────────────────────────────────
elif view_mode == "📊 SINGLE-STOCK / INDEX DEEP DIVE":
    sym_sessions = session_history.get(selected_symbol, {})
    latest_metrics = sym_sessions.get(latest_date, {})

    # ── Fallback: symbol dropped from F&O / no data for latest_date ──────────
    # Some symbols are removed from NSE's F&O segment (e.g. lot-size exclusions,
    # delistings). The compiler stops writing new entries for them, so
    # sym_sessions.get(latest_date) returns {} and every metric shows 0.0.
    # Fall back to the most recent date we DO have data for and warn the user.
    _sym_stale_date = None
    if not latest_metrics and sym_sessions:
        _sym_stale_date = max(sym_sessions.keys())
        latest_metrics = sym_sessions.get(_sym_stale_date, {})
    # ─────────────────────────────────────────────────────────────────────────

    ifs_score = float(latest_metrics.get("ifs_score") or 0.0)
    
    # Header badges styling
    _bg, _fc, _bc = sig_colors("bull" if ifs_score > 15 else "bear" if ifs_score < -15 else "neut")
    ring_html = f'<span class="score-ring" style="border-color:{_fc};color:{_fc};">{ifs_score:+.0f}</span>'
    badge_html = f'<span class="sig-badge" style="background:{_bg};color:{_fc};border:1px solid {_bc};">{latest_metrics.get("gamma_regime", "ROTATION")}</span>'
    
    struct_bias = latest_metrics.get("structural_bias", "UNKNOWN")
    struct_color = "#10b981" if "Expansion" in struct_bias else "#a78bfa" if "Compression" in struct_bias else "#38bdf8"
    struct_html = f'<span class="sig-badge" style="background:rgba(255,255,255,0.05);color:{struct_color};border:1px solid {struct_color};margin-left:5px;">{struct_bias.upper()}</span>'
    
    # Format active date and expiry for display
    active_date_formatted = format_date_safe(latest_date)
        
    if selected_expiry != "ALL EXPIRIES":
        expiry_formatted = format_date_safe(selected_expiry)
    else:
        expiry_formatted = "ALL EXPIRIES"

    render_html(f"""
    <div class="title-bar">
      <span style="font-size:22px;color:#a78bfa;">📊</span>
      <h1>{selected_symbol} DEEP DIVE</h1>
      {ring_html}&nbsp;{badge_html}{struct_html}
      <span class="sig-badge" style="background:#091c15;color:#fbbf24;border:1px solid #78350f;margin-left:10px;">📅 {active_date_formatted}</span>
      <span class="sig-badge" style="background:#091c15;color:#a78bfa;border:1px solid #2e1065;margin-left:5px;">⏳ EXPIRY: {expiry_formatted}</span>
      <span class="ts">VANGUARD INVENTORY CHRONOLOGY LEDGER</span>
    </div>
    """)
    
    # Show stale-data warning if this symbol has no recent F&O data
    if _sym_stale_date:
        st.warning(
            f"⚠️ **{selected_symbol}** has no F&O data after **{_sym_stale_date}** — "
            f"it may have been removed from NSE's derivatives segment. "
            f"Showing last available session ({_sym_stale_date}).",
            icon="🚫"
        )

    col_left, col_right = st.columns([7, 3])
    
    # Check if we are viewing a historical session date. If so, fall back directly to the compiled database values!
    is_historical = resolver.is_historical(latest_date)
    
    # Fetch options chain slice from Session Cache Service
    greeks_slice = session_cache.get_filtered_greeks(greeks_df, selected_symbol, token=greeks_mtime)
    if not greeks_slice.empty and selected_expiry != "ALL EXPIRIES":
        greeks_slice = greeks_slice[greeks_slice["EXPIRY_DT"] == selected_expiry].copy()
        
    # If looking at a historical date, we explicitly suppress live chain rendering by passing an empty dataframe.
    # The market engine will automatically fall back to the pre-compiled database metrics.
    active_chain_data = pd.DataFrame() if is_historical else greeks_slice
    
    # Get Decoupled Computed Market Structure State Object
    market_state = market_engine.compute_structure(
        selected_symbol, latest_date, 
        active_chain_data, 
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
    playbook_to_render = dict(latest_metrics.get("playbook", {}))
    ifs_score = float(latest_metrics.get("ifs_score") or 0.0)
    
    # Dynamic Playbook Override to prevent naive backend contradictions
    # (walls must exist — a missing wall is 0.0 and would always compare true)
    if market_state.call_wall > 0 and market_state.spot > market_state.call_wall and ifs_score > 30:
        playbook_to_render["bias"] = "Bullish Squeeze Breakout"
        playbook_to_render["expected_behavior"] = "Gamma Squeeze Expansion"
        playbook_to_render["dealer_behavior"] = "Forced Delta Buying (Short Gamma)"
    elif market_state.put_wall > 0 and market_state.spot < market_state.put_wall and ifs_score < -30:
        playbook_to_render["bias"] = "Bearish Cascade Breakdown"
        playbook_to_render["expected_behavior"] = "Support Floor Collapse"
        playbook_to_render["dealer_behavior"] = "Forced Delta Selling (Short Gamma)"
        
    render_playbook_card(playbook_to_render, container=col_left)
    
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
            st_greeks_filtered = session_cache.get_filtered_greeks(greeks_df, selected_symbol, token=greeks_mtime)
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

elif view_mode == "🔮 WATCHLIST BRIEFING":
    render_watchlist_briefing(latest_date, db_service)

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("""
<hr>
<p style="font-size:10px;color:#2a3a5a;text-align:center;letter-spacing:1px;font-family:'IBM Plex Sans';">
  VANGUARD INSTITUTIONAL TERMINAL · dealer positioning & inventory intelligence · EOD system
</p>
""", unsafe_allow_html=True)
