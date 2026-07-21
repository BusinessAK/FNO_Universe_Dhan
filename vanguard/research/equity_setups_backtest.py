#!/usr/bin/env python3
"""
Phase E4 backtest gate — docs/PRD_TRD_dual_track_signals_v1.md §8.2.

Same governing principle as data/research/ifs_verified_flow_validation.md:
a setup does not get trusted because it sounds right, it gets trusted
because derive_positions()'s real resolved history says so. Verdict per
setup type, not a single pass/fail for the whole track — a mixed result
(some setups pass, some don't) is the expected, honest outcome, same as the
F&O side's FLOOR_BOUNCE/INVENTORY_MIGRATION findings earlier this session.

Gate (per setup type):
  n < MIN_N              -> INCONCLUSIVE (sample too thin to trust either way)
  total_r <= 0           -> NO-GO
  win_rate > 50          -> PASS
  win_rate <= 50 but
    total_r > 0          -> PASS (asymmetric payoff — wins bigger than losses
                                   outweigh a sub-50% hit rate)

Usage: python3 -m vanguard.research.equity_setups_backtest
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
REPORT_PATH = RESEARCH / "equity_setups_validation_v1.md"


def _verdict(row: pd.Series) -> str:
    if row["n"] < MIN_N:
        return "INCONCLUSIVE (n too small)"
    if row["total_r"] <= 0:
        return "NO-GO"
    if row["win_rate"] > 50:
        return "PASS"
    return "PASS (asymmetric payoff)"


def run(con: duckdb.DuckDBPyConnection | None = None) -> pd.DataFrame:
    own_con = con is None
    con = con or duckdb.connect(str(DB), read_only=True)
    try:
        positions = con.execute("SELECT * FROM daily_equity_setup_positions").fetchdf()
    finally:
        if own_con:
            con.close()

    g = summarize_by_group(positions, group_col="setup_type")
    g["verdict"] = g.apply(_verdict, axis=1)
    return g


def write_report(g: pd.DataFrame) -> Path:
    lines = [
        "# Equity Setups (Track B) — E4 Backtest Gate",
        "",
        f"Run date: {date.today().isoformat()} · "
        f"docs/PRD_TRD_dual_track_signals_v1.md §8.2 · "
        f"resolved positions only (OPEN rows excluded — no R yet) · MIN_N = {MIN_N}",
        "",
        "| Setup Type | N | Win Rate | Avg R | Total R | Verdict |",
        "|---|---|---|---|---|---|",
    ]
    for setup_type, row in g.iterrows():
        lines.append(
            f"| {setup_type} | {int(row['n'])} | {row['win_rate']:.1f}% | "
            f"{row['avg_r']:+.3f}R | {row['total_r']:+.2f}R | **{row['verdict']}** |"
        )
    lines += [
        "",
        "## Reading this table",
        "- **PASS**: positive total R at n>=30, win rate above a coin flip in the direction claimed.",
        "- **PASS (asymmetric payoff)**: positive total R despite a sub-50% win rate — winners "
        "large enough to outweigh a lower hit rate. Worth a second look before fully trusting "
        "(asymmetric-payoff claims are exactly the kind of thing a few outlier trades can fake).",
        "- **NO-GO**: total R is flat-to-negative at a real sample size — same category as "
        "Track A's FLOOR_BOUNCE finding earlier this session. Root-cause or drop, don't ship.",
        "- **INCONCLUSIVE**: fewer than 30 resolved positions — not enough evidence either way yet.",
        "",
        "All six candidates are long-only (PRD §3.3) — there is no short side to cross-check "
        "against, and a raging bull market during the sample window would flatter every one of "
        "these numbers equally. Not adjusted for here; worth keeping in mind before over-trusting "
        "a PASS.",
    ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n")
    return REPORT_PATH


def main() -> int:
    g = run()
    if g.empty:
        print("[!] No resolved equity positions found — nothing to gate.")
        return 1
    pd.set_option("display.width", 120)
    print(g)
    path = write_report(g)
    print(f"\n[SUCCESS] Report written -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
