#!/usr/bin/env python3
"""
Vanguard Institutional Terminal - Equity Technicals Compiler (Track B / E1)

PRD: docs/PRD_TRD_dual_track_signals_v1.md. Additive to vanguard.duckdb —
never deletes or rebuilds the file (daily_compiler.py owns that). Must run
AFTER daily_compiler.py in the nightly chain, same slot poll_context.py
occupies; refuses to run otherwise (E-X7).

Unlike daily_compiler.py's incremental session_history skip-logic, this is a
full stateless recompute every run (same semantics as CashMarketBreadthEngine
itself) — rolling windows (DMA200, 52w high/low) need full history anyway,
and CREATE OR REPLACE TABLE on just this one table is cheap and safe: it
cannot touch any other table in the file.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import duckdb
import pandas as pd

from vanguard.config.paths import DB
from vanguard.engines.equity_technicals import build_equity_technicals
from vanguard.pipeline.equity_setups_pipeline import build_equity_setups_and_positions

CM_PARQUET = os.path.join("data", "compiled", "cash_market_prices.parquet")
OUTPUT_PARQUET = os.path.join("data", "compiled", "daily_equity_technicals.parquet")

_POSITIONS_COLS = ["symbol", "sector", "setup_type", "bias", "direction",
                   "trigger_date", "trigger_price", "sl_price", "target_price",
                   "status", "resolved_date", "resolved_price"]


def _ordering_guard(con: "duckdb.DuckDBPyConnection", latest_cm_date) -> None:
    """E-X7: refuse to run if daily_compiler.py hasn't compiled at least as
    far as the equity data we're about to write for. Prevents Track B ever
    landing ahead of, or independent of, Track A's rebuild."""
    import datetime as _dt

    def _to_date(v) -> _dt.date:
        return pd.Timestamp(v).date()

    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    if "daily_market_structure" not in tables:
        raise RuntimeError(
            "daily_market_structure table missing — daily_compiler.py must run "
            "before equity_compiler.py (see PRD §4 ordering requirement, E-X7).")
    latest_fo_date = con.execute(
        "SELECT MAX(date) FROM daily_market_structure").fetchone()[0]
    if latest_fo_date is None or _to_date(latest_fo_date) < _to_date(latest_cm_date):
        raise RuntimeError(
            f"daily_market_structure's latest date ({latest_fo_date}) is behind "
            f"cash_market_prices' latest date ({latest_cm_date}) — daily_compiler.py "
            "needs to run first for today (E-X7 ordering guard).")


def main() -> int:
    if not os.path.exists(CM_PARQUET):
        print(f"[!] {CM_PARQUET} not found — run cash_market_builder.py first.")
        return 1
    if not os.path.exists(DB):
        print(f"[!] {DB} not found — daily_compiler.py must run first "
              "(it creates the DB file; equity_compiler.py only adds to it).")
        return 1

    print("[*] Connecting to existing vanguard.duckdb (additive — not rebuilding)...")
    con = duckdb.connect(str(DB))
    try:
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        delivery_df = (con.execute(
            "SELECT date, symbol, delivery_pct, delivered_qty FROM daily_delivery").fetchdf()
            if "daily_delivery" in tables else None)
        if delivery_df is None or delivery_df.empty:
            print("[!] daily_delivery not found/empty — delivery_pct_ratio_20d and "
                  "deliverable_vol_ratio_20d will be null this run (cash_market_prices.parquet's "
                  "own delivery columns are always null — see equity_technicals.py docstring).")

        df = build_equity_technicals(CM_PARQUET, OUTPUT_PARQUET, delivery_df=delivery_df)
        latest_cm_date = str(df["date"].max())

        _ordering_guard(con, latest_cm_date)
        con.execute("CREATE OR REPLACE TABLE daily_equity_technicals AS SELECT * FROM df")
        n = con.execute("SELECT COUNT(*) FROM daily_equity_technicals").fetchone()[0]
        print(f"[SUCCESS] daily_equity_technicals: {n} rows "
              f"({df['symbol'].nunique()} symbols, through {latest_cm_date})")

        breadth = (con.execute("SELECT date, cm_pct_above_50dma, cm_pct_oversold_30 "
                               "FROM daily_cm_breadth").fetchdf()
                   if "daily_cm_breadth" in tables else pd.DataFrame())
        if breadth.empty:
            print("[!] daily_cm_breadth not found/empty — BREADTH_DIVERGENCE_REVERSAL and "
                  "RSI_EXTREME_REBOUND (both need breadth context) will not fire this run.")

        print("[*] Screening setups (E3 — screener output only, NOT backtested/trusted; that's E4)...")
        df_setups, position_rows = build_equity_setups_and_positions(df, breadth)
        for row in position_rows:
            row.setdefault("sector", None)   # industry tagging is E6, not built yet
        df_positions = pd.DataFrame(position_rows, columns=_POSITIONS_COLS) if position_rows \
            else pd.DataFrame(columns=_POSITIONS_COLS)

        con.execute("CREATE OR REPLACE TABLE daily_equity_setups AS SELECT * FROM df_setups")
        con.execute("CREATE OR REPLACE TABLE daily_equity_setup_positions AS SELECT * FROM df_positions")
        n_setups = con.execute("SELECT COUNT(*) FROM daily_equity_setups").fetchone()[0]
        n_pos = con.execute("SELECT COUNT(*) FROM daily_equity_setup_positions").fetchone()[0]
        n_open = con.execute(
            "SELECT COUNT(*) FROM daily_equity_setup_positions WHERE status='OPEN'").fetchone()[0]
        print(f"[SUCCESS] daily_equity_setups: {n_setups} rows")
        print(f"[SUCCESS] daily_equity_setup_positions: {n_pos} rows ({n_open} currently OPEN)")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
