import streamlit as st
from vanguard.config.settings import C
from vanguard.core.narrative import NarrativeEngine

def render_html(html_str: str, container=st):
    """Safely renders premium HTML code in Streamlit container."""
    cleaned = "\n".join([line.strip() for line in html_str.strip().split("\n")])
    container.markdown(cleaned, unsafe_allow_html=True)

def fmt_gex(val):
    if val is None or val == 0:
        return "0.00"
    abs_val = abs(val)
    sign = "+" if val >= 0 else "-"
    if abs_val >= 1e7:  return f"{sign}{abs_val/1e7:.2f} Cr"
    if abs_val >= 1e5:  return f"{sign}{abs_val/1e5:.2f} L"
    if abs_val >= 1e3:  return f"{sign}{abs_val/1e3:.1f} K"
    return f"{sign}{abs_val:.0f}"

def pct_gap(cmp, level):
    return round((cmp - level) / level * 100, 2) if level else 0.0

def format_score(score):
    if score >= 60:
        return f'<span class="card-score" style="background:#051d14;color:#10b981;border:1px solid #064e3b;">{score:+.1f}</span>'
    elif score <= -60:
        return f'<span class="card-score" style="background:#200808;color:#ef4444;border:1px solid #7f1d1d;">{score:+.1f}</span>'
    else:
        return f'<span class="card-score" style="background:#1a0f00;color:#f59e0b;border:1px solid #78350f;">{score:+.1f}</span>'

def sig_colors(regime):
    if regime == "bull":
        return "rgba(16, 185, 129, 0.1)", "#10b981", "#064e3b"
    elif regime == "bear":
        return "rgba(239, 68, 68, 0.1)", "#ef4444", "#7f1d1d"
    else:
        return "rgba(20, 20, 45, 0.5)", "#7888aa", "#141435"

def get_ifs_hsl(score):
    if score > 0:
        # Green hue 140. Lightness scales with absolute score
        opacity = min(0.9, abs(score) / 100.0 * 0.9 + 0.1)
        return f"rgba(16, 185, 129, {opacity:.3f})", "#a7f3d0"
    elif score < 0:
        # Red/Crimson hue 0
        opacity = min(0.9, abs(score) / 100.0 * 0.9 + 0.1)
        return f"rgba(239, 68, 68, {opacity:.3f})", "#fca5a5"
    else:
        return "rgba(20, 20, 45, 0.5)", "#7888aa"

def render_metric_row(cmp_val: float, spot_change_pct: float, cw_val: float, pw_val: float, gf_val: float, gex_val: float, pcr_val: float, container=st):
    """
    Renders custom responsive Bloomberg-style Metric Cards row.
    """
    spot_change_class = "positive" if spot_change_pct >= 0 else "negative"
    spot_change_arrow = "▲" if spot_change_pct >= 0 else "▼"

    def _level_card(label: str, level: float) -> str:
        """One wall/flip metric card; a missing level (0) renders as N/A, not ₹0."""
        if level <= 0:
            return f"""
      <div class="custom-metric-card">
        <div class="metric-label">{label}</div>
        <div class="metric-value" style="color:#7888aa;">N/A</div>
        <div style="height: 14px;"></div>
      </div>"""
        gap = pct_gap(cmp_val, level)
        gap_class = "positive" if gap >= 0 else "negative"
        gap_arrow = "▲" if gap >= 0 else "▼"
        return f"""
      <div class="custom-metric-card">
        <div class="metric-label">{label}</div>
        <div class="metric-value">₹{level:,.0f}</div>
        <div class="metric-delta {gap_class}">{gap_arrow} {gap:+.2f}% gap</div>
      </div>"""

    metrics_html = f"""
    <div class="custom-metrics-row">
      <div class="custom-metric-card">
        <div class="metric-label">SPOT CLOSE</div>
        <div class="metric-value">₹{cmp_val:,.2f}</div>
        <div class="metric-delta {spot_change_class}">{spot_change_arrow} {spot_change_pct:+.2f}%</div>
      </div>
      {_level_card("CALL WALL", cw_val)}
      {_level_card("PUT WALL", pw_val)}
      {_level_card("GAMMA FLIP", gf_val)}
      <div class="custom-metric-card">
        <div class="metric-label">DEALER GEX</div>
        <div class="metric-value">{fmt_gex(gex_val)}</div>
        <div style="height: 14px;"></div>
      </div>
      <div class="custom-metric-card">
        <div class="metric-label">PCR INDEX</div>
        <div class="metric-value">{pcr_val:.2f}</div>
        <div style="height: 14px;"></div>
      </div>
    </div>
    """
    render_html(metrics_html, container=container)

def render_alerts(cmp_val: float, cw_val: float, pw_val: float, gf_val: float, pe_interp: str, ce_interp: str, suggested_strategy: str, latest_metrics: dict = None, container=st):
    """
    Renders segmented structure interpretation alert cards.
    """
    container.markdown('<p class="term-header">STRUCTURE INTERPRETATION</p>', unsafe_allow_html=True)
    a1, a2, a3 = container.columns(3)

    with a1:
        if cmp_val > cw_val:
            st.markdown(f'<div class="alert-box bull">📈 CMP (₹{cmp_val:,.2f}) above CALL WALL (₹{cw_val:,.0f}) — dealer delta-buying active. Volatility squeeze expansion likely.</div>', unsafe_allow_html=True)
        elif cmp_val > gf_val:
            st.markdown(f'<div class="alert-box bull">🔋 CMP above Γ FLIP (₹{gf_val:,.0f}) — positive gamma regime. Volatility stabilized, buying on dips favored.</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="alert-box bear">⚠ CMP (₹{cmp_val:,.2f}) below Γ FLIP (₹{gf_val:,.0f}) — dealer short gamma. Hedging cascades accelerate downside drops.</div>', unsafe_allow_html=True)

    with a2:
        g_call = cw_val - cmp_val
        g_put = cmp_val - pw_val
        
        if cw_val == pw_val:
            # Concentrated Wall Case
            wall_val = cw_val
            dist = abs(cmp_val - wall_val)
            if cmp_val < wall_val:
                st.markdown(f'<div class="alert-box warn">🛡️ CONCENTRATED WALL (₹{wall_val:,.0f}) is ₹{dist:.1f} above — acting as a major resistance ceiling.</div>', unsafe_allow_html=True)
            elif cmp_val > wall_val:
                st.markdown(f'<div class="alert-box warn">🎯 CONCENTRATED WALL (₹{wall_val:,.0f}) is ₹{dist:.1f} below — acting as a major support floor.</div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="alert-box warn">🎯 Spot is exactly at the CONCENTRATED WALL (₹{wall_val:,.0f}) — key inflection zone.</div>', unsafe_allow_html=True)
        else:
            # Normal Case (cw_val > pw_val)
            if g_call < g_put and g_call >= 0:
                st.markdown(f'<div class="alert-box warn">🎯 ₹{g_call:.1f} to CALL WALL — critical breakout zone. Dealer buying triggers above Call Wall.</div>', unsafe_allow_html=True)
            else:
                if g_put >= 0:
                    st.markdown(f'<div class="alert-box warn">🛡️ PUT WALL (₹{pw_val:,.0f}) is ₹{g_put:.1f} below — dealers short put gamma, creating strong floor support.</div>', unsafe_allow_html=True)
                else:
                    st.markdown(f'<div class="alert-box warn">⚠️ PUT WALL (₹{pw_val:,.0f}) is ₹{abs(g_put):.1f} above — spot has breached support floor. Hedging may accelerate downmoves.</div>', unsafe_allow_html=True)

    with a3:
        # Compute recommended strikes dynamically based on option walls and playbook invalidation
        strike_recommendation = ""
        if latest_metrics:
            playbook = latest_metrics.get("playbook", {})
            invalid_strike = playbook.get("invalidation_strike", 0.0)
            
            # Determine dynamic interval for spacing hedges (default to 2.5% of wall or price)
            spacing = cw_val * 0.025 if cw_val > 10 else 5.0
            # Round spacing to nearest clean strike multiple (5, 10, 50, 100)
            if spacing > 50:
                spacing = 100.0
            elif spacing > 25:
                spacing = 50.0
            elif spacing > 7:
                spacing = 10.0
            else:
                spacing = 5.0

            if "Bull Put Spread" in suggested_strategy:
                sell_strike = pw_val
                if cw_val == pw_val:
                    # Concentrated Wall Case
                    buy_strike = sell_strike - spacing
                else:
                    buy_strike = invalid_strike if invalid_strike > 0 and invalid_strike < sell_strike else (sell_strike - spacing)
                strike_recommendation = f'<div style="margin-top:6px; font-size:9.5px; color:#a78bfa; font-family:\'JetBrains Mono\', monospace; border-top:1px solid rgba(167, 139, 250, 0.15); padding-top:4px;">🎯 Rec. Strikes:<br><b>SELL ₹{sell_strike:.0f} PE</b> (Put Wall)<br><b>BUY ₹{buy_strike:.0f} PE</b> (Hedge)</div>'
            elif "Bear Call Spread" in suggested_strategy:
                sell_strike = cw_val
                if cw_val == pw_val:
                    # Concentrated Wall Case
                    buy_strike = sell_strike + spacing
                else:
                    buy_strike = invalid_strike if invalid_strike > 0 and invalid_strike > sell_strike else (sell_strike + spacing)
                strike_recommendation = f'<div style="margin-top:6px; font-size:9.5px; color:#f43f5e; font-family:\'JetBrains Mono\', monospace; border-top:1px solid rgba(244, 63, 94, 0.15); padding-top:4px;">🎯 Rec. Strikes:<br><b>SELL ₹{sell_strike:.0f} CE</b> (Call Wall)<br><b>BUY ₹{buy_strike:.0f} CE</b> (Hedge)</div>'
            elif "Bull Call Spread" in suggested_strategy:
                if cw_val == pw_val:
                    # Concentrated Wall Case
                    buy_strike = cw_val
                    sell_strike = cw_val + spacing
                else:
                    buy_strike = pw_val
                    sell_strike = cw_val
                strike_recommendation = f'<div style="margin-top:6px; font-size:9.5px; color:#38bdf8; font-family:\'JetBrains Mono\', monospace; border-top:1px solid rgba(56, 189, 248, 0.15); padding-top:4px;">🎯 Rec. Strikes:<br><b>BUY ₹{buy_strike:.0f} CE</b> (Support)<br><b>SELL ₹{sell_strike:.0f} CE</b> (Ceiling)</div>'
            elif "Bear Put Spread" in suggested_strategy:
                if cw_val == pw_val:
                    # Concentrated Wall Case
                    buy_strike = pw_val
                    sell_strike = pw_val - spacing
                else:
                    buy_strike = cw_val
                    sell_strike = pw_val
                strike_recommendation = f'<div style="margin-top:6px; font-size:9.5px; color:#fbbf24; font-family:\'JetBrains Mono\', monospace; border-top:1px solid rgba(251, 191, 36, 0.15); padding-top:4px;">🎯 Rec. Strikes:<br><b>BUY ₹{buy_strike:.0f} PE</b> (Ceiling)<br><b>SELL ₹{sell_strike:.0f} PE</b> (Support)</div>'
                
        st.markdown(f'<div class="alert-box info">🤖 SUGGESTED STRATEGY: <b>{suggested_strategy}</b><br>Put Flow: {pe_interp} | Call Flow: {ce_interp}{strike_recommendation}</div>', unsafe_allow_html=True)

def render_intelligence_panel(selected_symbol: str, latest_metrics: dict, sym_sessions: dict, container=st):
    """
    Renders Vanguard right-hand side analytics and decision layer widgets.
    """
    container.markdown('<p class="term-header">VANGUARD INTELLIGENCE PANEL</p>', unsafe_allow_html=True)

    # 1. Narratives
    engine = NarrativeEngine()
    narrative_text = engine.generate(latest_metrics)

    # 2. Conviction Circle SVG
    conv_score = latest_metrics.get("conviction_score", 0.0)
    if conv_score >= 70:
        circle_color = "#10b981"
    elif conv_score >= 40:
        circle_color = "#fbbf24"
    else:
        circle_color = "#7888aa"

    svg_circle = f"""
    <svg width="70" height="70" viewBox="0 0 36 36">
      <path d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" fill="none" stroke="#141435" stroke-width="3" />
      <path stroke-dasharray="{conv_score}, 100" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" fill="none" stroke="{circle_color}" stroke-width="3" stroke-linecap="round" />
      <text x="18" y="21.5" font-family="'JetBrains Mono', monospace" font-size="8" font-weight="bold" fill="{circle_color}" text-anchor="middle">{conv_score:.0f}</text>
    </svg>
    """

    render_html(f"""
    <div class="glass-card">
      <div class="narrative-title">🤖 VANGUARD QUANT NARRATIVE</div>
      <div class="conviction-panel">
        {svg_circle}
        <div>
          <div style="font-size:10px; color:#7888aa; text-transform:uppercase; letter-spacing:0.5px;">Vanguard Conviction Score</div>
          <div style="font-size:15px; font-weight:700; color:{circle_color};">{conv_score:.1f}%</div>
          <div style="font-size:10px; color:#4a5a8a; font-style:italic;">Smart Money Accumulation Conviction</div>
        </div>
      </div>
      <hr style="margin: 12px 0; border-color: rgba(20, 20, 53, 0.4) !important;">
      <div class="narrative-body">{narrative_text}</div>
    </div>
    """, container=container)

    # 3. Live Wall Migration Meter
    spot_val = latest_metrics.get("spot_close", 0.0)
    cw_val = latest_metrics.get("call_wall", 0.0)
    pw_val = latest_metrics.get("put_wall", 0.0)

    if cw_val > pw_val:
        prox_pct = max(0.0, min(100.0, (spot_val - pw_val) / (cw_val - pw_val + 1e-5) * 100))
        labels_html = f"""
        <div class="migration-labels">
          <span style="color:#f85149; font-weight:bold;">PUT WALL (₹{pw_val:,.0f})</span>
          <span style="color:#fbbf24; font-weight:bold;">SPOT (₹{spot_val:,.2f})</span>
          <span style="color:#58a6ff; font-weight:bold;">CALL WALL (₹{cw_val:,.0f})</span>
        </div>
        """
        subtext = f"Spot is {prox_pct:.1f}% of the way from Put Wall to Call Wall"
    else:
        # Concentrated Wall Case (cw_val == pw_val)
        wall_val = cw_val
        deviation = (spot_val - wall_val) / (wall_val + 1e-5)
        # Scale ±5% deviation range to [0, 100] scale, centered at 50%
        prox_pct = max(0.0, min(100.0, 50.0 + deviation * 20.0 * 50.0))
        
        labels_html = f"""
        <div class="migration-labels">
          <span style="color:#7888aa; font-weight:bold;">₹{0.95 * wall_val:,.0f} (-5%)</span>
          <span style="color:#d39bf5; font-weight:bold;">CONCENTRATED WALL (₹{wall_val:,.0f})</span>
          <span style="color:#7888aa; font-weight:bold;">₹{1.05 * wall_val:,.0f} (+5%)</span>
        </div>
        """
        
        pct_diff = abs(deviation) * 100
        if spot_val < wall_val:
            subtext = f"Spot (₹{spot_val:,.2f}) is {pct_diff:.2f}% below Concentrated Wall (₹{wall_val:,.0f})"
        elif spot_val > wall_val:
            subtext = f"Spot (₹{spot_val:,.2f}) is {pct_diff:.2f}% above Concentrated Wall (₹{wall_val:,.0f})"
        else:
            subtext = f"Spot is exactly at the Concentrated Wall (₹{wall_val:,.0f})"

    render_html(f"""
    <div class="glass-card">
      <div class="narrative-title">🔄 LIVE WALL MIGRATION METER</div>
      <div style="font-size:11px; color:#cbd5e1; margin-bottom: 10px;">
        Tracking spot proximity relative to major dealer positioning.
      </div>
      <div class="migration-meter-container">
        {labels_html}
        <div class="migration-track">
          <div class="migration-fill" style="width: {prox_pct}%;"></div>
          <div class="migration-marker" style="left: {prox_pct}%;"></div>
        </div>
      </div>
      <div style="font-size:10px; color:#4a5a8a; font-style:italic; text-align:center; margin-top:4px;">
        {subtext}
      </div>
    </div>
    """, container=container)

    # 4. Dealer Danger Radar
    gf_val = latest_metrics.get("gamma_flip", 0.0)
    gamma_regime = latest_metrics.get("gamma_regime", "ROTATION")
    is_danger = gamma_regime == "SHORT_GAMMA"
    danger_class = "radar-danger" if is_danger else ""
    gf_gap_pct = abs(spot_val - gf_val) / spot_val * 100 if spot_val > 0 else 0.0

    render_html(f"""
    <div class="glass-card {danger_class}">
      <div class="narrative-title" style="color: {'#ef4444' if is_danger else '#8b5cf6'}">
        {'⚠ DEALER DANGER ZONE' if is_danger else '🛡 GAMMA FLIP RADAR'}
      </div>
      <div style="font-size:11px; color:#cbd5e1; margin-bottom: 8px;">
        {f"Spot is currently trading in a <b>SHORT GAMMA</b> hedging regime. Dealer delta-hedging will expand volatility." if is_danger else "Spot is currently in a stable <b>LONG GAMMA</b> or transition zone. Volatility is structurally capped."}
      </div>
      <div style="display:flex; justify-content:space-between; font-size:11px; color:#a0aec0; font-family:'JetBrains Mono';">
        <span>REGIME FLIP TRIGGER:</span>
        <span style="color:#fbbf24; font-weight:bold;">₹{gf_val:,.1f}</span>
      </div>
      <div style="display:flex; justify-content:space-between; font-size:11px; color:#a0aec0; font-family:'JetBrains Mono'; margin-top: 4px;">
        <span>PROXIMITY TO PIVOT:</span>
        <span style="color:{'#ef4444' if is_danger else '#10b981'}; font-weight:bold;">{gf_gap_pct:.2f}% gap</span>
      </div>
    </div>
    """, container=container)

    # 5. EOD Flow Velocity Meter
    net_oi_shift = latest_metrics.get("net_inv_shift", 0.0)
    net_oi_lakh = net_oi_shift / 1e5
    vol_delta = latest_metrics.get("delta_volume", 0.0)
    vol_delta_lakh = vol_delta / 1e5

    pos_color = "#10b981" if net_oi_lakh >= 0 else "#ef4444"
    vol_color = "#10b981" if vol_delta_lakh >= 0 else "#ef4444"

    render_html(f"""
    <div class="glass-card">
      <div class="narrative-title">⚡ EOD FLOW VELOCITY</div>
      <div style="font-size:11px; color:#cbd5e1; margin-bottom: 10px;">
        Session velocity representing daily net inventory & volume shifts.
      </div>
      <div class="velocity-grid">
        <div class="velocity-card">
          <div class="velocity-label">NET INVENTORY SHIFT</div>
          <div class="velocity-value" style="color: {pos_color};">{net_oi_lakh:+.2f}L shares</div>
        </div>
        <div class="velocity-card">
          <div class="velocity-label">VOLUME DELTA</div>
          <div class="velocity-value" style="color: {vol_color};">{vol_delta_lakh:+.2f}L shares</div>
        </div>
      </div>
    </div>
    """, container=container)

def render_greeks_ledger(st_greeks, cmp_val):
    """
    Renders the custom HTML Greeks Ledger table.
    """
    import pandas as pd
    rows_ledger_html = ""
    for _, r in st_greeks.iterrows():
        strike_k = r["STRIKE_PR"]
        is_atm = abs(strike_k - cmp_val) / cmp_val <= 0.01
        row_class = "atm" if is_atm else r["OPTION_TYP"].lower()
        
        # Format Expiry beautifully
        expiry_dt = r.get("EXPIRY_DT", "")
        try:
            expiry_str = pd.to_datetime(expiry_dt).strftime('%d %b')
        except Exception:
            expiry_str = str(expiry_dt)
        
        cells = (
            f"<td>{strike_k:.0f}</td>"
            f"<td style='color: {'#58a6ff' if r['OPTION_TYP'] == 'CE' else '#f85149'}; font-weight: bold;'>{r['OPTION_TYP']}</td>"
            f"<td style='color: #7888aa; font-weight: 500;'>{expiry_str}</td>"
            f"<td>₹{float(r['CLOSE']):,.2f}</td>"
            f"<td style='color: {'#34d399' if r['DELTA'] >= 0 else '#f87171'}'>{float(r['DELTA']):+.3f}</td>"
            f"<td>{float(r['GAMMA']):.6f}</td>"
            f"<td>{float(r.get('VEGA', 0)):.3f}</td>"
            f"<td>{float(r.get('THETA', 0)):.3f}</td>"
            f"<td>{float(r.get('VANNA', 0)):.3f}</td>"
            f"<td>{float(r.get('CHARM', 0)):.5f}</td>"
            f"<td>{float(r['OPEN_INT'])/1000:,.1f}K</td>"
            f"<td>{float(r['CHG_IN_OI'])/1000:,.1f}K</td>"
        )
        rows_ledger_html += f"<tr class='{row_class}'>{cells}</tr>"
        
    st.markdown(f"""
    <div style="overflow-x:auto; border: 1px solid #141435; border-radius: 6px;">
      <table class="g-table">
        <thead>
          <tr>
            <th>STRIKE</th>
            <th>TYPE</th>
            <th>EXPIRY</th>
            <th>LTP</th>
            <th>DELTA (Δ)</th>
            <th>GAMMA (Γ)</th>
            <th>VEGA (V)</th>
            <th>THETA (Θ)</th>
            <th>VANNA</th>
            <th>CHARM</th>
            <th>OI (LOTS)</th>
            <th>ΔOI (LOTS)</th>
          </tr>
        </thead>
        <tbody>
          {rows_ledger_html}
        </tbody>
      </table>
    </div>
    """, unsafe_allow_html=True)

def render_market_breadth_panel(breadth_metrics: dict, container=st):
    """
    Renders an institutional-grade top-down Market-Wide Breadth Panel.
    """
    bull_pct = breadth_metrics.get("bullish_pct", 50.0)
    bear_pct = breadth_metrics.get("bearish_pct", 50.0)
    comp_pct = breadth_metrics.get("compression_pct", 0.0)
    exp_pct = breadth_metrics.get("expansion_pct", 0.0)
    trans_pct = breadth_metrics.get("transition_pct", 0.0)
    mean_rev_pct = breadth_metrics.get("mean_rev_pct", 0.0)
    tot_sym = breadth_metrics.get("total_symbols", 0)
    neutral_pct = max(0.0, round(100.0 - bull_pct - bear_pct, 1))

    render_html(f"""
    <div class="glass-card" style="margin-bottom: 20px;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
        <div class="narrative-title" style="font-size:12px; margin:0;">📊 DAILY GLOBAL MARKET BREADTH REGISTER</div>
        <span style="font-family:'JetBrains Mono'; font-size:9px; color:#4a5a8a;">UNIVERSE: {tot_sym} F&O SYMBOLS</span>
      </div>
      <div style="font-size:11px; color:#cbd5e1; margin-bottom: 12px;">
        Top-down snapshot of F&O inventory cycles & positioning trends.
      </div>

      <!-- Breadth progress bar -->
      <div style="display:flex; height:18px; border-radius:4px; overflow:hidden; background:#141435; margin-bottom:12px; border:1px solid #1c1c4f;">
        <div style="width:{bull_pct}%; background:#10b981; display:flex; align-items:center; justify-content:center; font-size:9px; font-weight:bold; color:#03030c;" title="Bullish Flow: {bull_pct}%">{bull_pct}%</div>
        <div style="width:{neutral_pct}%; background:#2a3a5a; display:flex; align-items:center; justify-content:center; font-size:9px; font-weight:bold; color:#c0ccdd;" title="Neutral Flow: {neutral_pct}%">{neutral_pct}%</div>
        <div style="width:{bear_pct}%; background:#ef4444; display:flex; align-items:center; justify-content:center; font-size:9px; font-weight:bold; color:#03030c;" title="Bearish Flow: {bear_pct}%">{bear_pct}%</div>
      </div>
      
      <div class="velocity-grid" style="grid-template-columns: repeat(4, 1fr); gap: 10px;">
        <div class="velocity-card" style="padding: 6px 10px;">
          <div class="velocity-label">COMPRESSION (COILS)</div>
          <div class="velocity-value" style="color: #a78bfa; font-size: 14px;">{comp_pct}%</div>
        </div>
        <div class="velocity-card" style="padding: 6px 10px;">
          <div class="velocity-label">EXPANSION (TRENDING)</div>
          <div class="velocity-value" style="color: #fbbf24; font-size: 14px;">{exp_pct}%</div>
        </div>
        <div class="velocity-card" style="padding: 6px 10px;">
          <div class="velocity-label">TRANSITION REGIMES</div>
          <div class="velocity-value" style="color: #38bdf8; font-size: 14px;">{trans_pct}%</div>
        </div>
        <div class="velocity-card" style="padding: 6px 10px;">
          <div class="velocity-label">MEAN REVERSION</div>
          <div class="velocity-value" style="color: #cbd5e1; font-size: 14px;">{mean_rev_pct}%</div>
        </div>
      </div>
    </div>
    """, container=container)

def render_daily_changes_panel(changes_list: list, container=st):
    """
    Renders an institutional change detector panel summarizing today's key wall shifts.
    """
    container.markdown('<p class="term-header">⚠️ TODAY\'S INSTITUTIONAL STRUCTURE CHANGES</p>', unsafe_allow_html=True)
    
    if not changes_list:
        container.markdown('<div class="alert-box info">ℹ️ No major wall migrations or gamma flip crossovers detected in today\'s session. Market structure is consolidating.</div>', unsafe_allow_html=True)
        return
        
    # Interactive filters deck (Search box, Tab selector, Slider)
    col_ctrl1, col_ctrl2, col_ctrl3 = container.columns([3, 5, 2])
    with col_ctrl1:
        search_query = st.text_input(
            "Search Symbol",
            value="",
            placeholder="🔍 Enter symbol (e.g. 360ONE)...",
            label_visibility="collapsed",
            key="structure_change_search"
        )
    with col_ctrl2:
        selected_category = st.radio(
            "Category",
            options=["🏆 All Shifts", "🟢 Support Shifts", "🔋 Regime Flips", "⚡ Resistance Shifts"],
            horizontal=True,
            label_visibility="collapsed",
            key="structure_change_category"
        )
    with col_ctrl3:
        depth_limit = st.slider(
            "Limit",
            min_value=5,
            max_value=max(len(changes_list), 10),
            value=min(15, len(changes_list)),
            step=5,
            label_visibility="collapsed",
            key="structure_change_limit"
        )
        
    # 1. Filter by category
    filtered = changes_list
    if selected_category == "🟢 Support Shifts":
        filtered = [c for c in filtered if c.get("type") in ["support_rise", "support_drop", "dual_wall_rise", "dual_wall_fall"]]
    elif selected_category == "🔋 Regime Flips":
        filtered = [c for c in filtered if c.get("type") in ["regime_flip_bullish", "regime_flip_bearish", "option_wall_pinch", "option_wall_expansion", "gex_intensity_explosion"]]
    elif selected_category == "⚡ Resistance Shifts":
        filtered = [c for c in filtered if c.get("type") in ["resistance_rise", "resistance_fall", "dual_wall_rise", "dual_wall_fall"]]
        
    # 2. Filter by search query
    if search_query:
        query = search_query.strip().upper()
        filtered = [c for c in filtered if query in c.get("symbol", "").upper()]

    if not filtered:
        container.markdown('<div class="alert-box info" style="margin-top: 10px;">ℹ️ No matching structural changes found. Adjust your filters or search query.</div>', unsafe_allow_html=True)
        return

    # Render changes in a beautiful glassmorphic container with strict scroll cap
    changes_html = ""
    for change in filtered[:depth_limit]:
        msg = change.get("msg", "")
        icon = change.get("icon", "🟢")
        rank = change.get("rank", 999)
        
        # Premium Rank Badge coloring based on urgency
        if rank <= 5:
            badge_style = "border: 1px solid #fbbf24; background: rgba(251, 191, 36, 0.15); color: #fbbf24;"
        elif rank <= 15:
            badge_style = "border: 1px solid #a78bfa; background: rgba(167, 139, 250, 0.15); color: #a78bfa;"
        else:
            badge_style = "border: 1px solid #475569; background: rgba(71, 85, 105, 0.15); color: #94a3b8;"
            
        rank_badge = f'<span style="padding: 2px 6px; border-radius: 4px; font-size: 9px; font-weight: bold; font-family: \'JetBrains Mono\'; {badge_style} margin-right: 10px;">#{rank:02d}</span>'
        
        item_html = f'<div class="alert-box info" style="border-left-color: #38bdf8; color: #cbd5e1; padding: 8px 12px; margin: 5px 0; font-size: 11px; display: flex; align-items: center; background: rgba(30, 41, 59, 0.3);"><span style="font-size: 13px; margin-right: 8px;">{icon}</span>{rank_badge}<span style="flex-grow: 1;">{msg}</span></div>'
        changes_html += item_html
        
    container.markdown(f'<div style="max-height: 380px; overflow-y: auto; padding-right: 6px; margin-top: 12px; scrollbar-width: thin; scrollbar-color: #3b82f6 #0f172a;">{changes_html}</div>', unsafe_allow_html=True)

def render_playbook_card(playbook: dict, container=st):
    """
    Renders the EOD quantitative playbook sheet for the active stock.
    """
    container.markdown('<p class="term-header">ACTIONABLE EOD QUANT PLAYBOOK</p>', unsafe_allow_html=True)
    
    bias = playbook.get("bias", "Neutral")
    try:
        trig = float(playbook.get("trigger_strike") or 0.0)
    except (ValueError, TypeError):
        trig = 0.0
        
    try:
        invalid = float(playbook.get("invalidation_strike") or 0.0)
    except (ValueError, TypeError):
        invalid = 0.0
    behavior = playbook.get("expected_behavior", "Mean Reversion")
    dealer = playbook.get("dealer_behavior", "Long Gamma")
    
    trig_str = f"₹{trig:,.1f}" if trig > 0 else "N/A (Range)"
    invalid_str = f"₹{invalid:,.1f}" if invalid > 0 else "N/A (Range)"
    
    bias_color = "#10b981" if "Bullish" in bias else "#ef4444" if "Bearish" in bias else "#fbbf24"
    
    render_html(f"""
    <div class="glass-card" style="border-color: {bias_color}; box-shadow: 0 0 10px rgba(59,79,216,0.1);">
      <div class="narrative-title" style="color: {bias_color}; display:flex; justify-content:space-between;">
        <span>📖 VANGUARD PLAYBOOK SHEET</span>
        <span style="background:rgba(255,255,255,0.05); padding:2px 8px; border-radius:3px; font-size:10px;">TACTICAL BLUEPRINT</span>
      </div>
      <div class="velocity-grid" style="grid-template-columns: repeat(5, 1fr); gap: 10px; margin-top: 10px;">
        <div class="velocity-card">
          <div class="velocity-label">TACTICAL BIAS</div>
          <div class="velocity-value" style="color:{bias_color};">{bias}</div>
        </div>
        <div class="velocity-card">
          <div class="velocity-label">TRIGGER STRIKE</div>
          <div class="velocity-value" style="color:#fbbf24; font-weight:bold;">{trig_str}</div>
        </div>
        <div class="velocity-card">
          <div class="velocity-label">INVALIDATION LEVEL</div>
          <div class="velocity-value" style="color:#f43f5e; font-weight:bold;">{invalid_str}</div>
        </div>
        <div class="velocity-card">
          <div class="velocity-label">EXPECTATION</div>
          <div class="velocity-value" style="color:#38bdf8;">{behavior}</div>
        </div>
        <div class="velocity-card">
          <div class="velocity-label">DEALER BEHAVIOR</div>
          <div class="velocity-value" style="color:#a78bfa;">{dealer}</div>
        </div>
      </div>
    </div>
    """, container=container)


def render_cm_breadth_panel(cm_breadth: dict, container=st, anchor_date: str = ""):
    """
    Cash Market Price Breadth panel — full NSE EQ universe (~2,400 symbols).
    DISTINCT from the F&O structural breadth panel above.
    cm_breadth: one row dict from daily_cm_breadth parquet/DuckDB.
    anchor_date: first date in the CM dataset (A/D line anchor), for display.
    """
    if not cm_breadth:
        container.markdown(
            '<div style="padding:10px;background:#141435;border-radius:6px;color:#a0aec0;font-size:11px;">'
            'ℹ️ Cash market breadth data not available for this session.</div>',
            unsafe_allow_html=True
        )
        return

    total    = cm_breadth.get("cm_total_symbols", 0)
    adv      = int(cm_breadth.get("cm_advances", 0))
    dec      = int(cm_breadth.get("cm_declines", 0))
    unch     = int(cm_breadth.get("cm_unchanged", 0))
    adv_pct  = float(cm_breadth.get("cm_advance_pct", 0.0))
    dec_pct  = round(dec / max(total, 1) * 100, 1)
    unch_pct = round(unch / max(total, 1) * 100, 1)
    ad_ratio = float(cm_breadth.get("cm_ad_ratio", 1.0))
    vol_ad   = float(cm_breadth.get("cm_volume_ad_ratio", 1.0))
    p20      = cm_breadth.get("cm_pct_above_20dma")
    p50      = cm_breadth.get("cm_pct_above_50dma")
    p200     = cm_breadth.get("cm_pct_above_200dma")
    rsi_ob   = cm_breadth.get("cm_pct_overbought_70")
    rsi_os   = cm_breadth.get("cm_pct_oversold_30")
    nh_val    = cm_breadth.get("cm_new_highs")
    nl_val    = cm_breadth.get("cm_new_lows")
    nh_nl_val = cm_breadth.get("cm_nh_nl_ratio")
    mcl       = cm_breadth.get("cm_mcclellan_osc", 0.0)
    ad_line   = cm_breadth.get("cm_ad_line", 0.0)
    t20_pct   = cm_breadth.get("cm_turnover_top20_pct")
    ca_cnt    = int(cm_breadth.get("cm_ca_count", 0))

    days_rem = cm_breadth.get("cm_days_remaining", 0)
    if days_rem is None:
        days_rem = 0

    if days_rem > 0:
        extreme_label = f"EXTREMES (building 52w baseline, {days_rem}d remaining)"
    else:
        extreme_label = "52-WEEK EXTREMES"

    if nh_val is None or nh_val != nh_val or nl_val is None or nl_val != nl_val:
        nh_str = "&#8212;"
        nl_str = "&#8212;"
        nh_nl_str = "&#8212;"
        nh_color = "#cbd5e1"
    else:
        nh_str = str(int(nh_val))
        nl_str = str(int(nl_val))
        nh_nl_f = float(nh_nl_val)
        nh_nl_str = f"{nh_nl_f:.2f}"
        nh_color = "#10b981" if nh_nl_f >= 2.0 else "#f59e0b" if nh_nl_f >= 0.5 else "#ef4444"

    ad_color  = "#10b981" if adv_pct >= 55 else "#f59e0b" if adv_pct >= 45 else "#ef4444"
    vol_color = "#10b981" if vol_ad >= 1.2 else "#f59e0b" if vol_ad >= 0.8 else "#ef4444"
    mcl_color = "#10b981" if (mcl or 0) >= 30 else "#f59e0b" if (mcl or 0) >= -30 else "#ef4444"
    adl_color = "#10b981" if (ad_line or 0) >= 0 else "#ef4444"

    def _bar(pct, color, label):
        is_val = pct is not None and pct == pct  # check None and NaN
        if not is_val:
            return (
                f'<div style="margin-bottom:8px;">'
                f'<div style="display:flex;justify-content:space-between;font-size:10px;color:#7888aa;margin-bottom:3px;">'
                f'<span>{label}</span><span style="color:#7888aa;font-weight:700;">&#8212;</span></div>'
                f'<div style="background:#141435;border-radius:3px;height:10px;overflow:hidden;border:1px dashed #1c1c4f;">'
                f'</div></div>'
            )
        v = round(float(pct), 1)
        return (
            f'<div style="margin-bottom:8px;">'
            f'<div style="display:flex;justify-content:space-between;font-size:10px;color:#a0aec0;margin-bottom:3px;">'
            f'<span>{label}</span><span style="color:{color};font-weight:700;">{v}%</span></div>'
            f'<div style="background:#141435;border-radius:3px;height:10px;overflow:hidden;border:1px solid #1c1c4f;">'
            f'<div style="width:{min(v, 100)}%;height:100%;background:{color};border-radius:3px;"></div>'
            f'</div></div>'
        )

    def _stat(label, val, color="#cbd5e1"):
        return (
            f'<div style="display:flex;justify-content:space-between;font-size:11px;'
            f'color:#a0aec0;font-family:\'JetBrains Mono\';margin-bottom:5px;">'
            f'<span>{label}</span>'
            f'<span style="color:{color};font-weight:700;">{val}</span></div>'
        )

    anchor_note = (
        f"Anchored at 0 on {anchor_date} (start of dataset)" if anchor_date
        else "Anchored at 0 on the first date of the dataset"
    )
    ca_note = f"&#9888; {ca_cnt} corporate action(s) adjusted today." if ca_cnt > 0 else ""
    t20_str = f"{t20_pct:.1f}%" if (t20_pct is not None and t20_pct == t20_pct) else "&#8212;"
    mcl_str = f"{round(mcl, 1)}" if (mcl is not None and mcl == mcl) else "&#8212;"
    adl_str = f"{int(ad_line):+,}" if (ad_line is not None and ad_line == ad_line) else "&#8212;"

    html = f"""
    <div class="glass-card" style="margin-bottom:16px;">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
        <div class="narrative-title" style="font-size:12px;margin:0;">&#128202; CASH MARKET PRICE BREADTH</div>
        <span style="font-family:'JetBrains Mono';font-size:9px;color:#4a5a8a;">NSE EQ &#8212; {total:,} SYMBOLS</span>
      </div>
      <div style="font-size:10px;color:#4a5a8a;margin-bottom:12px;font-style:italic;">
        Price-based breadth across all NSE equity stocks. Distinct from F&amp;O structural breadth. {ca_note}
      </div>
      <div style="display:flex;height:20px;border-radius:4px;overflow:hidden;background:#141435;margin-bottom:12px;border:1px solid #1c1c4f;">
        <div style="width:{adv_pct}%;background:#10b981;display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:bold;color:#03030c;" title="Advances: {adv}">{adv_pct}%</div>
        <div style="width:{unch_pct}%;background:#2a3a5a;" title="Unchanged: {unch}"></div>
        <div style="width:{dec_pct}%;background:#ef4444;display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:bold;color:#03030c;" title="Declines: {dec}">{dec_pct}%</div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px;">
        <div style="background:#0d0d2b;border:1px solid #1c1c4f;border-radius:6px;padding:10px;">
          <div style="font-size:9px;color:#7888aa;text-transform:uppercase;margin-bottom:6px;">ADVANCES / DECLINES</div>
          {_stat("Advances", f"{adv:,}", "#10b981")}
          {_stat("Declines", f"{dec:,}", "#ef4444")}
          {_stat("A/D Ratio", f"{ad_ratio:.2f}", ad_color)}
          {_stat("Vol A/D Ratio", f"{vol_ad:.2f}", vol_color)}
        </div>
        <div style="background:#0d0d2b;border:1px solid #1c1c4f;border-radius:6px;padding:10px;">
          <div style="font-size:9px;color:#7888aa;text-transform:uppercase;margin-bottom:6px;">{extreme_label}</div>
          {_stat("New Highs", nh_str, "#10b981")}
          {_stat("New Lows", nl_str, "#ef4444")}
          {_stat("NH/NL Ratio", nh_nl_str, nh_color)}
          {_stat("McClellan Osc", mcl_str, mcl_color)}
        </div>
      </div>
      <div style="background:#0d0d2b;border:1px solid #1c1c4f;border-radius:6px;padding:10px;margin-bottom:10px;">
        <div style="font-size:9px;color:#7888aa;text-transform:uppercase;margin-bottom:8px;">DMA PARTICIPATION</div>
        {_bar(p20,  "#38bdf8", "% Above 20-DMA  (short-term)")}
        {_bar(p50,  "#a78bfa", "% Above 50-DMA  (medium-term)")}
        {_bar(p200, "#10b981", "% Above 200-DMA (structural)")}
      </div>
      <div style="background:#0d0d2b;border:1px solid #1c1c4f;border-radius:6px;padding:10px;margin-bottom:10px;">
        <div style="font-size:9px;color:#7888aa;text-transform:uppercase;margin-bottom:8px;">RSI BREADTH (14-PERIOD)</div>
        {_bar(rsi_ob, "#fbbf24", "% Overbought (RSI &gt; 70)")}
        {_bar(rsi_os, "#ef4444", "% Oversold (RSI &lt; 30)")}
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
        <div style="background:#0d0d2b;border:1px solid #1c1c4f;border-radius:6px;padding:10px;">
          <div style="font-size:9px;color:#7888aa;text-transform:uppercase;margin-bottom:6px;">CUMULATIVE A/D LINE</div>
          <div style="font-size:20px;font-weight:700;color:{adl_color};font-family:'JetBrains Mono';">{adl_str}</div>
          <div style="font-size:9px;color:#4a5a8a;margin-top:3px;">{anchor_note}</div>
        </div>
        <div style="background:#0d0d2b;border:1px solid #1c1c4f;border-radius:6px;padding:10px;">
          <div style="font-size:9px;color:#7888aa;text-transform:uppercase;margin-bottom:6px;">TURNOVER CONCENTRATION</div>
          <div style="font-size:20px;font-weight:700;color:#fbbf24;font-family:'JetBrains Mono';">{t20_str}</div>
          <div style="font-size:9px;color:#4a5a8a;margin-top:3px;">Top-20 stocks share of total market turnover</div>
        </div>
      </div>
    </div>
    """
    render_html(html, container=container)
