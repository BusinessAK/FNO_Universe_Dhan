"""
Vanguard Institutional Terminal - Equity Technicals Engine (Track B / E1+E2)
Per-symbol daily technical snapshot across the full NSE EQ universe.

PRD: docs/PRD_TRD_dual_track_signals_v1.md, Phases E1-E2.

Deliberately reuses CashMarketBreadthEngine's adjustment + DMA/RSI/52w
computation rather than reimplementing it — the PRD's §8.1 "CA-adjustment
reuse test" requirement is satisfied by construction (same object, same
pivot tables) rather than by a separate cross-check that could silently
drift from the aggregate breadth engine.

E1: DMA20/50/200, RSI14, 52w high/low (promoted from cash_breadth.py's
internal-only cache), ROC, volume ratio, delivery ratios.
E2 (this revision): NATR14 (S7's raw input) and Chaikin Money Flow (S3),
both computed on adj_high/adj_low/adj_close — cash_breadth.py's
_build_adjusted_close() was extended to also emit adj_high/adj_low (it
previously only adjusted close), a prerequisite for True Range and the Money
Flow Multiplier to be correct across a split/bonus ex-date.

2026-07-21 addition: range_high_10d, the trailing IMBALANCE_LOOKBACK_SESSIONS
rolling max of adj_high. Added after the E4 backtest gate found
IMBALANCE_CONSOLIDATION's dma50-anchored trigger let real entries overshoot
by a median 10% (79% of its "TARGET_HIT" rows already had the entry AT OR
PAST the nominal target on day one) — dma50 lags too far behind price for a
setup that's specifically screening for a fast breakout away from a quiet
range. equity_playbook.py now anchors this setup's trigger to (yesterday's)
range_high_10d instead, the same "use yesterday's rolling max, not today's"
pattern FIFTYTWO_WEEK_BREAKOUT already uses for prev_high_52w.

Deliberately NOT computed here: S6/S7's boolean imbalance_flag/
consolidation_flag. Those are threshold crossings over the raw metrics this
module produces, and per the PRD's schema review, threshold logic belongs in
equity_screener.py (E3, stateless functions, cheap to retune) — not baked
into this compiler's write path, where a threshold tweak would force a full
re-run. This module's job stops at raw, threshold-free numbers.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from vanguard.config.equity import IMBALANCE_LOOKBACK_SESSIONS
from vanguard.engines.cash_breadth import CashMarketBreadthEngine

_ROC_WINDOWS = (5, 20, 63)
_RATIO_WINDOW = 20
_ATR_PERIOD = 14
_CMF_WINDOW = 20

_DEFAULT_CM_PARQUET = "data/compiled/cash_market_prices.parquet"
_DEFAULT_OUTPUT = "data/compiled/daily_equity_technicals.parquet"


def _rolling_ratio(pivot: pd.DataFrame, window: int) -> pd.DataFrame:
    """today's value / trailing `window`-session mean of that value, per symbol."""
    avg = pivot.rolling(window, min_periods=window).mean()
    return pivot / avg.replace(0, np.nan)


def _compute_natr14(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame,
                     prev_close: pd.DataFrame) -> pd.DataFrame:
    """Normalized ATR14: True Range Wilder-smoothed the same way RSI's
    avg_gain/avg_loss are (ewm alpha=1/14), then divided by price so a
    ₹5,000 stock and a ₹50 stock are on the same scale (S7, PRD §3.2)."""
    tr = np.maximum(high - low, np.maximum((high - prev_close).abs(), (low - prev_close).abs()))
    atr14 = tr.ewm(alpha=1 / _ATR_PERIOD, min_periods=_ATR_PERIOD, adjust=False).mean()
    return atr14 / close.replace(0, np.nan) * 100.0


def _compute_cmf(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame,
                  volume: pd.DataFrame, window: int) -> pd.DataFrame:
    """Chaikin Money Flow: volume-weighted close-location-value, averaged
    over `window` sessions (S3, PRD §3.2). H==L (circuit-lock) guarded to
    MFM=0.0 per the PRD's negative-scenario E-X6, not NaN/inf."""
    hl_range = high - low
    mfm = ((close - low) - (high - close)) / hl_range.replace(0, np.nan)
    mfm = mfm.fillna(0.0)          # H==L days contribute zero money flow, not a gap
    mfv = mfm * volume
    cmf = mfv.rolling(window, min_periods=window).sum() / \
        volume.rolling(window, min_periods=window).sum().replace(0, np.nan)
    return cmf


def build_equity_technicals(
    cm_parquet: str = _DEFAULT_CM_PARQUET,
    output_path: Optional[str] = _DEFAULT_OUTPUT,
    delivery_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Full pipeline: load → adjust (reused) → DMA/RSI/52w (reused) → ROC/volume
    ratio/delivery ratios (new) → one row per (symbol, date), long format.

    delivery_df: optional date/symbol/delivery_pct/deliverable_qty frame —
    pass the context layer's `daily_delivery` table here (2026-07-21 finding:
    cash_market_prices.parquet's own delivery_pct/deliverable_qty columns are
    100% null for every row, because the NSE UDiFF bhavcopy format
    cash_market_builder.py reads never carries a delivery column at all —
    it says so in its own docstring. daily_delivery is populated from a
    DIFFERENT NSE source (sec_bhavdata_full) that does have real delivery
    data for the same 2,751-symbol universe. Without delivery_df, this
    function silently falls back to the always-null cm columns — matches
    the platform's "degrade visibly, don't fabricate" contract only if the
    caller checks has_delivery in the output, so callers should pass real
    data when available rather than relying on the fallback.
    """
    engine = CashMarketBreadthEngine()
    print("[EquityTechnicals] Loading + adjusting cash market prices...")
    engine._load_and_adjust(cm_parquet)
    print("[EquityTechnicals] Computing DMA/RSI/52w (shared with CashMarketBreadthEngine)...")
    engine._precompute_dmas()
    cm = engine._cm  # adjusted long-format frame: date, symbol, ..., adj_close

    if delivery_df is not None and not delivery_df.empty:
        print("[EquityTechnicals] Joining real delivery data (daily_delivery)...")
        dlv = delivery_df.rename(columns={"delivered_qty": "deliverable_qty"}).copy()
        dlv["date"] = pd.to_datetime(dlv["date"]).dt.normalize()
        dlv = dlv[["date", "symbol", "delivery_pct", "deliverable_qty"]]
        cm = cm.drop(columns=["delivery_pct", "deliverable_qty"], errors="ignore")
        cm = cm.merge(dlv, on=["date", "symbol"], how="left")

    print("[EquityTechnicals] Computing ROC / volume / delivery ratios...")
    close_pivot = cm.pivot_table(index="date", columns="symbol", values="adj_close", aggfunc="last")
    vol_pivot = cm.pivot_table(index="date", columns="symbol", values="volume", aggfunc="last")

    roc = {n: (close_pivot / close_pivot.shift(n) - 1.0) * 100.0 for n in _ROC_WINDOWS}
    volume_ratio = _rolling_ratio(vol_pivot, _RATIO_WINDOW)

    print("[EquityTechnicals] Computing NATR14 / Chaikin Money Flow...")
    high_pivot = cm.pivot_table(index="date", columns="symbol", values="adj_high", aggfunc="last")
    low_pivot = cm.pivot_table(index="date", columns="symbol", values="adj_low", aggfunc="last")
    prev_close_pivot = cm.pivot_table(index="date", columns="symbol", values="adj_prev_close", aggfunc="last")
    natr14 = _compute_natr14(high_pivot, low_pivot, close_pivot, prev_close_pivot)
    money_flow_20d = _compute_cmf(high_pivot, low_pivot, close_pivot, vol_pivot, _CMF_WINDOW)
    range_high_10d = high_pivot.rolling(IMBALANCE_LOOKBACK_SESSIONS,
                                        min_periods=IMBALANCE_LOOKBACK_SESSIONS).max()

    # Column presence alone isn't enough — cash_market_prices.parquet's own
    # delivery_pct column exists but is 100% null (see the docstring above),
    # which would otherwise silently produce an all-NaN ratio column instead
    # of correctly reporting "no delivery data."
    has_delivery = "delivery_pct" in cm.columns and cm["delivery_pct"].notna().any()
    if has_delivery:
        dlv_pivot = cm.pivot_table(index="date", columns="symbol", values="delivery_pct", aggfunc="last")
        delivery_pct_ratio = _rolling_ratio(dlv_pivot, _RATIO_WINDOW)
    if "deliverable_qty" in cm.columns and cm["deliverable_qty"].notna().any():
        dqty_pivot = cm.pivot_table(index="date", columns="symbol", values="deliverable_qty", aggfunc="last")
        deliverable_vol_ratio = _rolling_ratio(dqty_pivot, _RATIO_WINDOW)
    else:
        deliverable_vol_ratio = None

    dma_cache = engine._dma_cache
    high_52w, low_52w = dma_cache["52w_high"], dma_cache["52w_low"]
    pct_from_high = (close_pivot - high_52w) / high_52w * 100.0
    pct_from_low = (close_pivot - low_52w) / low_52w * 100.0

    def _melt(pivot: pd.DataFrame, col: str) -> pd.DataFrame:
        m = pivot.reset_index().melt(id_vars="date", var_name="symbol", value_name=col)
        return m.set_index(["date", "symbol"])

    parts = [
        _melt(close_pivot, "adj_close"),
        _melt(dma_cache[20], "dma20"),
        _melt(dma_cache[50], "dma50"),
        _melt(dma_cache[200], "dma200"),
        _melt(dma_cache["rsi14"], "rsi14"),
        _melt(high_52w, "high_52w"),
        _melt(low_52w, "low_52w"),
        _melt(pct_from_high, "pct_from_52w_high"),
        _melt(pct_from_low, "pct_from_52w_low"),
        _melt(volume_ratio, "volume_ratio_20d"),
        _melt(natr14, "natr14"),
        _melt(money_flow_20d, "money_flow_20d"),
        _melt(range_high_10d, "range_high_10d"),
    ]
    for n in _ROC_WINDOWS:
        parts.append(_melt(roc[n], f"roc_{n}d"))
    if has_delivery:
        parts.append(_melt(delivery_pct_ratio, "delivery_pct_ratio_20d"))
    if deliverable_vol_ratio is not None:
        parts.append(_melt(deliverable_vol_ratio, "deliverable_vol_ratio_20d"))

    out = pd.concat(parts, axis=1).reset_index()

    # Bring across raw close/volume/delivery_pct/deliverable_qty as-of each date —
    # not derived from a pivot, so a plain merge on the original long frame.
    raw_cols = ["date", "symbol", "close", "volume"]
    if has_delivery:
        raw_cols.append("delivery_pct")
    if "deliverable_qty" in cm.columns:
        raw_cols.append("deliverable_qty")
    out = out.merge(cm[raw_cols], on=["date", "symbol"], how="left")

    out = out.dropna(subset=["adj_close"]).sort_values(["symbol", "date"]).reset_index(drop=True)

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        out.to_parquet(output_path, index=False)
        print(f"[EquityTechnicals] Saved {len(out)} rows → {output_path}")
    return out
