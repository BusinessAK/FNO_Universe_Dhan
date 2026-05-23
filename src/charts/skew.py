"""
Vanguard Institutional Terminal - Implied Volatility (IV) Skew Charts
"""
import pandas as pd
import plotly.graph_objects as go
from src.config.settings import C, PB
from src.charts.base import apply_axes

def render_iv_skew_chart(
    greeks_df: pd.DataFrame,
    selected_symbol: str,
    selected_expiry: str,
    cmp_val: float,
    gf_val: float,
    cw_val: float,
    pw_val: float,
    strike_pct: float
) -> go.Figure:
    """
    Renders an Implied Volatility skew plot with ATM IV reference lines.
    """
    st_greeks = greeks_df[greeks_df["SYMBOL"] == selected_symbol.upper()].copy()
    if selected_expiry != "ALL EXPIRIES":
        st_greeks = st_greeks[st_greeks["EXPIRY_DT"] == selected_expiry].copy()
        
    if st_greeks.empty or "IV" not in st_greeks.columns:
        return None
        
    lo_strike = cmp_val * (1 - strike_pct / 100)
    hi_strike = cmp_val * (1 + strike_pct / 100)
    
    st_greeks["STRIKE_PR"] = pd.to_numeric(st_greeks["STRIKE_PR"], errors="coerce")
    st_greeks["IV"] = pd.to_numeric(st_greeks["IV"], errors="coerce")
    
    iv_df = st_greeks.dropna(subset=["STRIKE_PR", "IV", "OPTION_TYP"]).copy()
    iv_df = iv_df[(iv_df["STRIKE_PR"] >= lo_strike) & (iv_df["STRIKE_PR"] <= hi_strike)]
    
    if iv_df.empty:
        return None
        
    ce_iv = iv_df[iv_df["OPTION_TYP"] == "CE"].sort_values("STRIKE_PR")
    pe_iv = iv_df[iv_df["OPTION_TYP"] == "PE"].sort_values("STRIKE_PR")
    
    # Calculate ATM IV (closest strike to Spot CMP)
    atm_iv = 0.20
    if not ce_iv.empty:
        closest_idx = (ce_iv["STRIKE_PR"] - cmp_val).abs().argsort()[:1]
        if len(closest_idx) > 0:
            atm_iv = ce_iv.iloc[closest_idx]["IV"].values[0]
            
    fig = go.Figure()
    
    if not ce_iv.empty:
        fig.add_trace(go.Scatter(
            x=ce_iv["STRIKE_PR"], y=ce_iv["IV"] * 100, mode="lines+markers", name="Call IV",
            line=dict(color=C["call"], width=2), marker=dict(size=5)
        ))
        
    if not pe_iv.empty:
        fig.add_trace(go.Scatter(
            x=pe_iv["STRIKE_PR"], y=pe_iv["IV"] * 100, mode="lines+markers", name="Put IV",
            line=dict(color=C["put"], width=2), marker=dict(size=5)
        ))
        
    fig.add_hline(
        y=atm_iv * 100, line_dash="dot", line_color=C["cmp"],
        annotation_text=f" ATM IV: {atm_iv * 100:.1f}% ",
        annotation=dict(bgcolor="rgba(0,0,0,.75)", font_color=C["cmp"], font_size=10)
    )
    
    fig.add_vline(x=cmp_val, line_dash="dash", line_color=C["cmp"])
    if cw_val:
        fig.add_vline(x=cw_val, line_dash="solid", line_color=C["call"])
    if pw_val:
        fig.add_vline(x=pw_val, line_dash="solid", line_color=C["put"])
        
    fig.update_layout(
        **PB, height=520,
        legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="center", x=0.5, bgcolor="rgba(0,0,0,0)")
    )
    apply_axes(fig, {"xaxis": {"title": "Strike Price", "tickformat": ".0f"},
                        "yaxis": {"title": "Implied Volatility (%)"}})
                        
    return fig
