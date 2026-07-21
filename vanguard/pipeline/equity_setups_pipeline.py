"""
Track B / E3 orchestration — turns daily_equity_technicals + daily_cm_breadth
into daily_equity_setups + daily_equity_setup_positions. Lives outside
equity_compiler.py so it's importable/testable without touching a real
DuckDB file, same separation daily_compiler.py doesn't bother with (it's a
script) but the underlying rules modules (screener/playbook/positions) do.

Per-symbol, chronological pass building EquitySetupInputs with a trailing
history window (roc_5d/volume_ratio/natr14, today last) — the same shape
equity_screener.py's S6/S7 lookback needs. Feeds vanguard.rules.
setup_positions.derive_positions() unmodified, same function Track A uses.

2026-07-21 fix: uses adj_close, not raw close, as the "spot" fed everywhere
(EquitySetupInputs.close, spot_close, build_equity_playbook's close arg).
Every anchor (dma20/dma50/natr14/high_52w/range_high_10d) is computed on the
CA-adjusted series, so comparing them against a raw close only happened to
work for symbols with zero corporate actions in the window — found via a
batch of IMBALANCE_CONSOLIDATION positions with absurd (500%+) entry
overshoot that turned out to be a stock-split/bonus scale mismatch, not a
real price move. All position prices in daily_equity_setup_positions are
therefore in adjusted terms, same convention CashMarketBreadthEngine already
uses internally — fine for R-multiple backtesting (self-consistent ratios),
but would need converting back to real traded price for any future display
layer (deferred to E5, same as the rest of the UI).
"""
from __future__ import annotations

import pandas as pd

from vanguard.config.equity import (
    EQUITY_SETUP_PRIORITY, IMBALANCE_LOOKBACK_SESSIONS, CONSOLIDATION_NATR_WINDOW,
)
from vanguard.rules.equity_playbook import build_equity_playbook
from vanguard.rules.equity_screener import EquitySetupInputs, screen
from vanguard.rules.setup_positions import derive_positions

_WINDOW_N = max(IMBALANCE_LOOKBACK_SESSIONS, CONSOLIDATION_NATR_WINDOW)

_SETUPS_COLS = ["date", "symbol", "setup_type", "setup_types", "bias",
                "trigger_strike", "invalidation_strike", "expected_behavior"]


def _pick_primary(fired: list[str]) -> str:
    for st in EQUITY_SETUP_PRIORITY:
        if st in fired:
            return st
    return fired[0]  # defensive only — EQUITY_SETUP_PRIORITY lists all 6 candidates


def build_equity_setups_and_positions(
    technicals: pd.DataFrame, breadth: pd.DataFrame,
) -> tuple[pd.DataFrame, list[dict]]:
    """
    technicals: daily_equity_technicals shape (long format, one row per
    symbol/date). breadth: daily_cm_breadth shape, needs at least
    date/cm_pct_above_50dma/cm_pct_oversold_30.

    Returns (df_setups, position_rows) — position_rows is derive_positions()'s
    raw output (list[dict]), left for the caller to DataFrame + write, same
    as daily_compiler.py does for Track A.
    """
    breadth_by_date = {
        str(pd.Timestamp(r["date"]).date()): r for _, r in breadth.iterrows()
    } if not breadth.empty else {}

    setups_rows: list[dict] = []
    session_history: dict = {}

    for symbol, g in technicals.groupby("symbol", sort=False):
        g = g.sort_values("date").reset_index(drop=True)
        roc5_hist: list = []
        volr_hist: list = []
        natr_hist: list = []
        history: dict = {}

        for idx in range(len(g)):
            row = g.iloc[idx]
            date_str = str(pd.Timestamp(row["date"]).date())
            # adj_close, not raw close: dma20/dma50/natr14/high_52w/
            # range_high_10d are all computed on the CA-adjusted series (see
            # module docstring) -- comparing them against a RAW close is only
            # safe for symbols with zero corporate actions in the window.
            # 143/2751 symbols (2026-07-21 production audit) have a genuine
            # split/bonus in-window, where raw and adjusted close diverge by
            # up to ~17x -- feeding raw close in produced nonsense triggers/
            # targets for exactly those names (surfaced via IMBALANCE_
            # CONSOLIDATION's outlier overshoot rows, e.g. RNBDENIMS).
            close = row["adj_close"]

            roc5_hist.append(row["roc_5d"])
            volr_hist.append(row["volume_ratio_20d"])
            natr_hist.append(row["natr14"])
            if len(roc5_hist) > _WINDOW_N:
                roc5_hist, volr_hist, natr_hist = (
                    roc5_hist[-_WINDOW_N:], volr_hist[-_WINDOW_N:], natr_hist[-_WINDOW_N:])

            day_data = {"spot_close": float(close) if pd.notna(close) else None}

            # Need a previous row for FIFTYTWO_WEEK_BREAKOUT's prev_high_52w
            # anchor; first session of a symbol's history can't evaluate anything.
            if idx == 0 or pd.isna(close):
                history[date_str] = day_data
                continue

            prev = g.iloc[idx - 1]
            b = breadth_by_date.get(date_str)
            cm_above_50 = float(b["cm_pct_above_50dma"]) if b is not None and pd.notna(b.get("cm_pct_above_50dma")) else float("nan")
            cm_oversold = float(b["cm_pct_oversold_30"]) if b is not None and pd.notna(b.get("cm_pct_oversold_30")) else float("nan")

            inputs = EquitySetupInputs(
                close=close, dma20=row["dma20"], dma50=row["dma50"],
                rsi14=row["rsi14"], roc_5d=row["roc_5d"], roc_20d=row["roc_20d"], roc_63d=row["roc_63d"],
                natr14=row["natr14"], money_flow_20d=row["money_flow_20d"],
                volume_ratio_20d=row["volume_ratio_20d"],
                delivery_pct_ratio_20d=row.get("delivery_pct_ratio_20d", float("nan")),
                deliverable_vol_ratio_20d=row.get("deliverable_vol_ratio_20d", float("nan")),
                high_52w=row["high_52w"], cm_pct_above_50dma=cm_above_50, cm_pct_oversold_30=cm_oversold,
                roc_5d_window=list(roc5_hist), volume_ratio_window=list(volr_hist),
                natr14_window=list(natr_hist),
            )
            fired = screen(inputs)
            if fired:
                primary = _pick_primary(fired)
                # prev_high_52w, not today's — see equity_playbook.py's module
                # docstring for why (today's high_52w includes today's own
                # close via the rolling max, which is tautological on the
                # exact day a new high fires).
                pb = build_equity_playbook(primary, close, row["dma20"], row["dma50"],
                                          prev["high_52w"], natr14=row["natr14"],
                                          range_high_10d_prev=prev.get("range_high_10d", float("nan")))
                day_data["setups"] = fired
                day_data["primary_setup"] = primary
                day_data["playbook"] = pb
                setups_rows.append({
                    "date": date_str, "symbol": symbol, "setup_type": primary,
                    "setup_types": ",".join(fired), "bias": pb["bias"],
                    "trigger_strike": pb["trigger_strike"],
                    "invalidation_strike": pb["invalidation_strike"],
                    "expected_behavior": pb.get("expected_behavior", ""),
                })
            history[date_str] = day_data

        session_history[symbol] = history

    df_setups = pd.DataFrame(setups_rows, columns=_SETUPS_COLS) if setups_rows \
        else pd.DataFrame(columns=_SETUPS_COLS)
    position_rows = derive_positions(session_history)
    return df_setups, position_rows
