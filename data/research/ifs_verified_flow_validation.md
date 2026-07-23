# IFS Verified-Flow Fix — Pre-Recompile Validation Gate

Rows compared: 55,891 symbol-days. Forward-3-day return, quintile-bucketed by ifs_score, same methodology as flip_backtest_report.md.

## OLD (raw OI sign assumption)

          variant  quintile     n  fwd3_pct  hit3_pct
OLD (raw OI sign)         0 10998    -0.040      48.5
OLD (raw OI sign)         1 11000    -0.009      49.2
OLD (raw OI sign)         2 10982     0.022      49.5
OLD (raw OI sign)         3 10941     0.020      49.3
OLD (raw OI sign)         4 10974     0.053      49.4

corr(ifs_score, fwd3): 0.0066

## NEW (premium-verified flow)

            variant  quintile     n  fwd3_pct  hit3_pct
NEW (verified flow)         0 10982     0.090      50.6
NEW (verified flow)         1 10986    -0.054      49.5
NEW (verified flow)         2 10978    -0.000      49.7
NEW (verified flow)         3 10975    -0.020      47.9
NEW (verified flow)         4 10974     0.030      48.1

corr(ifs_score, fwd3): -0.0030

## Decision gate (matches flip_backtester precedent: quintile fwd3 must be non-decreasing bearish-to-bullish, with correct-signed extremes)

OLD clears gate: True
NEW clears gate: False

**Verdict: NO-GO — NEW does not clear the monotonicity/sign gate; do not recompile without revisiting the fix.**
