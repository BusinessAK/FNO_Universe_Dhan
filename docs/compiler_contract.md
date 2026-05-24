# Vanguard Institutional Compiler Output Contract

This contract defines the strict EOD output schemas persisted by the chronological data compiler (`daily_compiler.py`). 
All dashboard panels, visualization components, and analytical engines are built on top of this standardized database contract.

---

## 1. Table: `daily_market_structure`
Holds the core session metrics and dealer exposure profiles for each symbol.

| Field Name | Type | Unit / Description | Key Constraints |
| :--- | :--- | :--- | :--- |
| `symbol` | `VARCHAR` | F&O Symbol name (e.g. `ABB`, `CONCOR`) | Primary Key Segment |
| `date` | `VARCHAR` | ISO YYYY-MM-DD trading session date | Primary Key Segment |
| `spot_close` | `DOUBLE` | Spot close price (underlying asset close) | Non-zero |
| `spot_change_pct` | `DOUBLE` | Percentage price change from previous session | - |
| `pcr` | `DOUBLE` | Put-Call Open Interest Ratio (Total PE OI / Total CE OI) | - |
| `total_ce_oi` | `DOUBLE` | Cumulative Call options Open Interest | - |
| `total_pe_oi` | `DOUBLE` | Cumulative Put options Open Interest | - |
| `delta_ce_oi` | `DOUBLE` | Change in Call OI during active session | - |
| `delta_pe_oi` | `DOUBLE` | Change in Put OI during active session | - |
| `total_volume` | `DOUBLE` | Combined Call + Put traded volume (lots) | - |
| `delta_volume` | `DOUBLE` | Volume change relative to previous session | - |
| `net_inv_shift` | `DOUBLE` | Net smart money inventory change (PE ΔOI - CE ΔOI) | - |
| `ifs_score` | `DOUBLE` | Institutional Flow Score (-100.0 to +100.0) | - |
| `smart_money_persistence`| `DOUBLE` | Persistence conviction scaling score (0 to 100%) | - |
| `conviction_score` | `DOUBLE` | Final combined conviction confidence score (0 to 100%)| - |
| `priority_score` | `DOUBLE` | Squeeze priority metrics (Pty score) | - |
| `structural_bias` | `VARCHAR` | Trend classification label (e.g., `Support Building`)| - |
| `regime_transition` | `BOOLEAN` | True if Gamma regime flipped during the session | - |
| `call_wall` | `DOUBLE` | Maximum concentration Call options Open Interest strike | - |
| `put_wall` | `DOUBLE` | Maximum concentration Put options Open Interest strike | - |
| `gamma_flip` | `DOUBLE` | Gamma regime pivot crossover strike price | - |
| `gex` | `DOUBLE` | Cumulative smart money Net Gamma Exposure (lots) | - |
| `gex_intensity` | `DOUBLE` | Exposure scaling relative to lot sizes | - |
| `gex_shift` | `DOUBLE` | Dealer GEX change relative to previous session | - |
| `gamma_regime` | `VARCHAR` | Exposure regime (`LONG_GAMMA`, `SHORT_GAMMA`, etc.) | - |
| `iv` | `DOUBLE` | Average implied volatility (average CE + PE IV) | - |
| `iv_shift` | `DOUBLE` | Implied Volatility shift relative to previous session | - |
| `ce_interp` | `VARCHAR` | Option chain action description (e.g., `Call Writing`) | - |
| `pe_interp` | `VARCHAR` | Option chain action description (e.g., `Put Writing`) | - |
| `suggested_strategy` | `VARCHAR` | Actionable quant option spread suggestion | - |

---

## 2. Table: `daily_setups`
Governs the tactical triggers and targeted playbooks.

| Field Name | Type | Unit / Description |
| :--- | :--- | :--- |
| `symbol` | `VARCHAR` | F&O Symbol name |
| `date` | `VARCHAR` | ISO YYYY-MM-DD trading session date |
| `setup_type` | `VARCHAR` | Setup name (`GAMMA_SQUEEZE`, `INVENTORY_MIGRATION`, or `NONE`) |
| `bias` | `VARCHAR` | Directional bias (`Bullish Breakout`, `Bearish Breakdown`) |
| `trigger_strike` | `DOUBLE` | Operational entry trigger strike price |
| `invalidation_strike`| `DOUBLE`| Operational risk stop/pivot strike price |
| `expected_behavior`| `VARCHAR` | Targeted trade expected behavior description |
| `dealer_behavior` | `VARCHAR` | Dealer hedging delta-hedging expectations |

---

## 3. Table: `daily_inventory`
Maintains longitudinal inventory shifts.

| Field Name | Type | Unit / Description |
| :--- | :--- | :--- |
| `symbol` | `VARCHAR` | F&O Symbol name |
| `date` | `VARCHAR` | ISO YYYY-MM-DD trading session date |
| `put_wall_shift` | `VARCHAR` | Support floor shift state (`Higher`, `Lower`, `Stable`) |
| `call_wall_shift` | `VARCHAR` | Resistance ceiling shift state (`Higher`, `Lower`, `Stable`) |
| `regime_change` | `BOOLEAN` | True if GEX regime crossed over |
| `put_wall_pct_change` | `DOUBLE` | Percent shift in Put Wall strike |
| `call_wall_pct_change`| `DOUBLE` | Percent shift in Call Wall strike |
| `bullish_persistence` | `INTEGER` | Consecutive bullish EOD flow sessions count |
| `bearish_persistence` | `INTEGER` | Consecutive bearish EOD flow sessions count |

---

## 4. Table: `daily_market_breadth`
Global market-wide breadth aggregate.

| Field Name | Type | Unit / Description |
| :--- | :--- | :--- |
| `date` | `VARCHAR` | ISO YYYY-MM-DD trading session date |
| `bullish_pct` | `DOUBLE` | Percentage of symbols in bullish flow |
| `bearish_pct` | `DOUBLE` | Percentage of symbols in bearish flow |
| `compression_pct` | `DOUBLE` | Percentage of symbols in volatility compression (coils)|
| `expansion_pct` | `DOUBLE` | Percentage of symbols in volatility expansion (squeezes)|
| `transition_pct` | `DOUBLE` | Percentage of symbols in regime transitions |
| `mean_rev_pct` | `DOUBLE` | Percentage of symbols in mean-reversion zones |
| `total_symbols` | `INTEGER` | Combined universe size (e.g. 209) |

---

## 5. Table: `daily_changes`
EOD structure change ledger alerts.

| Field Name | Type | Unit / Description |
| :--- | :--- | :--- |
| `date` | `VARCHAR` | ISO YYYY-MM-DD trading session date |
| `symbol` | `VARCHAR` | F&O Symbol name |
| `icon` | `VARCHAR` | UI indicator icon (`🟢`, `🔴`, `🔋`, `⚠`) |
| `type` | `VARCHAR` | Event type (`support_rise`, `support_drop`, `regime_flip_bearish`) |
| `msg` | `VARCHAR` | Formatted descriptive text msg |
