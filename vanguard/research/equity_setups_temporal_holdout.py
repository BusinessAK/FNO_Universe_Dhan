#!/usr/bin/env python3
"""
Track B temporal holdout — is the E4 backtest gate's PASS real edge or a
parameter fit to the window it was measured on?

vanguard/config/equity.py's NATR_TRIGGER_MULT/NATR_SL_MULT for
IMBALANCE_CONSOLIDATION were chosen by a grid sweep evaluated against
total_r over the WHOLE history, then equity_setups_backtest.py reports a
PASS verdict measured over that same whole history — the config file's own
comment flags this as "in-sample only, still unlocked, no out-of-sample/
train-test split done." This script is that split.

Method: split resolved daily_equity_setup_positions by trigger_date at a
single cutoff into an earlier fold and a later fold, then run the exact
same summarize_by_group() math independently on each. The CURRENT (already
locked) multipliers were applied uniformly when this table was built, so
this is not re-deriving what parameters a train-only sweep would have
picked -- it answers a narrower but still load-bearing question: does the
edge these parameters produce hold up consistently across calendar time,
or is it concentrated in one part of the window (the classic fingerprint
of a fit that happened to work on this data, not a real, time-stable
effect)? A verdict that flips from PASS to NO-GO/INCONCLUSIVE in the later
fold is exactly the failure mode an in-sample sweep can hide.

Usage: python3 -m vanguard.research.equity_setups_temporal_holdout [cutoff]
Default cutoff: 2026-04-01 (roughly the midpoint of MOMENTUM_BUILDUP's
resolved history; leaves n>=30 in both folds for every setup type that
clears MIN_N over the full history).
"""
from __future__ import annotations

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
REPORT_PATH = RESEARCH / "equity_setups_temporal_holdout_v1.md"


def _verdict(row: pd.Series) -> str:
    if row["n"] < MIN_N:
        return "INCONCLUSIVE (n too small)"
    if row["total_r"] <= 0:
        return "NO-GO"
    if row["win_rate"] > 50:
        return "PASS"
    return "PASS (asymmetric payoff)"


def run(cutoff: str = DEFAULT_CUTOFF, con: duckdb.DuckDBPyConnection | None = None) -> pd.DataFrame:
    own_con = con is None
    con = con or duckdb.connect(str(DB), read_only=True)
    try:
        positions = con.execute(
            "SELECT * FROM daily_equity_setup_positions WHERE status != 'OPEN'"
        ).fetchdf()
    finally:
        if own_con:
            con.close()

    early = positions[positions["trigger_date"] < cutoff]
    late = positions[positions["trigger_date"] >= cutoff]

    g_early = summarize_by_group(early, group_col="setup_type")
    g_late = summarize_by_group(late, group_col="setup_type")
    g_early["verdict"] = g_early.apply(_verdict, axis=1)
    g_late["verdict"] = g_late.apply(_verdict, axis=1)

    combined = g_early.join(
        g_late, how="outer", lsuffix="_early", rsuffix="_late"
    )
    return combined


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


def write_report(g: pd.DataFrame, cutoff: str) -> Path:
    lines = [
        "# Equity Setups (Track B) — Temporal Holdout",
        "",
        f"Run date: {date.today().isoformat()} · cutoff {cutoff} · "
        f"early fold = trigger_date < cutoff, late fold = trigger_date >= cutoff · "
        f"resolved positions only · MIN_N = {MIN_N} per fold",
        "",
        "| Setup Type | N (early) | Total R (early) | Verdict (early) | "
        "N (late) | Total R (late) | Verdict (late) | Consistency |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for setup_type, row in g.iterrows():
        ne = "-" if pd.isna(row.get("n_early")) else int(row["n_early"])
        nl = "-" if pd.isna(row.get("n_late")) else int(row["n_late"])
        tre = "-" if pd.isna(row.get("total_r_early")) else f"{row['total_r_early']:+.2f}R"
        trl = "-" if pd.isna(row.get("total_r_late")) else f"{row['total_r_late']:+.2f}R"
        ve = row.get("verdict_early", "MISSING")
        vl = row.get("verdict_late", "MISSING")
        lines.append(
            f"| {setup_type} | {ne} | {tre} | {ve} | {nl} | {trl} | {vl} | "
            f"**{_consistency(row)}** |"
        )
    lines += [
        "",
        "## Reading this table",
        "- **CONSISTENT (holds in both folds)**: the edge survives outside the window used to "
        "eyeball/tune it — the strongest evidence available in this dataset that it's real.",
        "- **OVERFIT RISK**: verdict flips between folds. The parameters (or the whole setup) may "
        "be fit to quirks of one part of the sample, not a stable effect. Do not raise size/priority "
        "on this setup without independent confirmation.",
        "- **INCONCLUSIVE**: at least one fold has n < 30 — cutting the data in half exposed a "
        "sample-size problem that the full-history gate was papering over.",
        "",
        "Caveat shared with the full-history gate: both folds sit inside the same single-direction "
        "(long-only, PRD §3.3) regime — this checks time-consistency within one market regime, not "
        "robustness across bull/bear cycles. A verdict that's CONSISTENT here can still fail in a "
        "regime this dataset has never seen.",
    ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n")
    return REPORT_PATH


def main() -> int:
    cutoff = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CUTOFF
    g = run(cutoff)
    if g.empty:
        print("[!] No resolved equity positions found — nothing to test.")
        return 1
    pd.set_option("display.width", 160)
    print(g)
    path = write_report(g, cutoff)
    print(f"\n[SUCCESS] Report written -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
