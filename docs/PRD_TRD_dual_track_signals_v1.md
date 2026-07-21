# PRD + TRD — Dual-Track Signal Architecture v1 ("derivatives flow" + "cash breadth/technicals")

**Status:** E1–E4 implemented and backtested (2026-07-21). E5 (UI) still gated on a separately-agreed UI plan; E6 (sector/industry context) in progress. See §11 for what actually happened vs. what this doc originally proposed — several findings changed the design mid-flight.
**Owner:** Aniket · **Doc type:** combined PRD + TRD + test/backtest plan
**Governing principle:** no code lands without per-phase approval, same discipline as `PRD_TRD_nse_context_layer_v1.md`. Every new signal must clear a backtest gate before it is trusted, same discipline as the FLOOR_BOUNCE/REGIME_SHIFT fixes and the `ifs_verified_flow_backtest.py` precedent. Held to throughout implementation: every "sounds right" fix (the E4 root-causes in §11) was re-verified against a real backtest run before being trusted, not shipped on reasoning alone.

---

## 1. Objective

The platform splits into two independent, non-blended signal tracks, matching what each dataset actually can and can't see:

- **Track A — F&O (derivatives).** Purely options-chain-derived: IFS, gamma/dealer structure, IV. Universe = the ~249 F&O-eligible symbols. **No sector concept at all** — confirmed scope cut, this session. A stock's derivatives positioning doesn't need a sector lens; the whole point is that it's a single-name, options-chain-specific read.
- **Track B — Cash/Equity (breadth & technicals).** Price-action and volume-derived: moving averages, RSI, rate of change, money flow, delivery conviction, breadth context. Universe = all 500 Nifty 500 names (of which 249 overlap with Track A — those symbols get *both* a Track A and a Track B read, independently, never merged into one score). This is where "sector" belongs going forward — NSDL fortnightly FPI flow (`fpi_sector_flow`, already built) and the NSE-sourced per-stock `industry` tag (`equity_industry_map`, built 2026-07-21, see §11.6) are Track B concepts, not Track A.

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

| Candidate | Composed from | Story | **E4 verdict (2026-07-21)** |
|---|---|---|---|
| `MOMENTUM_BUILDUP` | S1 (above rising DMA20/50) + S2 (ROC rising, RSI 50–70) + S4 (volume ratio >1.2) | Trend continuation, not yet overbought | **PASS** — N=4,115, WR=62.5%, total_r=+86.61R |
| `IMBALANCE_CONSOLIDATION` | S6 fired within last N sessions + S7 currently true | Direct technical analogue of VOLATILITY_COIL — "watch for the resolution of a post-move compression," direction undetermined until it breaks | **PASS** — N=199, WR=61.3%, total_r=+84.02R, after two rounds of fixes (§11.2–11.4) |
| `DMA_RECLAIM` | Price crosses back above DMA50/DMA200 after being below + S4/S3 confirmation | Classic reclaim-of-trend setup, volume/money-flow gated so it isn't a low-conviction wiggle | **DROPPED** — NO-GO at first backtest (−206.66R), entry-quality tightening made it *worse* (−219.21R); the underlying thesis doesn't hold in this data. Deleted, not disabled (§11.1) |
| `BREADTH_DIVERGENCE_REVERSAL` | S2 oversold (RSI<30) while S8 says the broader tape is *not* oversold | An individual dislocation inside an otherwise healthy market — "buy the dip in a strong tape," not "catch every falling knife" | **Leaning NO-GO** — every trigger depth tested that preserves genuine "up" direction comes back net negative and gets *worse* with more N (N=6,998 → −961.9R). Left in place at its original tiny-N settings, not dropped, pending a decision (§11.5) |
| `FIFTYTWO_WEEK_BREAKOUT` | Close ≥ 52w high + S4 + S5 (`deliverable_vol_ratio_20d`, not just the percentage) both confirming | Breakout gated by volume *and* delivery, so a low-conviction new-high on thin turnover doesn't qualify | **PASS** — N=2,087, WR=56.8%, total_r=+316.25R, the strongest of the five |
| `RSI_EXTREME_REBOUND` | S2 (RSI14 < 25) + S4 (volume_ratio_20d > 1.5×) + S8 (breadth healthy — e.g. >40% of the 500-name universe above their own 50DMA) | Oversold dip *inside* a strong tape, not a falling-knife catch — the breadth cross-reference is what separates this from just "RSI is low" | **Leaning NO-GO** — same failure mode as BREADTH_DIVERGENCE_REVERSAL: widening the trigger while keeping direction="up" only makes total_r more negative (§11.5) |

Started as six placeholder candidates; after E4, three PASS, one was dropped (DMA_RECLAIM), two are left in place but data now suggests they don't have a genuine bullish edge as designed. See §11 for the full history of what was tried on each and why.

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
    volume_ratio_20d, range_high_10d
)                                    -- one row per (symbol, date), full 500-name universe.
                                     -- range_high_10d (added post-E4, see §11.3): trailing
                                     -- IMBALANCE_LOOKBACK_SESSIONS rolling max of adj_high,
                                     -- feeds IMBALANCE_CONSOLIDATION's re-anchored trigger.
                                     -- IMPORTANT (§11.2): every downstream consumer
                                     -- (equity_setups_pipeline.py) reads adj_close, NOT the
                                     -- raw close column, as "today's spot" — dma20/dma50/
                                     -- natr14/high_52w/range_high_10d are all computed on the
                                     -- CA-adjusted series, and 143/2751 symbols had a real
                                     -- corporate action in the observed window where raw and
                                     -- adjusted close diverge by up to ~17x. The raw close
                                     -- column stays for reference/display only.
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
equity_industry_map(as_of_date, symbol, company_name, industry, isin)         -- built 2026-07-21 (E6, §11.6)
                                     -- symbol -> NSE Industry classification, one snapshot per
                                     -- as_of_date (re-fetched idempotently per calendar day via
                                     -- poll_context.py). Feeds daily_equity_setup_positions.sector
                                     -- (previously always NULL) via equity_compiler.py's
                                     -- latest_symbol_industry_map() lookup. Covers exactly the 500
                                     -- Nifty 500 constituents by design -- positions on symbols
                                     -- outside that index (cash_market_prices.parquet's broader
                                     -- ~2,751-symbol universe) correctly stay NULL, not fabricated.
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

| Phase | Content | Gate | **Status** |
|---|---|---|---|
| **E1** | Promote `_dma_cache` (DMA/RSI/52w) to persisted `daily_equity_technicals`; add ROC, volume ratio, delivery ratio (trivial — data already present) | Unit tests green; spot-check 5 symbols' persisted values against a manual calculation | **Done** |
| **E2** | Add money-flow (CMF), ATR, imbalance/consolidation flags (S3, S6, S7) | Unit tests green; thresholds reviewed with you before locking (mirrors how `MIN_WALL_MIGRATION_PCT` etc. were chosen) | **Done** |
| **E3** | `equity_screener.py` + `equity_playbook.py` for the candidate setups (§3.3), reviewed line-by-line like the F&O screener was | Screener unit tests green; **setups exist in the DB but are not presented as trustworthy yet** | **Done** — two external code reviews caught a schema mismatch and a threshold-location issue, both verified against real code before fixing |
| **E4** | Backtest gate (§8.2) run on every candidate setup type | Each setup type individually passes or is dropped/redesigned; documented report per setup, same as the IFS validation precedent | **Done** — see §3.3's verdict column and §11 for the full history (risk-inflation root cause, CA-adjustment bug, direction-inversion bug, all found and fixed via this gate) |
| **E5** | Equity Track Record + Setup Queue UI section, **only for setups that passed E4** | Still gated by the standing "BAU until UI plan agreed" constraint — this phase doesn't start until that's separately signed off | **Not started** — UI plan being drafted separately |
| **E6** (later, optional) | Wire `fpi_sector_flow` + `industry` tagging as sector-rotation context on the Equity section | Depends on E5 shipping first | **Data layer done, ahead of E5** — `equity_industry_map` built and wired into `daily_equity_setup_positions.sector` (§11.6); UI-side sector-rotation display still waits on E5/the UI plan |

Estimated effort: E1 ≈ 1 day (mostly exposure, not new math) · E2 ≈ 1–2 days · E3 ≈ 2 days · E4 ≈ 1–2 days (mostly compute + your review of results) · E5 ≈ TBD with UI plan · E6 ≈ 1 day.

---

## 10. Open questions

1. ~~Separate tables vs. a shared table with an `asset_class` discriminator~~ — **resolved: separate** (§5), matching "keep NSDL separate." No dissent on review.
2. ~~Imbalance/consolidation thresholds (S6/S7)~~ — **resolved, still unlocked**: current live values are `MOMENTUM_MIN_VOLUME_RATIO=1.2`, `MOMENTUM_RSI_LOW/HIGH=55/70`, `MOMENTUM_MIN_ROC_5D=3.0`, `CONSOLIDATION_NATR_PERCENTILE=20`, `CONSOLIDATION_MAX_VOLUME_RATIO=0.8` (`vanguard/config/equity.py`), all retuned once against real winner/loser diagnostics per §11. Explicitly still in-sample only, no out-of-sample/train-test split has been run.
3. ~~Candidate setup list (§3.3)~~ — **resolved via E4**: DMA_RECLAIM dropped, two setups leaning NO-GO, three PASS. See §3.3's verdict column and §11.
4. ~~Does Track B need its own event-window gate~~ — **resolved: yes**, reusing `corporate_events`, deferred to E5 alongside the UI work.
5. ~~Money-flow indicator choice~~ — **resolved: Chaikin Money Flow (CMF)**, kept as originally proposed. Worth noting the case for CMF over MFI (less distorted by low-volume noise, since it weights by the H/L range rather than classifying whole days as up/down) is reasonable but itself unproven here — if E4's backtest shows CMF isn't pulling weight in a setup, MFI is the fallback to try, not a re-litigation from scratch.
6. ~~Pipeline wiring for `equity_compiler.py`~~ — **resolved: built as specified**, `_ordering_guard()` in `equity_compiler.py` refuses to run if `daily_market_structure`'s latest date is behind cash data's latest date, satisfying E-X7.
7. **(New) Should BREADTH_DIVERGENCE_REVERSAL / RSI_EXTREME_REBOUND be dropped, left as documented dead-ends, or reworked as short-side setups?** — open, see §11.5. Not decided yet; both are currently left in place at their original (very low N, likely non-viable) settings rather than either dropped or fixed.
8. **(New) IMBALANCE_CONSOLIDATION's entry/exit parameters (`trigger_mult=0.05`, `sl_mult=0.25`) are the result of an in-sample parameter sweep** (§11.4), not an out-of-sample-validated result. A train/test split was proposed and not yet done — worth doing before this setup is trusted with real capital, even though it's already cleared the E4 gate.
9. **(New) E6 sequencing changed** — originally scoped as strictly after E5 (§9), now starting before E5 since the UI plan isn't ready yet but the sector/industry data work can proceed independently.

---

## 11. E4 findings — what actually happened (post-implementation, 2026-07-21)

This section exists because several things this PRD assumed turned out to be wrong or incomplete once real backtests ran against real data. Kept as a permanent record — same spirit as `data/research/ifs_verified_flow_validation.md` — so nobody re-discovers these the hard way.

### 11.1 DMA_RECLAIM — dropped, not fixed
First backtest: NO-GO at −206.66R. The same winner/loser diagnostic that successfully retuned MOMENTUM_BUILDUP's thresholds was applied here too — tightening entry quality (volume ratio, a ROC_20d trend-context floor) made it *worse* (−219.21R), the opposite of every other setup's response to the same treatment. Read as a real signal, not noise: the underlying thesis (DMA50 reclaims predict continuation) doesn't hold in this data — classic bull-trap-at-the-average behavior. Function, config constants, and tests fully deleted rather than left disabled.

### 11.2 The risk-inflation bug (root cause of MOMENTUM_BUILDUP's first NO-GO)
`derive_positions()` sizes `target_price`/`sl_price` off the **nominal** trigger/invalidation *levels* computed by the playbook, but records `trigger_price` as the **actual spot** on the day the position opens — and there is no "pending order" state (a snapshot from an earlier day is never reconsidered; a position only opens on a day the screening condition is true again AND that same day's close already clears that same day's trigger). When a trigger anchor lags price (a moving average during a fast move), the actual entry can overshoot the nominal trigger substantially, inflating realized risk far beyond what the reward:risk ratio was sized for. Quantified directly: F&O's structural anchors (walls, gamma flip) overshoot only 0.2–1.5% median; Track B's original DMA-based anchors overshot 5–80%+ on exactly the fast-moving days these setups screen for.

**Fix:** size `trigger_strike`/`invalidation_strike` offsets as multiples of each stock's own NATR14 (`NATR_TRIGGER_MULT`/`NATR_SL_MULT` in `vanguard/config/equity.py`) instead of a fixed percentage, so a volatile stock's band widens with it. This alone flipped MOMENTUM_BUILDUP from NO-GO to PASS. It narrowed but did not eliminate overshoot for the other setups (see 11.3).

### 11.3 IMBALANCE_CONSOLIDATION — two more rounds after the NATR fix
Even after 11.2's fix, IMBALANCE_CONSOLIDATION's dma50-anchored trigger left a median ~10% entry overshoot — 79% of its "TARGET_HIT" rows had *already* overshot the nominal target on the day of entry, because dma50 is the slowest of the five anchors and this setup specifically screens for a fast break away from a quiet range. Dropping `DMA_RECLAIM` from `EQUITY_SETUP_PRIORITY` (11.1) then flipped IMBALANCE_CONSOLIDATION from PASS to NO-GO purely via priority reassignment — previously-contested symbol/days that DMA_RECLAIM used to win as primary flowed to IMBALANCE_CONSOLIDATION once DMA_RECLAIM was removed, exposing that the five (now four) setups' backtest stats are entangled by priority-based mutual exclusivity, not independently measured.

Root fix: re-anchored **both** trigger and invalidation to `range_high_10d_prev` (yesterday's trailing 10-session high — the actual consolidation range ceiling), instead of dma50. First attempt anchored only the trigger this way, leaving invalidation on dma50 — that silently flipped ~2/3 of positions to direction="down" (a bullish-labeled setup quietly becoming an inferred short), because `_direction()` reads direction purely from trigger-vs-invalidation ordering and the two independent anchors broke that ordering on a majority of days. Reverted to a single shared anchor (same pattern every other setup already used) once this was caught. Result: PASS, N=291, total_r=+32.02R.

A second, unrelated bug was found in the SAME re-anchor work: `equity_setups_pipeline.py` fed `row["close"]` (raw, unadjusted) into `EquitySetupInputs`/`derive_positions()` as "today's spot," while every anchor (dma20/dma50/natr14/high_52w/range_high_10d) is computed on the CA-adjusted series. For any symbol with a real corporate action in the observed window (143/2,751 symbols), this produced up to ~17x scale mismatches between the recorded entry price and the anchors it was being compared against — the actual cause of a batch of >500%-overshoot IMBALANCE_CONSOLIDATION positions that had looked like "illiquid microcap noise" until traced to a specific symbol (RNBDENIMS) and its raw-vs-adjusted close ratio. Fixed by switching to `adj_close` throughout the pipeline. This improved *every* setup, not just IMBALANCE_CONSOLIDATION (MOMENTUM_BUILDUP +78.47R→+86.61R, FIFTYTWO_WEEK_BREAKOUT +257.59R→+316.25R).

### 11.4 IMBALANCE_CONSOLIDATION entry/exit retune (in-sample, not yet out-of-sample validated)
Post-fix, swept the `range_high_10d` lookback window (5/10/15/20/30 sessions) — 10 (the original default) is near-optimal for per-trade quality; shorter trades more often for similar quality, longer decays. A "narrow range" filter on top of the existing NATR-percentile check was tested and explicitly rejected: total_r fell monotonically as the range was forced tighter, turning net negative below ~15% width — documented in `vanguard/config/equity.py` so it isn't retried without new evidence.

Swept `NATR_TRIGGER_MULT`/`NATR_SL_MULT` jointly (~20 combinations): `sl_mult=0.25` is a genuine local optimum confirmed from both directions (tighter whipsaws, looser decays). `trigger_mult=0.0` (bare "close ≥ range high") scored marginally higher than `0.05` but only once, at the exact edge of the tested range — the signature of an in-sample fluke rather than a real optimum — so `trigger_mult=0.05` was chosen instead: independently rediscovered as the best point in two separate sweep passes, and it preserves the NATR-scaled-confirmation design principle that `0.0` abandons. **Neither value has been validated out-of-sample** — this is flagged explicitly in the config and open question #8 above.

### 11.5 BREADTH_DIVERGENCE_REVERSAL / RSI_EXTREME_REBOUND — likely no genuine bullish edge
Both setups fire their screening condition thousands of times (BREADTH_DIVERGENCE_REVERSAL: 19,308 primary-fired symbol-days) but produced almost no tracked positions (12) — not because the setups are rare, but because the trigger sat far closer to the anchor (dma20) than the screening condition ever leaves price. Median distance on a firing day is ~8.9% below dma20 for BREADTH_DIVERGENCE_REVERSAL, while the trigger only reached ~1% below it — a near-impossible same-day round trip given `derive_positions()` has no multi-day "pending order" state.

Widening the trigger alone (without widening the SL to match) hit the exact direction-inversion bug from §11.3 again — trigger ended up below invalidation, flipping direction to "down." When corrected (widening trigger and SL together, confirmed direction="up" on every row), the result was unambiguous: total_r gets **monotonically worse** as N grows, from −11.6R (N=11) to −961.9R (N=6,998) for BREADTH_DIVERGENCE_REVERSAL, and similarly for RSI_EXTREME_REBOUND. This isn't a data-starvation problem — "buy the bounce" on a stock that's deeply oversold and still actively declining does not work in this dataset at any tested trigger depth. Both are left in place at their original, near-untriggerable settings rather than dropped, pending a decision (open question #7). Note: the *inverted* (accidentally short) version of BREADTH_DIVERGENCE_REVERSAL looked strong (+1,177R) — a short-side "oversold continuation" thesis may have real edge, but that's an unvalidated, differently-scoped idea (bearish labeling, its own screening logic, its own review), not a fix to this setup.

### 11.6 E6 — industry tagging built (2026-07-21)
Fetched NSE's `ind_nifty500list.csv` (Company Name, Industry, Symbol, Series, ISIN Code — 500 rows, 20 distinct Industry values) and cross-checked it against `fpi_sector_flow`'s live NSDL sector list before building anything: **18/20 category names are byte-identical**; the other 2 differ only by a missing comma ("Oil Gas & Consumable Fuels" vs "Oil, Gas & Consumable Fuels", and similarly for Media/Entertainment/Publication). NSDL's few extra buckets (Sovereign, Others, Utilities, Forest Materials) don't apply to individual equities and are expected to have no match. This confirmed the taxonomy match claimed during E6's earlier feasibility check — verified against live data this time, not just asserted.

Built `vanguard/pipeline/context/industry_map.py` (mirrors `fpi_sector_flow.py`'s shape: fetch → cache raw → parse → idempotent DDL/insert), normalizing the 2 comma-variant names so a plain join needs no separate mapping table. New table `equity_industry_map(as_of_date, symbol, company_name, industry, isin)`, snapshotted per calendar day (Nifty 500 constituents reconstitute periodically, not daily). Wired into `poll_context.py` alongside `fpi_sector_flow`'s ingestion, and into `equity_compiler.py` via `latest_symbol_industry_map()`, replacing the `sector=None` placeholder in `daily_equity_setup_positions` with a real lookup.

Live run: 500/500 Nifty 500 symbols tagged; 454 of them have at least one `daily_equity_setup_positions` row. The remaining ~1,668 distinct symbols in that table (out of 2,122 total) sit outside the Nifty 500 index — `cash_market_prices.parquet`'s universe is broader (~2,751 symbols, all NSE EQ-series, not just the 500 index constituents) — and correctly stay `sector = NULL` rather than being guessed. UI-side sector-rotation display (grouping/filtering the Equity section by this tag) is still E5 work, gated on the UI plan.
