# Equity Setups (Track B) — E4 Backtest Gate

Run date: 2026-07-22 · docs/PRD_TRD_dual_track_signals_v1.md §8.2 · resolved positions only (OPEN rows excluded — no R yet) · MIN_N = 30

| Setup Type | N | Win Rate | Avg R | Total R | Verdict |
|---|---|---|---|---|---|
| MOMENTUM_BUILDUP | 5035 | 64.7% | +0.029R | +144.14R | **PASS** |
| IMBALANCE_CONSOLIDATION | 221 | 61.5% | +0.404R | +89.32R | **PASS** |
| BREADTH_DIVERGENCE_REVERSAL | 12 | 16.7% | -0.817R | -9.80R | **INCONCLUSIVE (n too small)** |
| RSI_EXTREME_REBOUND | 10 | 50.0% | -0.202R | -2.02R | **INCONCLUSIVE (n too small)** |

## Reading this table
- **PASS**: positive total R at n>=30, win rate above a coin flip in the direction claimed.
- **PASS (asymmetric payoff)**: positive total R despite a sub-50% win rate — winners large enough to outweigh a lower hit rate. Worth a second look before fully trusting (asymmetric-payoff claims are exactly the kind of thing a few outlier trades can fake).
- **NO-GO**: total R is flat-to-negative at a real sample size — same category as Track A's FLOOR_BOUNCE finding earlier this session. Root-cause or drop, don't ship.
- **INCONCLUSIVE**: fewer than 30 resolved positions — not enough evidence either way yet.

All six candidates are long-only (PRD §3.3) — there is no short side to cross-check against, and a raging bull market during the sample window would flatter every one of these numbers equally. Not adjusted for here; worth keeping in mind before over-trusting a PASS.
