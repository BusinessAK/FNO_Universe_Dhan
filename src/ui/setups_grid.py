"""
Vanguard Institutional Terminal - Tiered Setup Catalog Grid Component
"""
import streamlit as st
from src.config.setup_registry import SETUP_REGISTRY
from src.core.config import INDEX_SYMBOLS as _INDEX_SYMBOLS
from src.ui.cards import format_score, render_html


# ─────────────────────────────────────────────────────────────────────────────
# STRUCTURE FLIP WATCH — helpers & renderer
# ─────────────────────────────────────────────────────────────────────────────

def _flip_confidence_badge(confidence: float, strength: str) -> str:
    """Returns an HTML badge for flip confidence + strength."""
    if strength == "STRONG":
        color = "#10b981"
        bg    = "rgba(16, 185, 129, 0.10)"
        border = "rgba(16, 185, 129, 0.30)"
    elif strength == "MODERATE":
        color = "#fbbf24"
        bg    = "rgba(251, 191, 36, 0.10)"
        border = "rgba(251, 191, 36, 0.30)"
    else:
        color = "#7888aa"
        bg    = "rgba(120, 136, 170, 0.08)"
        border = "rgba(120, 136, 170, 0.20)"
    return (
        f'<span style="background:{bg}; color:{color}; border:1px solid {border}; '
        f'font-size:9px; font-weight:700; padding:2px 7px; border-radius:4px; '
        f'font-family:\'Inter Tight\', sans-serif; white-space:nowrap;">'
        f'{strength} · {confidence:.1f}%</span>'
    )


def _render_flip_card(row: dict, select_stock_callback, prefix: str = "") -> None:
    """Renders a single structural flip card."""
    symbol       = str(row.get("symbol", ""))
    flip_type    = str(row.get("structure_flip", "NONE"))
    prev_bias    = str(row.get("prev_structural_bias", ""))
    curr_bias    = str(row.get("structural_bias", ""))
    prev_polarity = str(row.get("prev_polarity", ""))
    curr_polarity = str(row.get("curr_polarity", ""))
    confidence   = float(row.get("flip_confidence", 0.0))
    strength     = str(row.get("flip_strength", "WEAK"))
    spot         = float(row.get("spot_close", 0.0))
    spot_chg     = float(row.get("spot_change_pct", 0.0))
    ifs          = float(row.get("ifs_score", 0.0))
    sector       = str(row.get("sector") or "")
    gamma_regime = str(row.get("gamma_regime", ""))

    is_b2b = (flip_type == "BEARISH_TO_BULLISH")

    if is_b2b:
        card_color   = "#10b981"
        flip_icon    = "🔄"
        flip_label   = "BEAR → BULL"
        arrow_html   = (
            '<span style="color:#ef4444;font-weight:700;">BEARISH</span>'
            ' &nbsp;→&nbsp; '
            '<span style="color:#10b981;font-weight:700;">BULLISH</span>'
        )
        border_grad  = "linear-gradient(135deg, rgba(239,68,68,0.25) 0%, rgba(16,185,129,0.35) 100%)"
    else:
        card_color   = "#ef4444"
        flip_icon    = "🔻"
        flip_label   = "BULL → BEAR"
        arrow_html   = (
            '<span style="color:#10b981;font-weight:700;">BULLISH</span>'
            ' &nbsp;→&nbsp; '
            '<span style="color:#ef4444;font-weight:700;">BEARISH</span>'
        )
        border_grad  = "linear-gradient(135deg, rgba(16,185,129,0.25) 0%, rgba(239,68,68,0.35) 100%)"

    spot_str    = f"₹{spot:,.2f}" if spot > 0 else "N/A"
    chg_sign    = "+" if spot_chg >= 0 else ""
    chg_color   = "#10b981" if spot_chg >= 0 else "#ef4444"
    ifs_color   = "#10b981" if ifs >= 0 else "#ef4444"
    conf_badge  = _flip_confidence_badge(confidence, strength)

    sector_html = (
        f'<span style="background:rgba(120,136,170,0.10); color:#94a3b8; '
        f'font-size:8.5px; font-weight:600; padding:1.5px 5px; border-radius:3px; '
        f'font-family:\'IBM Plex Sans\', sans-serif;">{sector}</span>'
        if sector else ""
    )

    regime_html = ""
    if gamma_regime:
        rg_color = "#10b981" if gamma_regime == "LONG_GAMMA" else "#ef4444" if gamma_regime == "SHORT_GAMMA" else "#fbbf24"
        rg_label = gamma_regime.replace("_", " ")
        regime_html = (
            f'<span style="background:rgba(0,0,0,0.15); color:{rg_color}; '
            f'font-size:8px; font-weight:600; padding:1.5px 5px; border-radius:3px; '
            f'font-family:\'IBM Plex Sans\', sans-serif; border:1px solid {rg_color}33;">'
            f'{rg_label}</span>'
        )

    render_html(f"""
    <div style="
        background: rgba(13,13,30,0.85);
        border: 1px solid {card_color}44;
        border-left: 3.5px solid {card_color};
        border-radius: 8px;
        padding: 10px 12px 8px 12px;
        margin-bottom: 8px;
        box-shadow: 0 0 14px {card_color}18, inset 3px 0 8px rgba(0,0,0,0.25);
        position: relative;
        overflow: hidden;
    ">
        <!-- gradient sweep top bar -->
        <div style="
            position:absolute; top:0; left:0; right:0; height:2px;
            background:{border_grad};
        "></div>

        <!-- Header row -->
        <div style="display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:6px; margin-bottom:7px;">
            <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
                <span style="font-size:13px; font-weight:800; color:#e2e8f0;
                             font-family:'Inter Tight', sans-serif; letter-spacing:0.3px;">
                    {symbol}
                </span>
                {sector_html}
                {regime_html}
            </div>
            <div style="display:flex; align-items:center; gap:5px; flex-wrap:wrap;">
                {conf_badge}
                <span style="background:rgba(255,255,255,0.04); color:{card_color};
                             font-size:9px; font-weight:700; padding:2px 7px;
                             border-radius:4px; border:1px solid {card_color}44;
                             font-family:'Inter Tight', sans-serif; letter-spacing:0.4px;">
                    {flip_icon} {flip_label}
                </span>
            </div>
        </div>

        <!-- Flip direction row -->
        <div style="font-size:10.5px; color:#94a3b8; margin-bottom:6px;
                    font-family:'Inter Tight', sans-serif; display:flex; align-items:center; gap:4px;">
            Structure: &nbsp; {arrow_html}
        </div>

        <!-- Prev bias → Curr bias -->
        <div style="background:rgba(0,0,0,0.20); border-radius:5px; padding:6px 8px;
                    margin-bottom:6px; font-family:'IBM Plex Mono', monospace; font-size:9px;">
            <div style="color:#64748b; margin-bottom:3px; font-size:8px; letter-spacing:0.5px; text-transform:uppercase;">Yesterday</div>
            <div style="color:#ef4444aa;">{prev_bias or '—'} {f'({prev_polarity})' if prev_polarity else ''}</div>
            <div style="color:#64748b; margin:3px 0; font-size:8px; letter-spacing:0.5px; text-transform:uppercase;">Today</div>
            <div style="color:{card_color};">{curr_bias or '—'} {f'({curr_polarity})' if curr_polarity else ''}</div>
        </div>

        <!-- Metric row -->
        <div style="display:flex; gap:12px; flex-wrap:wrap; font-family:'Inter Tight', sans-serif; font-size:9.5px;">
            <div>
                <span style="color:#64748b;">Price</span>&nbsp;
                <span style="color:#e2e8f0; font-weight:700;">{spot_str}</span>
                &nbsp;<span style="color:{chg_color}; font-weight:600;">({chg_sign}{spot_chg:.2f}%)</span>
            </div>
            <div>
                <span style="color:#64748b;">IFS</span>&nbsp;
                <span style="color:{ifs_color}; font-weight:700;">{ifs:+.1f}</span>
            </div>
        </div>
    </div>
    """)
    st.button(
        f"Analyze {symbol}",
        key=f"{prefix}flip_btn_{symbol}",
        use_container_width=True,
        on_click=select_stock_callback,
        args=(symbol,)
    )


# Per-session flip cache lives in st.session_state (module globals are shared
# across all Streamlit sessions and would leak another session's date).
# Shape: {"date": <active_date>, "flips": {symbol: flip_event_dict}}
_FLIP_CACHE_KEY = "_structure_flip_cache"


def _get_cached_flips(active_date: str = None) -> dict:
    """Returns symbol->flip mapping for the given date ('' / None = whatever is cached)."""
    cached = st.session_state.get(_FLIP_CACHE_KEY, {})
    if active_date and cached.get("date") != active_date:
        return {}
    return cached.get("flips", {})


def _compute_flips_live(session_history: dict, active_date: str, min_confidence: float) -> list:
    """
    Computes structure flips live from session_history — no DB recompile needed.
    Iterates all symbols, builds their 2-session history slice ending on active_date,
    runs detect_structure_flip(), and returns a list of flip event dicts.
    """
    from src.core.longitudinal import LongitudinalEngine
    from src.config.sector_mapping import get_sector
    eng = LongitudinalEngine()

    results = []
    for sym, date_map in session_history.items():
        sorted_dates = sorted(date_map.keys())
        if active_date not in sorted_dates:
            continue
        idx = sorted_dates.index(active_date)
        if idx == 0:
            continue  # no previous session to compare

        prev_date = sorted_dates[idx - 1]
        prev_day  = date_map[prev_date]
        curr_day  = date_map[active_date]

        # Attach structural_bias to each slice (needed by _bias_polarity)
        # If the old JSON doesn't have structural_bias key, derive from ifs_score
        if not prev_day.get("structural_bias"):
            prev_ifs = float(prev_day.get("ifs_score", 0.0))
            prev_day = dict(prev_day)
            prev_day["structural_bias"] = "Support Building" if prev_ifs > 15 else "Support Weakening" if prev_ifs < -15 else "Dealer Controlled"
        if not curr_day.get("structural_bias"):
            curr_ifs = float(curr_day.get("ifs_score", 0.0))
            curr_day = dict(curr_day)
            curr_day["structural_bias"] = "Support Building" if curr_ifs > 15 else "Support Weakening" if curr_ifs < -15 else "Dealer Controlled"

        flip = eng.detect_structure_flip([prev_day, curr_day])

        if flip["flip_type"] == "NONE":
            continue
        if flip["flip_confidence"] < min_confidence:
            continue

        results.append({
            "symbol":               sym,
            "sector":               get_sector(sym),
            "date":                 active_date,
            "structure_flip":       flip["flip_type"],
            "prev_structural_bias": flip["prev_bias"],
            "structural_bias":      flip["curr_bias"],
            "prev_polarity":        flip["prev_polarity"],
            "curr_polarity":        flip["curr_polarity"],
            "flip_confidence":      flip["flip_confidence"],
            "flip_strength":        flip["flip_strength"],
            "spot_close":           float(curr_day.get("spot_close", 0.0)),
            "spot_change_pct":      float(curr_day.get("spot_change_pct", 0.0)),
            "ifs_score":            float(curr_day.get("ifs_score", 0.0)),
            "gamma_regime":         str(curr_day.get("gamma_regime", "")),
        })

    # Sort by flip_confidence descending
    results.sort(key=lambda r: r["flip_confidence"], reverse=True)

    return results


def render_structure_flip_watch(
    active_date: str,
    select_stock_callback,
    session_history: dict = None,
    selected_sectors: list = None,
) -> None:
    """
    Renders the Structure Flip Watch panel — a real-time screener showing
    stocks that have flipped structural polarity vs. the prior session.
    Computes flips live from session_history (no DB recompile needed).
    """
    if selected_sectors is None:
        selected_sectors = ["ALL"]
    if session_history is None:
        session_history = {}

    st.markdown(
        '<p class="term-header">🔄 STRUCTURE FLIP WATCH — BULL ↔ BEAR TRANSITION RADAR</p>',
        unsafe_allow_html=True,
    )

    # ── Controls ────────────────────────────────────────────────────────────
    ctrl_col1, _ = st.columns([2, 3])
    with ctrl_col1:
        min_conf = st.slider(
            "Min Confidence",
            min_value=0,
            max_value=90,
            value=25,
            step=5,
            key="flip_watch_min_conf",
            help="Filter flips by minimum confidence score (0–100)",
        )

    # ── Load flips: compiled DB first, live computation as fallback ────────
    # The DB carries pre-computed flip columns since the compiler writes them;
    # the live path covers older databases without those columns.
    from src.services.database_service import DatabaseService
    df_flips = DatabaseService().get_structure_flips(active_date, float(min_conf))
    if not df_flips.empty:
        all_flips = df_flips.to_dict(orient="records")
    else:
        all_flips = _compute_flips_live(session_history, active_date, float(min_conf))

    # Populate per-session cache for setup card badge lookups
    st.session_state[_FLIP_CACHE_KEY] = {
        "date": active_date,
        "flips": {r["symbol"]: r for r in all_flips},
    }

    # Apply sector filter
    if selected_sectors and "ALL" not in selected_sectors:
        all_flips = [r for r in all_flips if r.get("sector") in selected_sectors]

    b2b_flips = [r for r in all_flips if r.get("structure_flip") == "BEARISH_TO_BULLISH"]
    b2bear_flips = [r for r in all_flips if r.get("structure_flip") == "BULLISH_TO_BEARISH"]

    if not all_flips:
        st.markdown(
            '<p style="font-size:11px;color:#4a5a8a;font-style:italic;padding:4px 0 12px;">'
            'No structure flips detected for this session at the selected confidence threshold.</p>',
            unsafe_allow_html=True,
        )
        st.markdown('<hr style="margin: 4px 0 18px 0; border-color: #141435;">', unsafe_allow_html=True)
        return

    # ── Summary metrics ─────────────────────────────────────────────────────
    total_flips = len(all_flips)
    strong_flips = sum(1 for r in all_flips if r.get("flip_strength") == "STRONG")

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Total Flips", total_flips)
    with m2:
        st.metric("🟢 Bear → Bull", len(b2b_flips))
    with m3:
        st.metric("🔴 Bull → Bear", len(b2bear_flips))
    with m4:
        st.metric("⚡ Strong Signals", strong_flips)

    st.markdown("<div style='margin-top:10px;'></div>", unsafe_allow_html=True)

    # ── Two-column flip card layout ─────────────────────────────────────────
    left_col, right_col = st.columns(2)

    with left_col:
        st.markdown(
            '<p style="font-size:11px; font-weight:700; color:#10b981; margin-bottom:8px; '
            'letter-spacing:0.5px;">🟢 BEARISH → BULLISH STRUCTURAL FLIP</p>',
            unsafe_allow_html=True,
        )
        with st.container(height=420):
            if not b2b_flips:
                st.markdown(
                    '<p style="font-size:11px;color:#4a5a8a;font-style:italic;">No Bear→Bull flips this session.</p>',
                    unsafe_allow_html=True,
                )
            else:
                for row in b2b_flips:
                    _render_flip_card(row, select_stock_callback, prefix="b2b_")

    with right_col:
        st.markdown(
            '<p style="font-size:11px; font-weight:700; color:#ef4444; margin-bottom:8px; '
            'letter-spacing:0.5px;">🔴 BULLISH → BEARISH STRUCTURAL FLIP</p>',
            unsafe_allow_html=True,
        )
        with st.container(height=420):
            if not b2bear_flips:
                st.markdown(
                    '<p style="font-size:11px;color:#4a5a8a;font-style:italic;">No Bull→Bear flips this session.</p>',
                    unsafe_allow_html=True,
                )
            else:
                for row in b2bear_flips:
                    _render_flip_card(row, select_stock_callback, prefix="b2bear_")

    st.markdown('<hr style="margin: 18px 0; border-color: #141435;">', unsafe_allow_html=True)



@st.cache_data(ttl=60, show_spinner=False)
def _load_daily_catalysts() -> dict:
    """Loads compiled catalysts once, caching results for 1 minute."""
    import json
    import os
    path = os.path.join("data", "compiled", "daily_catalysts.json")
    mapping = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                for cat in data.get("catalysts", []):
                    impact = cat.get("impact", "NEUTRAL")
                    for sym in cat.get("affected_symbols", []):
                        if sym:
                            mapping[sym.strip().upper()] = impact
        except Exception:
            pass
    return mapping

def _get_setup_status_info(spot_price: float, bias: str, trig_strike: float, invalid_strike: float) -> tuple[str, str, str, str]:
    """Returns (status_str, color, bg, border)."""
    status_str = "Neutral"
    status_color = "#7888aa"
    status_bg = "rgba(120, 136, 170, 0.08)"
    status_border = "rgba(120, 136, 170, 0.2)"
    
    if spot_price > 0:
        if "Bullish" in bias or bias in ("Strong Bullish Momentum", "Bullish Accumulation", "Bullish Breakout"):
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
        elif "Bearish" in bias or bias in ("Strong Bearish Momentum", "Bearish Breakdown", "Bearish Consolidation"):
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
                status_str = "🌀 Coiling"
                status_color = "#a78bfa"
                status_bg = "rgba(167, 139, 250, 0.08)"
                status_border = "rgba(167, 139, 250, 0.2)"
        else:
            status_str = "⇅ Monitoring"
            status_color = "#38bdf8"
            status_bg = "rgba(56, 189, 248, 0.08)"
            status_border = "rgba(56, 189, 248, 0.2)"
    return status_str, status_color, status_bg, status_border

def render_setup_card(s_ticker: str, s_m: dict, s_type: str, select_stock_callback, prefix: str = ""):
    """
    Renders a single data-driven setup card.
    """
    score_badge = format_score(s_m.get('ifs_score', 0.0))
    cfg = SETUP_REGISTRY.get(s_type, {})
    title = cfg.get("title", s_type.replace("_", " ").title())
    color = cfg.get("color", "#7888aa")
    icon = cfg.get("icon", "⇅")
    
    # Pre-calculated Actionable EOD Playbook details
    playbook = dict(s_m.get("playbook", {}))
    ifs_score = float(s_m.get("ifs_score") or 0.0)
    spot_val = float(s_m.get("spot_close") or 0.0)
    cw_val = float(s_m.get("call_wall") or 0.0)
    pw_val = float(s_m.get("put_wall") or 0.0)
    
    bias = playbook.get("bias", "Neutral")
    
    # Dynamic Playbook Override to prevent naive backend contradictions
    if cw_val > 0 and spot_val > cw_val and ifs_score > 30:
        playbook["bias"] = "Bullish Squeeze Breakout"
        playbook["expected_behavior"] = "Gamma Squeeze Expansion"
    elif pw_val > 0 and spot_val < pw_val and ifs_score < -30:
        playbook["bias"] = "Bearish Cascade Breakdown"
        playbook["expected_behavior"] = "Support Floor Collapse"
    elif bias == "Bearish Breakdown" and ifs_score > 0:
        # Reconcile positive order flow during support floor breaches
        playbook["bias"] = "Support Building"
        playbook["expected_behavior"] = "Bullish Divergence Bounce"

    bias = playbook.get("bias", "Neutral")
    trig_strike = playbook.get("trigger_strike", 0.0)
    trig_strike_str = f"₹{trig_strike:,.1f}" if trig_strike > 0 else "N/A"
    invalid_strike = playbook.get("invalidation_strike", 0.0)
    invalid_strike_str = f"₹{invalid_strike:,.1f}" if invalid_strike > 0 else "N/A"
    expected_behavior = playbook.get("expected_behavior", "Mean Reversion")
    
    # Dynamic customization for option wall migrations (being pro in catching migrations!)
    if s_type == "INVENTORY_MIGRATION":
        if bias == "Strong Bullish Momentum":
            title = "Dual Wall Upward Shift"
            color = "#10b981"
            icon = "🚀"
        elif bias == "Strong Bearish Momentum":
            title = "Dual Wall Downward Shift"
            color = "#ef4444"
            icon = "🩸"
        elif bias == "Bullish Accumulation":
            title = "Support Floor Rise"
            color = "#34d399"
            icon = "🛡️"
        elif bias == "Bearish Breakdown":
            title = "Support Floor Collapse"
            color = "#f43f5e"
            icon = "💥"
        elif bias == "Support Building":
            title = "Institutional Support Floor"
            color = "#10b981"
            icon = "🛡️"
        elif bias == "Bullish Breakout":
            title = "Resistance Ceiling Rise"
            color = "#fbbf24"
            icon = "📈"
        elif bias == "Bearish Consolidation":
            title = "Resistance Ceiling Drop"
            color = "#a78bfa"
            icon = "📉"
        elif bias == "Range Shift":
            title = "Option Wall Rebalancing"
            color = "#38bdf8"
            icon = "🔄"
    elif s_type == "REGIME_SHIFT":
        if "Bearish" in bias or ifs_score < -30:
            title = "Bearish Gamma Flip"
            color = "#ef4444"
            icon = "💥"
        elif "Bullish" in bias or "Support" in bias or ifs_score > 30:
            title = "Bullish Gamma Flip"
            color = "#10b981"
            icon = "🚀"
    elif s_type == "FLOOR_BOUNCE":
        if "Squeeze" in bias or "Breakout" in bias:
            title = "Gamma Squeeze Breakout"
            color = "#10b981"
            icon = "🚀"
        elif "Bearish" in bias or ifs_score < -30:
            title = "Support Floor Collapse"
            color = "#ef4444"
            icon = "💥"
        elif "Support" in bias or ifs_score > 0:
            title = "Support Floor Building"
            color = "#10b981"
            icon = "🛡️"
    elif s_type == "IV_SKEW_ACCUMULATION":
        if "Bearish" in bias:
            title = "Downside Skew Chase"
            color = "#f43f5e"
            icon = "📉"
        else:
            title = "Upside Skew Chase"
            color = "#c084fc"
            icon = "📈"
            
    full_title = f"{icon} {title}"
    
    spot_price = s_m.get('spot_close', 0.0)
    spot_price_str = f"₹{spot_price:,.2f}" if spot_price > 0 else "N/A"
    
    # Calculate boundary alignment status using modular helper
    status_str, status_color, status_bg, status_border = _get_setup_status_info(spot_price, bias, trig_strike, invalid_strike)
    
    bias_color = "#10b981" if ("Bullish" in bias or "Support" in bias or bias in ("Strong Bullish Momentum", "Bullish Accumulation", "Bullish Breakout")) else "#ef4444" if ("Bearish" in bias or bias in ("Strong Bearish Momentum", "Bearish Breakdown", "Bearish Consolidation")) else "#fbbf24"
    
    # Check for active news catalyst and calculate divergence
    cat_badge_html = ""
    divergence_badge_html = ""
    divergence_msg_html = ""
    cat_impact = None
    try:
        catalysts = _load_daily_catalysts()
        cat_impact = catalysts.get(s_ticker.strip().upper())
        if cat_impact:
            cat_color = "#10b981" if cat_impact == "BULLISH" else "#ef4444" if cat_impact == "BEARISH" else "#f59e0b"
            cat_arrow = "▲" if cat_impact == "BULLISH" else "▼" if cat_impact == "BEARISH" else "◆"
            cat_badge_html = f'<span style="background:rgba(255,255,255,0.03); color:{cat_color}; border:1px dashed {cat_color}; font-size:8.5px; font-weight:700; padding:1.5px 5px; border-radius:3px; font-family:\'IBM Plex Sans\', sans-serif; display:inline-flex; align-items:center; gap:2px; margin-right:4px;">⚡ {cat_arrow} {cat_impact}</span>'
    except Exception:
        pass

    # Reconcile news vs quant positioning to check for divergence
    if cat_impact:
        is_cat_bullish = cat_impact == "BULLISH"
        is_cat_bearish = cat_impact == "BEARISH"
        is_quant_bearish = ("Bearish" in bias or ifs_score < -15)
        is_quant_bullish = ("Bullish" in bias or "Support" in bias or ifs_score > 15)
        
        if (is_cat_bullish and is_quant_bearish) or (is_cat_bearish and is_quant_bullish):
            divergence_badge_html = (
                '<span style="background:rgba(244,63,94,0.06); color:#f43f5e; border:1px solid rgba(244,63,94,0.25); '
                'font-size:8.5px; font-weight:700; padding:1.5px 5px; border-radius:3px; '
                'font-family:\'IBM Plex Sans\', sans-serif; display:inline-flex; align-items:center; gap:2px; margin-right:4px;">'
                '⚠️ DIVERGENT</span>'
            )
            div_details = "Bullish News vs Bearish Options" if is_cat_bullish else "Bearish News vs Bullish Options"
            divergence_msg_html = (
                f'<div class="card-stat-row" style="margin-top:6px; padding-top:4px; border-top:1px dashed rgba(244,63,94,0.15);">'
                f'<span style="color:#f43f5e; font-weight:600; font-family:\'Inter Tight\', sans-serif;">⚠️ Divergence:</span>'
                f'<span class="card-stat-val" style="color:#f43f5e; font-weight:bold; font-size:9.5px; font-family:\'Inter Tight\', sans-serif;">{div_details}</span></div>'
            )

    # Structure flip badge — read from the session flip cache (populated by flip watch panel)
    flip_badge_html = ""
    flip_event = _get_cached_flips().get(s_ticker, {})
    # Also fall back to s_m if already compiled with flip fields
    flip_type = flip_event.get("structure_flip") or str(s_m.get("structure_flip", "NONE"))
    flip_conf = flip_event.get("flip_confidence") or float(s_m.get("flip_confidence", 0.0))
    if flip_type == "BEARISH_TO_BULLISH":
        flip_badge_html = (
            '<span style="background:rgba(16,185,129,0.08); color:#10b981; '
            'border:1px solid rgba(16,185,129,0.30); font-size:8.5px; font-weight:700; '
            'padding:1.5px 5px; border-radius:3px; font-family:\'IBM Plex Sans\', sans-serif; '
            f'display:inline-flex; align-items:center; gap:2px; margin-right:4px;">🔄 BEAR→BULL · {flip_conf:.1f}%</span>'
        )
    elif flip_type == "BULLISH_TO_BEARISH":
        flip_badge_html = (
            '<span style="background:rgba(239,68,68,0.08); color:#ef4444; '
            'border:1px solid rgba(239,68,68,0.30); font-size:8.5px; font-weight:700; '
            'padding:1.5px 5px; border-radius:3px; font-family:\'IBM Plex Sans\', sans-serif; '
            f'display:inline-flex; align-items:center; gap:2px; margin-right:4px;">🔻 BULL→BEAR · {flip_conf:.1f}%</span>'
        )

    render_html(f"""
    <div class="setup-card" style="border-left: 3.5px solid {color}; box-shadow: inset 3px 0 6px rgba(0, 0, 0, 0.25);">
        <div class="card-header-flex" style="flex-wrap: wrap; gap: 6px;">
            <span class="card-ticker">{s_ticker}</span>
            <div style="display:flex; align-items:center; flex-wrap:wrap; gap:4px;">
                {cat_badge_html}
                {divergence_badge_html}
                {flip_badge_html}
                <span style="background:{status_bg}; color:{status_color}; border:1px solid {status_border}; font-size:9.5px; font-weight:700; padding:2px 6px; border-radius:4px; letter-spacing:0.5px; font-family:'Inter Tight', sans-serif; white-space:nowrap;">{status_str}</span>
            </div>
            {score_badge}
        </div>
        <div class="card-desc" style="color: {color};">{full_title}</div>
        <div class="card-stat-row"><span>Latest Price:</span><span class="card-stat-val" style="color:#e2e8f0; font-weight:bold;">{spot_price_str}</span></div>
        <div class="card-stat-row"><span>Tactical Bias:</span><span class="card-stat-val" style="color:{bias_color}; font-weight:bold;">{bias}</span></div>
        <div class="card-stat-row"><span>Expected Behavior:</span><span class="card-stat-val" style="color:#6ee7b7;">{expected_behavior}</span></div>
        <div class="card-stat-row"><span>Trigger Strike:</span><span class="card-stat-val" style="color:#fbbf24; font-weight:bold;">{trig_strike_str}</span></div>
        <div class="card-stat-row"><span>Priority Score (Pty):</span><span class="card-stat-val" style="color:#a78bfa; font-weight:bold;">{s_m.get('priority_score', 0.0):.1f}</span></div>
        {divergence_msg_html}
    </div>
    """)

    
    # Render navigation button (compliant with on_click callback state updates)
    st.button(f"Analyze {s_ticker}", key=f"{prefix}{s_type.lower()}_btn_{s_ticker}", use_container_width=True, on_click=select_stock_callback, args=(s_ticker,))

def _matches_filters(
    sym: str,
    s_m: dict,
    selected_sectors: list,
    status_filter: str,
    search_query: str,
) -> bool:
    from src.config.sector_mapping import get_sector
    sym_sector = get_sector(sym)

    # 1. Sector Check
    if selected_sectors and "ALL" not in selected_sectors:
        if sym_sector not in selected_sectors:
            return False

    # 2. Search Query Check
    if search_query:
        sym_upper = sym.upper()
        sec_upper = (sym_sector or "").upper()
        if search_query not in sym_upper and search_query not in sec_upper:
            return False

    # 3. Status Filter Check
    try:
        spot_price = float(s_m.get('spot_close') or 0.0)
    except (ValueError, TypeError):
        spot_price = 0.0
    playbook = s_m.get("playbook", {})
    bias = playbook.get("bias", "Neutral")
    try:
        trig_strike = float(playbook.get("trigger_strike") or 0.0)
    except (ValueError, TypeError):
        trig_strike = 0.0
    try:
        invalid_strike = float(playbook.get("invalidation_strike") or 0.0)
    except (ValueError, TypeError):
        invalid_strike = 0.0
        
    status_str, _, _, _ = _get_setup_status_info(spot_price, bias, trig_strike, invalid_strike)

    if status_filter != "ALL":
        if status_filter not in status_str:
            return False
    else:
        # Default behavior: exclude invalidated setups unless user explicitly filters for them
        if "Invalidated" in status_str:
            return False

    return True

INDEX_SYMBOLS = frozenset(_INDEX_SYMBOLS)

def render_setups_grid(categorized_setups: dict, select_stock_callback, selected_symbol: str = None, selected_sectors: list = ["ALL"], active_date: str = "", session_history: dict = None):
    """
    Renders the setup setups catalog deck in a perfectly aligned row-by-row structure,
    completely excluding invalidated setups by default, unless the user filters for them.
    Filters setups by active sector, status, and search query.
    """
    if session_history is None:
        session_history = {}
    # ── Structure Flip Watch (above everything else) ──────────────────────────
    if active_date and session_history:
        render_structure_flip_watch(active_date, select_stock_callback, session_history, selected_sectors)
    elif st.session_state.get(_FLIP_CACHE_KEY, {}).get("date") != active_date:
        # Flip watch skipped: drop any cache from a previously viewed date so
        # setup cards don't show another session date's flip badges.
        st.session_state.pop(_FLIP_CACHE_KEY, None)

    st.markdown('<p class="term-header">SECTION B — VANGUARD QUANTITATIVE SETUP ENGINE</p>', unsafe_allow_html=True)


    
    # Render Status and Search filters
    _col_f1, _col_f2 = st.columns([1, 2])
    with _col_f1:
        status_filter = st.selectbox(
            "Filter Status",
            options=["ALL", "🟢 Triggered", "⏳ Waiting", "🔴 Invalidated", "⇅ Monitoring", "🌀 Coiling"],
            index=0,
            key="screener_status_filter",
            label_visibility="collapsed"
        )
    with _col_f2:
        search_query = st.text_input(
            "Search Ticker...",
            placeholder="Search Ticker or Sector (e.g. Reliance, IT)...",
            key="screener_search_query",
            label_visibility="collapsed"
        ).strip().upper()

    # ── Highlight Selected Ticker Setup if Active ──
    if selected_symbol and selected_symbol not in INDEX_SYMBOLS:
        active_setups = []
        for s_type, items in categorized_setups.items():
            for sym, s_m in items:
                if sym == selected_symbol and _matches_filters(sym, s_m, selected_sectors, status_filter, search_query):
                    active_setups.append((s_type, s_m))
        
        if active_setups:
            st.markdown(f'<p style="font-size:12px;font-weight:bold;color:#fbbf24;margin-bottom:8px;letter-spacing:0.5px;">🔍 ACTIVE SETUPS FOR SELECTED TICKER: {selected_symbol}</p>', unsafe_allow_html=True)
            n_setups = len(active_setups)
            if n_setups == 1:
                col_sel, _ = st.columns([1, 2])
                with col_sel:
                    render_setup_card(selected_symbol, active_setups[0][1], active_setups[0][0], select_stock_callback, prefix="highlight_")
            elif n_setups == 2:
                col_sel1, col_sel2, _ = st.columns([1, 1, 1])
                with col_sel1:
                    render_setup_card(selected_symbol, active_setups[0][1], active_setups[0][0], select_stock_callback, prefix="highlight_0_")
                with col_sel2:
                    render_setup_card(selected_symbol, active_setups[1][1], active_setups[1][0], select_stock_callback, prefix="highlight_1_")
            else:
                cols = st.columns(min(n_setups, 4))
                for i, (s_type, s_m) in enumerate(active_setups[:4]):
                    with cols[i]:
                        render_setup_card(selected_symbol, s_m, s_type, select_stock_callback, prefix=f"highlight_{i}_")
            st.markdown('<hr style="margin: 15px 0; border-color: #141435;">', unsafe_allow_html=True)
    
    # ── ROW 1: TIER COLUMN HEADERS ──
    h1, h2, h3 = st.columns(3)
    with h1:
        st.markdown("""
        <div style="height: 65px; border-bottom: 1px solid #141435; margin-bottom: 10px;">
            <h4 style="color:#a78bfa; margin:0; padding:0; font-size: 15px;">⚡ TIER 1 — EXPANSION</h4>
            <p style="font-size:10px; color:#7888aa; text-transform:uppercase; letter-spacing:0.5px; margin: 4px 0 0 0; padding:0;">Short-term momentum breakouts</p>
        </div>
        """, unsafe_allow_html=True)
    with h2:
        st.markdown("""
        <div style="height: 65px; border-bottom: 1px solid #141435; margin-bottom: 10px;">
            <h4 style="color:#34d399; margin:0; padding:0; font-size: 15px;">🛡️ TIER 2 — SUPPORT/DEFENSE</h4>
            <p style="font-size:10px; color:#7888aa; text-transform:uppercase; letter-spacing:0.5px; margin: 4px 0 0 0; padding:0;">Institutional floors & hedging zones</p>
        </div>
        """, unsafe_allow_html=True)
    with h3:
        st.markdown("""
        <div style="height: 65px; border-bottom: 1px solid #141435; margin-bottom: 10px;">
            <h4 style="color:#f59e0b; margin:0; padding:0; font-size: 15px;">🔄 TIER 3 — REGIME CHANGE</h4>
            <p style="font-size:10px; color:#7888aa; text-transform:uppercase; letter-spacing:0.5px; margin: 4px 0 0 0; padding:0;">Long-term repositioning signals</p>
        </div>
        """, unsafe_allow_html=True)

    # ── ROW 2: PRIMARY SETUPS (Gamma Squeeze vs Floor Bounce vs Regime Shift) ──
    r1_c1, r1_c2, r1_c3 = st.columns(3)
    
    with r1_c1:
        st.markdown('<p style="font-size:11px;font-weight:bold;color:#fca5a5;margin:10px 0 5px;">🔥 GAMMA SQUEEZE CANDIDATES</p>', unsafe_allow_html=True)
        sq_items = [x for x in categorized_setups.get("GAMMA_SQUEEZE", []) if x[0] not in INDEX_SYMBOLS and _matches_filters(x[0], x[1], selected_sectors, status_filter, search_query)]
        with st.container(height=400):
            if not sq_items:
                st.markdown('<p style="font-size:11px;color:#4a5a8a;font-style:italic;">No active setups matching filters.</p>', unsafe_allow_html=True)
            else:
                for sym, s_m in sq_items:
                    render_setup_card(sym, s_m, "GAMMA_SQUEEZE", select_stock_callback, prefix="r1c1_")
                
    with r1_c2:
        st.markdown('<p style="font-size:11px;font-weight:bold;color:#6ee7b7;margin:10px 0 5px;">🛡️ INSTITUTIONAL FLOOR BOUNCE</p>', unsafe_allow_html=True)
        fb_items = [x for x in categorized_setups.get("FLOOR_BOUNCE", []) if x[0] not in INDEX_SYMBOLS and _matches_filters(x[0], x[1], selected_sectors, status_filter, search_query)]
        with st.container(height=400):
            if not fb_items:
                st.markdown('<p style="font-size:11px;color:#4a5a8a;font-style:italic;">No active setups matching filters.</p>', unsafe_allow_html=True)
            else:
                for sym, s_m in fb_items:
                    render_setup_card(sym, s_m, "FLOOR_BOUNCE", select_stock_callback, prefix="r1c2_")
                
    with r1_c3:
        st.markdown('<p style="font-size:11px;font-weight:bold;color:#fbbf24;margin:10px 0 5px;">🔄 REGIME SHIFT CROSSOVERS</p>', unsafe_allow_html=True)
        rs_items = [x for x in categorized_setups.get("REGIME_SHIFT", []) if x[0] not in INDEX_SYMBOLS and _matches_filters(x[0], x[1], selected_sectors, status_filter, search_query)]
        with st.container(height=400):
            if not rs_items:
                st.markdown('<p style="font-size:11px;color:#4a5a8a;font-style:italic;">No active setups matching filters.</p>', unsafe_allow_html=True)
            else:
                for sym, s_m in rs_items:
                    render_setup_card(sym, s_m, "REGIME_SHIFT", select_stock_callback, prefix="r1c3_")

    # ── ROW 3: SECONDARY SETUPS (Volatility Coils vs Dealer Defense vs Inventory Migrations) ──
    st.markdown('<div style="margin-top: 15px;"></div>', unsafe_allow_html=True)
    r2_c1, r2_c2, r2_c3 = st.columns(3)
    
    with r2_c1:
        st.markdown('<p style="font-size:11px;font-weight:bold;color:#a78bfa;margin:10px 0 5px;">🌀 VOLATILITY COILS & SKEW CHASE</p>', unsafe_allow_html=True)
        vc_items = [x for x in categorized_setups.get("VOLATILITY_COIL", []) if x[0] not in INDEX_SYMBOLS and _matches_filters(x[0], x[1], selected_sectors, status_filter, search_query)]
        pz_items = [x for x in categorized_setups.get("PINCH_ZONE", []) if x[0] not in INDEX_SYMBOLS and _matches_filters(x[0], x[1], selected_sectors, status_filter, search_query)]
        sk_items = [x for x in categorized_setups.get("IV_SKEW_ACCUMULATION", []) if x[0] not in INDEX_SYMBOLS and _matches_filters(x[0], x[1], selected_sectors, status_filter, search_query)]
        
        combined_coils = []
        for item in vc_items:
            combined_coils.append((item[0], item[1], "VOLATILITY_COIL"))
        for item in pz_items:
            combined_coils.append((item[0], item[1], "PINCH_ZONE"))
        for item in sk_items:
            combined_coils.append((item[0], item[1], "IV_SKEW_ACCUMULATION"))
            
        combined_coils = sorted(combined_coils, key=lambda x: float(x[1].get("priority_score") or 0.0), reverse=True)
        
        with st.container(height=400):
            if not combined_coils:
                st.markdown('<p style="font-size:11px;color:#4a5a8a;font-style:italic;">No active setups matching filters.</p>', unsafe_allow_html=True)
            else:
                for sym, s_m, s_type in combined_coils:
                    render_setup_card(sym, s_m, s_type, select_stock_callback, prefix="r2c1_")
                
    with r2_c2:
        st.markdown('<p style="font-size:11px;font-weight:bold;color:#38bdf8;margin:10px 0 5px;">🧲 DEALER DEFENSE & VOL SPIKES</p>', unsafe_allow_html=True)
        dd_items = [x for x in categorized_setups.get("DEALER_DEFENSE", []) if x[0] not in INDEX_SYMBOLS and _matches_filters(x[0], x[1], selected_sectors, status_filter, search_query)]
        vs_items = [x for x in categorized_setups.get("IV_SPIKE", []) if x[0] not in INDEX_SYMBOLS and _matches_filters(x[0], x[1], selected_sectors, status_filter, search_query)]
        
        combined_defense = []
        for item in dd_items:
            combined_defense.append((item[0], item[1], "DEALER_DEFENSE"))
        for item in vs_items:
            combined_defense.append((item[0], item[1], "IV_SPIKE"))
            
        combined_defense = sorted(combined_defense, key=lambda x: abs(float(x[1].get("ifs_score") or 0.0)), reverse=True)
        
        with st.container(height=400):
            if not combined_defense:
                st.markdown('<p style="font-size:11px;color:#4a5a8a;font-style:italic;">No active setups matching filters.</p>', unsafe_allow_html=True)
            else:
                for sym, s_m, s_type in combined_defense:
                    render_setup_card(sym, s_m, s_type, select_stock_callback, prefix="r2c2_")
                
    with r2_c3:
        st.markdown('<p style="font-size:11px;font-weight:bold;color:#fbbf24;margin:10px 0 5px;">📊 INVENTORY MIGRATIONS & CRUSH</p>', unsafe_allow_html=True)
        im_items = [x for x in categorized_setups.get("INVENTORY_MIGRATION", []) if x[0] not in INDEX_SYMBOLS and _matches_filters(x[0], x[1], selected_sectors, status_filter, search_query)]
        vc_crush = [x for x in categorized_setups.get("IV_CRUSH", []) if x[0] not in INDEX_SYMBOLS and _matches_filters(x[0], x[1], selected_sectors, status_filter, search_query)]
        
        combined_mig = []
        for item in im_items:
            combined_mig.append((item[0], item[1], "INVENTORY_MIGRATION"))
        for item in vc_crush:
            combined_mig.append((item[0], item[1], "IV_CRUSH"))
            
        combined_mig = sorted(combined_mig, key=lambda x: abs(float(x[1].get("ifs_score") or 0.0)), reverse=True)
        
        with st.container(height=400):
            if not combined_mig:
                st.markdown('<p style="font-size:11px;color:#4a5a8a;font-style:italic;">No active setups matching filters.</p>', unsafe_allow_html=True)
            else:
                for sym, s_m, s_type in combined_mig:
                    render_setup_card(sym, s_m, s_type, select_stock_callback, prefix="r2c3_")
