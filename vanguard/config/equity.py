"""
Track B (Cash/Equity) tunable constants — PRD docs/PRD_TRD_dual_track_signals_v1.md.

Every threshold here is a CANDIDATE starting number, explicitly not backtested
and not locked (§3.2/§10 of the PRD) — same status MIN_WALL_MIGRATION_PCT etc.
had before the F&O signal review. E4's backtest gate is what actually decides
whether these survive as-is, get retuned, or get dropped.
"""

# S6 — imbalance event
IMBALANCE_MIN_ABS_ROC_5D = 5.0        # percent
IMBALANCE_MIN_VOLUME_RATIO = 1.8
IMBALANCE_LOOKBACK_SESSIONS = 10      # "within the last N sessions" for IMBALANCE_CONSOLIDATION.
                                        # Also doubles as equity_technicals.py's range_high_10d
                                        # window (IMBALANCE_CONSOLIDATION's trigger/invalidation
                                        # anchor, see equity_playbook.py). Swept 2026-07-21 against
                                        # 5/10/15/20/30 on real data: total_r fell monotonically
                                        # past 10 (10:+42.9R -> 30:+17.4R), 5 traded more often for
                                        # slightly higher total_r (+58.7R) at a lower win rate
                                        # (59.6% vs 63.0%) -- 10 stays the pick for per-trade quality.

# S7 — consolidation
CONSOLIDATION_NATR_PERCENTILE = 20.0  # bottom 20th percentile of...
CONSOLIDATION_NATR_WINDOW = 63        # ...its own trailing 63-session window
CONSOLIDATION_MAX_VOLUME_RATIO = 0.8
# Tested and REJECTED 2026-07-21: an additional "narrow range" filter (10-day
# close range as % of price) on top of the NATR-percentile check above.
# Counterintuitive but clear in the data -- total_r fell monotonically as the
# range was required to be tighter (all-trades +42.9R -> range<=20%: +25.6R
# -> range<=10%: -3.0R, avg_r turning NEGATIVE below ~15% width). The
# NATR-percentile condition already selects for "quiet"; a truly tight
# 10-day range on top of that appears to select for genuine indecision/
# distribution (prone to failed breakouts) rather than coiled momentum. Do
# not add a range-width condition without new evidence.

# MOMENTUM_BUILDUP (retuned 2026-07-21 — E4 found winners cluster meaningfully
# higher than losers on both rsi14 (median 65.4 vs 60.8) and roc_5d (5.15 vs
# 3.66) at the OLD thresholds; tightening toward that tail):
MOMENTUM_MIN_VOLUME_RATIO = 1.2
MOMENTUM_RSI_LOW, MOMENTUM_RSI_HIGH = 55.0, 70.0     # was 50.0
MOMENTUM_MIN_ROC_5D = 3.0                             # new — was just "> 0"

# DMA_RECLAIM — DROPPED 2026-07-21 after the E4 backtest gate. Entry-quality
# tweaks (tighter volume_ratio + a roc_20d trend-context floor) statistically
# justified by the same winner/loser diagnostic that fixed MOMENTUM_BUILDUP
# made this one WORSE (-206.66R -> -219.21R), not better — a real signal that
# the underlying thesis (DMA50 reclaims predict continuation) doesn't hold
# in this data, not a calibration problem. See vanguard/rules/
# equity_screener.py's module docstring. Constants removed with it.

# BREADTH_DIVERGENCE_REVERSAL (retuned 2026-07-21 — counterintuitive but
# data-grounded finding: TARGET_HIT's roc_5d is MORE negative than SL_HIT's
# (median -5.06 vs +0.28) — the sharpest, still-accelerating declines snap
# back fastest (median 1 day to target); already-stabilizing names just
# grind down slowly into the stop (median 27.5 days). Also: SL_HIT's slow
# bleed means the exit was the other real problem — tightening it hard.
# Second pass, same day: found entries firing on days price had ALREADY
# rallied well above its own (still-lagging-low) dma20 — target sized off
# the stale low anchor was then already below the entry price. Fixed in
# equity_screener.py by requiring close < dma20, a structural condition,
# not a new tunable constant here):
DIVERGENCE_RSI_MAX = 30.0
DIVERGENCE_MAX_BREADTH_OVERSOLD_PCT = 20.0   # broader tape's own %oversold must be BELOW this
DIVERGENCE_MAX_ROC_5D = -3.0                  # new — select for sharp capitulation, not a slow grind

# FIFTYTWO_WEEK_BREAKOUT
BREAKOUT_MIN_VOLUME_RATIO = 1.2
BREAKOUT_MIN_DELIVERABLE_VOL_RATIO = 1.2

# RSI_EXTREME_REBOUND — trigger anchor fixed 2026-07-21 (see NATR_TRIGGER_MULT
# below); this setup fired only 2 times in 609,840 symbol-days at the old
# dma20-anchored trigger because RSI<25 means price is typically well BELOW
# dma20, making "close back at/above dma20 same day" an extreme ask.
REBOUND_RSI_MAX = 25.0
REBOUND_MIN_VOLUME_RATIO = 1.5
REBOUND_MIN_BREADTH_ABOVE_50DMA_PCT = 40.0

# Volatility-adaptive risk sizing (E4 root-cause fix, 2026-07-21): F&O's
# structural anchors (walls, gamma flip) barely overshoot before triggering
# (median 0.2-1.5% across all 7 setups, checked directly against real data).
# Equity's DMA-based anchors get blown through by 5-80%+ on exactly the
# fast-moving days these setups screen for, because a moving average lags
# far behind during a genuine momentum/breakout/reversal move — inflating
# realized risk to 1.6x-10x (even 58x for the rarest setup) of what the
# fixed-percentage bands assumed, and quietly destroying the intended 2:1
# reward:risk. Fix: size the trigger/invalidation offsets as multiples of
# each stock's OWN NATR14 (already computed) instead of a fixed percentage
# of the anchor — a volatile stock's band widens with it, so realized risk
# stays closer to what was priced in even when overshoot is large. Still
# placeholder multipliers, not backtested — re-run
# vanguard/research/equity_setups_backtest.py after any change to confirm it
# actually helped, not just theoretically should.
NATR_FALLBACK_PCT = 3.0   # used when natr14 is missing/NaN for a symbol/day

# (trigger_offset_natr_mult, invalidation_offset_natr_mult) per setup type.
# Negative trigger mult = trigger sits BELOW the anchor (reversal setups,
# confirming a bounce approaching from underneath, not a breakout above).
NATR_TRIGGER_MULT = {
    "MOMENTUM_BUILDUP": 0.25,
    "IMBALANCE_CONSOLIDATION": 0.05,   # was 0.5 off dma50, then 0.15 off
                                        # range_high_10d_prev (see
                                        # equity_playbook.py's module
                                        # docstring, point 3) -- retuned again
                                        # 2026-07-21 via an entry/exit sweep
                                        # (paired with sl_mult below): total_r
                                        # rose monotonically as this shrank
                                        # from 0.3->0.05 (+25R->+91R), with
                                        # 0.05 independently the best point in
                                        # TWO separate sweep passes. 0.0 (bare
                                        # "close>=range_high", no confirmation
                                        # buffer) scored marginally higher
                                        # still (+96.77R) but only showed up
                                        # once, at the exact edge of the
                                        # tested range -- the signature of an
                                        # in-sample fluke, not a real optimum,
                                        # so deliberately NOT used. In-sample
                                        # only, still unlocked -- no
                                        # out-of-sample/train-test split done.
    "BREADTH_DIVERGENCE_REVERSAL": -0.25,
    "FIFTYTWO_WEEK_BREAKOUT": 0.25,
    "RSI_EXTREME_REBOUND": -0.5,   # was +0.1 — fired 2x in 609,840 symbol-days;
                                    # matched to BREADTH_DIVERGENCE_REVERSAL's
                                    # below-anchor shape (deeper, since REBOUND's
                                    # RSI<25 floor is more extreme than DIVERGENCE's <30)
}
NATR_SL_MULT = {
    "MOMENTUM_BUILDUP": 1.0,
    "IMBALANCE_CONSOLIDATION": 0.25,   # was 0.5 -- 2026-07-21 sweep found this
                                        # a genuine local optimum, confirmed
                                        # from both directions: 0.1 (tighter)
                                        # whipsawed constantly (+26R only),
                                        # 0.5/0.75/1.0/1.5 (looser) all decay
                                        # steadily from here (+62R->+43R). See
                                        # NATR_TRIGGER_MULT's comment above --
                                        # in-sample only, still unlocked.
    "BREADTH_DIVERGENCE_REVERSAL": 0.75,   # was 2.0 — SL_HIT losses bled a median
                                            # 27.5 days at the wide stop; cut faster
    "FIFTYTWO_WEEK_BREAKOUT": 1.0,
    "RSI_EXTREME_REBOUND": 0.75,            # matched to the same tightened-stop logic
}

# Precedence when multiple setups fire the same symbol/day — narrowest/most
# selective condition wins, same convention as vanguard/config/eod.py's
# SETUP_PRIORITY for Track A. Placeholder ordering, same unlocked status as
# every threshold above. DMA_RECLAIM dropped 2026-07-21.
EQUITY_SETUP_PRIORITY = [
    "FIFTYTWO_WEEK_BREAKOUT",
    "RSI_EXTREME_REBOUND",
    "BREADTH_DIVERGENCE_REVERSAL",
    "IMBALANCE_CONSOLIDATION",
    "MOMENTUM_BUILDUP",
]
