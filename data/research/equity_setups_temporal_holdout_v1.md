# Equity Setups (Track B) — Temporal Holdout

Run date: 2026-07-22 · cutoff 2026-04-01 · early fold = trigger_date < cutoff, late fold = trigger_date >= cutoff · resolved positions only · MIN_N = 30 per fold

| Setup Type | N (early) | Total R (early) | Verdict (early) | N (late) | Total R (late) | Verdict (late) | Consistency |
|---|---|---|---|---|---|---|---|
| BREADTH_DIVERGENCE_REVERSAL | 10 | -10.55R | INCONCLUSIVE (n too small) | 2 | +0.75R | INCONCLUSIVE (n too small) | **INCONCLUSIVE (n too thin in a fold)** |
| IMBALANCE_CONSOLIDATION | 78 | +38.50R | PASS | 143 | +50.83R | PASS | **CONSISTENT — holds in both folds** |
| MOMENTUM_BUILDUP | 2423 | -237.86R | NO-GO | 2612 | +382.00R | PASS | **OVERFIT RISK — passed late, fails early** |
| RSI_EXTREME_REBOUND | 2 | +0.23R | INCONCLUSIVE (n too small) | 8 | -2.24R | INCONCLUSIVE (n too small) | **INCONCLUSIVE (n too thin in a fold)** |

## Reading this table
- **CONSISTENT (holds in both folds)**: the edge survives outside the window used to eyeball/tune it — the strongest evidence available in this dataset that it's real.
- **OVERFIT RISK**: verdict flips between folds. The parameters (or the whole setup) may be fit to quirks of one part of the sample, not a stable effect. Do not raise size/priority on this setup without independent confirmation.
- **INCONCLUSIVE**: at least one fold has n < 30 — cutting the data in half exposed a sample-size problem that the full-history gate was papering over.

Caveat shared with the full-history gate: both folds sit inside the same single-direction (long-only, PRD §3.3) regime — this checks time-consistency within one market regime, not robustness across bull/bear cycles. A verdict that's CONSISTENT here can still fail in a regime this dataset has never seen.
