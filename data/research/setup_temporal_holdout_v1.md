# Full-System Temporal Holdout — Every Setup Type, Both Tracks

Run date: 2026-07-22 · cutoff 2026-04-01 (NIFTY -10.2% Mar 2026 -> +5.8% Apr 2026 — a real regime boundary, not a fitted split point) · early = trigger_date < cutoff, late = trigger_date >= cutoff · resolved positions only · MIN_N = 30 per fold

## Track A / F&O

| Setup Type | N (full) | Total R (full) | Verdict (full) | N (early) | Total R (early) | N (late) | Total R (late) | Consistency |
|---|---|---|---|---|---|---|---|---|
| DEALER_DEFENSE | 50 | +6.17R | PASS (asymmetric payoff) | 44 | +4.29R | 6 | +1.87R | **INCONCLUSIVE (n too thin in a fold)** |
| FLOOR_BOUNCE | 1812 | -104.91R | NO-GO | 1254 | -209.26R | 558 | +104.35R | **OVERFIT RISK — passed late, fails early** |
| GAMMA_SQUEEZE | 68 | +1.38R | PASS | 35 | -7.79R | 33 | +9.17R | **OVERFIT RISK — passed late, fails early** |
| INVENTORY_MIGRATION | 4048 | -83.31R | NO-GO | 2877 | -27.54R | 1171 | -55.77R | **CONSISTENT — fails in both folds (real NO-GO)** |
| PINCH_ZONE | 777 | +11.97R | PASS (asymmetric payoff) | 532 | +65.32R | 245 | -53.35R | **OVERFIT RISK — passed early, fails late** |
| REGIME_SHIFT | 1678 | +21.16R | PASS (asymmetric payoff) | 1310 | -68.16R | 368 | +89.32R | **OVERFIT RISK — passed late, fails early** |
| VOLATILITY_COIL | 919 | -55.13R | NO-GO | 623 | -117.25R | 296 | +62.12R | **OVERFIT RISK — passed late, fails early** |

**Never reached a tracked position:** IV_CRUSH, IV_SKEW_ACCUMULATION, IV_SPIKE — see the 'structurally silenced' note below.

## Track B / Equity

| Setup Type | N (full) | Total R (full) | Verdict (full) | N (early) | Total R (early) | N (late) | Total R (late) | Consistency |
|---|---|---|---|---|---|---|---|---|
| BREADTH_DIVERGENCE_REVERSAL | 12 | -9.80R | INCONCLUSIVE (n too small) | 10 | -10.55R | 2 | +0.75R | **INCONCLUSIVE (n too thin in a fold)** |
| IMBALANCE_CONSOLIDATION | 221 | +89.32R | PASS | 78 | +38.50R | 143 | +50.83R | **CONSISTENT — holds in both folds** |
| MOMENTUM_BUILDUP | 5035 | +144.14R | PASS | 2423 | -237.86R | 2612 | +382.00R | **OVERFIT RISK — passed late, fails early** |
| RSI_EXTREME_REBOUND | 10 | -2.02R | INCONCLUSIVE (n too small) | 2 | +0.23R | 8 | -2.24R | **INCONCLUSIVE (n too thin in a fold)** |

**Never reached a tracked position:** FIFTYTWO_WEEK_BREAKOUT — see the 'structurally silenced' note below.

## Reading this table
- **CONSISTENT (holds in both folds)**: survives outside the window it was eyeballed on — the strongest evidence available in this dataset.
- **OVERFIT RISK**: verdict flips between folds — fit to one part of the sample, not a stable effect. Do not scale size/priority without independent confirmation.
- **INCONCLUSIVE**: n < 30 in at least one fold.

**Structurally silenced setups** (F&O: IV_SPIKE, IV_CRUSH, IV_SKEW_ACCUMULATION): these fire routinely as raw signals in `daily_setups` (219 / 232 / 3,222 times respectively) but sit last in `SETUP_PRIORITY` (config/eod.py) — whenever any of the other 7 F&O setup types also fires for the same symbol/day, one of those wins the slot instead. Result: zero rows in `daily_setup_positions`, ever. Not proven wrong — structurally prevented from ever being tested under the current priority scheme.

Same single-regime caveat as the equity-only run: every fold here sits inside the same ~13-month window (one correction, one recovery, no prolonged bear/range-bound market) — CONSISTENT across these two folds is not the same as robust across a full market cycle.
