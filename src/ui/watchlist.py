import os
import streamlit as st
import pandas as pd
import numpy as np
import duckdb
from src.services.database_service import DatabaseService
from src.ui.cards import render_html, sig_colors, fmt_gex
from src.core.watchlist_screener import screen_watchlist_candidates

def _num(val, default=0.0):
    """None/NaN-safe float coercion (CM breadth columns keep NaN for 'no data yet')."""
    try:
        f = float(val)
    except (TypeError, ValueError):
        return default
    return default if f != f else f


@st.cache_data(show_spinner=False)
def get_rsi_cache():
    """Loads CashMarketBreadthEngine once to pivot and compute 14-period RSI across all symbols."""
    from src.core.cash_market_breadth import CashMarketBreadthEngine
    try:
        engine = CashMarketBreadthEngine()
        engine._load_and_adjust("data/compiled/cash_market_prices.parquet")
        engine._precompute_dmas()
        return engine._dma_cache["rsi14"]
    except Exception as e:
        st.error(f"Failed to compile RSI cache: {e}")
        return pd.DataFrame()

def render_watchlist_briefing(latest_date: str, db_service: DatabaseService):
    """
    Renders the institutional-grade Tomorrow's Watchlist Briefing screen.
    """
    render_html(f"""
    <div class="title-bar">
      <span style="font-size:24px;color:#8b5cf6;">🔮</span>
      <h1>VANGUARD QUANT DESK — DAILY BRIEFING</h1>
      <span class="sig-badge" style="background:#091c15;color:#8b5cf6;border:1px solid #4c1d95;margin-left:15px;">TACTICAL DECISION SHEET ACTIVE</span>
      <span class="ts">ACTIVE SESSION: {pd.to_datetime(latest_date).strftime('%d %b %Y')}</span>
    </div>
    """)

    # 1. Load Cash Market Breadth and RSI Cache
    rsi_df = get_rsi_cache()
    
    # Fetch data from DuckDB
    if not os.path.exists(db_service.db_path):
        st.error("Database not found.")
        return

    # Get CM breadth row
    latest_cm_breadth = db_service.get_cm_breadth(latest_date)
    if not latest_cm_breadth:
        st.warning("Daily Cash Market Breadth data is unavailable for this session date.")
        return

    # Get Index metrics
    try:
        with db_service as db:
            df_indices = db.conn.execute("""
                SELECT symbol, spot_close, spot_change_pct, futures_oi, futures_oi_chg, pcr, gamma_regime, call_wall, put_wall, gamma_flip, suggested_strategy
                FROM daily_market_structure 
                WHERE date = ? AND symbol IN ('NIFTY', 'BANKNIFTY')
            """, [latest_date]).df()
    except Exception as e:
        st.error(f"Failed to query index metrics: {e}")
        df_indices = pd.DataFrame()

    # Get Sector flow
    df_sectors = db_service.get_sector_flow(latest_date)

    # Get setups and market structure for screening
    try:
        with db_service as db:
            df_ms = db.conn.execute("""
                SELECT symbol, sector, spot_close, conviction_score, ifs_score, gamma_regime, gamma_flip, call_wall, put_wall
                FROM daily_market_structure
                WHERE date = ? AND symbol NOT IN ('NIFTY', 'BANKNIFTY')
            """, [latest_date]).df()
            
            df_setups = db.conn.execute("""
                SELECT symbol, setup_type, bias, trigger_strike, invalidation_strike, expected_behavior
                FROM daily_setups
                WHERE date = ? AND symbol NOT IN ('NIFTY', 'BANKNIFTY')
            """, [latest_date]).df()
    except Exception as e:
        st.error(f"Failed to query F&O structure/setups: {e}")
        df_ms = pd.DataFrame()
        df_setups = pd.DataFrame()

    # Map symbol to its RSI for this date
    symbol_rsi = {}
    ts_date = pd.Timestamp(latest_date)
    if not rsi_df.empty and ts_date in rsi_df.index:
        rsi_row = rsi_df.loc[ts_date]
        for sym in rsi_row.index:
            val = rsi_row[sym]
            if not pd.isna(val):
                symbol_rsi[sym] = val

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 1 — MARKET REGIME CONTEXT & INDEX OPTIONS DETAILS
    # ─────────────────────────────────────────────────────────────────────────
    col_left, col_right = st.columns([6, 4])

    with col_left:
        col_left.markdown('<p class="term-header">STEP 1 — MARKET REGIME & SIZING CONTEXT</p>', unsafe_allow_html=True)
        
        # Cash market breadth stats (NaN-safe: early dates lack DMA/RSI history)
        adv = int(_num(latest_cm_breadth.get("cm_advances"), 0))
        dec = int(_num(latest_cm_breadth.get("cm_declines"), 0))
        total_syms = int(_num(latest_cm_breadth.get("cm_total_symbols"), 1))
        adv_pct = _num(latest_cm_breadth.get("cm_advance_pct"))
        dec_pct = round(dec / max(total_syms, 1) * 100, 1)
        ad_ratio = _num(latest_cm_breadth.get("cm_ad_ratio"), 1.0)
        vol_ad_ratio = _num(latest_cm_breadth.get("cm_volume_ad_ratio"), 1.0)

        p20 = _num(latest_cm_breadth.get("cm_pct_above_20dma"))
        p50 = _num(latest_cm_breadth.get("cm_pct_above_50dma"))
        p200 = _num(latest_cm_breadth.get("cm_pct_above_200dma"))

        rsi_ob = _num(latest_cm_breadth.get("cm_pct_overbought_70"))
        rsi_os = _num(latest_cm_breadth.get("cm_pct_oversold_30"))

        new_highs = _num(latest_cm_breadth.get("cm_new_highs"))
        new_lows = _num(latest_cm_breadth.get("cm_new_lows"))
        nh_nl = _num(latest_cm_breadth.get("cm_nh_nl_ratio"), 1.0)

        mcclellan = _num(latest_cm_breadth.get("cm_mcclellan_osc"))
        turnover_conc = _num(latest_cm_breadth.get("cm_turnover_top20_pct"))

        # Build one-line regime classification
        regime_desc = ""
        is_bullish_trend = (p20 > 50 and p50 > 50 and p200 > 45)
        
        if dec_pct > 60:
            if is_bullish_trend:
                regime_desc = f"Broad breadth weak ({dec_pct}% declines) but structurally still bullish ({p20}%/{p50}%/{p200}% above 20/50/200-DMA) — a pullback inside an uptrend, not a trend reversal."
                regime_type = "warn"
            else:
                regime_desc = f"Broad market weak ({dec_pct}% declines) and structural trends deteriorating ({p200}% above 200-DMA) — defense and capital preservation recommended."
                regime_type = "bear"
        elif adv_pct > 60:
            regime_desc = f"Broad market strong ({adv_pct}% advances) with robust trend participation — risk-on environment favoring aggressive long exposure."
            regime_type = "bull"
        else:
            regime_desc = f"Broad market in equilibrium (A/D Ratio: {ad_ratio:.2f}) with neutral momentum extremes — range-bound consolidation expected."
            regime_type = "info"

        # Explicit sizing guidance based on index GEX regimes + cash breadth
        has_long_gex = True
        for idx, r in df_indices.iterrows():
            if r["gamma_regime"] == "SHORT_GAMMA":
                has_long_gex = False
                break

        if has_long_gex and is_bullish_trend:
            _mcl_note = (
                "the short-term broad market is in a pullback" if mcclellan < 0
                else "short-term breadth momentum is constructive"
            )
            sizing_guidance = (
                "**LONG SETUPS PREFERRED (SELECTIVE)**: The indices sit in safe `LONG_GAMMA` regimes, providing a volatility buffer. "
                f"Since {_mcl_note} (McClellan: {mcclellan:+.1f}), size swing long positions "
                "selectively in strong sectors with tailwinds, and avoid short setups."
            )
        elif not has_long_gex:
            sizing_guidance = (
                "**NEUTRAL / SQUEEZE ALERTS (RANGE-BOUND)**: Indices are in `SHORT_GAMMA` or near the Gamma Flip level. "
                "Volatility can accelerate rapidly on breakout triggers. Size down swing exposure and focus on quick intraday volatility expansions."
            )
        else:
            sizing_guidance = (
                "**NEUTRAL / DEFENSIVE RANGE**: Breadth parameters are highly mixed. Focus on delta-neutral option configurations "
                "or write straddles near key option walls."
            )

        col_left.markdown(f"""
        <div class="alert-box {regime_type}">
          <strong>REGIME CLASSIFICATION:</strong><br>{regime_desc}
        </div>
        <div class="alert-box info" style="margin-top: 10px;">
          <strong>SIZING INSTRUCTIONS:</strong><br>{sizing_guidance}
        </div>
        """, unsafe_allow_html=True)

    with col_right:
        col_right.markdown('<p class="term-header">INDEX OPTION REGIMES & STRIKE LEVELS</p>', unsafe_allow_html=True)
        if df_indices.empty:
            st.info("No index levels loaded.")
        else:
            idx_html = ""
            for idx, r in df_indices.iterrows():
                symbol = r["symbol"]
                spot = r["spot_close"]
                chg = r["spot_change_pct"]
                oi = r["futures_oi"]
                oi_chg = r["futures_oi_chg"]
                regime = r["gamma_regime"]
                cw = r["call_wall"]
                pw = r["put_wall"]
                gf = r["gamma_flip"]
                strat = r["suggested_strategy"]
                
                chg_color = "#10b981" if chg >= 0 else "#ef4444"
                reg_color = "#10b981" if regime == "LONG_GAMMA" else "#ef4444" if regime == "SHORT_GAMMA" else "#f59e0b"
                
                idx_html += f"""
                <div style="background:#090915; border:1px solid #141435; border-radius:6px; padding:10px; margin-bottom:10px;">
                  <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #141435; padding-bottom:6px; margin-bottom:6px;">
                    <span style="font-weight:bold; font-size:12px; color:#f8fafc;">{symbol}</span>
                    <span style="font-size:10px; padding:2px 6px; border-radius:4px; font-weight:bold; background:rgba(0,0,0,0.3); border:1px solid {reg_color}; color:{reg_color};">{regime}</span>
                  </div>
                  <div style="font-size:11px; display:grid; grid-template-columns: 1fr 1fr; gap:6px;">
                    <div>SPOT CLOSE: <span style="font-weight:bold; color:#e2e8f0;">₹{spot:,.2f}</span> (<span style="color:{chg_color};">{chg:+.2f}%</span>)</div>
                    <div>FUTURES OI CHG: <span style="font-weight:bold; color:#e2e8f0;">{oi_chg:+,.0f}</span></div>
                    <div>CALL WALL: <span style="color:#fbbf24; font-weight:bold;">₹{cw:,.0f}</span></div>
                    <div>PUT WALL: <span style="color:#ef4444; font-weight:bold;">₹{pw:,.0f}</span></div>
                    <div>GAMMA FLIP: <span style="color:#a78bfa; font-weight:bold;">₹{gf:,.0f}</span></div>
                    <div style="grid-column: span 2; border-top: 1px dashed #141435; padding-top:4px; margin-top:2px;">
                      PLAY: <span style="color:#cbd5e1; font-weight:bold;">{strat}</span>
                    </div>
                  </div>
                </div>
                """
            render_html(idx_html, container=col_right)

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 2 — SECTOR ROTATION SCAN
    # ─────────────────────────────────────────────────────────────────────────
    st.markdown('<p class="term-header">STEP 2 — TOP-DOWN SECTOR ROTATION TABLE</p>', unsafe_allow_html=True)
    
    if df_sectors.empty:
        st.info("Sector flow table is empty for this date.")
    else:
        # Render sector rankings table
        sec_rows = ""
        for idx, s in enumerate(df_sectors.to_dict('records')):
            sec = s['sector']
            count = s['symbol_count']
            avg_ifs = s['avg_ifs']
            net_oi = s['total_net_inv_shift']
            gex = s['total_gex_shift']
            
            if avg_ifs >= 15:
                badge_bg, badge_fc = "rgba(16, 185, 129, 0.15)", "#10b981"
                trend = "🟢 ACCUMULATION"
            elif avg_ifs <= -15:
                badge_bg, badge_fc = "rgba(239, 68, 68, 0.15)", "#ef4444"
                trend = "🔴 DISTRIBUTION"
            else:
                badge_bg, badge_fc = "rgba(245, 158, 11, 0.15)", "#f59e0b"
                trend = "⚪ NEUTRAL"
                
            ifs_badge = f'<span style="background:{badge_bg}; color:{badge_fc}; border:1px solid {badge_fc}; padding:2px 6px; border-radius:4px; font-weight:bold; font-family:\'JetBrains Mono\';">{avg_ifs:+.1f}</span>'
            
            # Draw center-aligned split indicator bar
            if avg_ifs >= 0:
                bar_width = min(100.0, (avg_ifs / 100.0) * 100.0)
                bar_html = f"""
                <div style="display:flex; width:80px; height:6px; background:#111126; border:1px solid #1e293b; border-radius:3px; overflow:hidden;">
                  <div style="width:50%; background:transparent; border-right:1px solid #334155;"></div>
                  <div style="width:{bar_width/2}%; background:#10b981;"></div>
                  <div style="width:{50 - bar_width/2}%; background:transparent;"></div>
                </div>
                """
            else:
                bar_width = min(100.0, (abs(avg_ifs) / 100.0) * 100.0)
                bar_html = f"""
                <div style="display:flex; width:80px; height:6px; background:#111126; border:1px solid #1e293b; border-radius:3px; overflow:hidden;">
                  <div style="width:{50 - bar_width/2}%; background:transparent;"></div>
                  <div style="width:{bar_width/2}%; background:#ef4444; border-right:1px solid #334155;"></div>
                  <div style="width:50%; background:transparent;"></div>
                </div>
                """
            
            ifs_cell = f"""
            <div style="display:inline-flex; align-items:center; gap:8px;">
              {ifs_badge}
              {bar_html}
            </div>
            """

            oi_color = "#10b981" if net_oi > 0 else "#ef4444" if net_oi < 0 else "#cbd5e1"
            gex_color = "#10b981" if gex > 0 else "#ef4444" if gex < 0 else "#cbd5e1"
            
            sec_rows += f"""
            <tr>
              <td><span style="font-weight:bold; color:#f8fafc;">{sec}</span></td>
              <td>{count}</td>
              <td>{trend}</td>
              <td>{ifs_cell}</td>
              <td style="color:{oi_color}; font-family:'JetBrains Mono';">{fmt_gex(net_oi)}</td>
              <td style="color:{gex_color}; font-family:'JetBrains Mono';">{fmt_gex(gex)}</td>
            </tr>
            """
            
        sec_table_html = f"""
        <div style="overflow-x:auto; border:1px solid #141435; border-radius:6px; margin-bottom:20px;">
          <table class="g-table" style="width:100%; text-align:left;">
            <thead>
              <tr>
                <th>SECTOR</th>
                <th>SYMBOLS</th>
                <th>TREND STATUS</th>
                <th>AVG IFS</th>
                <th>NET OI SHIFT</th>
                <th>GEX SHIFT</th>
              </tr>
            </thead>
            <tbody>
              {sec_rows}
            </tbody>
          </table>
        </div>
        """
        render_html(sec_table_html)

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 3 & 4 — CANDIDATE WATCHLIST TABLES
    # ─────────────────────────────────────────────────────────────────────────
    st.markdown('<p class="term-header">STEPS 3 & 4 — ACTIONABLE WATCHLIST BUILDERS</p>', unsafe_allow_html=True)
    
    # Run screening logic
    swing_candidates, intraday_candidates = screen_watchlist_candidates(
        df_ms, df_setups, df_sectors, symbol_rsi
    )

    tab_swing, tab_intra = st.tabs(["📊 SWING WATCHLIST (Relaxed Conviction)", "⚡ INTRADAY WATCHLIST (Fast Compression)"])

    # Render Swing Watchlist
    with tab_swing:
        df_swing = pd.DataFrame(swing_candidates)
        if df_swing.empty:
            st.info("No swing candidates found matching strict rules for this session.")
        else:
            df_swing['abs_conviction'] = df_swing['conviction'].abs()
            df_swing = df_swing.sort_values('pct_diff').groupby('symbol').first().reset_index()
            df_swing = df_swing.sort_values(by='abs_conviction', ascending=False).head(8)
            
            swing_rows = ""
            for idx, r in enumerate(df_swing.to_dict('records')):
                sym = r['symbol']
                sec = r['sector']
                bias = r['bias']
                conv = r['conviction']
                trig = r['trigger']
                inval = r['invalidation']
                setup = r['setup']
                ifs = r['ifs']
                pct_diff = r['pct_diff']
                
                # conviction is a 0-100 magnitude; direction comes from the IFS sign
                bias_color = "#10b981" if ifs >= 0 else "#ef4444"
                bias_tag = "BULLISH" if ifs >= 0 else "BEARISH"
                
                # Check for stop levels
                inval_str = f"₹{inval:,.2f}" if (inval and inval > 0) else '<span style="color:#ef4444; font-weight:bold;">No Stop / Size Down</span>'
                
                # Construct "Why"
                why = f"Sector tailwind ({sec}) + {setup} + IFS {ifs:+.0f}, {pct_diff:.2%} distance to trigger."
                
                # Draw center-aligned split indicator bar for conviction
                if conv >= 0:
                    conv_width = min(100.0, (conv / 100.0) * 100.0)
                    conv_bar = f"""
                    <div style="display:flex; width:80px; height:6px; background:#111126; border:1px solid #1e293b; border-radius:3px; overflow:hidden;">
                      <div style="width:50%; background:transparent; border-right:1px solid #334155;"></div>
                      <div style="width:{conv_width/2}%; background:#10b981;"></div>
                      <div style="width:{50 - conv_width/2}%; background:transparent;"></div>
                    </div>
                    """
                else:
                    conv_width = min(100.0, (abs(conv) / 100.0) * 100.0)
                    conv_bar = f"""
                    <div style="display:flex; width:80px; height:6px; background:#111126; border:1px solid #1e293b; border-radius:3px; overflow:hidden;">
                      <div style="width:{50 - conv_width/2}%; background:transparent;"></div>
                      <div style="width:{conv_width/2}%; background:#ef4444; border-right:1px solid #334155;"></div>
                      <div style="width:50%; background:transparent;"></div>
                    </div>
                    """
                
                conv_cell = f"""
                <div style="display:inline-flex; align-items:center; gap:8px;">
                  <span style="font-weight:bold; color:#cbd5e1;">{conv:+.1f}</span>
                  {conv_bar}
                </div>
                """
                
                swing_rows += f"""
                <tr>
                  <td><strong>{idx+1}</strong></td>
                  <td><span style="font-weight:bold; color:#cbd5e1;">{sym}</span></td>
                  <td><span style="color:{bias_color}; font-weight:bold;">{bias_tag}</span></td>
                  <td style="font-family:'JetBrains Mono';">{conv_cell}</td>
                  <td style="font-family:'JetBrains Mono';">₹{trig:,.2f}</td>
                  <td style="font-family:'JetBrains Mono';">{inval_str}</td>
                  <td><span style="background:rgba(255,255,255,0.05); color:#a78bfa; border:1px solid #a78bfa; padding:2px 4px; border-radius:4px; font-size:10px;">{setup}</span></td>
                  <td style="font-size:10px; color:#94a3b8;">{why}</td>
                </tr>
                """
                
            swing_table_html = f"""
            <div style="overflow-x:auto; border:1px solid #141435; border-radius:6px;">
              <table class="g-table" style="width:100%; text-align:left;">
                <thead>
                  <tr>
                    <th>RANK</th>
                    <th>SYMBOL</th>
                    <th>BIAS</th>
                    <th>CONVICTION</th>
                    <th>TRIGGER</th>
                    <th>INVALIDATION</th>
                    <th>SETUP</th>
                    <th>CONFLUENCE (WHY)</th>
                  </tr>
                </thead>
                <tbody>
                  {swing_rows}
                </tbody>
              </table>
            </div>
            """
            render_html(swing_table_html)

    # Render Intraday Watchlist
    with tab_intra:
        df_intra = pd.DataFrame(intraday_candidates)
        if df_intra.empty:
            st.info("No intraday candidates found matching strict rules for this session.")
        else:
            df_intra['abs_conviction'] = df_intra['conviction'].abs()
            df_intra = df_intra.groupby('symbol').first().reset_index()
            df_intra = df_intra.sort_values(by='abs_conviction', ascending=False).head(8)
            
            intra_rows = ""
            for idx, r in enumerate(df_intra.to_dict('records')):
                sym = r['symbol']
                sec = r['sector']
                bias = r['bias']
                trig = r['trigger']
                inval = r['invalidation']
                setup = r['setup']
                rsi = r['rsi']
                regime = r['gamma_regime']
                flip = r['gamma_flip']
                is_near = r['is_near_flip']
                
                # conviction is a 0-100 magnitude; direction comes from the IFS sign
                bias_color = "#10b981" if r['ifs'] >= 0 else "#ef4444"
                bias_tag = "BULLISH" if r['ifs'] >= 0 else "BEARISH"
                
                inval_str = f"₹{inval:,.2f}" if (inval and inval > 0) else '<span style="color:#ef4444; font-weight:bold;">No Stop / Size Down</span>'
                
                # Construct "Why"
                rsi_str = f"{rsi:.1f}" if (rsi is not None and not (isinstance(rsi, float) and np.isnan(rsi))) else "N/A"
                why = f"Active {setup} compression (RSI: {rsi_str}) sits within {regime} + "
                if is_near:
                    why += f"proximity to Gamma Flip (₹{flip:,.0f})."
                else:
                    why += f"active Short Gamma acceleration."

                intra_rows += f"""
                <tr>
                  <td><strong>{idx+1}</strong></td>
                  <td><span style="font-weight:bold; color:#cbd5e1;">{sym}</span></td>
                  <td><span style="color:{bias_color}; font-weight:bold;">{bias_tag}</span></td>
                  <td style="font-family:'JetBrains Mono';">₹{trig:,.2f}</td>
                  <td style="font-family:'JetBrains Mono';">{inval_str}</td>
                  <td><span style="background:rgba(255,255,255,0.05); color:#a78bfa; border:1px solid #a78bfa; padding:2px 4px; border-radius:4px; font-size:10px;">{setup}</span></td>
                  <td style="font-size:10px; color:#94a3b8;">{why}</td>
                </tr>
                """
                
            intra_table_html = f"""
            <div style="overflow-x:auto; border:1px solid #141435; border-radius:6px;">
              <table class="g-table" style="width:100%; text-align:left;">
                <thead>
                  <tr>
                    <th>RANK</th>
                    <th>SYMBOL</th>
                    <th>BIAS</th>
                    <th>TRIGGER</th>
                    <th>INVALIDATION</th>
                    <th>SETUP</th>
                    <th>CONFLUENCE (WHY)</th>
                  </tr>
                </thead>
                <tbody>
                  {intra_rows}
                </tbody>
              </table>
            </div>
            """
            render_html(intra_table_html)





    # ─────────────────────────────────────────────────────────────────────────
    # STEP 5 — RISK NOTES & SAFETY GUIDANCE  (renumbered)
    # ─────────────────────────────────────────────────────────────────────────
    st.markdown('<p class="term-header">STEP 5 — VANGUARD QUANT RISK DECK</p>', unsafe_allow_html=True)

    # Bullet 1 — breadth pressure note driven by actual session values
    if dec_pct > 50 or mcclellan < 0:
        breadth_bullet = (
            f"<li><strong>Broad Market Selling Pressure</strong>: Today's cash market session registered "
            f"<strong>{dec_pct}% declines</strong> with a McClellan Oscillator of <strong>{mcclellan:+.1f}</strong>. "
            f"Limit overall trade sizing to prevent correlation drag.</li>"
        )
    else:
        breadth_bullet = (
            f"<li><strong>Broad Market Participation Healthy</strong>: Today's cash market session registered "
            f"<strong>{adv_pct}% advances</strong> with a McClellan Oscillator of <strong>{mcclellan:+.1f}</strong>. "
            f"Normal sizing applies, but avoid concentrating entries in a single sector.</li>"
        )

    # Bullet 3 — NIFTY regime anchor from the compiled gamma flip level (not a fixed number)
    nifty_gf = 0.0
    if not df_indices.empty:
        _nifty_rows = df_indices[df_indices["symbol"] == "NIFTY"]
        if not _nifty_rows.empty:
            nifty_gf = _num(_nifty_rows.iloc[0].get("gamma_flip"))
    if nifty_gf > 0:
        anchor_bullet = (
            f"<li><strong>Confirm Flip Anchors</strong>: Ensure <strong>NIFTY</strong> holds above its Gamma Flip pivot of "
            f"<strong>₹{nifty_gf:,.0f}</strong> at the open before adding swing long exposure. A breach below "
            f"₹{nifty_gf:,.0f} transforms the market regime to short-gamma, creating overnight cascade risk.</li>"
        )
    else:
        anchor_bullet = (
            "<li><strong>Confirm Flip Anchors</strong>: Verify the NIFTY gamma regime at the open before adding "
            "swing long exposure — a short-gamma index regime creates overnight cascade risk.</li>"
        )

    render_html(f"""
    <div style="background: rgba(239, 68, 68, 0.05); border: 1px solid rgba(239, 68, 68, 0.25); border-left: 4px solid #ef4444; border-radius: 6px; padding: 12px 16px; margin-bottom: 20px;">
      <span style="font-weight:700; color:#ef4444; font-size:12px; letter-spacing:0.5px; text-transform:uppercase;">
        ⚠️ SIZING INHIBITORS & EXECUTION SAFETY
      </span>
      <div style="font-size:11px; color:#cbd5e1; margin-top:8px; line-height:1.5;">
        <ul>
          {breadth_bullet}
          <li><strong>Stop Loss Enforcement</strong>: For all setups, exit immediately if the invalidation strike is breached on a 15-minute closing basis. If a candidate lists "No Stop / Size Down", do not buy the spot directly; write defined-risk spreads instead.</li>
          {anchor_bullet}
        </ul>
      </div>
    </div>
    
    <div style="font-size:10px; color:#4a5a8a; text-align:center; font-family:'JetBrains Mono'; letter-spacing:0.5px; border-top:1px dashed #141435; padding-top:10px; margin-top:20px;">
      Disclaimer: This is a structural options and market participation setup screen, not a price prediction. Always cross-validate setups with live opening price action.
    </div>
    """)
