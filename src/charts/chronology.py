"""
Vanguard Institutional Terminal - Chronological Wall Migration & OI Accumulation Charts
"""
import plotly.graph_objects as go
from src.config.settings import C, PB

def render_wall_migration_chart(sym_sessions: dict) -> go.Figure:
    """
    Plots the chronological wall migration step line chart showing Spot, Call Wall, Put Wall, and Gamma Flip.
    """
    chrono_dates = sorted(list(sym_sessions.keys()))
    spots = [sym_sessions[d]["spot_close"] for d in chrono_dates]
    calls = [sym_sessions[d]["call_wall"] for d in chrono_dates]
    puts = [sym_sessions[d]["put_wall"] for d in chrono_dates]
    flips = [sym_sessions[d]["gamma_flip"] for d in chrono_dates]
    
    fig = go.Figure()
    
    # Spot Price line
    fig.add_trace(go.Scatter(
        x=chrono_dates, y=spots, mode="lines+markers", name="Spot Close",
        line=dict(color=C["cmp"], width=2.5),
        marker=dict(size=6, symbol="circle")
    ))
    
    # Call Wall step line
    fig.add_trace(go.Scatter(
        x=chrono_dates, y=calls, mode="lines", name="Call Wall",
        line=dict(color=C["call"], width=2, shape="vh"),
        connectgaps=True
    ))
    
    # Put Wall step line
    fig.add_trace(go.Scatter(
        x=chrono_dates, y=puts, mode="lines", name="Put Wall",
        line=dict(color=C["put"], width=2, shape="vh"),
        connectgaps=True
    ))
    
    # Gamma Flip step line
    fig.add_trace(go.Scatter(
        x=chrono_dates, y=flips, mode="lines", name="Gamma Flip",
        line=dict(color=C["flip"], width=1.5, shape="vh", dash="dot"),
        connectgaps=True
    ))
    
    fig.update_layout(
        **PB,
        title="Chronological Wall Migration & Dealer Positioning Drift",
        height=460,
        xaxis=dict(gridcolor=C["grid"]),
        yaxis=dict(gridcolor=C["grid"]),
        legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, bgcolor="rgba(0,0,0,0)")
    )
    return fig

def render_cumulative_oi_chart(sym_sessions: dict) -> go.Figure:
    """
    Plots the stacked area chart of multi-day PE vs CE cumulative Open Interest.
    """
    chrono_dates = sorted(list(sym_sessions.keys()))
    ce_oi_cum = [sym_sessions[d]["total_ce_oi"] for d in chrono_dates]
    pe_oi_cum = [sym_sessions[d]["total_pe_oi"] for d in chrono_dates]
    
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(
        x=chrono_dates, y=ce_oi_cum, mode="lines", name="Total Call OI (CE)",
        line=dict(color=C["call"], width=2),
        stackgroup="one"
    ))
    fig.add_trace(go.Scatter(
        x=chrono_dates, y=pe_oi_cum, mode="lines", name="Total Put OI (PE)",
        line=dict(color=C["put"], width=2),
        stackgroup="two"
    ))
    
    fig.update_layout(
        **PB,
        title="Multi-Day F&O Inventory Accumulation Profile (Cumulative Open Interest)",
        height=400,
        xaxis=dict(gridcolor=C["grid"]),
        yaxis=dict(gridcolor=C["grid"]),
        legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, bgcolor="rgba(0,0,0,0)")
    )
    return fig
