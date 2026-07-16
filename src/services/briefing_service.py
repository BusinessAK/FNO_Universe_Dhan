"""
briefing_service.py — Pure query layer for the daily Watchlist briefing.

All functions take an open duckdb.Connection and a date string (YYYY-MM-DD).
No I/O is performed here; callers handle printing and file-writing.
"""
from __future__ import annotations
import duckdb
import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Market Regime Context
# ─────────────────────────────────────────────────────────────────────────────

def get_regime_context(conn: duckdb.DuckDBPyConnection, date: str) -> dict:
    """
    Pulls cash market breadth + F&O index structure for the given date
    and synthesises a regime label and directional bias.

    Returns a dict with all raw metrics plus:
        regime_label  : str  one-liner description
        bias          : str  'LONG' | 'SHORT' | 'NEUTRAL'
        sizing        : str  'FULL' | 'HALF' | 'REDUCED'
    """
    # ── Cash breadth ──────────────────────────────────────────────────────────
    tables = conn.execute("SHOW TABLES").df()["name"].tolist()
    cm = {}
    if "daily_cm_breadth" in tables:
        row = conn.execute(
            "SELECT * FROM daily_cm_breadth WHERE CAST(date AS VARCHAR) LIKE ?",
            [f"{date}%"]
        ).df()
        if not row.empty:
            cm = row.iloc[0].to_dict()

    # ── F&O breadth ───────────────────────────────────────────────────────────
    fo = {}
    if "daily_market_breadth" in tables:
        row = conn.execute(
            "SELECT * FROM daily_market_breadth WHERE date = ?", [date]
        ).df()
        if not row.empty:
            fo = row.iloc[0].to_dict()

    # ── NIFTY / BANKNIFTY key levels ─────────────────────────────────────────
    idx = {}
    if "daily_market_structure" in tables:
        row = conn.execute(
            """SELECT symbol, spot_close, call_wall, put_wall, gamma_flip,
                      gamma_regime, futures_oi_chg, gex
               FROM daily_market_structure
               WHERE date = ? AND symbol IN ('NIFTY','BANKNIFTY')
               ORDER BY symbol""",
            [date]
        ).df()
        if not row.empty:
            for _, r in row.iterrows():
                idx[r["symbol"]] = r.to_dict()

    # ── Synthesise regime ─────────────────────────────────────────────────────
    adv_pct   = cm.get("cm_advance_pct", 0.0)
    dma20     = cm.get("cm_pct_above_20dma", 0.0)
    dma50     = cm.get("cm_pct_above_50dma", 0.0)
    dma200    = cm.get("cm_pct_above_200dma", 0.0)
    mcl       = cm.get("cm_mcclellan_osc", 0.0)

    # Structural score: how many DMA layers are above 50%?
    structural_score = sum([dma20 >= 50, dma50 >= 50, dma200 >= 50])

    # Missing cash breadth must read as "no data", never as "broad weakness":
    # with all metrics defaulting to 0.0 the elif chain below would otherwise
    # classify a data gap as SHORT / FULL sizing.
    if not cm or pd.isna(adv_pct):
        return {
            **cm,
            "fo_breadth": fo,
            "index_levels": idx,
            "regime_label": "Cash market breadth unavailable for this date — regime unknown.",
            "bias": "NEUTRAL",
            "sizing": "REDUCED",
        }

    if adv_pct >= 60 and structural_score >= 2:
        regime_label = (
            f"Broad strength ({adv_pct:.0f}% advancing) with bullish structure "
            f"({dma20:.0f}%/{dma50:.0f}%/{dma200:.0f}% above 20/50/200-DMA) — trending up."
        )
        bias = "LONG"
        sizing = "FULL"
    elif adv_pct < 40 and structural_score <= 1:
        regime_label = (
            f"Broad weakness ({100-adv_pct:.0f}% declining) with bearish structure "
            f"({dma20:.0f}%/{dma50:.0f}%/{dma200:.0f}% above 20/50/200-DMA) — downtrend."
        )
        bias = "SHORT"
        sizing = "FULL"
    elif adv_pct < 45 and structural_score >= 2:
        regime_label = (
            f"Bearish breadth ({100-adv_pct:.0f}% declining) but structurally bullish "
            f"({dma20:.0f}%/{dma50:.0f}%/{dma200:.0f}% above 20/50/200-DMA) "
            f"— pullback inside uptrend, NOT a trend reversal."
        )
        bias = "NEUTRAL"
        sizing = "HALF"
    elif adv_pct >= 55 and structural_score <= 1:
        regime_label = (
            f"Bullish breadth ({adv_pct:.0f}% advancing) but structurally weak "
            f"({dma20:.0f}%/{dma50:.0f}%/{dma200:.0f}% above 20/50/200-DMA) "
            f"— bounce inside downtrend, fade into strength."
        )
        bias = "SHORT"
        sizing = "HALF"
    else:
        regime_label = (
            f"Mixed/compression ({adv_pct:.0f}% advancing, "
            f"{dma20:.0f}%/{dma50:.0f}%/{dma200:.0f}% above 20/50/200-DMA) "
            f"— range-bound, await breakout."
        )
        bias = "NEUTRAL"
        sizing = "REDUCED"

    return {
        **cm,
        "fo_breadth": fo,
        "index_levels": idx,
        "regime_label": regime_label,
        "bias": bias,
        "sizing": sizing,
    }


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Top Setups
# ─────────────────────────────────────────────────────────────────────────────

def get_top_setups(
    conn: duckdb.DuckDBPyConnection,
    date: str,
    n: int = 15,
    bias: str = "NEUTRAL",
) -> list[dict]:
    """
    Returns the top-N setups for the date, ranked by priority_score DESC.
    If bias is LONG/SHORT, filters to matching bias first, then fills remainder.
    """
    tables = conn.execute("SHOW TABLES").df()["name"].tolist()
    if "daily_setups" not in tables or "daily_market_structure" not in tables:
        return []

    query = """
        SELECT
            s.symbol,
            s.sector,
            s.setup_type,
            s.bias,
            s.trigger_strike,
            s.invalidation_strike,
            s.expected_behavior,
            m.spot_close,
            m.call_wall,
            m.put_wall,
            m.gamma_flip,
            m.ifs_score,
            m.gamma_regime,
            m.priority_score,
            m.structural_bias
        FROM daily_setups s
        JOIN daily_market_structure m
            ON s.symbol = m.symbol AND s.date = m.date
        WHERE s.date = ?
          AND s.setup_type != 'NONE'
          AND s.setup_type IS NOT NULL
        ORDER BY m.priority_score DESC
    """
    df = conn.execute(query, [date]).df()
    if df.empty:
        return []

    # Reorder BEFORE limiting so matching-bias setups from the full day are
    # promoted, then the remainder fills up to n (as the docstring promises).
    if bias in ("LONG", "SHORT"):
        match = df[df["bias"].str.upper() == bias]
        rest  = df[df["bias"].str.upper() != bias]
        df = pd.concat([match, rest])

    return df.head(n).to_dict(orient="records")


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Sector Pulse
# ─────────────────────────────────────────────────────────────────────────────

def get_sector_pulse(
    conn: duckdb.DuckDBPyConnection, date: str
) -> list[dict]:
    """
    Aggregates IFS score, net inventory shift, and GEX shift by sector.
    Returns list sorted by avg_ifs DESC.
    """
    tables = conn.execute("SHOW TABLES").df()["name"].tolist()
    if "daily_market_structure" not in tables:
        return []

    query = """
        SELECT
            sector,
            COUNT(symbol)              AS symbols,
            ROUND(AVG(ifs_score), 2)   AS avg_ifs,
            ROUND(SUM(net_inv_shift), 0) AS total_net_inv,
            ROUND(SUM(gex_shift), 0)   AS total_gex_shift,
            ROUND(AVG(spot_change_pct), 2) AS avg_chg_pct
        FROM daily_market_structure
        WHERE date = ?
          AND sector IS NOT NULL
          AND sector NOT IN ('Other', 'Index')
        GROUP BY sector
        ORDER BY avg_ifs DESC
    """
    df = conn.execute(query, [date]).df()
    if df.empty:
        return []
    return df.to_dict(orient="records")


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Key Levels (NIFTY / BANKNIFTY)
# ─────────────────────────────────────────────────────────────────────────────

def get_key_levels(
    conn: duckdb.DuckDBPyConnection, date: str
) -> dict:
    """Returns gamma-level data for NIFTY and BANKNIFTY."""
    tables = conn.execute("SHOW TABLES").df()["name"].tolist()
    if "daily_market_structure" not in tables:
        return {}

    row = conn.execute(
        """SELECT symbol, spot_close, call_wall, put_wall, gamma_flip,
                  gamma_regime, futures_oi_chg, gex, gex_intensity,
                  structural_bias, suggested_strategy
           FROM daily_market_structure
           WHERE date = ? AND symbol IN ('NIFTY', 'BANKNIFTY')
           ORDER BY symbol""",
        [date]
    ).df()
    if row.empty:
        return {}

    result = {}
    for _, r in row.iterrows():
        result[r["symbol"]] = r.to_dict()
    return result


# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — IFS Leaders & Laggards
# ─────────────────────────────────────────────────────────────────────────────

def get_ifs_leaders(
    conn: duckdb.DuckDBPyConnection,
    date: str,
    n: int = 5,
) -> dict:
    """
    Returns top-N (bullish) and bottom-N (bearish) symbols by IFS score
    for the given date.
    """
    tables = conn.execute("SHOW TABLES").df()["name"].tolist()
    if "daily_market_structure" not in tables:
        return {"leaders": [], "laggards": []}

    base_query = """
        SELECT symbol, sector, ifs_score, spot_close, spot_change_pct,
               structural_bias, gamma_regime
        FROM daily_market_structure
        WHERE date = ? AND symbol NOT IN ('NIFTY', 'BANKNIFTY')
    """
    leaders  = conn.execute(
        base_query + " ORDER BY ifs_score DESC LIMIT ?", [date, n]
    ).df().to_dict(orient="records")

    laggards = conn.execute(
        base_query + " ORDER BY ifs_score ASC LIMIT ?", [date, n]
    ).df().to_dict(orient="records")

    return {"leaders": leaders, "laggards": laggards}


# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — Structural Alerts (daily_changes)
# ─────────────────────────────────────────────────────────────────────────────

def get_structural_alerts(
    conn: duckdb.DuckDBPyConnection, date: str, top_n: int = 20
) -> list[dict]:
    """Returns the top structural change alerts for the session."""
    tables = conn.execute("SHOW TABLES").df()["name"].tolist()
    if "daily_changes" not in tables:
        return []

    df = conn.execute(
        "SELECT * FROM daily_changes WHERE date = ? ORDER BY rank LIMIT ?",
        [date, top_n]
    ).df()
    if df.empty:
        return []
    return df.to_dict(orient="records")
