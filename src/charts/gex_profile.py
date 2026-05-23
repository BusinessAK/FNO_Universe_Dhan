"""
Vanguard Institutional Terminal - Dealer GEX Profile & Subplots
"""
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from src.config.settings import C, PB
from src.charts.base import add_hlines, apply_axes

def render_gex_profile_chart(
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
    Renders a two-pane bar chart showing Put/Call GEX by Strike and Net GEX Profile.
    """
    st_greeks = greeks_df[greeks_df["SYMBOL"] == selected_symbol.upper()].copy()
    if selected_expiry != "ALL EXPIRIES":
        st_greeks = st_greeks[st_greeks["EXPIRY_DT"] == selected_expiry].copy()
        
    if st_greeks.empty or "GEX" not in st_greeks.columns:
        return None
        
    lo_strike = cmp_val * (1 - strike_pct / 100)
    hi_strike = cmp_val * (1 + strike_pct / 100)
    
    # Cast and group GEX per strike
    st_greeks["STRIKE_PR"] = pd.to_numeric(st_greeks["STRIKE_PR"], errors="coerce")
    st_greeks["GEX"] = pd.to_numeric(st_greeks["GEX"], errors="coerce")
    
    sg = (st_greeks.dropna(subset=["STRIKE_PR", "GEX"])
             .groupby(["STRIKE_PR", "OPTION_TYP"])["GEX"]
             .sum().unstack(fill_value=0))
             
    for col in ["CE", "PE"]:
        if col not in sg.columns:
            sg[col] = 0.0
            
    sg = sg[(sg.index >= lo_strike) & (sg.index <= hi_strike)]
    sg["NET"] = sg["CE"] + sg["PE"]
    
    fig = make_subplots(
        rows=1, cols=2, column_widths=[0.60, 0.40],
        subplot_titles=["Dealer GEX by Strike (Lakhs)", "Net GEX Profile"],
        horizontal_spacing=0.06, shared_yaxes=True
    )
    
    # Put Bar (PE GEX is negative or positive, let's keep PE GEX / 1e5 as is)
    fig.add_trace(go.Bar(
        y=sg.index, x=sg["PE"]/1e5, name="Put GEX",
        orientation="h", marker=dict(color=C["put"], opacity=0.85)
    ), row=1, col=1)
    
    # Call Bar
    fig.add_trace(go.Bar(
        y=sg.index, x=sg["CE"]/1e5, name="Call GEX",
        orientation="h", marker=dict(color=C["call"], opacity=0.85)
    ), row=1, col=1)
    
    # Net Bar
    nc_colors = [C["net_pos"] if v >= 0 else C["net_neg"] for v in sg["NET"]]
    fig.add_trace(go.Bar(
        y=sg.index, x=sg["NET"]/1e5, name="Net GEX",
        orientation="h", marker=dict(color=nc_colors, opacity=0.9)
    ), row=1, col=2)
    
    add_hlines(fig, cmp_val, gf_val, cw_val, pw_val, rows_cols=[(1, 1), (1, 2)])
    
    fig.update_layout(
        **PB, barmode="relative", height=580,
        legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="center", x=0.5, bgcolor="rgba(0,0,0,0)")
    )
    apply_axes(fig, {"yaxis": {"title": "Strike Price", "tickformat": ".0f"},
                     "xaxis": {"title": "GEX (Lakhs)"},
                     "yaxis2": {"tickformat": ".0f"},
                     "xaxis2": {"title": "Net GEX (Lakhs)"}})
                     
    return fig
