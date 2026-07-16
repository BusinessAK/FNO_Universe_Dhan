#!/usr/bin/env python3
"""
Attribution study for top 20-session stock gainers.

This starts from realized forward winners, then inspects the signal date metrics
that existed before the move. The intent is to identify metrics that repeatedly
precede large gains, not to fit a prediction model.
"""
from __future__ import annotations

import argparse
import os

import duckdb
import numpy as np
import pandas as pd

from src.research.swing_backtester import (
    DEFAULT_PRICE_DATA_PATH,
    attach_trend_features,
    load_cash_price_data,
)


DEFAULT_DB = "data/compiled/vanguard.duckdb"
DEFAULT_OUTPUT_DIR = "data/research"


def load_compiled_metrics(db_path: str) -> pd.DataFrame:
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
                CASE WHEN COALESCE(setup_types, setup_type) LIKE '%GAMMA_SQUEEZE%'       THEN 1 ELSE 0 END AS has_gamma_squeeze,
                CASE WHEN COALESCE(setup_types, setup_type) LIKE '%FLOOR_BOUNCE%'        THEN 1 ELSE 0 END AS has_floor_bounce,
                CASE WHEN COALESCE(setup_types, setup_type) LIKE '%VOLATILITY_COIL%'     THEN 1 ELSE 0 END AS has_volatility_coil,
                CASE WHEN COALESCE(setup_types, setup_type) LIKE '%PINCH_ZONE%'          THEN 1 ELSE 0 END AS has_pinch_zone,
                CASE WHEN COALESCE(setup_types, setup_type) LIKE '%REGIME_SHIFT%'        THEN 1 ELSE 0 END AS has_regime_shift,
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
    return out


def build_forward_returns(prices: pd.DataFrame, symbols: set[str], horizon: int) -> pd.DataFrame:
    px = prices[prices["symbol"].isin(symbols)][["symbol", "date", "open", "high", "low", "close", "volume"]].copy()
    px = px.sort_values(["symbol", "date"])
    grouped = px.groupby("symbol", group_keys=False)

    px["entry_date"] = grouped["date"].shift(-1)
    px["entry_open"] = grouped["open"].shift(-1)
    px["exit_date"] = grouped["date"].shift(-horizon)
    px["exit_close"] = grouped["close"].shift(-horizon)
    px["fwd_return_20d_pct"] = ((px["exit_close"] / px["entry_open"]) - 1.0) * 100.0
    return px.dropna(subset=["entry_open", "exit_close", "fwd_return_20d_pct"])


def add_metric_buckets(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ifs_bucket"] = pd.cut(
        out["ifs_score"],
        bins=[-100, -30, 0, 15, 30, 60, 100],
        labels=["ifs_lt_-30", "ifs_-30_0", "ifs_0_15", "ifs_15_30", "ifs_30_60", "ifs_gt_60"],
    )
    out["rs20_bucket"] = pd.cut(
        out["trend_rs20_pct"],
        bins=[-100, -5, 0, 5, 10, 100],
        labels=["rs_lt_-5", "rs_-5_0", "rs_0_5", "rs_5_10", "rs_gt_10"],
    )
    out["ret20_bucket"] = pd.cut(
        out["trend_ret20_pct"],
        bins=[-100, -5, 0, 5, 10, 100],
        labels=["ret_lt_-5", "ret_-5_0", "ret_0_5", "ret_5_10", "ret_gt_10"],
    )
    out["gex_shift_bucket"] = pd.qcut(
        out["gex_shift"].rank(method="first"),
        q=5,
        labels=["gex_q1", "gex_q2", "gex_q3", "gex_q4", "gex_q5"],
    )
    out["net_inv_bucket"] = pd.qcut(
        out["net_inv_shift"].rank(method="first"),
        q=5,
        labels=["inv_q1", "inv_q2", "inv_q3", "inv_q4", "inv_q5"],
    )
    out["ml_bucket"] = pd.cut(
        out["ml_breakout_prob"].fillna(0.0),
        bins=[-0.01, 30, 40, 50, 60, 100],
        labels=["ml_0_30", "ml_30_40", "ml_40_50", "ml_50_60", "ml_gt_60"],
    )
    return out


def summarize_metric_lift(df: pd.DataFrame, baseline_cutoff: float) -> pd.DataFrame:
    rows = []
    metrics = [
        "ifs_bucket",
        "rs20_bucket",
        "ret20_bucket",
        "gex_shift_bucket",
        "net_inv_bucket",
        "ml_bucket",
        "gamma_regime",
        "structural_bias",
        "sector",
    ]
    setup_cols = [c for c in df.columns if c.startswith("has_")]

    for metric in metrics:
        for value, group in df.groupby(metric, dropna=True):
            if len(group) < 20:
                continue
            rows.append({
                "metric": metric,
                "value": value,
                "samples": len(group),
                "avg_fwd_20d_pct": group["fwd_return_20d_pct"].mean(),
                "median_fwd_20d_pct": group["fwd_return_20d_pct"].median(),
                "top_gainer_rate_pct": (group["fwd_return_20d_pct"] >= baseline_cutoff).mean() * 100.0,
                "win_rate_pct": (group["fwd_return_20d_pct"] > 0).mean() * 100.0,
            })

    for col in setup_cols:
        group = df[df[col] == 1]
        if len(group) < 20:
            continue
        rows.append({
            "metric": "setup_flag",
            "value": col.replace("has_", ""),
            "samples": len(group),
            "avg_fwd_20d_pct": group["fwd_return_20d_pct"].mean(),
            "median_fwd_20d_pct": group["fwd_return_20d_pct"].median(),
            "top_gainer_rate_pct": (group["fwd_return_20d_pct"] >= baseline_cutoff).mean() * 100.0,
            "win_rate_pct": (group["fwd_return_20d_pct"] > 0).mean() * 100.0,
        })

    summary = pd.DataFrame(rows)
    if summary.empty:
        return summary
    numeric = ["avg_fwd_20d_pct", "median_fwd_20d_pct", "top_gainer_rate_pct", "win_rate_pct"]
    summary[numeric] = summary[numeric].round(3)
    return summary.sort_values(["top_gainer_rate_pct", "avg_fwd_20d_pct"], ascending=False).reset_index(drop=True)


def run_study(
    db_path: str = DEFAULT_DB,
    price_data_path: str = DEFAULT_PRICE_DATA_PATH,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    horizon: int = 20,
    top_n: int = 50,
) -> dict[str, str]:
    os.makedirs(output_dir, exist_ok=True)
    metrics = load_compiled_metrics(db_path)
    prices = load_cash_price_data(price_data_path)
    fwd = build_forward_returns(prices, set(metrics["symbol"].unique()), horizon)

    study = metrics.merge(
        fwd[["symbol", "date", "entry_date", "entry_open", "exit_date", "exit_close", "fwd_return_20d_pct"]],
        on=["symbol", "date"],
        how="inner",
    )
    study = attach_trend_features(study, prices, db_path)
    study = add_metric_buckets(study)

    cutoff = study["fwd_return_20d_pct"].quantile(0.90)
    top_gainers = study.sort_values("fwd_return_20d_pct", ascending=False).head(top_n).copy()
    metric_lift = summarize_metric_lift(study, cutoff)

    paths = {
        "top_gainers": os.path.join(output_dir, "top_20d_gainers_attribution.csv"),
        "metric_lift": os.path.join(output_dir, "top_20d_metric_lift.csv"),
        "all_events": os.path.join(output_dir, "top_20d_all_events.csv"),
        "report": os.path.join(output_dir, "top_20d_gainers_report.md"),
    }

    top_cols = [
        "symbol", "sector", "date", "entry_date", "entry_open", "exit_date", "exit_close",
        "fwd_return_20d_pct", "setup_types", "ifs_score", "trend_ret20_pct",
        "trend_rs20_pct", "net_inv_shift", "gex_shift", "gex_intensity",
        "gamma_regime", "structural_bias", "conviction_score", "ml_breakout_prob",
        "call_wall", "put_wall", "gamma_flip",
    ]
    for col in top_cols:
        if col not in top_gainers.columns:
            top_gainers[col] = pd.NA
    top_gainers[top_cols].to_csv(paths["top_gainers"], index=False)
    metric_lift.to_csv(paths["metric_lift"], index=False)
    study.to_csv(paths["all_events"], index=False)
    write_report(paths["report"], study, top_gainers, metric_lift, cutoff, horizon)
    return paths


def write_report(path: str, study: pd.DataFrame, top_gainers: pd.DataFrame, metric_lift: pd.DataFrame, cutoff: float, horizon: int) -> None:
    lines = [
        "# Top 20-Session Gainers Attribution",
        "",
        f"- Events studied: `{len(study):,}`",
        f"- Forward horizon: `{horizon}` trading sessions",
        f"- Top-decile cutoff: `{cutoff:.2f}%`",
        f"- Universe: compiled F&O symbols with cash OHLC",
        "",
        "## Top Metric Buckets By Gainer Rate",
        "",
        _markdown_table(metric_lift.head(20)),
        "",
        "## Top Realized 20-Session Gainers",
        "",
        _markdown_table(top_gainers[[
            "symbol", "sector", "date", "fwd_return_20d_pct", "setup_types",
            "ifs_score", "trend_ret20_pct", "trend_rs20_pct", "net_inv_shift",
            "gex_shift", "gamma_regime", "structural_bias",
        ]].head(25)),
        "",
    ]
    with open(path, "w") as f:
        f.write("\n".join(lines))


def _markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_No rows._"
    return df.to_markdown(index=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Study metrics preceding top 20-session gainers.")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--price-data", default=DEFAULT_PRICE_DATA_PATH)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--horizon", type=int, default=20)
    parser.add_argument("--top-n", type=int, default=50)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = run_study(args.db, args.price_data, args.output_dir, args.horizon, args.top_n)
    print("[SUCCESS] Top gainer attribution complete.")
    for label, path in paths.items():
        print(f"{label}: {path}")


if __name__ == "__main__":
    main()

