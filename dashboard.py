import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
from datetime import datetime

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Vanguard Quantitative Terminal",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Base */
    .stApp { background-color: #020209; color: #e2e8f0; font-family: 'Courier New', monospace; }
    section[data-testid="stSidebar"] { background-color: #0a0a14; }

    /* Metric cards */
    div[data-testid="metric-container"] {
        background: linear-gradient(135deg, #0d0d1a 0%, #111122 100%);
        border: 1px solid #1e2a4a;
        border-radius: 8px;
        padding: 12px 16px;
        transition: border-color 0.2s;
    }
    div[data-testid="metric-container"]:hover { border-color: #3b4fd8; }
    div[data-testid="metric-container"] label { color: #7888aa !important; font-size: 11px !important; letter-spacing: 1px; }
    div[data-testid="metric-container"] [data-testid="metric-value"] { color: #e2e8f0; font-size: 20px; font-weight: 700; }

    /* Signal badges */
    .badge-bull  { background:#0d2b1a; color:#34d399; border:1px solid #1f6b44; padding:3px 10px; border-radius:4px; font-size:11px; font-weight:700; letter-spacing:1px; }
    .badge-bear  { background:#2b0d0d; color:#f87171; border:1px solid #6b1f1f; padding:3px 10px; border-radius:4px; font-size:11px; font-weight:700; letter-spacing:1px; }
    .badge-neut  { background:#1a1a0d; color:#fbbf24; border:1px solid #6b5a1f; padding:3px 10px; border-radius:4px; font-size:11px; font-weight:700; letter-spacing:1px; }

    /* Section headers */
    .term-header {
        font-size: 11px; letter-spacing: 2px; color: #4a5a8a;
        border-bottom: 1px solid #1e2a4a; padding-bottom: 6px;
        margin: 20px 0 14px; text-transform: uppercase;
    }

    /* Divider */
    hr { border-color: #1e2a4a !important; }

    /* Alert box */
    .alert-box {
        background: #0d1a2b; border-left: 3px solid #3b82f6;
        padding: 10px 14px; border-radius: 0 6px 6px 0;
        font-size: 12px; color: #93c5fd; margin: 6px 0;
    }
    .alert-box.bull { border-left-color: #34d399; color: #6ee7b7; background: #0d2b1a; }
    .alert-box.bear { border-left-color: #f87171; color: #fca5a5; background: #2b0d0d; }
    .alert-box.warn { border-left-color: #fbbf24; color: #fde68a; background: #1a1500; }

    /* Dataframe */
    .dataframe { background-color: #0a0a14 !important; }
    iframe[title="st.dataframe"] { border: 1px solid #1e2a4a; border-radius: 6px; }

    /* Selectbox */
    .stSelectbox > div > div { background-color: #0d0d1a; border-color: #1e2a4a; color: #e2e8f0; }

    /* Tabs */
    button[data-baseweb="tab"] { color: #7888aa; }
    button[data-baseweb="tab"][aria-selected="true"] { color: #e2e8f0; border-bottom: 2px solid #3b4fd8; }

    /* Title bar */
    .title-bar {
        display: flex; align-items: center; gap: 12px;
        border-bottom: 1px solid #1e2a4a; padding-bottom: 14px; margin-bottom: 20px;
    }
    .title-bar h1 { font-size: 18px; letter-spacing: 3px; color: #e2e8f0; margin: 0; }
    .title-bar .ts { font-size: 11px; color: #4a5a8a; margin-left: auto; }

    /* Greeks table */
    .g-table { width: 100%; font-size: 12px; border-collapse: collapse; }
    .g-table th { color: #4a5a8a; text-align: right; padding: 5px 10px; border-bottom: 1px solid #1e2a4a; font-size: 10px; letter-spacing: 1px; }
    .g-table th:first-child { text-align: left; }
    .g-table td { text-align: right; padding: 4px 10px; border-bottom: 1px solid #0d1020; color: #c0ccdd; }
    .g-table td:first-child { text-align: left; color: #e2e8f0; font-weight: 600; }
    .g-table tr:hover td { background: #0d1020; }
    .g-table .atm td { color: #fbbf24; background: #141008; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────
COLORS = {
    "call":       "#58a6ff",
    "put":        "#f85149",
    "cmp":        "#fbbf24",
    "flip":       "#a78bfa",
    "call_wall":  "#58a6ff",
    "put_wall":   "#f85149",
    "net_pos":    "#34d399",
    "net_neg":    "#f87171",
}

def pct_from_wall(cmp, wall):
    if wall == 0:
        return 0.0
    return round((cmp - wall) / wall * 100, 2)

def signal_label(row):
    """Derive a simple bias label from wall/flip positioning."""
    cmp = float(row["CMP"])
    cw  = float(row["CALL_WALL"])
    pw  = float(row["PUT_WALL"])
    gf  = float(row["GAMMA_FLIP"])
    gex = float(row.get("Δ GEX (Lakhs)", 0))

    if cmp > cw and gex > 0:
        return "BULL", "bull"
    if cmp < pw and gex < 0:
        return "BEAR", "bear"
    if cmp > gf:
        return "BULL WATCH", "bull"
    if cmp < gf:
        return "BEAR WATCH", "bear"
    return "NEUTRAL", "neut"


# ── Data ──────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=2, show_spinner=False)
def load_data():
    try:
        signals = pd.read_csv("data/processed/signals.csv")
        greeks  = pd.read_csv("data/processed/greeks.csv")
        return signals, greeks
    except FileNotFoundError:
        return pd.DataFrame(), pd.DataFrame()

signals_df, greeks_df = load_data()

if signals_df.empty or greeks_df.empty:
    st.error("⚠  Data missing — run `python3 main.py` first.")
    st.stop()

# Normalise column names
signals_df.columns = signals_df.columns.str.strip()
greeks_df.columns  = greeks_df.columns.str.strip()

# Ensure numeric
for col in ["CMP", "CALL_WALL", "PUT_WALL", "GAMMA_FLIP"]:
    signals_df[col] = pd.to_numeric(signals_df[col], errors="coerce")

# Derive signal column
signals_df[["_signal_txt", "_signal_cls"]] = signals_df.apply(
    lambda r: pd.Series(signal_label(r)), axis=1
)


# ── Title bar ─────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="title-bar">
  <span style="font-size:22px;">⚡</span>
  <h1>VANGUARD QUANTITATIVE TERMINAL</h1>
  <span class="ts">LAST REFRESH: {datetime.now().strftime('%d %b %Y  %H:%M:%S')}</span>
</div>
""", unsafe_allow_html=True)

# Auto-refresh toggle
col_r1, col_r2 = st.columns([8, 2])
with col_r2:
    auto_refresh = st.toggle("AUTO REFRESH (60s)", value=False)
if auto_refresh:
    import time
    st.toast("Auto-refresh active — reloads every 60 s", icon="🔄")
    time.sleep(60)
    st.cache_data.clear()
    st.rerun()


# ── Symbol selector ───────────────────────────────────────────────────────────
col_s1, col_s2, col_s3 = st.columns([2, 1, 5])
with col_s1:
    selected_symbol = st.selectbox(
        "SELECT SYMBOL",
        options=signals_df["SYMBOL"].tolist(),
        index=0,
    )
with col_s2:
    compare_mode = st.toggle("COMPARE", value=False)
if compare_mode:
    with col_s3:
        compare_symbol = st.selectbox(
            "COMPARE WITH",
            options=[s for s in signals_df["SYMBOL"].tolist() if s != selected_symbol],
            index=0,
        )

row = signals_df[signals_df["SYMBOL"] == selected_symbol].iloc[0]
cmp        = float(row["CMP"])
call_wall  = float(row["CALL_WALL"])
put_wall   = float(row["PUT_WALL"])
gamma_flip = float(row["GAMMA_FLIP"])
gex_shift  = float(row.get("Δ GEX (Lakhs)", 0))
sig_txt, sig_cls = row["_signal_txt"], row["_signal_cls"]


# ── Top metrics row ───────────────────────────────────────────────────────────
st.markdown('<p class="term-header">KEY LEVELS</p>', unsafe_allow_html=True)

m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("CMP",          f"₹{cmp:,.2f}")

if call_wall == 0 and put_wall == 0:
    m2.metric("CALL WALL",    "N/A")
    m3.metric("PUT WALL",     "N/A")
    m4.metric("GAMMA FLIP",   "N/A")
    m5.metric("GEX SHIFT",    "N/A")
    m6.metric("BIAS",         "NEUTRAL")

    # ── Signal alerts ─────────────────────────────────────────────────────────────
    st.markdown('<p class="term-header">SIGNAL ALERTS</p>', unsafe_allow_html=True)
    st.markdown('<div class="alert-box">ℹ️ Spot price tracking active. Options chain and dealer GEX calculations are not loaded/applicable for this symbol.</div>', unsafe_allow_html=True)
else:
    m2.metric("CALL WALL",    f"₹{call_wall:,.0f}",  f"{pct_from_wall(cmp, call_wall):+.2f}% gap")
    m3.metric("PUT WALL",     f"₹{put_wall:,.0f}",   f"{pct_from_wall(cmp, put_wall):+.2f}% gap")
    m4.metric("GAMMA FLIP",   f"₹{gamma_flip:,.0f}", f"{pct_from_wall(cmp, gamma_flip):+.2f}% gap")
    m5.metric("GEX SHIFT",    f"{gex_shift:+.2f}L")
    m6.metric("BIAS",         sig_txt)

    # ── Signal alerts ─────────────────────────────────────────────────────────────
    st.markdown('<p class="term-header">SIGNAL ALERTS</p>', unsafe_allow_html=True)
    a1, a2 = st.columns(2)
    with a1:
        if cmp > call_wall:
            st.markdown(f'<div class="alert-box bull">📈 CMP ({cmp}) has CROSSED above CALL WALL ({call_wall}) — dealer delta-buying pressure active. Watch for squeeze continuation.</div>', unsafe_allow_html=True)
        elif cmp > gamma_flip:
            st.markdown(f'<div class="alert-box bull">⚡ CMP above GAMMA FLIP ({gamma_flip}) — positive gamma regime. Moves upward are dealer-amplified.</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="alert-box bear">⚠ CMP ({cmp}) below GAMMA FLIP ({gamma_flip}) — negative gamma regime. Downside moves get amplified.</div>', unsafe_allow_html=True)

    with a2:
        gap_to_call = call_wall - cmp
        gap_to_put  = cmp - put_wall
        if gap_to_call < gap_to_put:
            st.markdown(f'<div class="alert-box warn">🎯 Only ₹{gap_to_call:.1f} to CALL WALL breakout. Breakout = bullish gamma cascade. Failure = pin at current level.</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="alert-box warn">🛡 PUT WALL ({put_wall}) is ₹{gap_to_put:.1f} below CMP — strong dealer support floor here.</div>', unsafe_allow_html=True)


# ── Main charts ───────────────────────────────────────────────────────────────
st.markdown('<p class="term-header">GAMMA EXPOSURE PROFILE</p>', unsafe_allow_html=True)

tab1, tab2, tab3 = st.tabs(["📊  GEX PROFILE", "📈  OI CHANGE", "🔢  GREEKS TABLE"])

stock_greeks = greeks_df[greeks_df["SYMBOL"] == selected_symbol].copy()


# ── Tab 1: GEX profile + net GEX ─────────────────────────────────────────────
with tab1:
    if stock_greeks.empty:
        st.warning("No options data for this symbol.")
    else:
        for col in ["STRIKE_PR", "GEX"]:
            stock_greeks[col] = pd.to_numeric(stock_greeks[col], errors="coerce")
        stock_greeks.dropna(subset=["STRIKE_PR", "GEX"], inplace=True)

        strike_gex = (
            stock_greeks.groupby(["STRIKE_PR", "OPTION_TYP"])["GEX"]
            .sum()
            .unstack(fill_value=0)
        )
        if "CE" not in strike_gex.columns: strike_gex["CE"] = 0
        if "PE" not in strike_gex.columns: strike_gex["PE"] = 0

        strike_gex = strike_gex[
            (strike_gex.index >= cmp * 0.90) &
            (strike_gex.index <= cmp * 1.10)
        ]
        strike_gex["NET"] = strike_gex["CE"] + strike_gex["PE"]

        fig = make_subplots(
            rows=1, cols=2,
            column_widths=[0.72, 0.28],
            subplot_titles=("Net Gamma by Strike (Lakhs)", "Cumulative Net GEX"),
            horizontal_spacing=0.05,
            shared_yaxes=True,
        )

        # Left: CE + PE bars
        fig.add_trace(go.Bar(
            y=strike_gex.index,
            x=strike_gex["PE"] / 1e5,
            name="Put GEX",
            orientation="h",
            marker=dict(color=COLORS["put"], opacity=0.85),
        ), row=1, col=1)

        fig.add_trace(go.Bar(
            y=strike_gex.index,
            x=strike_gex["CE"] / 1e5,
            name="Call GEX",
            orientation="h",
            marker=dict(color=COLORS["call"], opacity=0.85),
        ), row=1, col=1)

        # Right: Net GEX as horizontal bars (green/red)
        net_colors = [COLORS["net_pos"] if v >= 0 else COLORS["net_neg"] for v in strike_gex["NET"]]
        fig.add_trace(go.Bar(
            y=strike_gex.index,
            x=strike_gex["NET"] / 1e5,
            name="Net GEX",
            orientation="h",
            marker=dict(color=net_colors, opacity=0.9),
            showlegend=True,
        ), row=1, col=2)

        # Reference lines helper with premium overlap protection
        def draw_reference_lines(fig, cmp, flip, call_wall, put_wall):
            for col in [1, 2]:
                # CMP Line
                fig.add_hline(y=cmp, line_dash="dash", line_color="yellow", line_width=1.2,
                              annotation_text=f" CMP: {cmp} ", annotation_position="bottom left",
                              annotation=dict(bgcolor="rgba(0,0,0,0.75)", font_color="yellow", font_size=10),
                              row=1, col=col)
                
                # Overlap logic
                if call_wall == put_wall and call_wall == flip:
                    fig.add_hline(y=flip, line_dash="solid", line_color="white", line_width=2,
                                  annotation_text=f" ⚡ THE STRADDLE PIN (WALLS & FLIP): {flip} ", annotation_position="top right",
                                  annotation=dict(bgcolor="rgba(255,255,255,0.2)", font_color="white", font_size=10),
                                  row=1, col=col)
                elif call_wall == put_wall:
                    fig.add_hline(y=call_wall, line_dash="solid", line_color="purple", line_width=2,
                                  annotation_text=f" 💥 CALL & PUT WALL: {call_wall} ", annotation_position="top right",
                                  annotation=dict(bgcolor="rgba(128,0,128,0.3)", font_color="#ffffff", font_size=10),
                                  row=1, col=col)
                    fig.add_hline(y=flip, line_dash="solid", line_color="yellow", 
                                  annotation_text=f" Γ FLIP: {flip} ", annotation_position="bottom right",
                                  annotation=dict(bgcolor="rgba(0,0,0,0.7)", font_color="yellow", font_size=10),
                                  row=1, col=col)
                elif flip == call_wall:
                    fig.add_hline(y=flip, line_dash="solid", line_color="#58a6ff", line_width=2,
                                  annotation_text=f" CALL WALL & Γ FLIP: {flip} ", annotation_position="top right",
                                  annotation=dict(bgcolor="rgba(88,166,255,0.3)", font_color="#ffffff", font_size=10),
                                  row=1, col=col)
                    fig.add_hline(y=put_wall, line_dash="solid", line_color="#f85149", line_width=2,
                                  annotation_text=f" PUT WALL: {put_wall} ", annotation_position="bottom right",
                                  annotation=dict(bgcolor="rgba(248,81,73,0.2)", font_color="#f85149", font_size=10),
                                  row=1, col=col)
                elif flip == put_wall:
                    fig.add_hline(y=flip, line_dash="solid", line_color="#f85149", line_width=2,
                                  annotation_text=f" PUT WALL & Γ FLIP: {flip} ", annotation_position="top right",
                                  annotation=dict(bgcolor="rgba(248,81,73,0.3)", font_color="#ffffff", font_size=10),
                                  row=1, col=col)
                    fig.add_hline(y=call_wall, line_dash="solid", line_color="#58a6ff", line_width=2,
                                  annotation_text=f" CALL WALL: {call_wall} ", annotation_position="bottom right",
                                  annotation=dict(bgcolor="rgba(88,166,255,0.2)", font_color="#58a6ff", font_size=10),
                                  row=1, col=col)
                else:
                    fig.add_hline(y=call_wall, line_dash="solid", line_color="#58a6ff", line_width=2,
                                  annotation_text=f" CALL WALL: {call_wall} ", annotation_position="top right",
                                  annotation=dict(bgcolor="rgba(88,166,255,0.2)", font_color="#58a6ff", font_size=10),
                                  row=1, col=col)
                    fig.add_hline(y=put_wall, line_dash="solid", line_color="#f85149", line_width=2,
                                  annotation_text=f" PUT WALL: {put_wall} ", annotation_position="bottom right",
                                  annotation=dict(bgcolor="rgba(248,81,73,0.2)", font_color="#f85149", font_size=10),
                                  row=1, col=col)
                    fig.add_hline(y=flip, line_dash="solid", line_color="yellow", 
                                  annotation_text=f" Γ FLIP: {flip} ", annotation_position="bottom right",
                                  annotation=dict(bgcolor="rgba(0,0,0,0.7)", font_color="yellow", font_size=10),
                                  row=1, col=col)

        draw_reference_lines(fig, cmp, gamma_flip, call_wall, put_wall)

        fig.update_layout(
            barmode="relative",
            plot_bgcolor="#0a0a14",
            paper_bgcolor="#020209",
            font=dict(color="#c0ccdd", family="Courier New", size=11),
            height=620,
            legend=dict(
                orientation="h", yanchor="bottom", y=1.02,
                xanchor="right", x=1,
                bgcolor="rgba(0,0,0,0)",
                font=dict(size=11),
            ),
            margin=dict(l=10, r=10, t=40, b=10),
        )
        for axis in ["xaxis", "yaxis", "xaxis2", "yaxis2"]:
            fig.update_layout(**{axis: dict(gridcolor="#1e2a4a", zerolinecolor="#2a3a5a")})
        fig.update_layout(
            yaxis=dict(title="Strike Price", tickformat=".0f"),
            xaxis=dict(title="GEX (Lakhs)"),
            yaxis2=dict(tickformat=".0f"),
            xaxis2=dict(title="Net GEX (Lakhs)"),
        )

        st.plotly_chart(fig, use_container_width=True)


# ── Tab 2: OI change ─────────────────────────────────────────────────────────
with tab2:
    oi_cols = [c for c in greeks_df.columns if "OI" in c.upper() or "CHNG" in c.upper()]

    if "STRIKE_PR" in stock_greeks.columns and len(oi_cols) > 0:
        oi_col = oi_cols[0]
        stock_greeks[oi_col] = pd.to_numeric(stock_greeks[oi_col], errors="coerce")

        oi_data = (
            stock_greeks.groupby(["STRIKE_PR", "OPTION_TYP"])[oi_col]
            .sum()
            .unstack(fill_value=0)
        )
        if "CE" not in oi_data.columns: oi_data["CE"] = 0
        if "PE" not in oi_data.columns: oi_data["PE"] = 0

        oi_data = oi_data[
            (oi_data.index >= cmp * 0.90) &
            (oi_data.index <= cmp * 1.10)
        ]

        fig2 = go.Figure()
        fig2.add_trace(go.Bar(
            y=oi_data.index, x=-oi_data["PE"] / 1e5,
            name="Put OI Change", orientation="h",
            marker=dict(color=COLORS["put"], opacity=0.85),
        ))
        fig2.add_trace(go.Bar(
            y=oi_data.index, x=oi_data["CE"] / 1e5,
            name="Call OI Change", orientation="h",
            marker=dict(color=COLORS["call"], opacity=0.85),
        ))
        fig2.add_hline(y=cmp, line_dash="dash", line_color=COLORS["cmp"],
                       annotation_text=f" CMP: {cmp} ",
                       annotation=dict(bgcolor="rgba(0,0,0,.75)", font_color=COLORS["cmp"], font_size=10))
        fig2.update_layout(
            barmode="overlay", height=560,
            plot_bgcolor="#0a0a14", paper_bgcolor="#020209",
            font=dict(color="#c0ccdd", family="Courier New", size=11),
            yaxis=dict(title="Strike", tickformat=".0f", gridcolor="#1e2a4a"),
            xaxis=dict(title=f"{oi_col} (Lakhs)", gridcolor="#1e2a4a"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                        bgcolor="rgba(0,0,0,0)"),
            margin=dict(l=10, r=10, t=30, b=10),
        )
        st.plotly_chart(fig2, use_container_width=True)
    else:
        # Fallback: show ΔCall OI / ΔPut OI from signals across all stocks
        st.markdown('<p class="term-header">MARKET-WIDE ΔOI COMPARISON</p>', unsafe_allow_html=True)
        oi_plot = signals_df[["SYMBOL", "Δ CALL OI", "Δ PUT OI"]].copy()
        for c in ["Δ CALL OI", "Δ PUT OI"]:
            if c in oi_plot.columns:
                oi_plot[c] = pd.to_numeric(oi_plot[c].astype(str).str.replace("L", ""), errors="coerce")

        fig3 = go.Figure()
        if "Δ CALL OI" in oi_plot.columns:
            fig3.add_trace(go.Bar(
                x=oi_plot["SYMBOL"], y=oi_plot["Δ CALL OI"],
                name="ΔCall OI", marker_color=COLORS["call"],
            ))
        if "Δ PUT OI" in oi_plot.columns:
            fig3.add_trace(go.Bar(
                x=oi_plot["SYMBOL"], y=oi_plot["Δ PUT OI"],
                name="ΔPut OI", marker_color=COLORS["put"],
            ))
        fig3.update_layout(
            barmode="group", height=400,
            plot_bgcolor="#0a0a14", paper_bgcolor="#020209",
            font=dict(color="#c0ccdd", family="Courier New", size=11),
            xaxis=dict(gridcolor="#1e2a4a"), yaxis=dict(gridcolor="#1e2a4a", title="OI Change (L)"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                        bgcolor="rgba(0,0,0,0)"),
            margin=dict(l=10, r=10, t=20, b=10),
        )
        st.plotly_chart(fig3, use_container_width=True)


# ── Tab 3: Greeks table ───────────────────────────────────────────────────────
with tab3:
    greek_cols = ["STRIKE_PR", "OPTION_TYP", "LTP", "DELTA", "GAMMA", "THETA", "VEGA", "IV", "OI"]
    available  = [c for c in greek_cols if c in stock_greeks.columns]

    if len(available) > 2:
        g_df = stock_greeks[available].copy()
        for c in available[2:]:
            g_df[c] = pd.to_numeric(g_df[c], errors="coerce")

        g_df = g_df[
            (g_df["STRIKE_PR"] >= cmp * 0.90) &
            (g_df["STRIKE_PR"] <= cmp * 1.10)
        ].sort_values("STRIKE_PR")

        # ATM flag
        g_df["_atm"] = (g_df["STRIKE_PR"] - cmp).abs() == (g_df["STRIKE_PR"] - cmp).abs().min()

        # Build HTML table
        rows_html = ""
        for _, r in g_df.iterrows():
            atm_cls = "atm" if r["_atm"] else ""
            cells = f"<td>{r['STRIKE_PR']:.0f}</td><td>{r.get('OPTION_TYP','')}</td>"
            for c in available[2:]:
                v = r[c]
                cells += f"<td>{v:.4f}</td>" if isinstance(v, float) else f"<td>{v}</td>"
            rows_html += f"<tr class='{atm_cls}'>{cells}</tr>"

        headers = "".join(f"<th>{c}</th>" for c in available)
        st.markdown(f"""
        <div style="overflow-x:auto; max-height:480px; overflow-y:auto;">
          <table class="g-table">
            <thead><tr>{headers}</tr></thead>
            <tbody>{rows_html}</tbody>
          </table>
        </div>
        <p style="font-size:10px;color:#4a5a8a;margin-top:6px;">Yellow rows = ATM strike</p>
        """, unsafe_allow_html=True)
    else:
        st.info("Delta / Gamma / Theta / Vega columns not found in greeks.csv. Ensure `intelligence.py` computes them.")


# ── Comparison panel ──────────────────────────────────────────────────────────
if compare_mode:
    st.markdown(f'<p class="term-header">COMPARE: {selected_symbol} vs {compare_symbol}</p>', unsafe_allow_html=True)

    rows_cmp = signals_df[signals_df["SYMBOL"].isin([selected_symbol, compare_symbol])].copy()
    rows_cmp = rows_cmp.set_index("SYMBOL")[["CMP", "CALL_WALL", "PUT_WALL", "GAMMA_FLIP", "Δ GEX (Lakhs)", "SCORE"]].T

    fig_cmp = go.Figure()
    bar_metrics = ["CMP", "CALL_WALL", "PUT_WALL", "GAMMA_FLIP"]
    for sym in [selected_symbol, compare_symbol]:
        if sym in rows_cmp.columns:
            fig_cmp.add_trace(go.Bar(
                name=sym,
                x=bar_metrics,
                y=[float(rows_cmp.at[m, sym]) for m in bar_metrics],
            ))

    fig_cmp.update_layout(
        barmode="group", height=320,
        plot_bgcolor="#0a0a14", paper_bgcolor="#020209",
        font=dict(color="#c0ccdd", family="Courier New", size=11),
        xaxis=dict(gridcolor="#1e2a4a"),
        yaxis=dict(title="Price Level", gridcolor="#1e2a4a"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=10, r=10, t=20, b=10),
    )
    st.plotly_chart(fig_cmp, use_container_width=True)

    st.dataframe(
        rows_cmp.style.highlight_max(axis=1, color="#0d2b1a")
                      .highlight_min(axis=1, color="#2b0d0d"),
        use_container_width=True,
    )


# ── Global F&O Matrix ─────────────────────────────────────────────────────────
st.markdown('<p class="term-header">GLOBAL F&O MATRIX</p>', unsafe_allow_html=True)

display_df = signals_df.drop(columns=["_signal_txt", "_signal_cls"], errors="ignore").copy()

# Colour-code score column
def score_color(v):
    try:
        v = float(v)
        if v >= 45: return "color: #34d399"
        if v >= 35: return "color: #fbbf24"
        return "color: #f87171"
    except:
        return ""

styled = (
    display_df
    .set_index("RANK")
    .style
    .applymap(score_color, subset=["SCORE"] if "SCORE" in display_df.columns else [])
    .set_properties(**{"background-color": "#0a0a14", "color": "#c0ccdd"})
)

st.dataframe(styled, height=420, use_container_width=True)

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("""
<hr>
<p style="font-size:10px;color:#2a3a5a;text-align:center;letter-spacing:1px;">
  VANGUARD QUANTITATIVE TERMINAL · FOR INFORMATIONAL USE ONLY · NOT FINANCIAL ADVICE
</p>
""", unsafe_allow_html=True)
