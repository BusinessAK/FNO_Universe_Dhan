# Cross-Sectional Ranking Validation — Can We Rank the F&O Universe?

Panel: 57,738 symbol-days · 274 sessions (2025-06-26 00:00:00 → 2026-08-07 00:00:00) · 244 symbols  
Scoring: cross-sectional z-score within each session (winsorized ±3.0) · metric: per-session Spearman rank IC vs **fwd3**  
Returns: split-adjusted `adj_close`, entry = NEXT session close · holdout cutoff 2026-04-01 · MIN_N=30 · cost 0.4% round trip

Every factor tested is listed, including failures — this table is the record of what was tried, so a winner cannot be cherry-picked out of it.

## Single-factor IC vs forward 3-day return

| Factor | Family | Mean IC | t | IC>0 % | Early IC | Late IC | L/S spread % | net % | Verdict |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| `pcr` | Derivatives | +0.0333 | +5.74 | 64% | +0.0376 | +0.0234 | +0.232 | -0.168 | **CONSISTENT — same sign both folds, |t| >= 2** |
| `skew_slope` | Derivatives | +0.0402 | +5.13 | 62% | +0.0472 | +0.0241 | +0.260 | -0.140 | **CONSISTENT — same sign both folds, |t| >= 2** |
| `delivery_pct_ratio_20d` | Volume | +0.0213 | +3.81 | 60% | +0.0295 | +0.0043 | +0.190 | -0.210 | **CONSISTENT — same sign both folds, |t| >= 2** |
| `pct_from_52w_low` | Price | +0.0334 | +2.97 | 57% | +0.0652 | -0.0055 | +0.211 | -0.189 | **OVERFIT RISK — sign flips between folds** |
| `rsi14` | Price | +0.0264 | +2.72 | 56% | +0.0377 | +0.0022 | +0.156 | -0.244 | **CONSISTENT — same sign both folds, |t| >= 2** |
| `delivery_pct` | Volume | +0.0229 | +2.59 | 55% | +0.0325 | +0.0010 | +0.110 | -0.290 | **CONSISTENT — same sign both folds, |t| >= 2** |
| `pct_from_52w_high` | Price | +0.0328 | +2.42 | 54% | +0.0644 | -0.0058 | +0.061 | -0.339 | **OVERFIT RISK — sign flips between folds** |
| `dma50_gap` | Price | +0.0261 | +2.23 | 54% | +0.0372 | +0.0071 | +0.178 | -0.222 | **CONSISTENT — same sign both folds, |t| >= 2** |
| `gex_intensity` | Derivatives | -0.0156 | -2.21 | 42% | -0.0049 | -0.0401 | -0.243 | -0.643 | **CONSISTENT — same sign both folds, |t| >= 2** |
| `roc_63d` | Returns | +0.0235 | +1.93 | 52% | +0.0408 | -0.0031 | +0.014 | -0.386 | **OVERFIT RISK — sign flips between folds** |
| `net_inv_shift` | Derivatives | +0.0103 | +1.92 | 53% | +0.0114 | +0.0076 | +0.034 | -0.366 | no signal (|t| < 2) |
| `gex_shift` | Derivatives | -0.0106 | -1.92 | 47% | -0.0086 | -0.0153 | -0.002 | -0.402 | no signal (|t| < 2) |
| `money_flow_20d` | Volume | +0.0138 | +1.85 | 54% | +0.0193 | +0.0023 | -0.003 | -0.403 | no signal (|t| < 2) |
| `dma20_gap` | Price | +0.0174 | +1.84 | 55% | +0.0293 | -0.0072 | +0.281 | -0.119 | **OVERFIT RISK — sign flips between folds** |
| `iv` | Derivatives | -0.0193 | -1.70 | 49% | -0.0378 | +0.0232 | +0.072 | -0.328 | **OVERFIT RISK — sign flips between folds** |
| `roc_20d` | Returns | +0.0170 | +1.68 | 53% | +0.0288 | -0.0074 | +0.100 | -0.300 | **OVERFIT RISK — sign flips between folds** |
| `priority_score` | Derivatives | -0.0072 | -1.14 | 46% | +0.0026 | -0.0295 | -0.158 | -0.558 | **OVERFIT RISK — sign flips between folds** |
| `deliverable_vol_ratio_20d` | Volume | +0.0057 | +1.05 | 52% | +0.0042 | +0.0089 | +0.054 | -0.346 | no signal (|t| < 2) |
| `spot_change_pct` | Returns | -0.0075 | -1.00 | 46% | -0.0058 | -0.0114 | -0.004 | -0.404 | no signal (|t| < 2) |
| `roc_5d` | Returns | +0.0056 | +0.71 | 53% | +0.0083 | -0.0005 | +0.204 | -0.196 | **OVERFIT RISK — sign flips between folds** |
| `conviction_score` | Derivatives | -0.0044 | -0.69 | 45% | +0.0066 | -0.0298 | -0.085 | -0.485 | **OVERFIT RISK — sign flips between folds** |
| `natr14` | Price | -0.0074 | -0.66 | 54% | -0.0241 | +0.0282 | +0.192 | -0.208 | **OVERFIT RISK — sign flips between folds** |
| `iv_shift` | Derivatives | +0.0037 | +0.64 | 50% | +0.0054 | -0.0003 | +0.063 | -0.337 | **OVERFIT RISK — sign flips between folds** |
| `iv_rank` | Derivatives | -0.0022 | -0.40 | 46% | -0.0083 | +0.0115 | -0.019 | -0.419 | **OVERFIT RISK — sign flips between folds** |
| `volume_ratio_20d` | Volume | -0.0014 | -0.23 | 50% | -0.0057 | +0.0076 | +0.051 | -0.349 | **OVERFIT RISK — sign flips between folds** |
| `ifs_score` | Derivatives | -0.0009 | -0.16 | 47% | +0.0007 | -0.0047 | -0.023 | -0.423 | **OVERFIT RISK — sign flips between folds** |
| `futures_oi_chg_pct` | Derivatives | -0.0005 | -0.09 | 51% | -0.0011 | +0.0009 | -0.015 | -0.415 | **OVERFIT RISK — sign flips between folds** |

## Factors surviving both gates (|t| ≥ 2 and no sign flip)

- `pcr` (put/call ratio) — IC +0.0333, t +5.74, L/S spread +0.232% (-0.168% net of cost)
- `skew_slope` (skew slope) — IC +0.0402, t +5.13, L/S spread +0.260% (-0.140% net of cost)
- `delivery_pct_ratio_20d` (delivery % vs 20d) — IC +0.0213, t +3.81, L/S spread +0.190% (-0.210% net of cost)
- `rsi14` (RSI(14)) — IC +0.0264, t +2.72, L/S spread +0.156% (-0.244% net of cost)
- `delivery_pct` (delivery %) — IC +0.0229, t +2.59, L/S spread +0.110% (-0.290% net of cost)
- `dma50_gap` (close vs 50DMA %) — IC +0.0261, t +2.23, L/S spread +0.178% (-0.222% net of cost)
- `gex_intensity` (GEX intensity) — IC -0.0156, t -2.21, L/S spread -0.243% (-0.643% net of cost)

## Decile forward-3d return — strongest factors by |t|

**`pcr`** (put/call ratio) — decile 0 = lowest score, 9 = highest

| decile | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| fwd3 % | -0.050 | +0.013 | -0.028 | +0.074 | +0.073 | +0.145 | +0.108 | +0.139 | +0.122 | +0.177 |

**`skew_slope`** (skew slope) — decile 0 = lowest score, 9 = highest

| decile | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| fwd3 % | -0.083 | -0.044 | +0.008 | +0.018 | +0.072 | +0.077 | +0.094 | +0.180 | +0.277 | +0.175 |

**`delivery_pct_ratio_20d`** (delivery % vs 20d) — decile 0 = lowest score, 9 = highest

| decile | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| fwd3 % | +0.003 | +0.116 | +0.049 | +0.110 | +0.158 | +0.137 | +0.084 | +0.185 | +0.142 | +0.193 |

**`pct_from_52w_low`** (% from 52w low) — decile 0 = lowest score, 9 = highest

| decile | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| fwd3 % | +0.068 | +0.010 | -0.011 | -0.045 | +0.098 | +0.262 | +0.015 | +0.226 | +0.147 | +0.280 |

**`rsi14`** (RSI(14)) — decile 0 = lowest score, 9 = highest

| decile | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| fwd3 % | +0.104 | +0.004 | +0.044 | +0.003 | +0.044 | +0.015 | +0.081 | +0.108 | +0.179 | +0.262 |

## Reading this table

- **Mean IC** — average per-session Spearman correlation between the factor and the next-3-session return. Single-session IC has SE ≈ 0.069, so only the average over 274 sessions is interpretable; a few days would be pure noise.
- **t** — mean IC divided by its standard error across sessions. |t| ≥ 2 is the minimum bar; it is not proof, and with ~27 factors tested roughly one would clear |t| ≥ 2 by chance alone.
- **L/S spread** — mean forward return of the top decile minus the bottom decile, computed per session then averaged. **net** subtracts 0.4% round-trip cost.
- **OVERFIT RISK** — mean IC changes sign between the pre/post-2026-04-01 folds: fitted to one part of the sample, not a stable effect.

Single-regime caveat, same as every prior study here: the whole panel sits inside one ~13-month window with one correction and one recovery. Surviving both folds is not the same as robust across a full market cycle.

---

# Follow-up — horizon, composite, and the overlap correction

The fwd3 table above is the answer to the original question ("do ranked names
move the same way over the *next few sessions*?"). They do not: the best
single-factor long-short decile spread is +0.28% gross against 0.40%
round-trip cost. **Every factor is net-negative at fwd3.**

Because cost is charged per round trip regardless of hold length, a longer
hold amortizes it. Extending the horizon:

| hold | composite gross | composite net | pcr gross | pcr net |
|---:|---:|---:|---:|---:|
| 3  | +0.314% | **-0.086%** | +0.232% | **-0.168%** |
| 5  | +0.463% | +0.063% | +0.446% | +0.046% |
| 10 | +0.748% | +0.348% | +0.867% | +0.467% |
| 20 | +1.391% | +0.991% | +1.473% | +1.073% |

## The overlap correction (this is the important part)

Forward-20d returns on consecutive sessions share ~95% of their window, so
treating 274 sessions as independent inflates every t-stat. Re-testing on
**non-overlapping** windows (every 20th session) and with Newey-West(L=19):

| | overlapping t | non-overlap t (3 offsets) | Newey-West t |
|---|---:|---|---:|
| composite (7 survivors) | +5.47 | +0.94 / +0.58 / +1.05 | +2.10 |
| **pcr alone** | +9.78 | **+3.88 / +3.50 / +3.29** | **+3.94** |

**The composite's significance was an artifact of overlap.** It does not
survive. The single factor beats the 7-factor blend — the survivors are
heavily collinear (rsi14/dma50_gap r=0.91, skew_slope/rsi14 r=0.71,
delivery_pct pair r=0.62, pcr/gex_intensity r=-0.54), so equal-weighting
mostly double-counts one momentum bet and dilutes pcr, while
`delivery_pct_ratio_20d` actively fails at every horizon beyond 3 days.

## What pcr actually says

Ranked by within-session PCR quintile, forward-20d return:

| quintile | median pcr | fwd20 % | n |
|---:|---:|---:|---:|
| 0 (lowest) | 0.48 | -0.21 | 10,594 |
| 1 | 0.58 | +0.30 | 10,478 |
| 2 | 0.65 | +0.42 | 10,481 |
| 3 | 0.73 | +0.67 | 10,478 |
| 4 (highest) | 0.87 | +0.92 | 10,583 |

Deciles are monotonic in 8 of 9 steps (-0.43% -> +1.03%). Economically this is
a contrarian sentiment read: names carrying heavy put positioning relative to
calls subsequently outperform. Robustness:

- **liquid half only (above-median futures OI): t +2.74, net +2.68%** — the
  effect is *stronger* on liquid names, so it is not an illiquidity artifact.
- trimmed to the 5th-95th pcr percentile: t +1.76 — part of the effect does
  live in the tails.

## Verdict — INCONCLUSIVE, not a green light

| fold | non-overlapping windows | mean spread | t | net |
|---|---:|---:|---:|---:|
| early (< 2026-04-01) | 10 | +2.13% | +2.72 | +1.73% |
| late (>= 2026-04-01) | **4** | +0.70% | **+0.54** | +0.30% |

The whole 20-day result rests on ~13 independent windows, and the recent fold
has only **4** — far below this repo's MIN_N=30 gate, and not significant
(t +0.54). By the standard applied in `setup_temporal_holdout_v1.md` this is
**INCONCLUSIVE (n too thin in a fold)**, not CONSISTENT.

## Bottom line

1. **The 3-day premise is dead.** Nothing tested clears cost at fwd3, and the
   late fold is weaker still. A ranking section promising "these move next
   session" is not supported by this data.
2. **pcr at a ~20-day horizon is the one real candidate** — monotonic,
   economically coherent, stronger on liquid names, and it clears cost by a
   wide margin in-sample.
3. **It is not yet confirmable.** 4 independent windows in the recent fold
   cannot distinguish a live edge from a decayed one. Confirming it needs
   either more history than this DB holds, or a forward paper-trade log.
4. The composite is worse than the single factor; do not ship a blended score.

Single-regime caveat applies as everywhere else here: one ~13-month window,
one correction, one recovery.


---

# Optimisation pass — step by step

35+ configurations tested. At that count ~1.8 would clear |t| >= 2 by chance,
so every number below is overlap-corrected: for horizon h the series is
sampled every h-th session across ALL h offsets (`t_no mean` / `t_no min`),
plus Newey-West(L=h-1). The naive per-session t is never used as evidence.

## Step 1 — horizon curve

| hold | independent windows | gross | net | t_no mean (min) | t_NW |
|---:|---:|---:|---:|---|---:|
| 3  | 90 | +0.232 | **-0.168** | +2.21 (+1.99) | +2.77 |
| 5  | 54 | +0.446 | +0.046 | +2.46 (+1.85) | +3.20 |
| 10 | 27 | +0.867 | +0.467 | +2.14 (+0.80) | +3.01 |
| 15 | 18 | +1.173 | +0.773 | +2.19 (+0.77) | +3.30 |
| 20 | 13 | +1.473 | +1.073 | +2.19 (+0.90) | +3.94 |
| 30 |  9 | +2.532 | +2.132 | +2.36 (+0.76) | +4.72 |
| 40 |  6 | +2.750 | +2.350 | +1.89 (-0.05) | +3.90 |

A smooth monotone plateau, not a spike at one horizon — the signature of a
real effect. The trade-off is explicit: longer horizon pays more but has fewer
independent windows to confirm it. **fwd10 is the balance point** (27 windows,
clears cost by 0.47%).

## Step 2 — what part of pcr carries it

| variant | net (fwd20) | t_NW |
|---|---:|---:|
| pcr **level** | +1.073 | +3.94 |
| pcr 1d **change** | -0.283 | +1.15 |
| pcr vs its **own 20d** history | -0.459 | -0.19 |
| pcr residualised on roc_5d/roc_20d/rsi14 | +0.743 | +2.43 |

The signal is in the cross-sectional **level**, not in any change or
self-relative move. It is not merely a momentum proxy — residualising against
returns and RSI leaves ~70% of it intact.

## Step 3 — is it stock selection or a sector bet?

| variant | net (fwd20) | t_NW |
|---|---:|---:|
| raw | +1.073 | +3.94 |
| **sector-neutral** | +0.421 | +2.91 |
| liquid half (above-median futures OI) | +1.350 | +3.03 |
| illiquid half | +0.417 | +1.99 |

**Roughly half the edge is a sector tilt.** The stock-specific residual
survives but is half the size. It is stronger on liquid names — the opposite
of a microstructure artifact.

## Step 4 — is it outlier-driven? (the test that nearly killed it)

Dropping the top realised contributors destroys it (drop 20 of 244 names ->
net -0.226%). **But that test is invalid** — removing the best ex-post
performers destroys any strategy. The unbiased versions:

| variant | gross | net |
|---|---:|---:|
| raw mean | +1.473 | +1.073 |
| winsorized 5/95 pct | +1.389 | +0.989 |
| hard cap +-20% | +1.498 | +1.098 |
| **median spread (outlier-immune)** | **+1.590** | **+1.190** |

The median spread is *larger* than the mean. Breadth confirms it: top decile
54.4% positive vs bottom decile 43.8%, ~5,300 observations each, skew 0.20.
**Broad-based, not a few lottery tickets.**

## Step 5 — construction and legs

| config | net/tranche (fwd10) | annualised |
|---|---:|---:|
| quintile (43 names/leg) | +0.165 | ~+4% |
| **decile (21 names/leg)** | **+0.467** | **~+11.7%** |
| top 5% (11 names/leg) | +0.679 | ~+17.0% |

Short leg carries more than the long leg (fwd20: -0.65% vs +0.42% net), so a
long-only implementation gets the weaker half.

## Step 6 — 27 independent tranches, fwd10 decile L/S, net of cost

Total **+22.14%**, profitable in **16/27 (59%)**, worst tranche -3.91%,
tranche stdev 2.19%, crude annualised Sharpe **1.87**.

Cumulative peaked +23.6% (Feb 2026), drew down to +15.3% (Apr 2026), recovered
to +22.1%. Split by fold: **early +1.01%/tranche (19 tranches) vs late
+0.36%/tranche (8 tranches)** — still positive, but about a third the
strength.

## Verdict — a candidate worth paper-trading, not capital

Best configuration: **rank the liquid half of the F&O universe by PCR, long
top decile / short bottom decile, 10-session hold.**

Supporting it: monotone deciles (8/9), smooth horizon plateau, broad-based and
outlier-immune, economically coherent (heavy put positioning -> subsequent
outperformance, a contrarian sentiment read), turns over properly (20d rank
autocorrelation 0.057, 21.6% top-decile overlap), stronger on liquid names,
and survives momentum residualisation.

Against it: the late fold runs a third of the early fold's strength on only 8
tranches; half the edge is a sector tilt; the short leg carries more than the
long; 35+ configurations were tested against one 13-month single-regime
window; and no fold ever cleared this repo's MIN_N=30 gate.

Nothing here has been out-of-sample tested in the sense that matters — every
number above comes from the same window the configuration was chosen on. The
only honest confirmation is forward paper-trading the fixed rule above and
comparing against these figures.


---

# Position-building confirmation — tested and rejected

Different hypothesis from the ranking work above: rather than "which stock
will rise", identify stocks where **positioning is being built visibly enough
that a move follows in either direction**, and discard names where the data
does not confirm participation.

Standard OI x price quadrant framework: price up + OI up = LONG_BUILDUP,
price down + OI up = SHORT_BUILDUP, price up + OI down = SHORT_COVERING,
price down + OI down = LONG_UNWINDING. Participation score = cross-sectional
z of |OI change %| + volume vs 20d + delivery% vs 20d; CONFIRMED = top
quartile within session, UNCONFIRMED = bottom quartile.

This is an *interaction* hypothesis, which is why the linear factor scan above
could not have detected it — `futures_oi_chg` scored IC ~0 standalone
precisely because its meaning is conditional on price direction.

## Result 1 — the quadrants carry no directional information

Forward-10d return, raw (not sign-adjusted):

| quadrant | n | mean | median | % > 0 |
|---|---:|---:|---:|---:|
| LONG_BUILDUP | 14,132 | +0.217 | -0.117 | 48.9% |
| SHORT_BUILDUP | 16,927 | +0.226 | -0.058 | 49.5% |
| SHORT_COVERING | 13,116 | +0.153 | -0.125 | 49.0% |
| LONG_UNWINDING | 10,662 | +0.248 | +0.000 | 50.0% |
| **universe** | 55,054 | **+0.210** | -0.085 | 49.3% |

Every quadrant is indistinguishable from the universe. Per-date excess vs
universe, overlap-corrected: -0.001 / +0.015 / -0.078 / +0.042, all |t| < 1.
The supposedly bearish SHORT_BUILDUP quadrant marginally *outperforms* the
bullish LONG_BUILDUP one.

## Result 2 — "confirmed participation" is a volatility proxy, nothing more

CONFIRMED minus UNCONFIRMED, absolute forward-10d move:

| measure | difference | t (min) | t_NW |
|---|---:|---|---:|
| raw \|move\| | +0.232 | +1.37 (+0.35) | +3.46 |
| **normalised by the symbol's own natr14** | **+0.009** | +0.12 (-0.55) | +0.37 |

Confirmed names do move more in absolute terms — and that difference vanishes
completely once divided by each stock's own baseline volatility. The clearest
demonstration is OI-change magnitude alone, by quintile:

| \|OI chg\| quintile | raw \|fwd10\| | vol-normalised |
|---|---:|---:|
| 0 (smallest) | 4.330 | 1.737 |
| 1 | 4.361 | 1.727 |
| 2 | 4.436 | 1.730 |
| 3 | 4.508 | 1.725 |
| 4 (largest) | **4.816** | **1.712** |

Raw move size rises monotonically with OI build (4.33 -> 4.82). Volatility-
normalised it is **flat, and if anything slightly declining** (1.737 ->
1.712). The entire apparent "big position build -> big move" relationship is
just big builds happening in names that always move a lot. You would be paying
for volatility you already knew about.

## Result 3 — the filter adds nothing, and does not replicate

Within-quadrant CONFIRMED-minus-UNCONFIRMED directional return: +0.227 /
+0.070 / +0.112 / +0.236 at fwd10, all |t| < 0.5. Holdout signs flip for both
main quadrants (LONG_BUILDUP early +0.348 -> late -0.025; SHORT_BUILDUP early
-0.160 -> late +0.607).

32 tests, ~1.6 expected to clear |t| >= 2 by chance; nothing cleared it on the
strict (min non-overlapping) criterion.

## Verdict

**Rejected.** In this dataset you cannot identify stocks whose positioning is
"so evident that price will move" — neither the direction of the move
(all four quadrants sit at ~49% hit rate, same as the universe) nor its
magnitude beyond each stock's own normal volatility.

This is worth stating plainly because the OI x price quadrant framework is
near-universal in Indian F&O commentary. It does not survive contact with this
book's own 274 sessions.

**One legitimate use survives:** participation/liquidity screening as a
TRADEABILITY filter — avoiding names you cannot get filled in — is still
sensible. It just is not a predictive signal, and should not be presented as
one.


---

# The contrarian thread — the one result that survives

Both nulls above pointed the same way: bearish positioning (high PCR, short
buildup) was followed by mild *out*performance, not the decline the
conventional framework predicts. Following that thread.

## A priori hypothesis, stated before testing

`pcr` and `skew_slope` both measure appetite for downside protection, yet
correlate only **+0.17**. If the contrarian effect is real rather than an
artifact of either series, a 2-factor composite should beat both. This is the
inverse of the failed 7-factor blend, which diluted signal with collinear
momentum factors.

**CONTRA = (z(pcr) + z(skew_slope)) / 2**, both cross-sectional per session.

## Result — it beats both components at every horizon

| horizon | | gross | net | t_min | t_NW |
|---|---|---:|---:|---:|---:|
| fwd5 | pcr | +0.446 | +0.046 | +1.85 | +3.20 |
| | skew | +0.401 | +0.001 | +1.59 | +2.53 |
| | **CONTRA** | **+0.575** | **+0.175** | **+2.53** | **+3.86** |
| fwd10 | pcr | +0.867 | +0.467 | +0.80 | +3.01 |
| | skew | +0.626 | +0.226 | +0.78 | +2.50 |
| | **CONTRA** | **+1.021** | **+0.621** | **+2.06** | **+3.97** |
| fwd20 | **CONTRA** | +1.730 | +1.330 | +0.74 | +4.84 |

`t_min` is the strict criterion — the *worst* of all non-overlapping offsets.
At fwd10 `pcr` alone scores +0.80 there (not significant); the composite
scores **+2.06, significant at every offset**. Skew residualised on pcr still
carries independent signal (net +0.068, t_NW +1.85), confirming the two are
not the same bet.

## Mechanism — it is a pessimism unwind

Contrarian composite within recent-return terciles (fwd5):

| bucket | net | t_min | t_NW |
|---|---:|---:|---:|
| recent LOSERS (roc20 bottom 3rd) | **+0.112** | +1.79 | +3.14 |
| recent MIDDLE | -0.109 | +0.04 | +2.15 |
| recent WINNERS (roc20 top 3rd) | -0.008 | +0.95 | +2.73 |

Strongest in names that have already fallen *and* carry heavy put demand —
a coherent capitulation-then-unwind story rather than a statistical accident.

## Tranche reality check — fwd10, 27 independent tranches, net of cost

| config | total | profitable | mean | median | worst | Sharpe | ann |
|---|---:|---:|---:|---:|---:|---:|---:|
| decile (21/leg) | +18.28% | 16/27 (59%) | +0.677% | +0.082% | -3.23% | 1.83 | ~+16.9% |
| top 5% (11/leg) | +25.48% | 18/27 (67%) | +0.944% | +0.410% | -3.77% | 1.81 | ~+23.6% |

Max drawdown -4.55% (decile) / -5.28% (top 5%).

**Median tranche is only +0.082%.** Half the tranches deliver essentially
nothing; the mean is carried by the right tail. This is a positive-skew
strategy, not a steady drip.

## Leg decomposition — the practical catch

| leg | return | vs universe |
|---|---:|---:|
| top decile | +0.666% | **+0.389%** |
| bottom decile | -0.411% | **-0.689%** |

The **short leg carries ~64% of the edge**. Long-only nets +0.189%/tranche
after half-cost, roughly **+4.7%/yr** — a quarter of the long-short headline.
This strategy needs the short side to be worth trading.

## Holdout

| fold | horizon | net | t_min | t_NW |
|---|---|---:|---:|---:|
| early | fwd10 | +0.704 | +1.39 | +3.52 |
| **late** | fwd10 | **+0.412** | +0.49 | +1.87 |
| early | fwd10 liquid | +0.775 | +0.24 | +2.70 |
| **late** | fwd10 liquid | **+0.526** | +0.38 | +1.71 |

**Positive in every fold and every configuration — no sign flip anywhere.**
That is more than anything else in this investigation managed. But the late
fold is never *significant*: 8 independent windows cannot carry a t-stat, and
it runs ~60% of early-fold strength.

## Verdict

Best rule: **CONTRA = mean of cross-sectional z(pcr) and z(skew_slope); long
top decile, short bottom decile; 10-session hold.**

The strongest result here, and the only one clearing t_min > 2 across all
offsets. It was predicted a priori from the correlation structure rather than
found by scanning, it improves on both inputs, it has a coherent economic
mechanism concentrated exactly where the story says it should be, and it never
flips sign across the regime boundary.

Against it: **~107 configurations were tested across this investigation**, so
~5 would clear |t| >= 2 by chance; the late fold is positive but unconfirmable
on 8 windows; the median tranche is near zero with the mean carried by the
tail; the short leg carries most of the edge; and no fold ever met this repo's
MIN_N=30 gate. Single 13-month regime throughout.

**Recommendation: paper-trade this exact rule forward.** It is the only
candidate that has earned that. It has not earned capital, and it has not
earned a HUD section, until forward results match these figures.
