"""
Equity setup screener (Track B / E3-E4) — 5 of the original 6 candidate
technical setups from docs/PRD_TRD_dual_track_signals_v1.md §3.3, mirroring
vanguard/rules/setup_screener.py's shape (pure functions, one per setup,
table-driven tests, thresholds imported by name from a config module).

DMA_RECLAIM was formally dropped 2026-07-21 after the E4 backtest gate: it
started NO-GO (-206.66R), and entry-quality tweaks that helped every other
struggling setup (tighter volume/trend-context filters, statistically
justified by the same win/loss diagnostic that fixed MOMENTUM_BUILDUP) made
it *worse* (-219.21R), not better. That's a real signal, not noise: this
isn't a calibration problem, the underlying thesis (DMA50 reclaims predict
continuation) doesn't hold up in this data — classic bull-trap-at-the-average
behavior. Removed rather than left disabled; see git history if this needs
revisiting.

All five remaining candidates are long-only, matching the PRD's own §3.3
descriptions — flagged, not silently accepted: worth deciding later whether
bearish mirrors (momentum breakdown, 52-week-low breakdown, RSI-overbought
reversal) belong in a later revision, same review process as everything else
here got.

None of these setups is presented as trustworthy by default — they exist so
E4 can backtest them. `screen()` returning a setup name means "the condition
fired," not "this has edge." (MOMENTUM_BUILDUP, FIFTYTWO_WEEK_BREAKOUT and
IMBALANCE_CONSOLIDATION have since cleared that bar; BREADTH_DIVERGENCE_
REVERSAL is still being iterated on; RSI_EXTREME_REBOUND still lacks enough
resolved samples to judge.)

Contract: EquitySetupInputs is a data container only — every threshold
constant lives in vanguard.config.equity and is applied inside these
functions, never pre-baked into the input. S6/S7's lookback needs are met by
carrying a short history window (oldest→newest, today last) rather than a
single T/T-1 pair the way Track A's screener gets away with.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from vanguard.config.equity import (
    IMBALANCE_MIN_ABS_ROC_5D, IMBALANCE_MIN_VOLUME_RATIO, IMBALANCE_LOOKBACK_SESSIONS,
    CONSOLIDATION_NATR_PERCENTILE, CONSOLIDATION_MAX_VOLUME_RATIO,
    MOMENTUM_MIN_VOLUME_RATIO, MOMENTUM_RSI_LOW, MOMENTUM_RSI_HIGH, MOMENTUM_MIN_ROC_5D,
    DIVERGENCE_RSI_MAX, DIVERGENCE_MAX_BREADTH_OVERSOLD_PCT, DIVERGENCE_MAX_ROC_5D,
    BREAKOUT_MIN_VOLUME_RATIO, BREAKOUT_MIN_DELIVERABLE_VOL_RATIO,
    REBOUND_RSI_MAX, REBOUND_MIN_VOLUME_RATIO, REBOUND_MIN_BREADTH_ABOVE_50DMA_PCT,
)


@dataclass
class EquitySetupInputs:
    """Today's raw technicals + just enough yesterday/history to evaluate all
    5 active setups. roc_5d_window/volume_ratio_window/natr14_window are the
    last <=IMBALANCE_LOOKBACK_SESSIONS / <=CONSOLIDATION_NATR_WINDOW sessions,
    oldest first, TODAY LAST (so today's own value is window[-1], not a
    separately-tracked field) — avoids double-bookkeeping the same number."""
    close: float
    dma20: float
    dma50: float
    rsi14: float
    roc_5d: float
    roc_20d: float
    roc_63d: float
    natr14: float
    money_flow_20d: float
    volume_ratio_20d: float
    delivery_pct_ratio_20d: float
    deliverable_vol_ratio_20d: float
    high_52w: float
    cm_pct_above_50dma: float
    cm_pct_oversold_30: float
    roc_5d_window: list = field(default_factory=list)
    volume_ratio_window: list = field(default_factory=list)
    natr14_window: list = field(default_factory=list)


def _isfinite(*vals) -> bool:
    return all(v is not None and np.isfinite(v) for v in vals)


# ── individual rules (pure; one boolean each) ────────────────────────────────

def momentum_buildup(i: EquitySetupInputs) -> bool:
    if not _isfinite(i.close, i.dma20, i.dma50, i.rsi14, i.roc_5d, i.volume_ratio_20d):
        return False
    trend_aligned = i.close > i.dma20 > i.dma50
    momentum_ok = i.roc_5d > MOMENTUM_MIN_ROC_5D and MOMENTUM_RSI_LOW <= i.rsi14 <= MOMENTUM_RSI_HIGH
    return trend_aligned and momentum_ok and i.volume_ratio_20d > MOMENTUM_MIN_VOLUME_RATIO


def _imbalance_in_lookback(i: EquitySetupInputs) -> bool:
    window = list(zip(i.roc_5d_window, i.volume_ratio_window))[-IMBALANCE_LOOKBACK_SESSIONS:]
    return any(
        _isfinite(roc, vr) and abs(roc) >= IMBALANCE_MIN_ABS_ROC_5D and vr >= IMBALANCE_MIN_VOLUME_RATIO
        for roc, vr in window
    )


def imbalance_consolidation(i: EquitySetupInputs) -> bool:
    if not _isfinite(i.natr14, i.volume_ratio_20d) or len(i.natr14_window) < 2:
        return False
    if not _imbalance_in_lookback(i):
        return False
    threshold = np.percentile([v for v in i.natr14_window if v is not None and np.isfinite(v)],
                              CONSOLIDATION_NATR_PERCENTILE)
    return i.natr14 <= threshold and i.volume_ratio_20d <= CONSOLIDATION_MAX_VOLUME_RATIO


def breadth_divergence_reversal(i: EquitySetupInputs) -> bool:
    """close < dma20 (2026-07-21 addition): DMA20 lags badly after a sharp
    crash, staying low for a while even as price rallies hard. Without this,
    the RSI<30 condition could still be (re-)satisfied on a day price has
    already rallied well above its own lagging DMA20 — entry then occurs far
    above the anchor the target was sized from, making the eventual
    "TARGET_HIT" a near-guaranteed but economically empty label (real
    example found in production data: entry 122.04, target 83.90 — BELOW
    the entry). Requiring close < dma20 keeps this to genuine,
    still-in-progress reversals, not a stale re-fire long after the bottom."""
    if not _isfinite(i.rsi14, i.cm_pct_oversold_30, i.roc_5d, i.close, i.dma20):
        return False
    return (i.rsi14 < DIVERGENCE_RSI_MAX
            and i.cm_pct_oversold_30 < DIVERGENCE_MAX_BREADTH_OVERSOLD_PCT
            and i.roc_5d < DIVERGENCE_MAX_ROC_5D
            and i.close < i.dma20)


def fiftytwo_week_breakout(i: EquitySetupInputs) -> bool:
    if not _isfinite(i.close, i.high_52w, i.volume_ratio_20d, i.deliverable_vol_ratio_20d):
        return False
    return (i.close >= i.high_52w
            and i.volume_ratio_20d > BREAKOUT_MIN_VOLUME_RATIO
            and i.deliverable_vol_ratio_20d > BREAKOUT_MIN_DELIVERABLE_VOL_RATIO)


def rsi_extreme_rebound(i: EquitySetupInputs) -> bool:
    if not _isfinite(i.rsi14, i.volume_ratio_20d, i.cm_pct_above_50dma):
        return False
    return (i.rsi14 < REBOUND_RSI_MAX
            and i.volume_ratio_20d > REBOUND_MIN_VOLUME_RATIO
            and i.cm_pct_above_50dma > REBOUND_MIN_BREADTH_ABOVE_50DMA_PCT)


def screen(i: EquitySetupInputs) -> list[str]:
    """All fired setups. Order matches EQUITY_SETUP_PRIORITY's declaration
    order for readability; daily_compiler-side priority selection still goes
    through EQUITY_SETUP_PRIORITY explicitly, not this list's order."""
    setups: list[str] = []
    if fiftytwo_week_breakout(i):
        setups.append("FIFTYTWO_WEEK_BREAKOUT")
    if rsi_extreme_rebound(i):
        setups.append("RSI_EXTREME_REBOUND")
    if breadth_divergence_reversal(i):
        setups.append("BREADTH_DIVERGENCE_REVERSAL")
    if imbalance_consolidation(i):
        setups.append("IMBALANCE_CONSOLIDATION")
    if momentum_buildup(i):
        setups.append("MOMENTUM_BUILDUP")
    return setups
