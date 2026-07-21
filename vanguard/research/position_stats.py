"""
Shared R-multiple / win-rate / expectancy math for setup_positions-shaped
tables — factored out so Track A (daily_setup_positions) and Track B
(daily_equity_setup_positions) compute Track Record numbers identically, per
docs/PRD_TRD_dual_track_signals_v1.md §6.4. Previously ad-hoc pandas run
inline earlier this session for the F&O numbers; this is that same logic,
named and tested once.
"""
from __future__ import annotations

import pandas as pd


def compute_r_multiple(row: pd.Series) -> float | None:
    """R = how many multiples of initial risk the position closed at.
    up: (resolved - trigger) / risk; down: (trigger - resolved) / risk.
    None if risk is zero/missing or the position never resolved (still OPEN
    — R is undefined for a position with no resolved_price yet)."""
    risk = abs(row["trigger_price"] - row["sl_price"])
    resolved = row.get("resolved_price")
    if risk <= 0 or resolved is None or pd.isna(resolved):
        return None
    if row["direction"] == "up":
        return (resolved - row["trigger_price"]) / risk
    return (row["trigger_price"] - resolved) / risk


def summarize_by_group(positions: pd.DataFrame, group_col: str = "setup_type") -> pd.DataFrame:
    """Resolved-only (OPEN rows have no R yet) win rate / avg R / total R per
    group, sorted by N descending. Columns: n, win_rate (%), avg_r, total_r."""
    df = positions.copy()
    df["R"] = df.apply(compute_r_multiple, axis=1)
    df = df.dropna(subset=["R"])
    if df.empty:
        return pd.DataFrame(columns=["n", "win_rate", "avg_r", "total_r"])
    g = df.groupby(group_col).agg(
        n=("R", "count"),
        win_rate=("R", lambda s: (s > 0).mean() * 100),
        avg_r=("R", "mean"),
        total_r=("R", "sum"),
    ).round(3).sort_values("n", ascending=False)
    return g
