# F&O Footprint Forward Backtest Report

**Trigger Logic:** `IFS > 30` AND `Structural Bias == EXPANSION` AND `Inventory Migration Setup Present`
**Execution Slippage Assumed:** 0.20% per round trip (entry + exit)

### Total Signals Fired: 3379

| Metric | Win Rate | Avg Win | Avg Loss | **Expectancy (Edge)** |
|---|---|---|---|---|
| T+1 Close | 39.8% | +1.34% | -1.43% | -0.33% |
| T+3 Close | 44.0% | +2.31% | -2.67% | -0.48% |
| T+5 Close | 46.0% | +3.00% | -3.21% | -0.35% |
| T+3 Max Close | 60.2% | +2.19% | -1.31% | **+0.80%** |
| T+5 Max Close | 68.4% | +2.87% | -1.29% | **+1.55%** |

> **Analysis Note:** Expectancy is the true mathematical edge per trade (Win Rate × Avg Win) + (Loss Rate × Avg Loss). A positive expectancy means this footprint possesses genuine predictive alpha over random entry.
