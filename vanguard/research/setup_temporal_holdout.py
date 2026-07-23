#!/usr/bin/env python3
"""
Full-system temporal holdout — every setup type, both tracks, one method.

Follow-on to equity_setups_temporal_holdout.py's finding that MOMENTUM_BUILDUP's
full-history PASS verdict was masking a hard regime flip (NO-GO before the
2026-03 correction, PASS only after the 2026-04 V-shaped recovery). That
result means no setup type in either track can be trusted from a single
full-history win_rate/total_r number alone -- this script runs the same
early/late split against daily_setup_positions (Track A / F&O) AND
daily_equity_setup_positions (Track B / Equity) so every setup type gets
checked the same way, not just the two Track B setups large enough to have
prompted the question.

Cutoff default (2026-04-01) is not track-specific -- it lines up with a real,
whole-market event (NIFTY -10.2% in March 2026, +5.8% in April), so it is
exactly as relevant to F&O setups as it was to the equity ones.

Usage:
  python3 -m vanguard.research.setup_temporal_holdout                  # both tracks
  python3 -m vanguard.research.setup_temporal_holdout --table fno      # F&O only
  python3 -m vanguard.research.setup_temporal_holdout --table equity   # equity only
  python3 -m vanguard.research.setup_temporal_holdout --cutoff 2026-05-01
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from vanguard.config.paths import DB, RESEARCH  # noqa: E402
from vanguard.research.position_stats import summarize_by_group  # noqa: E402

MIN_N = 30
DEFAULT_CUTOFF = "2026-04-01"
REPORT_PATH = RESEARCH / "setup_temporal_holdout_v1.md"

TABLES = {
    "fno": ("daily_setup_positions", "Track A / F&O"),
    "equity": ("daily_equity_setup_positions", "Track B / Equity"),
}


def _verdict(row: pd.Series) -> str:
    if row["n"] < MIN_N:
        return "INCONCLUSIVE (n too small)"
    if row["total_r"] <= 0:
        return "NO-GO"
    if row["win_rate"] > 50:
        return "PASS"
    return "PASS (asymmetric payoff)"


def _consistency(row: pd.Series) -> str:
    ve, vl = row.get("verdict_early"), row.get("verdict_late")
    if pd.isna(ve) or pd.isna(vl):
        return "MISSING FOLD"
    early_pass = str(ve).startswith("PASS")
    late_pass = str(vl).startswith("PASS")
    if "INCONCLUSIVE" in str(ve) or "INCONCLUSIVE" in str(vl):
        return "INCONCLUSIVE (n too thin in a fold)"
    if early_pass and late_pass:
        return "CONSISTENT — holds in both folds"
    if early_pass and not late_pass:
        return "OVERFIT RISK — passed early, fails late"
    if not early_pass and late_pass:
        return "OVERFIT RISK — passed late, fails early"
    return "CONSISTENT — fails in both folds (real NO-GO)"


def run_table(table: str, cutoff: str, con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    positions = con.execute(
        f"SELECT * FROM {table} WHERE status != 'OPEN'"
    ).fetchdf()
    if positions.empty:
        return pd.DataFrame()

    early = positions[positions["trigger_date"] < cutoff]
    late = positions[positions["trigger_date"] >= cutoff]

    g_early = summarize_by_group(early, group_col="setup_type")
    g_late = summarize_by_group(late, group_col="setup_type")
    g_full = summarize_by_group(positions, group_col="setup_type")
    g_early["verdict"] = g_early.apply(_verdict, axis=1)
    g_late["verdict"] = g_late.apply(_verdict, axis=1)
    g_full["verdict"] = g_full.apply(_verdict, axis=1)

    combined = g_full[["n", "total_r", "verdict"]].join(
        g_early[["n", "total_r", "verdict"]], how="outer", lsuffix="_full", rsuffix="_early"
    ).join(
        g_late[["n", "total_r", "verdict"]].rename(
            columns={"n": "n_late", "total_r": "total_r_late", "verdict": "verdict_late"}
        ),
        how="outer",
    )
    return combined


def write_report(results: dict[str, pd.DataFrame], cutoff: str, unfired: dict[str, list[str]]) -> Path:
    lines = [
        "# Full-System Temporal Holdout — Every Setup Type, Both Tracks",
        "",
        f"Run date: {date.today().isoformat()} · cutoff {cutoff} "
        f"(NIFTY -10.2% Mar 2026 -> +5.8% Apr 2026 — a real regime boundary, "
        f"not a fitted split point) · early = trigger_date < cutoff, "
        f"late = trigger_date >= cutoff · resolved positions only · MIN_N = {MIN_N} per fold",
        "",
    ]
    for key, df in results.items():
        _, label = TABLES[key]
        lines += [f"## {label}", "",
            "| Setup Type | N (full) | Total R (full) | Verdict (full) | "
            "N (early) | Total R (early) | N (late) | Total R (late) | Consistency |",
            "|---|---|---|---|---|---|---|---|---|"]
        for setup_type, row in df.iterrows():
            def fnum(v, fmt="+.2f"):
                return "-" if pd.isna(v) else f"{v:{fmt}}"
            def fint(v):
                return "-" if pd.isna(v) else int(v)
            lines.append(
                f"| {setup_type} | {fint(row.get('n_full'))} | {fnum(row.get('total_r_full'))}R | "
                f"{row.get('verdict_full', 'MISSING')} | {fint(row.get('n_early'))} | "
                f"{fnum(row.get('total_r_early'))}R | {fint(row.get('n_late'))} | "
                f"{fnum(row.get('total_r_late'))}R | **{_consistency(row)}** |"
            )
        if unfired.get(key):
            lines.append("")
            lines.append(
                f"**Never reached a tracked position:** {', '.join(unfired[key])} — "
                "see the 'structurally silenced' note below."
            )
        lines.append("")

    lines += [
        "## Reading this table",
        "- **CONSISTENT (holds in both folds)**: survives outside the window it was eyeballed on — "
        "the strongest evidence available in this dataset.",
        "- **OVERFIT RISK**: verdict flips between folds — fit to one part of the sample, not a "
        "stable effect. Do not scale size/priority without independent confirmation.",
        "- **INCONCLUSIVE**: n < 30 in at least one fold.",
        "",
        "**Structurally silenced setups** (F&O: IV_SPIKE, IV_CRUSH, IV_SKEW_ACCUMULATION): these "
        "fire routinely as raw signals in `daily_setups` (219 / 232 / 3,222 times respectively) but "
        "sit last in `SETUP_PRIORITY` (config/eod.py) — whenever any of the other 7 F&O setup types "
        "also fires for the same symbol/day, one of those wins the slot instead. Result: zero rows "
        "in `daily_setup_positions`, ever. Not proven wrong — structurally prevented from ever being "
        "tested under the current priority scheme.",
        "",
        "Same single-regime caveat as the equity-only run: every fold here sits inside the same "
        "~13-month window (one correction, one recovery, no prolonged bear/range-bound market) — "
        "CONSISTENT across these two folds is not the same as robust across a full market cycle.",
    ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n")
    return REPORT_PATH


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", choices=["fno", "equity", "both"], default="both")
    ap.add_argument("--cutoff", default=DEFAULT_CUTOFF)
    args = ap.parse_args()

    keys = ["fno", "equity"] if args.table == "both" else [args.table]
    con = duckdb.connect(str(DB), read_only=True)
    results = {}
    unfired = {}
    try:
        for key in keys:
            table, label = TABLES[key]
            print(f"=== {label} ({table}) ===")
            df = run_table(table, args.cutoff, con)
            results[key] = df
            pd.set_option("display.width", 160)
            print(df)
            print()
            if key == "fno":
                configured = {"DEALER_DEFENSE", "FLOOR_BOUNCE", "GAMMA_SQUEEZE",
                              "INVENTORY_MIGRATION", "IV_CRUSH", "IV_SKEW_ACCUMULATION",
                              "IV_SPIKE", "PINCH_ZONE", "REGIME_SHIFT", "VOLATILITY_COIL"}
                unfired[key] = sorted(configured - set(df.index))
            elif key == "equity":
                configured = {"BREADTH_DIVERGENCE_REVERSAL", "IMBALANCE_CONSOLIDATION",
                              "MOMENTUM_BUILDUP", "RSI_EXTREME_REBOUND", "FIFTYTWO_WEEK_BREAKOUT"}
                unfired[key] = sorted(configured - set(df.index))
    finally:
        con.close()

    path = write_report(results, args.cutoff, unfired)
    print(f"[SUCCESS] Report written -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
