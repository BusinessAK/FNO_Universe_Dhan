"""
Equity playbook builder (Track B / E3-E4) — mirrors vanguard/rules/
playbook.py's role for Track A: turns a fired setup type into {bias,
trigger_strike, invalidation_strike}. No suggested-strategy output — that
layer was cut from the platform entirely this session.

Key names are "trigger_strike"/"invalidation_strike", not "trigger_price" —
matches setup_positions.py's hardcoded read exactly (PRD §1 schema contract).

History, two fixes deep:

1. Tautology fix (E3, found via this module's own integration test):
   derive_positions() checks `spot >= trigger` using THAT SAME day's
   spot_close — so a trigger defined as close*offset is checked against the
   exact value it was derived from and can never fire. Fixed by anchoring
   every trigger to a value NOT equal to today's own close: DMA20/DMA50 (a
   20/50-day mean dilutes today's contribution, no fixed relationship to
   today's close) or, for FIFTYTWO_WEEK_BREAKOUT, YESTERDAY's high_52w (not
   today's, which is a rolling max that equals today's close exactly on the
   day a new high fires).

2. Risk-inflation fix (E4, found via the backtest gate + a direct A/B check
   against Track A): DMA anchors lag far behind price during the exact fast
   moves these setups screen for, so real entries (derive_positions() enters
   at that day's actual spot, not the trigger level) routinely land 5-80%+
   past the nominal trigger — inflating realized risk 1.6x-10x beyond what
   the fixed-percentage bands assumed, since risk/target were sized off the
   LEVEL, not the entry. Fixed by sizing trigger/invalidation offsets as
   multiples of each stock's own NATR14 instead of a fixed percentage, so a
   volatile stock's band widens with it (see vanguard/config/equity.py's
   NATR_TRIGGER_MULT/NATR_SL_MULT for the per-setup multipliers and full
   rationale, including the F&O comparison that motivated this).

3. IMBALANCE_CONSOLIDATION re-anchor (2026-07-21, second pass on the same
   root cause): NATR-scaling alone still left this setup's dma50 anchor a
   median ~10% below the actual entry price, because dma50 is the slowest
   of all five anchors and this setup specifically screens for a fast break
   away from a quiet range — 79% of its "TARGET_HIT" rows had already
   overshot the nominal target on the very day of entry (measured directly
   against production data). Both trigger AND invalidation now anchor to
   range_high_10d_prev (yesterday's trailing-10-session high — the top of
   the actual consolidation range being broken), the same "yesterday's
   rolling max, not today's" pattern already used for FIFTYTWO_WEEK_
   BREAKOUT's prev_high_52w.

   First attempt at this (reverted, not left in): anchoring ONLY the trigger
   to range_high_10d_prev while leaving invalidation on dma50. That broke
   direction inference — _direction() reads "up" vs "down" purely from
   trigger vs invalidation ordering, and range_high_10d_prev and dma50 are
   independent enough that invalidation ended up ABOVE trigger on roughly
   two-thirds of symbol/days, silently turning most of a strictly-bullish
   breakout setup into inferred "down" (short) positions. Anchoring both
   ends to the SAME value guarantees trigger > invalidation whenever that
   anchor is positive, the same invariant every other setup relies on.
   Falls back to dma50 for both when range_high_10d_prev is unavailable
   (symbol has <10 sessions of history).
"""
from __future__ import annotations

import math

from vanguard.config.equity import NATR_FALLBACK_PCT, NATR_SL_MULT, NATR_TRIGGER_MULT

_BIAS = {
    "MOMENTUM_BUILDUP": "Bullish Momentum Buildup",
    "IMBALANCE_CONSOLIDATION": "Consolidation — Breakout Watch",
    "BREADTH_DIVERGENCE_REVERSAL": "Bullish Mean Reversion (Breadth Divergence)",
    "FIFTYTWO_WEEK_BREAKOUT": "Bullish 52-Week Breakout",
    "RSI_EXTREME_REBOUND": "Bullish Oversold Rebound",
}
_EXPECTED_BEHAVIOR = {
    "MOMENTUM_BUILDUP": "Trend Continuation",
    "IMBALANCE_CONSOLIDATION": "Post-Imbalance Compression Break",
    "BREADTH_DIVERGENCE_REVERSAL": "Oversold Dislocation Rebound",
    "FIFTYTWO_WEEK_BREAKOUT": "New-High Follow-Through",
    "RSI_EXTREME_REBOUND": "Extreme Oversold Snapback",
}
_ANCHOR_KEY = {
    # which build_equity_playbook() argument each setup anchors BOTH its
    # trigger and invalidation to. Must stay a single shared anchor per
    # setup (never split trigger/invalidation across two independent
    # values) — see point 3 in the module docstring above for why.
    "MOMENTUM_BUILDUP": "dma20",
    "IMBALANCE_CONSOLIDATION": "range_high_10d_prev",
    "BREADTH_DIVERGENCE_REVERSAL": "dma20",
    "FIFTYTWO_WEEK_BREAKOUT": "prev_high_52w",
    "RSI_EXTREME_REBOUND": "dma20",
}


def build_equity_playbook(setup_type: str, close: float, dma20: float, dma50: float,
                          prev_high_52w: float, natr14: float | None = None,
                          range_high_10d_prev: float | None = None) -> dict:
    if setup_type not in _BIAS:
        raise ValueError(f"unknown equity setup_type: {setup_type!r}")

    range_high_ok = (range_high_10d_prev is not None and math.isfinite(range_high_10d_prev)
                     and range_high_10d_prev > 0)
    anchors = {
        "dma20": dma20, "dma50": dma50, "prev_high_52w": prev_high_52w,
        # <10 sessions of history yet -> fall back to dma50, same as before this fix
        "range_high_10d_prev": range_high_10d_prev if range_high_ok else dma50,
    }
    anchor = anchors[_ANCHOR_KEY[setup_type]]

    natr_frac = (natr14 / 100.0 if natr14 is not None and math.isfinite(natr14) and natr14 > 0
                else NATR_FALLBACK_PCT / 100.0)
    trigger = anchor * (1 + NATR_TRIGGER_MULT[setup_type] * natr_frac)
    invalidation = anchor * (1 - NATR_SL_MULT[setup_type] * natr_frac)

    return {
        "bias": _BIAS[setup_type],
        "trigger_strike": float(trigger),
        "invalidation_strike": float(invalidation),
        "expected_behavior": _EXPECTED_BEHAVIOR[setup_type],
    }
