#!/usr/bin/env python3
"""
Validation gate for the premium-verified IFS/net_inv_shift fix (Phase 3 of the
consolidated remediation plan), before it is trusted with a full recompile.

Mirrors vanguard/research/flip_backtester.py's methodology (forward-return
evaluation via attach_forward, quintile monotonicity as the decision
criterion) rather than inventing a new evaluation style, since that script's
pre-registered gate is the existing precedent in this repo for "should we
trust a corrected signal enough to recompile 258 sessions of history."

The NEW ifs_score is computed by re-running the real, now-fixed
InstitutionalIntelligence.analyze_market_structure across every consecutive
raw bhavcopy pair (the same call daily_compiler.py makes per day) and
re-applying daily_compiler.py's IFS formula (verbatim — see IFS_WEIGHTS
below) to its output. This does not touch data/compiled/ — it is read-only
against data/raw/ and vanguard.duckdb.

Usage:
    python3 vanguard/research/ifs_verified_flow_backtest.py [--db PATH] [--out DIR]
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from vanguard.intelligence import InstitutionalIntelligence  # noqa: E402
from vanguard.research.flip_backtester import attach_forward  # noqa: E402

HOLDS = (1, 3, 5)
COST_RT_PCT = 0.40


def safe_float(v, default=0.0):
    try:
        f = float(v)
        return default if np.isnan(f) else f
    except (TypeError, ValueError):
        return default


def compute_ifs_row(row: pd.Series) -> float:
    """Verbatim reproduction of the IFS formula at daily_compiler.py:183-200,
    post Phase-1 fix (verified flow, summed not subtracted)."""
    vol_t = safe_float(row.get("VOLUME_CE_T")) + safe_float(row.get("VOLUME_PE_T"))
    vol_tm1 = safe_float(row.get("VOLUME_CE_TM1")) + safe_float(row.get("VOLUME_PE_TM1"))
    vol_delta_scaled = (vol_t - vol_tm1) / 1e5

    pe_oi_scaled = safe_float(row.get("VERIFIED_PE_FLOW")) / 1e5
    ce_oi_scaled = safe_float(row.get("VERIFIED_CE_FLOW")) / 1e5
    gex_shift_scaled = safe_float(row.get("GEX_SHIFT")) / 2e5
    price_acc = safe_float(row.get("SPOT_CHG_PCT"))

    ifs = (0.35 * pe_oi_scaled) + (0.35 * ce_oi_scaled) + (0.10 * vol_delta_scaled) \
        + (0.10 * gex_shift_scaled) + (0.10 * price_acc)
    return round(max(-100.0, min(100.0, ifs * 15.0)), 1)


def recompute_new_ifs(raw_dir: str) -> pd.DataFrame:
    files = sorted(glob.glob(os.path.join(raw_dir, "FO_BhavCopy*.csv")))
    intel = InstitutionalIntelligence()
    rows = []
    for f_tm1, f_t in zip(files, files[1:]):
        date_str = re.search(r"_(\d{8})_", f_t).group(1)
        date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        try:
            final = intel.analyze_market_structure(f_t, f_tm1, export_path=None)
        except Exception as e:
            print(f"[!] skip {date}: {e}", file=sys.stderr)
            continue
        for _, row in final.iterrows():
            rows.append({
                "symbol": row["SYMBOL"], "date": date,
                "new_ifs_score": compute_ifs_row(row),
            })
    return pd.DataFrame(rows)


def load_old(db_path: str) -> pd.DataFrame:
    con = duckdb.connect(db_path, read_only=True)
    try:
        df = con.execute("""
            SELECT symbol, date, spot_close, ifs_score AS old_ifs_score
            FROM daily_market_structure ORDER BY symbol, date
        """).df()
    finally:
        con.close()
    df["date"] = df["date"].astype(str)
    return df


EMPTY_BUCKETS = pd.DataFrame(columns=["variant", "quintile", "n", "fwd3_pct", "hit3_pct"])


def quintile_report(df: pd.DataFrame, score_col: str, label: str) -> pd.DataFrame:
    d = df.dropna(subset=[score_col, "entry_close", "exit_3"]).copy()
    if len(d) < 5:
        print(f"[!] {label}: only {len(d)} rows have a forward-3d return "
              f"(not enough history in range for quintiles) — skipping.", file=sys.stderr)
        return EMPTY_BUCKETS
    d["fwd3"] = (d["exit_3"] - d["entry_close"]) / d["entry_close"] * 100.0
    d["q"] = pd.qcut(d[score_col], 5, labels=False, duplicates="drop")
    rows = []
    for q, sub in d.groupby("q"):
        rows.append({
            "variant": label, "quintile": int(q), "n": len(sub),
            "fwd3_pct": round(sub["fwd3"].mean(), 3),
            "hit3_pct": round((sub["fwd3"] > 0).mean() * 100, 1),
        })
    return pd.DataFrame(rows).sort_values("quintile")


def is_monotonic_improving(bucket_df: pd.DataFrame) -> bool:
    """Decision-gate criterion, matching flip_backtester's precedent: forward
    return should rise monotonically (non-decreasing) from bearish to
    bullish quintiles, and the extremes should carry the correct sign."""
    vals = bucket_df.sort_values("quintile")["fwd3_pct"].tolist()
    if len(vals) < 5:
        return False
    non_decreasing = all(b >= a - 0.02 for a, b in zip(vals, vals[1:]))  # tiny float slack
    correct_signs = vals[0] < 0 and vals[-1] > 0
    return non_decreasing and correct_signs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "compiled" / "vanguard.duckdb"))
    ap.add_argument("--raw", default=str(ROOT / "data" / "raw"))
    ap.add_argument("--out", default=str(ROOT / "data" / "research"))
    args = ap.parse_args()

    print("[*] Loading stored (old) ifs_score + spot history from DB...")
    old = load_old(args.db)

    print("[*] Recomputing (new) verified-flow ifs_score across full raw history...")
    new = recompute_new_ifs(args.raw)

    merged = old.merge(new, on=["symbol", "date"], how="inner")
    print(f"[*] joined rows: {len(merged):,}  "
          f"(old-only: {len(old) - len(merged):,}, new-only: {len(new) - len(merged):,})")

    px = merged[["symbol", "date", "spot_close"]].drop_duplicates()
    entry_exit = attach_forward(merged[["symbol", "date"]], px)
    merged = merged.merge(entry_exit, on=["symbol", "date"], how="left")

    old_buckets = quintile_report(merged, "old_ifs_score", "OLD (raw OI sign)")
    new_buckets = quintile_report(merged, "new_ifs_score", "NEW (verified flow)")

    corr_frame = merged.dropna(subset=["entry_close", "exit_3"]).copy()
    if len(corr_frame) >= 2:
        corr_frame["fwd3"] = (corr_frame["exit_3"] - corr_frame["entry_close"]) / corr_frame["entry_close"] * 100.0
        corr_old = corr_frame["old_ifs_score"].corr(corr_frame["fwd3"])
        corr_new = corr_frame["new_ifs_score"].corr(corr_frame["fwd3"])
    else:
        corr_old = corr_new = float("nan")

    os.makedirs(args.out, exist_ok=True)
    report_lines = [
        "# IFS Verified-Flow Fix — Pre-Recompile Validation Gate", "",
        f"Rows compared: {len(merged):,} symbol-days. Forward-3-day return, "
        f"quintile-bucketed by ifs_score, same methodology as "
        f"flip_backtest_report.md.", "",
        "## OLD (raw OI sign assumption)", "",
        old_buckets.to_string(index=False), "",
        f"corr(ifs_score, fwd3): {corr_old:.4f}", "",
        "## NEW (premium-verified flow)", "",
        new_buckets.to_string(index=False), "",
        f"corr(ifs_score, fwd3): {corr_new:.4f}", "",
    ]

    gate_old = is_monotonic_improving(old_buckets)
    gate_new = is_monotonic_improving(new_buckets)
    verdict = (
        "PASS — NEW clears the monotonicity/sign gate; proceed to recompile."
        if gate_new else
        "NO-GO — NEW does not clear the monotonicity/sign gate; do not recompile "
        "without revisiting the fix."
    )
    report_lines += [
        "## Decision gate (matches flip_backtester precedent: quintile fwd3 "
        "must be non-decreasing bearish-to-bullish, with correct-signed "
        "extremes)", "",
        f"OLD clears gate: {gate_old}", f"NEW clears gate: {gate_new}", "",
        f"**Verdict: {verdict}**", "",
    ]

    report_path = Path(args.out) / "ifs_verified_flow_validation.md"
    report_path.write_text("\n".join(report_lines))

    print()
    print("=== OLD (raw OI sign) ===")
    print(old_buckets.to_string(index=False))
    print(f"corr={corr_old:.4f}  gate={'PASS' if gate_old else 'FAIL'}")
    print()
    print("=== NEW (verified flow) ===")
    print(new_buckets.to_string(index=False))
    print(f"corr={corr_new:.4f}  gate={'PASS' if gate_new else 'FAIL'}")
    print()
    print(f"VERDICT: {verdict}")
    print(f"report -> {report_path}")


if __name__ == "__main__":
    main()
