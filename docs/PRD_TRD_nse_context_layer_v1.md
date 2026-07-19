# PRD + TRD — NSE Context Layer v1 ("who holds what, and what's tradeable")

**Status:** Approved scope, pre-implementation · **Owner:** Aniket · **Doc type:** combined PRD + TRD + test plan
**Approved datasets (2026-07-17):** Participant-wise OI · F&O ban list + MWPL · India VIX (EOD) · FII/DII cash flows · Results calendar + corporate actions · NSE corporate announcements · Security-wise delivery %
**Explicitly out of scope (v1):** intraday VIX, pre-open auction data, SLB, reference rates, any auto-trading. No code lands without per-phase approval.

---

## 1. Objective

The platform currently *infers* positioning from chain math (walls, GEX, IFS) and reads news via third-party RSS. This layer adds NSE's **measured** context — who actually holds what (participant OI, FII/DII flows, delivery), what is legally tradeable (ban/MWPL), the market's vol regime (VIX), and what is scheduled to happen (results/corporate actions) — so every inferred signal gets an official cross-check and every setup gets an honesty gate.

Design principle carried over from the live layer: **each dataset is an independent, failure-isolated nightly ingestion**; a missing participant-OI file must never delay the bhav compile, and vice versa. The EOD compile remains the referee; this layer only adds context tables and UI annotations.

---

## 2. PRD — features per dataset

### 2.1 Participant-wise Open Interest (the headline feature)
*The official answer to the question IFS approximates.*

- **New HUD panel "Positioning"** (row with Cash Internals): FII / DII / Pro / Client net contracts in index futures (long − short), today vs yesterday, with a 60-session net-FII-index-futures line chart. Index options net (calls−puts, long−short) as a secondary toggle.
- **Command-bar tile:** `FII IDX FUT net −212k ▼18k` — the single most-watched institutional number in Indian derivatives.
- **IFS cross-check chip (dossier):** when the day's IFS polarity for index-heavy names agrees/disagrees with FII futures delta direction, show `IFS ✓ FII-confirmed` / `IFS ⚠ FII-divergent`. Display-only in v1 (no score change) — divergence is information, not an error.
- **Research unlock:** a clean daily institutional-positioning series in DuckDB for `src/research/` (e.g., does FII net-short extreme + SHORT_GAMMA breadth predict squeeze days?).

### 2.2 F&O ban list + MWPL (the honesty gate)
- **Scanner + setup cards:** `⛔ BAN` chip (red) for banned symbols; `▲ MWPL 87%` amber chip when ≥ 80% (near-ban).
- **Setup arming gate:** the trigger engine's armed book **excludes banned symbols** (config `BAN_ARMING = "exclude"`, alternatives `"annotate"`); the Setup Queue still *shows* the card but with the chip and a strike-through on trigger levels — you can see the structure, you just can't trade it.
- **Signal-integrity caveat:** OI flows on near-ban names are partly *forced* (position unwinds to exit ban) — dossier shows a one-line caveat on OI-derived tiles when MWPL ≥ 80%, because IFS/buildup labels are less meaningful under compulsion.
- **Alert:** entering/exiting the ban list appears in the Signal Feed (`ban_enter` / `ban_exit` types).

### 2.3 India VIX (EOD)
- **Command-bar tile:** `VIX 13.42 ▲0.31` colored by percentile of the last 252 sessions (calm/normal/stressed).
- **Breadth panel:** VIX line added to the Net Breadth chart's context (same axis treatment as COIL) — vol regime next to breadth regime.
- **Setup context:** VOLATILITY_COIL and IV_* setup cards show the day's VIX percentile ("coil at VIX p12 — expansion has room"). Display-only in v1; using VIX as a gating input is a research question, not a v1 rule.
- **Bonus (free from the same file):** official closes for all NSE indices — sectoral index levels become available to replace/validate the synthesized sector averages later.

### 2.4 FII/DII daily cash provisional flows
- **Cash Internals tiles:** `FII CASH −1,842Cr` / `DII CASH +2,105Cr` with day-over-day arrows, plus a 60-session cumulative-flow line vs NIFTY (same indexed-overlay treatment as the A/D line).
- **Divergence context:** breadth up + FII selling = distribution flavor; annotation only, no derived score in v1.
- **Caveat shown in UI:** these are *provisional* same-day numbers; NSE/SEBI final numbers can differ — label the tile `provisional`.

### 2.5 Results calendar + corporate actions (forward-looking, deterministic)
- **Dossier + setup cards:** `📅 RESULTS 22 JUL` chip when a symbol has results within the next 5 sessions; `EX-DIV 21 JUL` etc. for corporate actions.
- **Event-window annotation on setups:** setups on symbols inside T−3…T+1 of results get an `EVENT WINDOW` tag — an IV_SPIKE "setup" 2 days before earnings is an event bet, and the card should say so. v1 annotates; suppression of arming is a config flag default-off (`EVENT_ARMING = "annotate"`).
- **Manifest-builder hardening (feeds fullmap TRD N7):** known corporate actions (splits/bonus, symbol changes) become *expected* mapping breaks — the morning parity handshake can distinguish "known corporate action" from "unexplained drift."
- **Briefing:** tomorrow's watchlist (briefing.py) lists tomorrow's results among covered names.

### 2.6 NSE corporate announcements feed (catalyst source upgrade)
- **catalyst_service gains a first-party source:** NSE announcements API alongside the existing RSS feeds — faster, complete, and includes **insider trading / SAST disclosures**, which get their own catalyst category (`INSIDER`) since they're a genuine smart-money footprint the RSS feeds miss.
- Same scoring pipeline (keyword rules / Gemini) — this is a source upgrade, not a new engine. Dedup across sources by (symbol, normalized headline, date).

### 2.7 Security-wise delivery % (cash conviction)
- **Scanner column `DLV%`** (sortable) + dossier tile showing today's delivery % and its ratio to the symbol's own 20-session average (`2.1× avg` — the ratio matters more than the level; large-caps run high delivery structurally).
- **Buildup enrichment (display-only v1):** F&O buildup label + high relative delivery = "conviction" annotation; futures long-buildup on 0.4× delivery = "churn" annotation.

---

## 3. TRD — architecture

```
nightly chain (after poll_eod → daily_compiler):
  poll_context.py ──▶ src/data/nse_context.py (one fetcher per dataset, failure-isolated)
        │                   │ session-cookie client (same dance as poll_eod)
        │                   ▼
        │             data/raw/context/<dataset>/<file>          (immutable raw archive)
        │                   ▼ parse + validate (schema-pinned)
        │             DuckDB context tables (§4)                  (idempotent upserts by date)
        ▼
  build_hud.py additions (join context per symbol/date into the payload)
  briefing.py / catalyst_service (events + announcements)
  run_live.py: load_armed_book( ) joins daily_ban_list (arming gate)
```

- **`src/data/nse_context.py`:** `NseClient` (session bootstrap: hit a referer page for cookies, browser UA, retry with backoff — exactly the proven `poll_eod.py` pattern, factored out) + one `fetch_<dataset>()` per source returning a parsed DataFrame, + `ingest(date)` orchestrator that runs all seven independently and writes a per-dataset status line to `data/live/nightly_<date>.log`.
- **Raw-first discipline:** every fetched file is archived under `data/raw/context/` before parsing (gitignored) — parsers are re-runnable offline, and schema-drift debugging never depends on refetching.
- **Idempotence:** re-running for a date replaces that date's rows (DELETE+INSERT per date per table). Safe to run in a retry loop.
- **Failure isolation:** each dataset wrapped in its own try/except; one failure logs + notifies (alert_sink) and the chain continues. A dataset absent for a day leaves a gap row-set, never a fabricated one; UI renders "—" for missing dates.

### 3.1 Sources (URL templates + formats)

| Dataset | Source (template) | Format | Notes |
|---|---|---|---|
| Participant OI | `archives.nseindia.com/content/nsccl/fao_participant_oi_DDMMYYYY.csv` | CSV, 2 header rows | Rows: Client/DII/FII/Pro/TOTAL × long/short contract counts per product class. Companion `fao_participant_vol_` deferred |
| Ban list | `nseindia.com/api/…` current-day ban + archives `fo_secban` file | CSV/JSON | Ban file is names-only; MWPL % comes from the MWPL/combined-OI report joined on symbol |
| MWPL | NSE MWPL daily report (combined OI vs limit) | CSV | Gives `mwpl_pct` for the ≥80% amber tier |
| India VIX + indices | `archives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv` | CSV | One file = every index official close incl. India VIX — simplest source, no API session needed |
| FII/DII cash | `nseindia.com/api/fiidiiTradeReact` | JSON | Session-gated; one row FII + one DII per day (₹ Cr buy/sell/net) |
| Results calendar | `nseindia.com/api/event-calendar` | JSON | Forward-looking; refreshed nightly, upsert by (symbol, event_date, purpose) |
| Corporate actions | `nseindia.com/api/corporates-corporateActions?index=equities` | JSON | Ex-dates, purpose (div/split/bonus) |
| Announcements | `nseindia.com/api/corporate-announcements?index=equities` | JSON | Nightly batch pull (last 24 h); intraday polling deferred |
| Delivery % | `archives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv` | CSV | Has DELIV_QTY / DELIV_PER per series-EQ row |

**Implementation note (first task of Phase C1):** exact URL shapes and column headers get pinned by a one-time recorded fetch per dataset (the "schema pinning" fixtures of §6.1). Templates above are the known-good candidates; the client's per-dataset config makes a URL change a one-line fix, and every parser fails loudly on header drift (same N10 posture as the manifest builder).

---

## 4. Data model (new DuckDB tables — `daily_market_structure` untouched)

```sql
daily_participant_oi(date, participant,            -- 'FII','DII','PRO','CLIENT'
    fut_idx_long, fut_idx_short, fut_stk_long, fut_stk_short,
    opt_idx_call_long, opt_idx_call_short, opt_idx_put_long, opt_idx_put_short,
    opt_stk_call_long, opt_stk_call_short, opt_stk_put_long, opt_stk_put_short,
    total_long, total_short)                        -- contracts, as published

daily_ban_mwpl(date, symbol, banned BOOLEAN, mwpl_pct DOUBLE,
    combined_oi BIGINT, mwpl_limit BIGINT)          -- one row per F&O symbol per day

daily_index_close(date, index_name, close, prev_close, chg_pct)
                                                    -- 'INDIA VIX' + all NSE indices

daily_fii_dii(date, category,                       -- 'FII','DII'
    buy_cr DOUBLE, sell_cr DOUBLE, net_cr DOUBLE, provisional BOOLEAN DEFAULT TRUE)

corporate_events(symbol, event_type,                -- 'RESULTS','EX_DIVIDEND','SPLIT','BONUS','AGM','OTHER'
    event_date, announced_on, details,
    PRIMARY KEY-ish upsert on (symbol, event_type, event_date))

corporate_announcements(ts, symbol, category,       -- incl. 'INSIDER' for SAST/PIT
    subject, source DEFAULT 'NSE', url)

daily_delivery(date, symbol, traded_qty BIGINT, delivered_qty BIGINT,
    delivery_pct DOUBLE)                            -- series EQ only
```

Derived at export time (build_hud), not stored: participant *net* columns, FII net delta vs prior day, per-symbol `delivery_ratio_20d` (today ÷ trailing-20-session mean), VIX 252-session percentile, "results within 5 sessions" flag.

**Universe mapping:** ban/MWPL/delivery/events tables key on NSE symbol = compiled-universe symbol (same source symbology as the bhav — no Dhan mapping involved). Rows for non-universe symbols are kept (tables are cheap) but only universe rows export to the HUD.

---

## 5. Integration points (each is a separate reviewable change)

> **Seam update (2026-07-19, per docs/ARCHITECTURE.md):** all UI-bound data below
> wires through `vanguard/store/export_service.py` (one payload builder, baked or
> served) — not directly into build_hud. Fetchers live in `vanguard/pipeline/context/`.

1. **build_hud.py:** new payload blocks — `positioning` (participant OI, 60 sessions), `context` per symbol/date (`banned, mwpl_pct, delivery_pct, delivery_ratio, next_event`), `vix` (60 sessions), `fii_dii` (60 sessions). HUD renders per §2; every new panel degrades to hidden when its block is absent (missing dataset ≠ broken deck).
2. **run_live.py / trigger_engine:** `load_armed_book()` gains a ban-list join — banned symbols' setups load into a `suppressed` book (visible in logs, never armed) under `BAN_ARMING="exclude"`.
3. **catalyst_service.py:** `fetch_nse_announcements()` as an additional source + `INSIDER` category + cross-source dedup.
4. **briefing.py:** tomorrow's results among covered names.
5. **manifest builder (fullmap TRD §2):** corporate_events feeds an "expected mapping breaks" allowlist for the morning parity handshake.

---

## 6. Negative scenarios & handling

| # | Scenario | Handling |
|---|---|---|
| X1 | NSE blocks/429s the API endpoints (session dance fails) | Per-dataset backoff + retry (3 attempts, jittered); archive-host CSVs (participant OI, indices, delivery) are static files and rarely blocked — API-dependent datasets (FII/DII, events, announcements) degrade independently. Notification on final failure |
| X2 | File not yet published at run time (NSE posts some reports late evening) | Poller re-runs at +30 min intervals up to a cutoff (23:00 IST); per-dataset `ingested_at` recorded; UI shows "—" until landed |
| X3 | Schema drift (NSE renames columns — they do) | Parsers pin exact expected headers; on mismatch: archive the raw file, log a diff, notify, skip the day. Never guess-map columns (manifest-builder N10 posture) |
| X4 | Holiday / weekend | Calendar-gated; ingestion no-ops on non-trading days. A trading day with zero datasets landed by cutoff = one loud notification (systemic, not per-dataset) |
| X5 | FII/DII provisional → final restatement | v1 stores provisional only, labeled in UI. Restatement reconciliation is out of scope; `provisional` flag reserves the door |
| X6 | Ban list changes intraday (rare additions) | v1 is EOD-truth: the gate uses yesterday-evening's list for today's arming (matches how MWPL bans actually apply — declared for the *next* day). Intraday re-check deferred to the live layer |
| X7 | Symbol mismatches (name changes, new listings) | Non-universe rows ignored at export; universe symbols missing from a landed file are logged per-symbol (the delivery file legitimately lacks suspended names). ≥10% of universe missing → treat as X3 |
| X8 | Announcements flood (result season: hundreds/day) | catalyst_service already caps + scores; NSE source adds `category` server-side filtering (board meetings, results, SAST only by default — configurable) |
| X9 | Event calendar shows postponed/duplicate events | Upsert by (symbol, type, event_date); postponements naturally appear as a new date — old future-dated rows for the same (symbol, type) within ±7 days get superseded flag |
| X10 | Backfill gaps (starting history from zero) | Participant OI, indices, delivery are archive-fetchable for past dates — Phase C1 includes a 1-year backfill script (paced 1 req/2s) so charts and 20d/252d baselines are meaningful on day one. FII/DII + events are forward-only |

---

## 7. Testing approach

### 7.1 Fixtures & unit tests (offline, in `run_tests.py`, `SKIP_LIVE_TESTS` honored)
- **Recorded fixtures:** one real file per dataset committed under `tests/fixtures/nse_context/` (small: single day, truncated to ~20 rows where large). These pin the schema.
- **Parser golden tests** (`tests/test_nse_context_parsers.py`): each parser over its fixture → exact expected rows (counts, dtypes, a spot-checked value per column). Participant OI: TOTAL row equals sum of the four participants (NSE's own invariant — catches silent row drops).
- **Drift tests:** fixture with a renamed column / extra column / empty file / half-written file → parser raises the loud per-dataset error, never returns a partial frame.
- **Idempotence:** ingest the same fixture date twice → row counts unchanged.
- **Derivation tests:** delivery_ratio_20d (incl. <20 sessions history → null, zero-volume days excluded), VIX percentile windowing, "results within 5 sessions" boundary (T+5 yes, T+6 no), ban/near-ban tiering (79.9/80.0/95.0).

### 7.2 Integration tests
- **Mini-DuckDB end-to-end** (`tests/test_nse_context_e2e.py`): fixtures → ingest into a temp DB → `build_hud` export path over it → assert the payload blocks exist, per-symbol context joined correctly, and a symbol missing context renders without the blocks (degradation contract).
- **Arming gate:** temp DB with a banned symbol that has an armed setup → `load_armed_book()` returns it in `suppressed`, not armed; `BAN_ARMING="annotate"` returns it armed with the flag. Both asserted.
- **catalyst dedup:** same story via RSS fixture + NSE fixture → one CatalystEntry.
- **Failure isolation:** monkeypatched fetcher raising for one dataset → other six ingest, status log shows exactly one failure.

### 7.3 Live smoke (manual, market-day evening, before each phase's sign-off)
- `python3 poll_context.py --date today --only <dataset>` per new dataset: fetch real file, schema check passes, row counts sane (participant OI = 5 rows exactly; delivery ≈ 2,000+ rows; indices ≥ 100 rows incl. 'INDIA VIX').
- Cross-validation day one: FII/DII net vs a public aggregator; FII index-futures net vs a published participant-OI tracker; 3 random symbols' delivery % vs NSE quote page. Documented in the phase sign-off note.

### 7.4 UI validation (the screenshot-audit discipline)
- After each phase's HUD change: rebuild, then validate every new tile/chip against direct DuckDB queries (the same field-by-field audit we've been running on existing panels — regime core, breadth, internals — extended to the new panels). Recorded as a checklist in the PR/commit message.
- Stale-data honesty: with a dataset missing for the latest session, the affected tiles must show "—"/hidden — verified by deleting the day's rows in a scratch DB copy.

### 7.5 Backfill validation (C1)
- After the 1-year backfill: continuity checks (no >3-session gaps on trading days), spot-check 5 random historical dates per dataset against archives, and re-run all derivation tests over real history (percentiles/ratios must be finite and sane).

---

## 8. Rollout phases (each lands only after your approval of its diff)

| Phase | Content | Gate |
|---|---|---|
| **C1** | `NseClient` + fetchers/parsers for the three archive-host CSVs (participant OI, indices/VIX, delivery) + tables + backfill script + fixtures/tests | Live smoke on 2 market days; backfill validation (§7.5) |
| **C2** | HUD: Positioning panel, VIX tile, DLV% column + dossier tiles; build_hud payload blocks | UI validation audit (§7.4) |
| **C3** | Ban/MWPL ingestion + arming gate + Signal Feed ban events + OI-caveat chip | Arming-gate integration tests green; one live evening confirms ban file parse against NSE's published list |
| **C4** | FII/DII + results calendar + corporate actions (API-session datasets) + briefing/dossier event chips | 3 consecutive evenings of successful API fetches (session dance is the risk); event-window boundary tests |
| **C5** | NSE announcements → catalyst_service source + INSIDER category + dedup | Dedup test green; one result-season evening without flooding the feed |

Estimated effort: C1 ≈ 2 days · C2 ≈ 1–2 days · C3 ≈ 1 day · C4 ≈ 1–2 days · C5 ≈ 1 day.

---

## 9. Open questions

1. **Ban-gate default:** `exclude` (recommended — never arm the untradeable) vs `annotate`. Default proposed: `exclude`, one config line to flip.
2. **Event-window suppression:** v1 annotates only; do you want a config to auto-suppress arming inside T−1 of results from day one?
3. **Participant-OI derived signal:** v1 is display + research data. Promoting it into IFS/conviction scoring is deliberately deferred until `src/research/` backtests it on the backfilled year — agreed?
4. **Adjacent, previously discussed, not in this scope:** persisting `skew_slope` + true IV-skew columns (from the SBICARD divergence finding). Separate small change; want it bundled into C1's compiler touch or kept standalone?
