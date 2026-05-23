"""
Vanguard Institutional EOD Terminal - Main Streamlit Orchestration
"""
import streamlit as st
import pandas as pd
import numpy as np
import json
import os, sys
import duckdb

# Setup package paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
sys.path.insert(0, os.path.dirname(__file__))

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
    trading_dates = sorted(list(session_history[all_symbols[0]].keys()))

if not trading_dates:
    st.error("⚠ No compiled dates found in session history database.")
    st.stop()

if "selected_date" not in st.session_state:
    st.session_state.selected_date = trading_dates[-1]

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR CONTROLLER DECK
# ─────────────────────────────────────────────────────────────────────────────
view_mode, selected_symbol, selected_expiry, strike_pct, active_date = render_sidebar(
    all_symbols, st.session_state.selected_date, session_history, greeks_df, trading_dates
)
st.session_state.selected_date = active_date
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
    
    # ── EOD-Only global breadth and alerts loading from DuckDB ──
    latest_breadth = {
        "bullish_pct": 50.0, "bearish_pct": 50.0,
        "compression_pct": 0.0, "expansion_pct": 0.0,
        "transition_pct": 0.0, "mean_rev_pct": 100.0,
        "total_symbols": len(all_symbols)
    }
    today_changes = []
    
    db_path = "data/compiled/vanguard.duckdb"
    if os.path.exists(db_path):
        try:
            conn = duckdb.connect(db_path)
            res_b = conn.execute("SELECT * FROM daily_market_breadth WHERE date = ?", [latest_date]).df()
            if not res_b.empty:
                latest_breadth = res_b.iloc[0].to_dict()
            
            res_c = conn.execute("SELECT * FROM daily_changes WHERE date = ?", [latest_date]).df()
            if not res_c.empty:
                today_changes = res_c.to_dict(orient="records")
            conn.close()
        except Exception:
            pass
            
    # Render premium daily global breadth panels
    render_market_breadth_panel(latest_breadth)
    render_daily_changes_panel(today_changes)
    
    # Section A - flagships matrix
    st.markdown('<p class="term-header">SECTION A — INSTITUTIONAL INVENTORY MATRIX</p>', unsafe_allow_html=True)
    render_inventory_matrix(all_symbols, session_history, latest_date, trading_dates)
    
    # Section B - setups scanner loading direct from DuckDB setups registry
    categorized_setups = {
        "GAMMA_SQUEEZE": [], "VOLATILITY_COIL": [], "FLOOR_BOUNCE": [],
        "DEALER_DEFENSE": [], "REGIME_SHIFT": [], "INVENTORY_MIGRATION": []
    }
    if os.path.exists(db_path):
        try:
            conn = duckdb.connect(db_path)
            setups_df = conn.execute("SELECT * FROM daily_setups WHERE date = ? AND setup_type != 'NONE'", [latest_date]).df()
            conn.close()
            for _, r in setups_df.iterrows():
                s_sym = r["symbol"]
                s_type = r["setup_type"]
                s_m = session_history.get(s_sym, {}).get(latest_date, {})
                if s_m and s_type in categorized_setups:
                     categorized_setups[s_type].append((s_sym, s_m))
            # Sort setups: Volatility Coils sorted by Priority Score (Pty) descending; all others sorted by absolute IFS score descending
            for s_type in categorized_setups:
                if s_type == "VOLATILITY_COIL":
                    categorized_setups[s_type] = sorted(
                        categorized_setups[s_type],
                        key=lambda x: x[1].get("priority_score", 0.0),
                        reverse=True
                    )
                else:
                    categorized_setups[s_type] = sorted(
                        categorized_setups[s_type],
                        key=lambda x: abs(x[1].get("ifs_score", 0.0)),
                        reverse=True
                    )
        except Exception:
            pass
            
    render_setups_grid(categorized_setups, select_stock)

# ─────────────────────────────────────────────────────────────────────────────
# MODULE 2: SINGLE-STOCK / INDEX DEEP DIVE (Detailed Chronology)
# ─────────────────────────────────────────────────────────────────────────────
else:
    sym_sessions = session_history.get(selected_symbol, {})
    latest_metrics = sym_sessions.get(latest_date, {})
    ifs_score = latest_metrics.get("ifs_score", 0.0)
    
    # Header badges styling
    _bg, _fc, _bc = sig_colors("bull" if ifs_score > 15 else "bear" if ifs_score < -15 else "neut")
    ring_html = f'<span class="score-ring" style="border-color:{_fc};color:{_fc};">{ifs_score:+.0f}</span>'
    badge_html = f'<span class="sig-badge" style="background:{_bg};color:{_fc};border:1px solid {_bc};">{latest_metrics.get("gamma_regime", "ROTATION")}</span>'
    
    st.markdown(f"""
    <div class="title-bar">
      <span style="font-size:22px;color:#a78bfa;">📊</span>
      <h1>{selected_symbol} DEEP DIVE</h1>
      {ring_html}&nbsp;{badge_html}
      <span class="ts">VANGUARD INVENTORY CHRONOLOGY LEDGER</span>
    </div>
    """, unsafe_allow_html=True)
    
    col_left, col_right = st.columns([7, 3])
    
    # Check if we are viewing a historical session date. If so, fall back directly to the compiled database values!
    is_historical = (latest_date != trading_dates[-1])
    
    sym_greeks = greeks_df[greeks_df["SYMBOL"] == selected_symbol.upper()]
    if not sym_greeks.empty and not is_historical:
        if selected_expiry != "ALL EXPIRIES":
            exp_greeks = sym_greeks[sym_greeks["EXPIRY_DT"] == selected_expiry].copy()
        else:
            exp_greeks = sym_greeks.copy()
            
        if not exp_greeks.empty:
            cmp_val = float(exp_greeks["SPOT"].iloc[0]) if "SPOT" in exp_greeks.columns and not pd.isna(exp_greeks["SPOT"].iloc[0]) else latest_metrics.get("spot_close", 0.0)
            
            exp_greeks["GEX"] = pd.to_numeric(exp_greeks["GEX"], errors="coerce")
            exp_greeks["STRIKE_PR"] = pd.to_numeric(exp_greeks["STRIKE_PR"], errors="coerce")
            exp_greeks["OPEN_INT"] = pd.to_numeric(exp_greeks["OPEN_INT"], errors="coerce")
            
            ce_gex = exp_greeks[exp_greeks['OPTION_TYP'] == 'CE'].groupby('STRIKE_PR')['GEX'].sum()
            pe_gex = exp_greeks[exp_greeks['OPTION_TYP'] == 'PE'].groupby('STRIKE_PR')['GEX'].sum().abs()
            
            cw_val = ce_gex.idxmax() if not ce_gex.empty and not ce_gex.isna().all() else latest_metrics.get("call_wall", 0.0)
            pw_val = pe_gex.idxmax() if not pe_gex.empty and not pe_gex.isna().all() else latest_metrics.get("put_wall", 0.0)
            
            overlap = pd.concat([ce_gex, pe_gex], axis=1).min(axis=1)
            gf_val = overlap.idxmax() if not overlap.empty and not overlap.isna().all() else latest_metrics.get("gamma_flip", 0.0)
            
            gex_val = exp_greeks['GEX'].sum()
            
            ce_oi = exp_greeks[exp_greeks['OPTION_TYP'] == 'CE']['OPEN_INT'].sum()
            pe_oi = exp_greeks[exp_greeks['OPTION_TYP'] == 'PE']['OPEN_INT'].sum()
            pcr_val = pe_oi / ce_oi if ce_oi > 0 else latest_metrics.get("pcr", 0.0)
        else:
            cmp_val = latest_metrics.get("spot_close", 0.0)
            cw_val = latest_metrics.get("call_wall", 0.0)
            pw_val = latest_metrics.get("put_wall", 0.0)
            gf_val = latest_metrics.get("gamma_flip", 0.0)
            gex_val = latest_metrics.get("gex", 0.0)
            pcr_val = latest_metrics.get("pcr", 0.0)
    else:
        cmp_val = latest_metrics.get("spot_close", 0.0)
        cw_val = latest_metrics.get("call_wall", 0.0)
        pw_val = latest_metrics.get("put_wall", 0.0)
        gf_val = latest_metrics.get("gamma_flip", 0.0)
        gex_val = latest_metrics.get("gex", 0.0)
        pcr_val = latest_metrics.get("pcr", 0.0)
    
    # ── Left Cockpit Panel (Bloomberg cards, Playbook and detailed longitudinal charts) ──
    col_left.markdown('<p class="term-header">KEY MARKET STRUCTURE LEVELS (LATEST CLOSE)</p>', unsafe_allow_html=True)
    render_metric_row(cmp_val, latest_metrics.get('spot_change_pct', 0.0), cw_val, pw_val, gf_val, gex_val, pcr_val, container=col_left)
    
    # Actionable Tactical Playbook Sheet (NEW)
    render_playbook_card(latest_metrics.get("playbook", {}), container=col_left)
    
    render_alerts(
        cmp_val, cw_val, pw_val, gf_val, 
        latest_metrics.get("pe_interp", "Neutral"), latest_metrics.get("ce_interp", "Neutral"), 
        latest_metrics.get("suggested_strategy", "Wait for Setup"), container=col_left
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
        if is_historical:
            st.warning("⚠️ Option chain GEX profile charts are only available for the latest active trading session. Chronological metrics, wall migrations, and historical setup backtests are fully accessible for this date.")
        else:
            fig_gex = render_gex_profile_chart(greeks_df, selected_symbol, selected_expiry, cmp_val, gf_val, cw_val, pw_val, strike_pct)
            if fig_gex is None:
                st.warning("No GEX data available in system processed files for this symbol.")
            else:
                st.plotly_chart(fig_gex, use_container_width=True)
            
    # OI Concentration Chart
    with tab_oi:
        if is_historical:
            st.warning("⚠️ Option chain OI concentration charts are only available for the latest active trading session. Chronological metrics, wall migrations, and historical setup backtests are fully accessible for this date.")
        else:
            fig_oi = render_oi_concentration_chart(greeks_df, selected_symbol, selected_expiry, cmp_val, gf_val, cw_val, pw_val, strike_pct)
            if fig_oi is None:
                st.warning("No option chain data available for this symbol.")
            else:
                st.plotly_chart(fig_oi, use_container_width=True)
            
    # IV Skew Chart
    with tab_skew:
        if is_historical:
            st.warning("⚠️ Option chain IV skew charts are only available for the latest active trading session. Chronological metrics, wall migrations, and historical setup backtests are fully accessible for this date.")
        else:
            fig_iv = render_iv_skew_chart(greeks_df, selected_symbol, selected_expiry, cmp_val, gf_val, cw_val, pw_val, strike_pct)
            if fig_iv is None:
                st.warning("IV data unavailable for this symbol.")
            else:
                st.plotly_chart(fig_iv, use_container_width=True)
            
    # Greeks Ledger Table
    with tab_table:
        if is_historical:
            st.warning("⚠️ Intraday Greeks ledgers are only available for the latest active trading session. Chronological metrics, wall migrations, and historical setup backtests are fully accessible for this date.")
        else:
            st_greeks_filtered = greeks_df[greeks_df["SYMBOL"] == selected_symbol.upper()].copy()
            if selected_expiry != "ALL EXPIRIES":
                st_greeks_filtered = st_greeks_filtered[st_greeks_filtered["EXPIRY_DT"] == selected_expiry].copy()
                
            if st_greeks_filtered.empty:
                st.warning("No Greeks record compiled for this ticker.")
            else:
                lo_strike = cmp_val * (1 - strike_pct / 100)
                hi_strike = cmp_val * (1 + strike_pct / 100)
                st_greeks_filtered["STRIKE_PR"] = pd.to_numeric(st_greeks_filtered["STRIKE_PR"], errors="coerce")
                st_greeks_filtered = st_greeks_filtered[
                    (st_greeks_filtered["STRIKE_PR"] >= lo_strike) & 
                    (st_greeks_filtered["STRIKE_PR"] <= hi_strike)
                ].sort_values(["STRIKE_PR", "OPTION_TYP"])
                
                render_greeks_ledger(st_greeks_filtered, cmp_val)

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("""
<hr>
<p style="font-size:10px;color:#2a3a5a;text-align:center;letter-spacing:1px;font-family:'IBM Plex Sans';">
  VANGUARD INSTITUTIONAL TERMINAL · dealer positioning & inventory intelligence · EOD system
</p>
""", unsafe_allow_html=True)
