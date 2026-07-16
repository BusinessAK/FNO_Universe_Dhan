#!/usr/bin/env python3
"""
Day-wise F&O top gainers footprint study.

For each compiled trading date, this identifies the top cash-market gainers
inside the F&O universe and inspects which Vanguard metrics were visible on the
same date and the prior session.
"""
from __future__ import annotations

import argparse
import os

import duckdb
import pandas as pd

from src.research.swing_backtester import (
    DEFAULT_PRICE_DATA_PATH,
    attach_trend_features,
    load_cash_price_data,
)


DEFAULT_DB = "data/compiled/vanguard.duckdb"
DEFAULT_OUTPUT_DIR = "data/research"


def load_metrics_with_setups(db_path: str) -> pd.DataFrame:
    con = duckdb.connect(db_path, read_only=True)
    try:
        metrics = con.execute(
            """
            SELECT
                s.*,
                b.bullish_pct AS market_bullish_pct,
                b.bearish_pct AS market_bearish_pct,
                b.expansion_pct AS market_expansion_pct,
                b.compression_pct AS market_compression_pct,
                b.macro_regime_prob
            FROM daily_market_structure s
            LEFT JOIN daily_market_breadth b
              ON b.date = s.date
            """
        ).df()
        setups = con.execute(
            """
            SELECT
                symbol,
                date,
                -- setup_types is now a pre-computed pipe-delimited column (one row per symbol/date)
                COALESCE(setup_types, setup_type) AS setup_types,
                CASE WHEN COALESCE(setup_types, setup_type) LIKE '%GAMMA_SQUEEZE%'     THEN 1 ELSE 0 END AS has_gamma_squeeze,
                CASE WHEN COALESCE(setup_types, setup_type) LIKE '%FLOOR_BOUNCE%'      THEN 1 ELSE 0 END AS has_floor_bounce,
                CASE WHEN COALESCE(setup_types, setup_type) LIKE '%VOLATILITY_COIL%'   THEN 1 ELSE 0 END AS has_volatility_coil,
                CASE WHEN COALESCE(setup_types, setup_type) LIKE '%PINCH_ZONE%'        THEN 1 ELSE 0 END AS has_pinch_zone,
                CASE WHEN COALESCE(setup_types, setup_type) LIKE '%REGIME_SHIFT%'      THEN 1 ELSE 0 END AS has_regime_shift,
                CASE WHEN COALESCE(setup_types, setup_type) LIKE '%INVENTORY_MIGRATION%' THEN 1 ELSE 0 END AS has_inventory_migration,
                CASE WHEN COALESCE(setup_types, setup_type) LIKE '%IV_SKEW_ACCUMULATION%' THEN 1 ELSE 0 END AS has_iv_skew_accumulation
            FROM daily_setups
            WHERE setup_type != 'NONE'
            """
        ).df()
    finally:
        con.close()

    metrics["date"] = pd.to_datetime(metrics["date"])
    setups["date"] = pd.to_datetime(setups["date"])
    out = metrics.merge(setups, on=["symbol", "date"], how="left")
    out["setup_types"] = out["setup_types"].fillna("")
    for col in [c for c in out.columns if c.startswith("has_")]:
        out[col] = out[col].fillna(0).astype(int)
    return out.sort_values(["symbol", "date"]).reset_index(drop=True)


def build_daily_return_frame(prices: pd.DataFrame, fno_symbols: set[str]) -> pd.DataFrame:
    px = prices[prices["symbol"].isin(fno_symbols)].copy()
    px = px.sort_values(["symbol", "date"])
    grouped = px.groupby("symbol", group_keys=False)
    px["prev_close"] = grouped["close"].shift(1)
    px["day_return_pct"] = ((px["close"] / px["prev_close"]) - 1.0) * 100.0
    px["intraday_return_pct"] = ((px["close"] / px["open"]) - 1.0) * 100.0
    px["range_pct"] = ((px["high"] / px["low"]) - 1.0) * 100.0
    return px.dropna(subset=["prev_close", "day_return_pct"])


def add_prior_metrics(metrics: pd.DataFrame) -> pd.DataFrame:
    out = metrics.copy()
    prior_cols = [
        "ifs_score", "net_inv_shift", "gex_shift", "gex_intensity", "iv_shift",
        "ml_breakout_prob", "conviction_score", "priority_score",
        "gamma_regime", "structural_bias", "setup_types",
        "has_gamma_squeeze", "has_floor_bounce", "has_volatility_coil",
        "has_pinch_zone", "has_regime_shift", "has_inventory_migration",
        "has_iv_skew_accumulation",
    ]
    grouped = out.groupby("symbol", group_keys=False)
    for col in prior_cols:
        if col in out.columns:
            out[f"prev_{col}"] = grouped[col].shift(1)
    return out


def summarize_footprints(top: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    rows = []
    setup_cols = [c for c in top.columns if c.startswith("prev_has_")]
    same_setup_cols = [c for c in top.columns if c.startswith("has_")]

    def add_row(metric: str, value: str, mask_top: pd.Series, mask_all: pd.Series):
        top_rate = float(mask_top.mean() * 100.0) if len(mask_top) else 0.0
        all_rate = float(mask_all.mean() * 100.0) if len(mask_all) else 0.0
        rows.append({
            "metric": metric,
            "value": value,
            "top_gainer_rate_pct": round(top_rate, 3),
            "all_fno_rate_pct": round(all_rate, 3),
            "lift_pct_points": round(top_rate - all_rate, 3),
            "top_samples": int(mask_top.sum()),
            "all_samples": int(mask_all.sum()),
        })

    for col in setup_cols:
        base_col = col.replace("prev_", "")
        if base_col in universe.columns:
            add_row("prior_setup", col.replace("prev_has_", ""), top[col].fillna(0).eq(1), universe[base_col].fillna(0).eq(1))

    for col in same_setup_cols:
        if col in universe.columns:
            add_row("same_day_setup", col.replace("has_", ""), top[col].fillna(0).eq(1), universe[col].fillna(0).eq(1))

    bucket_specs = [
        ("prev_gamma_regime", "gamma_regime"),
        ("prev_structural_bias", "structural_bias"),
        ("sector", "sector"),
    ]
    for top_col, all_col in bucket_specs:
        if top_col not in top.columns or all_col not in universe.columns:
            continue
        for value in sorted(top[top_col].dropna().unique()):
            add_row(top_col, str(value), top[top_col].eq(value), universe[all_col].eq(value))

    numeric_checks = [
        ("prev_ml_breakout_prob", "ml_breakout_prob", 60.0, ">60"),
        ("prev_ifs_score", "ifs_score", 30.0, ">30"),
        ("prev_net_inv_shift", "net_inv_shift", 0.0, ">0"),
        ("prev_gex_shift", "gex_shift", 0.0, ">0"),
        ("prev_iv_shift", "iv_shift", 0.0, ">0"),
        ("trend_rs20_pct", "trend_rs20_pct", 5.0, ">5"),
        ("trend_ret20_pct", "trend_ret20_pct", 0.0, ">0"),
    ]
    for top_col, all_col, threshold, label in numeric_checks:
        if top_col in top.columns and all_col in universe.columns:
            add_row(top_col, label, pd.to_numeric(top[top_col], errors="coerce").gt(threshold), pd.to_numeric(universe[all_col], errors="coerce").gt(threshold))

    summary = pd.DataFrame(rows)
    if summary.empty:
        return summary
    return summary.sort_values(["lift_pct_points", "top_gainer_rate_pct"], ascending=False).reset_index(drop=True)


def run_study(
    db_path: str = DEFAULT_DB,
    price_data_path: str = DEFAULT_PRICE_DATA_PATH,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    top_n_per_day: int = 10,
) -> dict[str, str]:
    os.makedirs(output_dir, exist_ok=True)
    metrics = load_metrics_with_setups(db_path)
    prices = load_cash_price_data(price_data_path)
    returns = build_daily_return_frame(prices, set(metrics["symbol"].unique()))

    universe = metrics.merge(
        returns[["symbol", "date", "open", "high", "low", "close", "prev_close", "day_return_pct", "intraday_return_pct", "range_pct", "volume"]],
        on=["symbol", "date"],
        how="inner",
    )
    universe = attach_trend_features(universe, prices, db_path)
    universe = add_prior_metrics(universe)
    universe = universe.dropna(subset=["day_return_pct"])

    top = (
        universe.sort_values(["date", "day_return_pct"], ascending=[True, False])
        .groupby("date", group_keys=False)
        .head(top_n_per_day)
        .sort_values(["date", "day_return_pct"], ascending=[True, False])
        .reset_index(drop=True)
    )
    summary = summarize_footprints(top, universe)

    paths = {
        "daily_top_gainers": os.path.join(output_dir, "daily_fno_top_gainers_footprints.csv"),
        "footprint_lift": os.path.join(output_dir, "daily_fno_top_gainers_footprint_lift.csv"),
        "report": os.path.join(output_dir, "daily_fno_top_gainers_footprints_report.md"),
    }

    top_cols = [
        "date", "symbol", "sector", "day_return_pct", "intraday_return_pct", "range_pct",
        "open", "high", "low", "close", "volume", "prev_setup_types", "setup_types",
        "prev_gamma_regime", "gamma_regime", "prev_structural_bias", "structural_bias",
        "prev_ifs_score", "ifs_score", "prev_ml_breakout_prob", "ml_breakout_prob",
        "prev_net_inv_shift", "net_inv_shift", "prev_gex_shift", "gex_shift",
        "prev_iv_shift", "iv_shift", "trend_ret20_pct", "trend_rs20_pct",
    ]
    for col in top_cols:
        if col not in top.columns:
            top[col] = pd.NA

    top[top_cols].to_csv(paths["daily_top_gainers"], index=False)
    summary.to_csv(paths["footprint_lift"], index=False)
    write_report(paths["report"], top[top_cols], summary, top_n_per_day)
    return paths


def write_report(path: str, top: pd.DataFrame, summary: pd.DataFrame, top_n_per_day: int) -> None:
    lines = [
        "# Day-Wise F&O Top Gainers Footprint Study",
        "",
        f"- Top gainers per day: `{top_n_per_day}`",
        f"- Top gainer rows: `{len(top):,}`",
        "",
        "## Strongest Footprint Lifts",
        "",
        _markdown_table(summary.head(30)),
        "",
        "## Recent Day-Wise Top Gainers",
        "",
        _markdown_table(top.sort_values(["date", "day_return_pct"], ascending=[False, False]).head(40)),
        "",
    ]
    with open(path, "w") as f:
        f.write("\n".join(lines))


def _markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_No rows._"
    return df.to_markdown(index=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Study day-wise F&O top gainer footprints.")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--price-data", default=DEFAULT_PRICE_DATA_PATH)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--top-n", type=int, default=10)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = run_study(args.db, args.price_data, args.output_dir, args.top_n)
    print("[SUCCESS] Day-wise top gainers footprint study complete.")
    for label, path in paths.items():
        print(f"{label}: {path}")


if __name__ == "__main__":
    main()

