"""
Vanguard Institutional Terminal - Open Interest (OI) Concentration Charts
"""
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from vanguard.config.settings import C, PB
from vanguard.charts.base import add_hlines, apply_axes

def render_oi_concentration_chart(
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
    Renders a two-pane bar chart showing Call vs Put OI Profile and CE-PE Divergence.
    """
    st_greeks = greeks_df[greeks_df["SYMBOL"] == selected_symbol.upper()].copy()
    if selected_expiry != "ALL EXPIRIES":
        st_greeks = st_greeks[st_greeks["EXPIRY_DT"] == selected_expiry].copy()
        
    if st_greeks.empty:
        return None
        
    lo_strike = cmp_val * (1 - strike_pct / 100)
    hi_strike = cmp_val * (1 + strike_pct / 100)
    
    st_greeks["STRIKE_PR"] = pd.to_numeric(st_greeks["STRIKE_PR"], errors="coerce")
    st_greeks["OPEN_INT"] = pd.to_numeric(st_greeks["OPEN_INT"], errors="coerce")
    
    oi_data = (st_greeks.dropna(subset=["STRIKE_PR", "OPEN_INT"])
               .groupby(["STRIKE_PR", "OPTION_TYP"])["OPEN_INT"]
               .sum().unstack(fill_value=0))
               
    for col in ["CE", "PE"]:
        if col not in oi_data.columns:
            oi_data[col] = 0.0
            
    oi_data = oi_data[(oi_data.index >= lo_strike) & (oi_data.index <= hi_strike)]
    
    fig = make_subplots(
        rows=1, cols=2, column_widths=[0.60, 0.40],
        subplot_titles=["Call vs Put OI Profile (Lots)", "CE - PE Divergence"],
        horizontal_spacing=0.06, shared_yaxes=True
    )
    
    # Put OI (plotted negatively to show left side of profile)
    fig.add_trace(go.Bar(
        y=oi_data.index, x=-oi_data["PE"], name="Put OI",
        orientation="h", marker=dict(color=C["put"], opacity=0.85)
    ), row=1, col=1)
    
    # Call OI
    fig.add_trace(go.Bar(
        y=oi_data.index, x=oi_data["CE"], name="Call OI",
        orientation="h", marker=dict(color=C["call"], opacity=0.85)
    ), row=1, col=1)
    
    # Divergence
    diverg = oi_data["CE"] - oi_data["PE"]
    d_colors = [C["call"] if v > 0 else C["put"] for v in diverg]
    
    fig.add_trace(go.Bar(
        y=oi_data.index, x=diverg, name="Divergence",
        orientation="h", marker=dict(color=d_colors, opacity=0.9)
    ), row=1, col=2)
    
    add_hlines(fig, cmp_val, gf_val, cw_val, pw_val, rows_cols=[(1, 1), (1, 2)])
    
    fig.update_layout(
        **PB, barmode="overlay", height=580,
        legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="center", x=0.5, bgcolor="rgba(0,0,0,0)")
    )
    apply_axes(fig, {"yaxis": {"title": "Strike Price", "tickformat": ".0f"},
                        "xaxis": {"title": "Open Interest (Lots)"},
                        "yaxis2": {"tickformat": ".0f"},
                        "xaxis2": {"title": "Divergence (CE-PE)"}})
                        
    return fig
