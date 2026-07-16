#!/usr/bin/env python3
"""
Generate latest stock swing candidates from validated OHLC backtest buckets.

This is not a signal generator by itself. It is a research gate: current
Vanguard setups are allowed through only when their historical setup/sector
and symbol buckets show positive expectancy under the latest OHLC backtest.
"""
from __future__ import annotations

import argparse
import os

import duckdb
import pandas as pd

from src.research.swing_backtester import (
    BacktestConfig,
    attach_trend_features,
    classify_long_candidate,
    compute_alpha_score,
    load_cash_price_data,
)


DEFAULT_OUTPUT = "data/research/latest_swing_candidates.csv"


def load_latest_setups(db_path: str, signal_date: str | None = None) -> pd.DataFrame:
    con = duckdb.connect(db_path, read_only=True)
    try:
        if signal_date is None:
            signal_date = con.execute("SELECT max(date) FROM daily_market_structure").fetchone()[0]
        query = """
            SELECT
                s.symbol,
                s.sector,
                s.date,
                s.spot_close,
                s.spot_change_pct,
                s.futures_oi_chg,
                s.net_inv_shift,
                s.ifs_score,
                s.smart_money_persistence,
                s.conviction_score,
                s.priority_score,
                s.call_wall,
                s.put_wall,
                s.gamma_flip,
                s.gamma_regime,
                s.structural_bias,
                s.suggested_strategy,
                COALESCE(s.ml_breakout_prob, 0.0) AS ml_breakout_prob,
                b.macro_regime_prob,
                st.setup_type,
                st.bias,
                st.trigger_strike,
                st.invalidation_strike,
                st.expected_behavior,
                st.dealer_behavior
            FROM daily_setups st
            JOIN daily_market_structure s
              ON s.symbol = st.symbol AND s.date = st.date
            LEFT JOIN daily_market_breadth b
              ON b.date = st.date
            WHERE st.setup_type != 'NONE'
              AND st.date = ?
        """
        df = con.execute(query, [signal_date]).df()
    finally:
        con.close()
    return df


def load_expectancy_tables(research_dir: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    setup = pd.read_csv(os.path.join(research_dir, "swing_setup_expectancy.csv"))
    sector = pd.read_csv(os.path.join(research_dir, "swing_sector_expectancy.csv"))
    symbol = pd.read_csv(os.path.join(research_dir, "swing_symbol_expectancy.csv"))
    return setup, sector, symbol


def best_positive(df: pd.DataFrame, keys: list[str], min_trades: int, min_avg: float) -> pd.DataFrame:
    work = df[(df["trades"] >= min_trades) & (df["avg_return_pct"] > min_avg)].copy()
    if work.empty:
        return work
    work = work.sort_values(keys + ["expectancy_rank", "avg_return_pct"], ascending=[True] * len(keys) + [False, False])
    return work.drop_duplicates(keys, keep="first")


def generate_candidates(
    config: BacktestConfig,
    research_dir: str = "data/research",
    signal_date: str | None = None,
    min_setup_avg: float = 0.0,
    min_sector_avg: float = 0.0,
    min_symbol_avg: float = 0.0,
    min_setup_trades: int = 25,
    min_sector_trades: int = 100,
    min_symbol_trades: int = 10,
) -> pd.DataFrame:
    latest = load_latest_setups(config.db_path, signal_date)
    if latest.empty:
        return latest

    latest["long_candidate"] = latest.apply(classify_long_candidate, axis=1)
    latest["alpha_score"] = latest.apply(compute_alpha_score, axis=1)
    latest = latest[latest["long_candidate"]].copy()
    if latest.empty:
        return latest

    if config.use_trend_filter:
        cash_prices = load_cash_price_data(config.price_data_path)
        if not cash_prices.empty:
            latest = attach_trend_features(latest, cash_prices, config.db_path)
            latest = latest[latest["trend_pass"].fillna(False)].copy()
            if latest.empty:
                return latest

    setup_exp, sector_exp, symbol_exp = load_expectancy_tables(research_dir)
    setup_best = best_positive(setup_exp, ["setup_type"], min_setup_trades, min_setup_avg)
    sector_best = best_positive(sector_exp, ["sector"], min_sector_trades, min_sector_avg)
    symbol_best = best_positive(symbol_exp, ["symbol"], min_symbol_trades, min_symbol_avg)

    out = latest.merge(
        setup_best.add_prefix("setup_hist_"),
        left_on="setup_type",
        right_on="setup_hist_setup_type",
        how="inner",
    )
    out = out.merge(
        sector_best.add_prefix("sector_hist_"),
        left_on="sector",
        right_on="sector_hist_sector",
        how="inner",
    )
    out = out.merge(
        symbol_best.add_prefix("symbol_hist_"),
        left_on="symbol",
        right_on="symbol_hist_symbol",
        how="left",
    )

    out["symbol_hist_avg_return_pct"] = out["symbol_hist_avg_return_pct"].fillna(0.0)
    out["symbol_hist_win_rate_pct"] = out["symbol_hist_win_rate_pct"].fillna(0.0)
    out["research_edge_score"] = (
        out["setup_hist_avg_return_pct"] * 0.35
        + out["sector_hist_avg_return_pct"] * 0.35
        + out["symbol_hist_avg_return_pct"] * 0.20
        + out["alpha_score"] * 0.01
    )

    out["planned_holding_days"] = out["setup_hist_holding_days"]
    out["fallback_stop"] = out["spot_close"] * 0.93
    out["planned_stop"] = out.apply(
        lambda r: max(float(r["invalidation_strike"] or 0.0), float(r["fallback_stop"]))
        if 0 < float(r["invalidation_strike"] or 0.0) < float(r["spot_close"])
        else float(r["fallback_stop"]),
        axis=1,
    )
    out["risk_pct_to_stop"] = ((out["planned_stop"] / out["spot_close"]) - 1.0) * 100.0
    out["expected_avg_return_pct"] = (
        out["setup_hist_avg_return_pct"] * 0.45
        + out["sector_hist_avg_return_pct"] * 0.35
        + out["symbol_hist_avg_return_pct"] * 0.20
    )

    cols = [
        "date", "symbol", "sector", "setup_type", "bias", "spot_close",
        "planned_stop", "risk_pct_to_stop", "planned_holding_days",
        "expected_avg_return_pct", "research_edge_score", "alpha_score",
        "trend_ret20_pct", "trend_rs20_pct", "trend_sma20", "trend_sma50",
        "ifs_score", "conviction_score", "macro_regime_prob",
        "setup_hist_avg_return_pct", "setup_hist_win_rate_pct", "setup_hist_trades",
        "sector_hist_avg_return_pct", "sector_hist_win_rate_pct", "sector_hist_trades",
        "symbol_hist_avg_return_pct", "symbol_hist_win_rate_pct", "symbol_hist_trades",
        "trigger_strike", "invalidation_strike", "suggested_strategy",
        "gamma_regime", "structural_bias",
    ]
    for col in cols:
        if col not in out.columns:
            out[col] = pd.NA

    return out[cols].sort_values(["research_edge_score", "expected_avg_return_pct"], ascending=False).reset_index(drop=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate validated latest stock swing candidates.")
    parser.add_argument("--db", default="data/compiled/vanguard.duckdb")
    parser.add_argument("--research-dir", default="data/research")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--date", default=None, help="Optional signal date YYYY-MM-DD. Defaults to latest compiled date.")
    parser.add_argument("--min-setup-avg", type=float, default=0.0)
    parser.add_argument("--min-sector-avg", type=float, default=0.0)
    parser.add_argument("--min-symbol-avg", type=float, default=0.0)
    parser.add_argument("--no-trend-filter", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = BacktestConfig(db_path=args.db, use_trend_filter=not args.no_trend_filter)
    candidates = generate_candidates(
        config=config,
        research_dir=args.research_dir,
        signal_date=args.date,
        min_setup_avg=args.min_setup_avg,
        min_sector_avg=args.min_sector_avg,
        min_symbol_avg=args.min_symbol_avg,
    )
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    candidates.to_csv(args.output, index=False)
    print("[SUCCESS] Latest swing candidate research gate complete.")
    print(f"candidates: {len(candidates):,}")
    print(f"output: {args.output}")
    if not candidates.empty:
        print(candidates.head(20).to_string(index=False))


if __name__ == "__main__":
    main()
