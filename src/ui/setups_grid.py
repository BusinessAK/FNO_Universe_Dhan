"""
Vanguard Institutional Terminal - Tiered Setup Catalog Grid Component
"""
import streamlit as st
from src.core.setup_detector import SETUP_REGISTRY
from src.ui.cards import format_score

def render_setup_card(s_ticker: str, s_m: dict, s_type: str, select_stock_callback):
    """
    Renders a single data-driven setup card.
    """
    score_badge = format_score(s_m.get('ifs_score', 0.0))
    cfg = SETUP_REGISTRY.get(s_type, {})
    title = cfg.get("title", s_type.replace("_", " ").title())
    
    # Pre-calculated Actionable EOD Playbook details
    playbook = s_m.get("playbook", {})
    bias = playbook.get("bias", "Neutral")
    trig_strike = playbook.get("trigger_strike", 0.0)
    trig_strike_str = f"₹{trig_strike:,.1f}" if trig_strike > 0 else "N/A"
    invalid_strike = playbook.get("invalidation_strike", 0.0)
    invalid_strike_str = f"₹{invalid_strike:,.1f}" if invalid_strike > 0 else "N/A"
    expected_behavior = playbook.get("expected_behavior", "Mean Reversion")
    
    spot_price = s_m.get('spot_close', 0.0)
    spot_price_str = f"₹{spot_price:,.2f}" if spot_price > 0 else "N/A"
    
    # Calculate boundary alignment status
    status_str = "Neutral"
    status_color = "#7888aa"  # Slate grey
    status_bg = "rgba(120, 136, 170, 0.08)"
    status_border = "rgba(120, 136, 170, 0.2)"
    
    if spot_price > 0:
        if "Bullish" in bias:
            if trig_strike > 0 and spot_price >= trig_strike:
                status_str = "🟢 Triggered"
                status_color = "#10b981"
                status_bg = "rgba(16, 185, 129, 0.08)"
                status_border = "rgba(16, 185, 129, 0.2)"
            elif invalid_strike > 0 and spot_price <= invalid_strike:
                status_str = "🔴 Invalidated"
                status_color = "#ef4444"
                status_bg = "rgba(239, 68, 68, 0.08)"
                status_border = "rgba(239, 68, 68, 0.2)"
            else:
                status_str = "⏳ Waiting"
                status_color = "#fbbf24"
                status_bg = "rgba(251, 191, 36, 0.08)"
                status_border = "rgba(251, 191, 36, 0.2)"
        elif "Bearish" in bias:
            if trig_strike > 0 and spot_price <= trig_strike:
                status_str = "🟢 Triggered"
                status_color = "#10b981"
                status_bg = "rgba(16, 185, 129, 0.08)"
                status_border = "rgba(16, 185, 129, 0.2)"
            elif invalid_strike > 0 and spot_price >= invalid_strike:
                status_str = "🔴 Invalidated"
                status_color = "#ef4444"
                status_bg = "rgba(239, 68, 68, 0.08)"
                status_border = "rgba(239, 68, 68, 0.2)"
            else:
                status_str = "⏳ Waiting"
                status_color = "#fbbf24"
                status_bg = "rgba(251, 191, 36, 0.08)"
                status_border = "rgba(251, 191, 36, 0.2)"
        elif bias == "Volatility Expansion":
            # Symmetric breakout
            if trig_strike > 0 and spot_price >= trig_strike:
                status_str = "🟢 Bullish Breakout"
                status_color = "#10b981"
                status_bg = "rgba(16, 185, 129, 0.08)"
                status_border = "rgba(16, 185, 129, 0.2)"
            elif invalid_strike > 0 and spot_price <= invalid_strike:
                status_str = "🔴 Bearish Breakdown"
                status_color = "#ef4444"
                status_bg = "rgba(239, 68, 68, 0.08)"
                status_border = "rgba(239, 68, 68, 0.2)"
            else:
                status_str = "🌀 Coiling"
                status_color = "#a78bfa"
                status_bg = "rgba(167, 139, 250, 0.08)"
                status_border = "rgba(167, 139, 250, 0.2)"
        else:
            status_str = "⇅ Monitoring"
            status_color = "#38bdf8"
            status_bg = "rgba(56, 189, 248, 0.08)"
            status_border = "rgba(56, 189, 248, 0.2)"
            
    bias_color = "#10b981" if "Bullish" in bias else "#ef4444" if "Bearish" in bias else "#fbbf24"
    
    st.markdown(f"""
    <div class="setup-card">
        <div class="card-header-flex">
            <span class="card-ticker">{s_ticker}</span>
            <span style="background:{status_bg}; color:{status_color}; border:1px solid {status_border}; font-size:9.5px; font-weight:700; padding:2px 6px; border-radius:4px; letter-spacing:0.5px; font-family:'Inter Tight', sans-serif;">{status_str}</span>
            {score_badge}
        </div>
        <div class="card-desc">{title}</div>
        <div class="card-stat-row"><span>Latest Price:</span><span class="card-stat-val" style="color:#e2e8f0; font-weight:bold;">{spot_price_str}</span></div>
        <div class="card-stat-row"><span>Tactical Bias:</span><span class="card-stat-val" style="color:{bias_color}; font-weight:bold;">{bias}</span></div>
        <div class="card-stat-row"><span>Expected Behavior:</span><span class="card-stat-val" style="color:#6ee7b7;">{expected_behavior}</span></div>
        <div class="card-stat-row"><span>Trigger Strike:</span><span class="card-stat-val" style="color:#fbbf24; font-weight:bold;">{trig_strike_str}</span></div>
        <div class="card-stat-row"><span>Invalidation Pivot:</span><span class="card-stat-val" style="color:#f43f5e;">{invalid_strike_str}</span></div>
        <div class="card-stat-row"><span>Priority Score (Pty):</span><span class="card-stat-val" style="color:#a78bfa; font-weight:bold;">{s_m.get('priority_score', 0.0):.1f}</span></div>
    </div>
    """, unsafe_allow_html=True)
    
    # Render navigation button (compliant with on_click callback state updates)
    st.button(f"Analyze {s_ticker}", key=f"{s_type.lower()}_btn_{s_ticker}", use_container_width=True, on_click=select_stock_callback, args=(s_ticker,))

def render_setups_grid(categorized_setups: dict, select_stock_callback):
    """
    Renders the setup setups catalog deck in 3 columns (Tier 1, 2, 3).
    """
    st.markdown('<p class="term-header">SECTION B — VANGUARD QUANTITATIVE SETUP ENGINE</p>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)

    # 1. TIER 1 — EXPANSION SETUPS
    with c1:
        st.markdown('<h4 style="color:#a78bfa;border-bottom:1px solid #141435;padding-bottom:5px;">⚡ TIER 1 — EXPANSION SETUPS</h4>', unsafe_allow_html=True)
        st.markdown('<p style="font-size:10px;color:#7888aa;text-transform:uppercase;letter-spacing:0.5px;">Short-term high momentum volatility breakouts</p>', unsafe_allow_html=True)
        
        # Gamma Squeezes
        st.markdown('<p style="font-size:11px;font-weight:bold;color:#fca5a5;margin:10px 0 5px;">🔥 GAMMA SQUEEZE CANDIDATES</p>', unsafe_allow_html=True)
        sq_items = categorized_setups.get("GAMMA_SQUEEZE", [])
        if not sq_items:
            st.markdown('<p style="font-size:11px;color:#4a5a8a;font-style:italic;">No active gamma squeeze triggers today.</p>', unsafe_allow_html=True)
        else:
            for sym, s_m in sq_items[:3]:
                render_setup_card(sym, s_m, "GAMMA_SQUEEZE", select_stock_callback)
                
        # Volatility Coils
        st.markdown('<p style="font-size:11px;font-weight:bold;color:#a78bfa;margin:15px 0 5px;">🌀 VOLATILITY EXPANSION COILS</p>', unsafe_allow_html=True)
        vc_items = categorized_setups.get("VOLATILITY_COIL", [])
        if not vc_items:
            st.markdown('<p style="font-size:11px;color:#4a5a8a;font-style:italic;">No compressed volatility coils observed.</p>', unsafe_allow_html=True)
        else:
            for sym, s_m in vc_items[:3]:
                render_setup_card(sym, s_m, "VOLATILITY_COIL", select_stock_callback)

    # 2. TIER 2 — SUPPORT/DEFENSE SETUPS
    with c2:
        st.markdown('<h4 style="color:#34d399;border-bottom:1px solid #141435;padding-bottom:5px;">🛡️ TIER 2 — SUPPORT/DEFENSE SETUPS</h4>', unsafe_allow_html=True)
        st.markdown('<p style="font-size:10px;color:#7888aa;text-transform:uppercase;letter-spacing:0.5px;">Institutional floors and dealer hedging zones</p>', unsafe_allow_html=True)
        
        # Floor Bounces
        st.markdown('<p style="font-size:11px;font-weight:bold;color:#6ee7b7;margin:10px 0 5px;">🛡️ INSTITUTIONAL FLOOR BOUNCE</p>', unsafe_allow_html=True)
        fb_items = categorized_setups.get("FLOOR_BOUNCE", [])
        if not fb_items:
            st.markdown('<p style="font-size:11px;color:#4a5a8a;font-style:italic;">No symbols at institutional floor bounds.</p>', unsafe_allow_html=True)
        else:
            for sym, s_m in fb_items[:3]:
                render_setup_card(sym, s_m, "FLOOR_BOUNCE", select_stock_callback)
                
        # Dealer Defense
        st.markdown('<p style="font-size:11px;font-weight:bold;color:#38bdf8;margin:15px 0 5px;">🧲 DEALER DEFENSE PIN ZONES</p>', unsafe_allow_html=True)
        dd_items = categorized_setups.get("DEALER_DEFENSE", [])
        if not dd_items:
            st.markdown('<p style="font-size:11px;color:#4a5a8a;font-style:italic;">No dealer straddle magnet pins detected.</p>', unsafe_allow_html=True)
        else:
            for sym, s_m in dd_items[:3]:
                render_setup_card(sym, s_m, "DEALER_DEFENSE", select_stock_callback)

    # 3. TIER 3 — REGIME CHANGE SETUPS
    with c3:
        st.markdown('<h4 style="color:#f59e0b;border-bottom:1px solid #141435;padding-bottom:5px;">🔄 TIER 3 — REGIME CHANGE SETUPS</h4>', unsafe_allow_html=True)
        st.markdown('<p style="font-size:10px;color:#7888aa;text-transform:uppercase;letter-spacing:0.5px;">Long-term institutional repositioning signals</p>', unsafe_allow_html=True)
        
        # Regime Shifts
        st.markdown('<p style="font-size:11px;font-weight:bold;color:#fbbf24;margin:10px 0 5px;">🔄 REGIME SHIFT CROSSOVERS</p>', unsafe_allow_html=True)
        rs_items = categorized_setups.get("REGIME_SHIFT", [])
        if not rs_items:
            st.markdown('<p style="font-size:11px;color:#4a5a8a;font-style:italic;">No recent regime flip crossovers detected.</p>', unsafe_allow_html=True)
        else:
            for sym, s_m in rs_items[:3]:
                render_setup_card(sym, s_m, "REGIME_SHIFT", select_stock_callback)
                
        # Support Floor Migrations
        st.markdown('<p style="font-size:11px;font-weight:bold;color:#f59e0b;margin:15px 0 5px;">🚀 INVENTORY MIGRATION BREAKOUTS</p>', unsafe_allow_html=True)
        im_items = categorized_setups.get("INVENTORY_MIGRATION", [])
        if not im_items:
            st.markdown('<p style="font-size:11px;color:#4a5a8a;font-style:italic;">No active inventory wall migrations.</p>', unsafe_allow_html=True)
        else:
            for sym, s_m in im_items[:3]:
                render_setup_card(sym, s_m, "INVENTORY_MIGRATION", select_stock_callback)
