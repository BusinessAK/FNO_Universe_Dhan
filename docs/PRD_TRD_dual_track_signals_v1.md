# PRD + TRD — Dual-Track Signal Architecture v1 ("derivatives flow" + "cash breadth/technicals")

**Status:** Draft, pre-implementation — nothing in this document is built yet
**Owner:** Aniket · **Doc type:** combined PRD + TRD + test/backtest plan
**Governing principle:** no code lands without per-phase approval, same discipline as `PRD_TRD_nse_context_layer_v1.md`. Every new signal must clear a backtest gate before it is trusted, same discipline as the FLOOR_BOUNCE/REGIME_SHIFT fixes and the `ifs_verified_flow_backtest.py` precedent.

---

## 1. Objective

The platform splits into two independent, non-blended signal tracks, matching what each dataset actually can and can't see:

- **Track A — F&O (derivatives).** Purely options-chain-derived: IFS, gamma/dealer structure, IV. Universe = the ~249 F&O-eligible symbols. **No sector concept at all** — confirmed scope cut, this session. A stock's derivatives positioning doesn't need a sector lens; the whole point is that it's a single-name, options-chain-specific read.
- **Track B — Cash/Equity (breadth & technicals).** Price-action and volume-derived: moving averages, RSI, rate of change, money flow, delivery conviction, breadth context. Universe = all 500 Nifty 500 names (of which 249 overlap with Track A — those symbols get *both* a Track A and a Track B read, independently, never merged into one score). This is where "sector" belongs going forward — NSDL fortnightly FPI flow (`fpi_sector_flow`, already built) and the NSE-sourced per-stock `industry` tag (validated, not yet built) are Track B concepts, not Track A.

Both tracks end at the same shape — **setups with `{bias, trigger, invalidation, target}`, tracked through the same generic position-lifecycle machinery, measured by the same win-rate/expectancy math** — because `derive_positions()` (`vanguard/rules/setup_positions.py`) is already source-agnostic: it only needs a `day_data` dict with `setups`/`primary_setup`/`playbook`/`spot_close`. Track B reuses this without modification. What's genuinely new is everything upstream of that: the per-symbol technical computation, the screener, and the playbook.

**Schema contract (reviewed 2026-07-21):** `_setup_snapshot()` at `setup_positions.py:36-37` reads the playbook dict via the literal keys `"trigger_strike"` / `"invalidation_strike"` — hardcoded, no fallback. For reuse to actually work, **`equity_playbook.py` must emit a dict using those exact same two keys**, even though "strike" reads oddly for a cash price level. This is a naming-convention requirement on Track B's code, not a change to `setup_positions.py` — deliberately not adding a `trigger_price` fallback there, since accepting two key shapes forks the schema and is exactly the kind of drift this session has been removing elsewhere (single-sourced predicates, no duplicate logic paths).

**Explicitly required by this doc's sponsor:** every new signal must be unit-testable in isolation, and every new setup type must be backtestable with a real accept/reject gate before it's trusted — not "shipped because it sounds right." We already have one cautionary tale from this session (FLOOR_BOUNCE) of a setup that sounded right and lost money at scale.

---

## 2. PRD — Track A: F&O (confirm & simplify)

No new features. This section documents the cut, so the two tracks don't silently drift back together.

- **Drop:** the "Smart Money Map" / Sector Activity Score tier proposed earlier in the UI mockup pass. F&O setups keep their existing per-stock bias/trigger/SL/target shape (already live) with no sector rollup, no sector filter chip tied to F&O-specific logic.
- **Keep as-is:** IFS, gamma/dealer structure, IV metrics, the 10 setup types (`vanguard/rules/setup_screener.py`, `vanguard/rules/playbook.py`), the FLOOR_BOUNCE/REGIME_SHIFT fixes just shipped.
- **Migrate out:** `fpi_sector_flow` (NSDL) and the planned `industry` per-stock tag move to Track B's data model (§5) — they were being designed for F&O's sector layer, which no longer exists.

---

## 3. PRD — Track B: Cash/Equity (the new build)

### 3.1 What already exists vs. what's new

Checked the actual code before proposing anything new — a meaningful chunk of the "macro structure" half of this ask is **already built and live**:

**Already live (`vanguard/engines/cash_breadth.py` → `daily_cm_breadth` table, exported today):**
advances/declines, A/D ratio, cumulative A/D line, McClellan oscillator, % of the ~2,400-symbol CM universe above 20/50/200 DMA, % overbought (RSI>70) / oversold (RSI<30), new-highs/new-lows, volume A/D ratio, turnover concentration. This is the **macro structure** the ask names — done, no changes needed here.

**Already computed internally, but never persisted per symbol** (`CashMarketBreadthEngine._dma_cache`, only ever aggregated): DMA20/50/200, RSI14 (Wilder's), 52-week high/low, all computed on corporate-action-adjusted close, per symbol, per day — for the full CM universe including all 500 Nifty 500 names (verified: 500/500 covered). This is exactly the **micro structure** raw material — it's sitting in an in-memory pivot table today and thrown away after the aggregate is computed. Promoting it to a persisted per-symbol table is Phase E1 below, and it's exposure, not new math.

**Genuinely new — nothing like this exists yet:**
- Rate of change (ROC) over multiple windows
- A money-flow indicator (volume-weighted price pressure — candidate: Chaikin Money Flow)
- ATR / a volatility-contraction measure (needed for "consolidating")
- "Imbalance" event detection (a flagged large move + volume spike)
- Delivery-ratio-vs-20d-avg at the per-symbol technical level (the *data* exists in `cash_market_prices.parquet`; the *ratio computation* mirrors what `daily_delivery`'s F&O-side export already does, just not built for this table)
- A Track-B setup screener and playbook (the actual "entry point" layer)

### 3.2 Candidate signals (proposed, not approved — same review process as the F&O signal stack got)

| # | Signal | Grain | Definition (proposed) | Status |
|---|---|---|---|---|
| S1 | Trend structure | per stock | Price vs. DMA20/50/200 alignment (above/below each, DMA20 vs DMA50 cross) | Promote existing computation |
| S2 | Momentum | per stock | RSI14 level + ROC over 5d/20d/63d | RSI exists; ROC is new |
| S3 | Money flow | per stock | Chaikin Money Flow (20d) — volume-weighted accumulation/distribution pressure | New |
| S4 | Volume conviction | per stock | Today's volume ÷ 20d average volume | New (trivial — data's already there) |
| S5 | Delivery conviction | per stock | Today's delivery % ÷ 20d average delivery % (same ratio pattern as the F&O side's `daily_delivery` export) | New (same pattern, new table) |
| S6 | Imbalance event | per stock | A day (or short window) where `|ROC|` and volume ratio both exceed a threshold — flagged, not continuous | New — candidate starting numbers: `\|ROC_5d\| ≥ 5.0%` AND `volume_ratio_20d ≥ 1.8×`. **Not backtested, not locked** — same review `MIN_WALL_MIGRATION_PCT` got |
| S7 | Consolidation | per stock | **Normalized** ATR (`NATR14 = ATR14 / adj_close × 100`, not raw ATR — raw ATR isn't comparable across price levels, a ₹5,000 stock and a ₹50 stock aren't on the same scale) dropping into the bottom 20th percentile of its own rolling 63-session window, optionally required to follow an S6 flag within a lookback window | New — direct technical-side analogue of `VOLATILITY_COIL`. Candidate: also require `volume_ratio_20d ≤ 0.8×`. **Not backtested, not locked** |
| S8 | Breadth context | per stock, cross-referenced | Today's `daily_cm_breadth` state (is the whole tape oversold/overbought) joined against the individual stock's S1/S2 — lets a setup ask "is this stock dislocated *from* a healthy tape, or *with* a weak one" | New — this is the literal "micro vs macro" cross-reference the ask names |

**Hard requirements on all of S1–S8 (not optional, not deferred):**
- **Adjusted prices only.** Every indicator above is computed on `adj_close`/`adj_high`/`adj_low` from `cash_breadth.py`'s existing `_build_adjusted_close()` — reused, not reimplemented. Computing ROC or RSI across an unadjusted split/bonus ex-date produces a fake ±80% move that would falsely fire S6 (imbalance) on a day nothing actually happened.
- **S3 (money flow) zero-division guard.** The Money Flow Multiplier's denominator is `(High − Low)`. Indian circuit-filter stocks can lock limit-up/limit-down for a full session with `High == Low == Close` — a real, not theoretical, case (see negative scenario E-X6). Must resolve to `MFM = 0.0`, not throw or emit `NaN`/`inf`.
- **S5 (delivery conviction) needs a second, absolute-quantity ratio, not just the percentage.** `delivery_pct` is bounded 0–100% and can spike on a low-*volume* day even though the actual delivered quantity is small — a real, known distortion in delivery-based reads. Track both `delivery_pct_ratio_20d` (existing plan) *and* `deliverable_vol_ratio_20d = deliverable_qty ÷ 20d avg deliverable_qty` (from the `deliverable_qty` column already sitting in `cash_market_prices.parquet`, unused today). `FIFTYTWO_WEEK_BREAKOUT` and similar should gate on the volume ratio, not the percentage alone.

### 3.3 Candidate setup types (proposed — for the same line-by-line review the 10 F&O setups got, not final)

| Candidate | Composed from | Story |
|---|---|---|
| `MOMENTUM_BUILDUP` | S1 (above rising DMA20/50) + S2 (ROC rising, RSI 50–70) + S4 (volume ratio >1.2) | Trend continuation, not yet overbought |
| `IMBALANCE_CONSOLIDATION` | S6 fired within last N sessions + S7 currently true | Direct technical analogue of VOLATILITY_COIL — "watch for the resolution of a post-move compression," direction undetermined until it breaks |
| `DMA_RECLAIM` | Price crosses back above DMA50/DMA200 after being below + S4/S3 confirmation | Classic reclaim-of-trend setup, volume/money-flow gated so it isn't a low-conviction wiggle |
| `BREADTH_DIVERGENCE_REVERSAL` | S2 oversold (RSI<30) while S8 says the broader tape is *not* oversold | An individual dislocation inside an otherwise healthy market — "buy the dip in a strong tape," not "catch every falling knife" |
| `FIFTYTWO_WEEK_BREAKOUT` | Close ≥ 52w high + S4 + S5 (`deliverable_vol_ratio_20d`, not just the percentage) both confirming | Breakout gated by volume *and* delivery, so a low-conviction new-high on thin turnover doesn't qualify |
| `RSI_EXTREME_REBOUND` | S2 (RSI14 < 25) + S4 (volume_ratio_20d > 1.5×) + S8 (breadth healthy — e.g. >40% of the 500-name universe above their own 50DMA) | Oversold dip *inside* a strong tape, not a falling-knife catch — the breadth cross-reference is what separates this from just "RSI is low" |

Six candidates now, all still placeholders for the review conversation, not a finalized spec — exactly how the F&O side started before `setup_screener.py` was written. None of the threshold numbers anywhere in this table are backtested yet.

---

## 4. TRD — architecture

```
poll_eod.py
  → daily_compiler.py            -- os.remove(db_path); FULL REBUILD of vanguard.duckdb (verified: daily_compiler.py:636-637)
      → session_history.json (F&O universe)
      → setup_screener.py → playbook.py → derive_positions() → daily_setup_positions
  → poll_context.py              -- ADDITIVE, already runs after, never blocks daily_compiler.py
  → equity_compiler.py (NEW)     -- ADDITIVE, must also run strictly AFTER daily_compiler.py, same slot as poll_context.py
      → cash_market_builder.py → cash_market_prices.parquet (already exists, 500/500 Nifty covered)
      → promotes CashMarketBreadthEngine._dma_cache to a persisted per-symbol table
      → computes S2–S8 (new math)
      → equity_session_history.json (NEW — separate store, mirrors session_history.json's shape)
      → equity_screener.py (NEW, mirrors setup_screener.py's pattern: pure functions, one per setup, table-driven tests)
      → equity_playbook.py (NEW, mirrors playbook.py — MUST emit "trigger_strike"/"invalidation_strike" keys, see §1)
      → derive_positions() -- REUSED, unmodified, called a second time with Track B's history
      → CONNECT to the already-rebuilt vanguard.duckdb (never os.remove it) and
        CREATE TABLE IF NOT EXISTS + DELETE/INSERT by date — identical additive
        pattern to fpi_sector_flow.py, not a second full-rebuild pass
      → daily_equity_setup_positions (NEW table, same column shape as daily_setup_positions)
```

**Ordering is load-bearing, not incidental (reviewed 2026-07-21).** `daily_compiler.py` doesn't just rebuild its own tables — `os.remove(db_path)` deletes the *entire DuckDB file*, unconditionally, every run. This is the identical mechanism that wiped the context-layer tables (`daily_fii_dii` etc.) earlier this session during a `--force` rebuild, requiring a backfill to recover. If `equity_compiler.py` ever ran *before* `daily_compiler.py`, or if `daily_compiler.py` gets re-triggered after Track B has already landed its tables for the day, Track B's entire output is silently destroyed. **`equity_compiler.py` must be wired into `poll_eod.py`'s chain strictly after `daily_compiler.py`, in the same additive slot `poll_context.py` already occupies** — this is now a hard requirement, not a design nicety. Track B never calls `os.remove()`; it connects to the file `daily_compiler.py` just finished rebuilding and adds its own tables on top, exactly like `fpi_sector_flow.py` already does for the context layer.

Separate `session_history.json` is still correct for the reason originally stated: Track A's history dict is keyed and shaped around the 249-symbol F&O universe, and a 500-symbol, differently-shaped history has no reason to share that file.

---

## 5. Data model (new tables — nothing existing is altered)

```sql
daily_equity_technicals(
    date, symbol, close, adj_close, volume, delivery_pct, delivery_pct_ratio_20d,
    deliverable_qty, deliverable_vol_ratio_20d,
    dma20, dma50, dma200, rsi14, roc_5d, roc_20d, roc_63d, natr14,
    money_flow_20d, high_52w, low_52w, pct_from_52w_high, pct_from_52w_low,
    volume_ratio_20d
)                                    -- one row per (symbol, date), full 500-name universe.
                                     -- Deliberately NO imbalance_flag/consolidation_flag
                                     -- columns here (reviewed 2026-07-21) — S6/S7's thresholds
                                     -- are explicitly unlocked, subject to E4 tuning, and this
                                     -- table's job is raw metrics only, same role
                                     -- daily_market_structure plays for Track A (stores
                                     -- gex_intensity/spot_chg etc., never a precomputed
                                     -- "coil_flag"). Baking a threshold-derived boolean into
                                     -- the compiler's write path means every threshold tweak
                                     -- during E4 forces a full equity_compiler.py re-run;
                                     -- computing it in equity_screener.py at screening time
                                     -- (mirrors setup_screener.py's stateless functions over
                                     -- SetupInputs) makes retuning free. If the UI later needs
                                     -- to show imbalance/consolidation independent of any setup
                                     -- firing, add it back as an export-time derivation in
                                     -- export_service.py, not a compiler-time stored column.

daily_equity_setups(
    date, symbol, setup_type, bias, trigger_strike, invalidation_strike
)                                    -- mirrors daily_setups exactly

daily_equity_setup_positions(
    symbol, sector /* industry, see below */, setup_type, bias, direction,
    trigger_date, trigger_price, sl_price, target_price, status,
    resolved_date, resolved_price
)                                    -- identical column shape to daily_setup_positions,
                                     -- kept as a SEPARATE table (not a shared table with
                                     -- an asset_class discriminator) so Track A and Track B
                                     -- stats can never accidentally blend — same reasoning
                                     -- as "keep the NSDL section separate"

-- Migrated from the earlier F&O-sector planning pass, now Track B's:
fpi_sector_flow(fortnight_end, sector, equity_net_inv_cr, total_net_inv_cr)   -- already built, live
-- industry tagging (NSE Nifty 500 list, validated 241/249 F&O + 500/500 overall coverage) — not yet built
```

`derive_positions()` is called twice — once per track — each against its own `session_history` file, writing to its own table. No shared code path is modified.

---

## 6. Integration points

1. **`equity_compiler.py` (new script):** parallel to `daily_compiler.py`, reads `cash_market_prices.parquet`, writes `daily_equity_technicals`, `daily_equity_setups`, `daily_equity_setup_positions`. Does not import or touch `daily_compiler.py`.
2. **`vanguard/rules/equity_screener.py`, `vanguard/rules/equity_playbook.py` (new):** structured exactly like the F&O pair — pure functions, one per candidate setup, table-driven unit tests (§8.1) before any backtest is even attempted.
3. **`vanguard/store/export_service.py`:** new payload block(s) once Track B has cleared its backtest gate — explicitly **not** part of this PRD's early phases. UI wiring stays BAU (per the standing constraint) until a concrete UI plan is agreed separately.
4. **Track Record math:** the R-multiple/win-rate computation used for the F&O numbers earlier this session gets factored into a small reusable function (it was ad-hoc pandas so far) so both tracks compute it identically — one function, two callers, no drift.

---

## 7. Negative scenarios & handling

| # | Scenario | Handling |
|---|---|---|
| E-X1 | A Nifty 500 constituent has <252 sessions of history (recent listing) | 52w high/low, DMA200 stay null (matches existing `min_periods` guards in `cash_breadth.py`); setups requiring those signals simply don't fire for that symbol until enough history accrues |
| E-X2 | Corporate action distorts a technical indicator | Reuse `_build_adjusted_close`'s existing CA-adjustment chain — already handles this for the aggregate breadth engine, same adjusted series feeds the per-symbol table |
| E-X3 | A candidate setup type fails its backtest gate | Documented NO-GO (same format as `data/research/ifs_verified_flow_validation.md`), setup is dropped or redesigned — never shipped "because it sounds right" |
| E-X4 | Track A and Track B disagree on a symbol that's in both universes (e.g. F&O says bullish gamma structure, Track B says RSI overbought/momentum exhausted) | v1 shows both, unreconciled, clearly labeled by track. No auto-resolution logic — that's a research question for later, not a v1 rule (same posture as the FII cross-check chip in the context-layer PRD) |
| E-X5 | `equity_compiler.py` run fails mid-way | Independent of Track A entirely — a Track B failure cannot block or corrupt `vanguard.duckdb`'s F&O tables |
| E-X6 | Circuit-filter lock (upper/lower freeze) — a real, not theoretical, Indian small/mid-cap occurrence, full session at `High == Low == Close` | S3 (money flow)'s Money Flow Multiplier denominator is `(High − Low)` → 0 on a locked day. Must resolve to `MFM = 0.0` explicitly, never raise or emit `NaN`/`inf` into `daily_equity_technicals` |
| E-X7 | `equity_compiler.py` runs before `daily_compiler.py` on a given night (ordering violation) | Guard at startup: refuse to run (loud error) if `daily_compiler.py`'s tables for today's date aren't present yet, rather than silently proceeding against a stale or mid-rebuild DB |

---

## 8. Testing approach

### 8.1 Unit tests (offline, fixtures)
- **Indicator golden tests:** each of S1–S8 tested against a small hand-built synthetic OHLCV series (10–30 rows) with a manually verified expected value — same golden-fixture discipline as `test_nse_context.py`, not against live data.
- **Screener table-driven tests:** one test per candidate setup type, flipping exactly one condition across its threshold (same pattern as `test_setup_screener.py`'s `base()` helper) — written *before* the backtest, so semantics are pinned regardless of what the backtest later decides.
- **CA-adjustment reuse test:** confirm the per-symbol technical table's adjusted series matches `cash_breadth.py`'s own adjusted series for the same symbol/date (protects against the two computations silently diverging).

### 8.2 Backtest gate (mandatory, per setup type, before any setup is "trusted")
Reuses the exact methodology already precedented in this codebase (`vanguard/research/ifs_verified_flow_backtest.py`, and the ad-hoc R-multiple check run on the F&O setups earlier this session):
1. Run `derive_positions()` over full history for the candidate setup type.
2. Compute win rate, avg R, total R, same as the F&O Track Record numbers.
3. **Gate:** positive total R at realistic sample size, win rate meaningfully away from a coin flip in the direction the setup claims. A setup that's flat-to-negative (like FLOOR_BOUNCE was) does not ship — either gets root-caused and fixed (like FLOOR_BOUNCE's `pe_interp` gate) or dropped.
4. Result documented as a dated `.md` report under `data/research/`, same format as the existing IFS verified-flow validation doc — a permanent record of what was tried and whether it passed.

### 8.3 Integration test
- Mini-DuckDB end-to-end: fixture prices → `equity_compiler.py` → assert `daily_equity_setup_positions` rows have the same shape/invariants as the F&O side's existing `test_export_api.py::test_setup_positions_present_and_point_in_time_consistent` (status/resolved_date/resolved_price contract).

---

## 9. Rollout phases (each lands only after approval of its diff)

| Phase | Content | Gate |
|---|---|---|
| **E1** | Promote `_dma_cache` (DMA/RSI/52w) to persisted `daily_equity_technicals`; add ROC, volume ratio, delivery ratio (trivial — data already present) | Unit tests green; spot-check 5 symbols' persisted values against a manual calculation |
| **E2** | Add money-flow (CMF), ATR, imbalance/consolidation flags (S3, S6, S7) | Unit tests green; thresholds reviewed with you before locking (mirrors how `MIN_WALL_MIGRATION_PCT` etc. were chosen) |
| **E3** | `equity_screener.py` + `equity_playbook.py` for the candidate setups (§3.3), reviewed line-by-line like the F&O screener was | Screener unit tests green; **setups exist in the DB but are not presented as trustworthy yet** |
| **E4** | Backtest gate (§8.2) run on every candidate setup type | Each setup type individually passes or is dropped/redesigned; documented report per setup, same as the IFS validation precedent |
| **E5** | Equity Track Record + Setup Queue UI section, **only for setups that passed E4** | Still gated by the standing "BAU until UI plan agreed" constraint — this phase doesn't start until that's separately signed off |
| **E6** (later, optional) | Wire `fpi_sector_flow` + `industry` tagging as sector-rotation context on the Equity section | Depends on E5 shipping first |

Estimated effort: E1 ≈ 1 day (mostly exposure, not new math) · E2 ≈ 1–2 days · E3 ≈ 2 days · E4 ≈ 1–2 days (mostly compute + your review of results) · E5 ≈ TBD with UI plan · E6 ≈ 1 day.

---

## 10. Open questions

1. ~~Separate tables vs. a shared table with an `asset_class` discriminator~~ — **resolved: separate** (§5), matching "keep NSDL separate." No dissent on review.
2. **Imbalance/consolidation thresholds (S6/S7)** — candidate starting numbers now logged in §3.2 (`|ROC_5d|≥5%` + `volume_ratio≥1.8×` for S6; NATR14 bottom-20th-percentile + `volume_ratio≤0.8×` for S7). **Explicitly not backtested, not locked** — same E4 gate as every other setup parameter, chosen the same collaborative way `MIN_WALL_MIGRATION_PCT = 2.0` was for Track A.
3. **Candidate setup list (§3.3)** — now six (`RSI_EXTREME_REBOUND` added on review), still almost certainly incomplete or wrong in places. Same "one by one" review the F&O setups got, before E3 starts.
4. ~~Does Track B need its own event-window gate~~ — **resolved: yes**, reusing `corporate_events`, deferred to E5 alongside the UI work.
5. ~~Money-flow indicator choice~~ — **resolved: Chaikin Money Flow (CMF)**, kept as originally proposed. Worth noting the case for CMF over MFI (less distorted by low-volume noise, since it weights by the H/L range rather than classifying whole days as up/down) is reasonable but itself unproven here — if E4's backtest shows CMF isn't pulling weight in a setup, MFI is the fallback to try, not a re-litigation from scratch.
6. **(New, from lifecycle review) Pipeline wiring for `equity_compiler.py`** — must land in `poll_eod.py`'s chain strictly after `daily_compiler.py`, in the same additive slot as `poll_context.py` (§4). This is now a hard architectural requirement, not a phase-E1 detail — flagging it here so it isn't lost before E1 implementation starts.
