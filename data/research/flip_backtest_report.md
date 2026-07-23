# Structure-Flip Variant Backtest

Universe: 249 symbols · 264 sessions (2025-06-26 → 2026-07-22)
Entry: next-session close · returns are directional (flip direction) · net = gross − 0.4% round trip

V0 validation vs stored DB flips: 13879 stored / 13879 simulated, 0 missing, 0 extra, 0 confidence mismatches

## V0 baseline

- events: **13879** (52.6/day) · STRONG: 5311 · whipsaw share: **66.9%**

| strength | n | fwd1 % | fwd3 % | fwd5 % | fwd3 net % | hit3 % |
|---|---|---|---|---|---|---|
| STRONG | 5157 | -0.068 | -0.116 | -0.033 | -0.516 | 48.0 |
| MODERATE | 5960 | -0.02 | -0.026 | -0.066 | -0.426 | 49.9 |
| WEAK | 2340 | 0.098 | 0.19 | 0.28 | -0.21 | 52.6 |

## V1 confirm2

- events: **5455** (20.7/day) · STRONG: 568 · whipsaw share: **26.9%**

| strength | n | fwd1 % | fwd3 % | fwd5 % | fwd3 net % | hit3 % |
|---|---|---|---|---|---|---|
| STRONG | 553 | -0.183 | -0.025 | -0.02 | -0.425 | 50.1 |
| MODERATE | 1632 | -0.048 | -0.011 | -0.046 | -0.411 | 50.2 |
| WEAK | 3136 | -0.079 | 0.245 | 0.23 | -0.155 | 52.2 |

## V2 ema3

- events: **10133** (38.4/day) · STRONG: 4012 · whipsaw share: **59.1%**

| strength | n | fwd1 % | fwd3 % | fwd5 % | fwd3 net % | hit3 % |
|---|---|---|---|---|---|---|
| STRONG | 3896 | -0.082 | -0.077 | -0.046 | -0.477 | 47.8 |
| MODERATE | 4138 | -0.036 | -0.043 | -0.101 | -0.443 | 50.0 |
| WEAK | 1791 | 0.07 | 0.093 | 0.193 | -0.307 | 50.4 |

## V3 ema3+penalty

- events: **10133** (38.4/day) · STRONG: 2195 · whipsaw share: **59.1%**

| strength | n | fwd1 % | fwd3 % | fwd5 % | fwd3 net % | hit3 % |
|---|---|---|---|---|---|---|
| STRONG | 2141 | -0.165 | -0.184 | -0.215 | -0.584 | 47.8 |
| MODERATE | 3449 | -0.025 | 0.005 | 0.076 | -0.395 | 49.5 |
| WEAK | 4235 | 0.023 | 0.015 | -0.013 | -0.385 | 49.8 |

## V4 confirm2+penalty

- events: **5455** (20.7/day) · STRONG: 356 · whipsaw share: **26.9%**

| strength | n | fwd1 % | fwd3 % | fwd5 % | fwd3 net % | hit3 % |
|---|---|---|---|---|---|---|
| STRONG | 345 | -0.2 | -0.049 | -0.171 | -0.449 | 51.9 |
| MODERATE | 1341 | -0.085 | -0.019 | 0.037 | -0.419 | 49.2 |
| WEAK | 3635 | -0.068 | 0.214 | 0.177 | -0.186 | 52.1 |
