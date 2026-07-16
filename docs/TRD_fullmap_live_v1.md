# TRD — Full-Map Live Coverage v1

**Pairs with:** [PRD_fullmap_live_v1.md](PRD_fullmap_live_v1.md) · requirement IDs (C*, N*, U*, F*) refer to that document.
**Principle carried over from M0–M2:** reuse the EOD math verbatim so parity is always checkable; the EOD compile is the referee, never the live path.

---

## 0. Pre-implementation validation (run 2026-07-16, offline)

| # | Assumption | Result |
|---|---|---|
| V1 | Bhav ↔ instrument-master mapping (manifest builder join) | **PASS** — 0/12,052 strikes unmapped on the 2026-07-15 bhav; final manifest 13,122 instruments (12,692 opt + 215 spot + 215 fut) packs into exactly 3 connections; bounds check passes |
| V2 | Per-row `brentq` too slow at full-map scale | **CONFIRMED** — 5.6 s for 12.2k rows (19% of the 30 s cycle, before greeks/walls) |
| V3 | Vectorized Newton meets the < 2 s budget | **PASS** — 4–11 ms (≈1,300× faster); 98.4% of rows converge < 1e-4 vs brentq; the 1.6% non-converged tail (near-zero-vega rows) **requires** the §4 brentq fallback — measured ≈ 90 ms, acceptable |
| V4 | Snapshot v2 ≤ 150 KB | **PASS** — 97 KB fully populated (215 symbols × quotes/flow/structure + 40 events) |
| V5 | Tick journal replayable for the §8 harness | **PASS with fix** — parquet parts readable (~1.15 M ticks on 2026-07-16), but schema is inferred from tick dicts and **carried no `oi` column all day**; journal must write an explicit stable schema incl. `oi` |
| V6 | WS Quote mode (17) delivers OI | **FAIL — design change.** `dhanhq` SDK inspection: the Quote packet has **no OI field**; OI exists only in Full-mode packets and standalone `OI Data` packets, and zero OI ticks arrived in the Quote-mode session of 2026-07-16. **All F&O instruments must subscribe in `MODE_FULL` (21)** (§3). Spot equities/indices stay Quote |
| V7 | Previous Close packet carries prev OI (handshake baseline) | **PASS** — SDK `process_prev_pause`/pclose parser exposes `prev_OI` |

**Remaining live-session checks (first F1 session, before F2 begins):**
1. Full-mode OI actually flows for futures + options at our subscription scale (V6 fix verified end-to-end); measure OI update cadence vs the ~3-min NSE floor.
2. Dhan accepts 3 × ~4.4k Full-mode subscriptions on one token without server-side throttling; measure real tick rate at open (§8 burst budget).
3. Option-Chain REST response schema + real pacing headroom for the sweeper (one paced probe is enough).
4. `OI Data` packet behavior in Full mode (dedupe if OI arrives via both paths).

---

## 1. Architecture

```
                       nightly                          09:10 daemon start
  bhav ──▶ daily_compiler ──▶ DuckDB ──▶ manifest_builder ──▶ ws_manifest.parquet
                                              │ (12k strikes + ATM buffer + spot/fut)
                                              ▼
   Dhan WS ×3 conns ──▶ feed_handler (per conn) ──▶ state_store (seg,sid keyed)
        ▲                                             │        │
        │ resubscribe on reconnect                    │        ├──▶ tick_journal
   conn_supervisor                                    │        │
                                                      ▼        ▼
   Dhan REST ──▶ chain_sweeper ──────────────▶ oi_diff_engine  live_compute (30s, all 215)
   (token bucket, ≤60min rotation)             (Δ vs bhav)     vectorized greeks → walls/GEX/regime
        │                                             │        │
        └── morning parity handshake ──▶ quarantine ──┤        │
                                                      ▼        ▼
                                        snapshot writer (5s) ──▶ live_snapshot.json
                                                      │            + live_structure_<d>.parquet
                                                      ▼            + chain_sweep_<d>.parquet
                                        bridge :8787 ──▶ HUD (session state machine)
```

New modules: `manifest_builder.py`, `conn_supervisor` (inside feed layer), `chain_sweeper.py`, `oi_diff_engine.py`, vectorized path in `greeks_engine.py`. Everything else is modification of existing `src/live/` modules.

## 2. Manifest builder (`scripts/build_ws_manifest.py`) — C1, C2, N10, N11

Runs as the last step of the nightly chain (PRD §7).

**Input:** latest bhav in `data/raw/`, `data/live/instrument_master.parquet` (refreshed each morning from the Dhan scrip master), `daily_setups` (armed names), config.

**Algorithm:**
1. Parse bhav option rows (`FinInstrmTp ∈ {STO, IDO}`). Schema-validate column names; on mismatch emit a schema diff report and **reuse the previous manifest** with `stale_manifest=true` (N10).
2. Rank strikes by `OpnIntrst` descending; take the prefix reaching `OI_COVERAGE = 0.995` of total OI (~12k on current data).
3. Add zero-OI buffer: for every one of the 215 names, ±`ATM_BUFFER = 5` strikes around prior close, front expiry (both sides), if not already selected.
4. Add a **wider ATM window** (±12 strikes, `ARMED_WINDOW`) for every name with an armed setup. *(Amended during build: 186/215 names arm daily on this platform, so "armed" is not a hot list and the originally-specified full-chain rule blows the size bounds — measured 31.7k. Trigger/invalidation levels are near ATM by construction, so the window carries the same information.)*
5. Rollover rule (N6): if front expiry ≤ T+1, select from *next* expiry as well for that name (both series live on expiry eve; dead series dropped at expiry date).
6. Map `(symbol, expiry, strike, type)` → `(segment, security_id)` via instrument master. **Unmapped rows are logged, never silently dropped**; > 1% unmapped aborts to previous manifest (mapping drift = corporate-action signal).
7. Emit `data/live/ws_manifest_<date>.parquet` with columns `seg, sid, symbol, expiry, strike, otype, oi_baseline, close_baseline, reason ∈ {oi_set, atm_buffer, armed, rollover}` + a JSON coverage report (counts, % OI covered, conns needed).
8. Bounds check (N11): abort < 8,000 or > 15,000 rows (retry at 99% threshold before aborting high).

The manifest **is** the OI baseline: `oi_baseline`/`close_baseline` per strike replaces the `greeks.csv` seed (which currently reads a 20-row TESTCO fixture — bug, must die in F1).

## 3. Feed layer — multi-connection (C1, N2, N3, N4)

- **Subscription modes (V6):** all F&O instruments (options + futures) subscribe in `MODE_FULL` (21) — the Quote packet carries no OI, so Quote-mode F&O silently starves the diff engine (observed 2026-07-16). Spot equities/indices stay `MODE_QUOTE`. `normalize()` already parses Full packets; add dedupe if OI arrives via both Full and `OI Data` packets (live check #4).
- `SubscriptionManager.pack_connections()` (exists) splits the manifest into ≤ 5,000-instrument connections; target ≤ 3 data conns, conns 4–5 reserved.
- **One `FeedHandler` thread per connection**, all writing to the shared `StateStore`.
  **Thread-safety argument (must hold, documented in code):** each instrument lives on exactly one connection, so per-key state (incl. bar aggregation) has a single writer; `dict` get/set is atomic under the GIL; readers (compute/snapshot threads) tolerate momentary staleness. No locks on the hot path. Cross-checked by a debug assertion that a key's writing thread never changes.
- `conn_supervisor`: per-conn watchdog — reconnect with exponential backoff + jitter; on reconnect, resubscribe that conn's chunk (100 instruments/message) and re-request prev-close packets. Publishes `conns_alive/conns_target` into the snapshot (drives DEGRADED, U1/N2).
- **Instance lock (N4):** `data/live/daemon.pid` with liveness check; second instance exits with a loud message.
- Option instruments get a slim `SecurityState`: **no 400-bar deque** (bars exist only for spot/futures where the trigger engine needs them). Memory: ~12.5k options × ~200 B + 430 spot/fut with bars ≈ **< 10 MB** — trivial.
- Estimated tick load: deep strikes tick rarely; near-ATM dominates. Envelope: open-auction burst ~3–5k ticks/s worst case, steady state < 1k/s. `normalize()` is dict-ops only; measured budget in §8.

## 4. Vectorized greeks (`greeks_engine.py`) — F0 gate

- New `implied_vol_vectorized(df)`: Newton–Raphson on vega with clamped domain `[0.001, 5.0]`, **warm-started from the previous cycle's IV per instrument** (intraday moves are small → 1–2 iterations). Fallback: rows failing to converge in 8 iterations fall back to scalar `brentq`; still-failing rows get `IV=NaN` and are excluded from IV aggregates but keep OI weight for walls (N8 sibling).
- Alternative accepted: `py_vollib_vectorized` (Jäckel "Let's Be Rational") if the dependency is acceptable; interface identical either way.
- `process_dataframe()` keeps its exact signature and column contract; a `method` flag selects scalar vs vectorized. **EOD compile switches to vectorized only after F0 parity** (|ΔIV| ≤ 1e-4 vs brentq on a full historical chain; greeks within float tolerance).
- Perf target: 12,500 rows end-to-end (IV + all greeks) **< 2 s** on the M-series laptop; leaves ≥ 28 s headroom in the 30 s cycle.

## 5. OI diff engine (`src/live/oi_diff_engine.py`) — the bhav comparison

- Holds the manifest's `oi_baseline` per `(seg,sid)`.
- On each compute cycle: `ΔOI = live_oi − oi_baseline` per strike; aggregates per symbol: `delta_ce_oi, delta_pe_oi, live_pcr, live_total_oi`, futures ΔOI, and per-strike ladder deltas for the dossier.
- Buildup classification (long/short buildup, unwinding, short covering) = futures ΔOI × futures price change, mirroring [oi_buildup.md](../oi_buildup.md) semantics so intraday and EOD labels agree.
- Strikes with no live OI tick yet report `ΔOI = 0` with `age = null` (unknown ≠ unchanged; UI renders em-dash, C5).
- New-strike case: live OI on a strike absent from the baseline → baseline 0, flagged `born_today` (feeds `COVERAGE_GAP` when sweep-detected outside the WS set, C3/N13).

## 6. Chain sweeper (`src/live/chain_sweeper.py`) — thin, C4, N9

- Single token bucket at the documented 1 req/3 s shared by *all* REST option-chain calls; the sweeper only consumes idle tokens.
- Rotation: round-robin over 215 names; priority queue jumps names with armed setups or spot within 1% of a wall (refresh ≤ 10 min); guaranteed full rotation ≤ 60 min.
- Each response: full-chain rows → `chain_sweep_<date>.parquet` (append) → diff vs WS set → material OI outside the set (> 0.5% of side OI) raises `COVERAGE_GAP` (coalesced 1/symbol/15 min, N13).
- 429 → exponential backoff + jitter; sweeper failure degrades silently (safety net, never a dependency).
- **Morning parity handshake (F3, N7, U8):** between 09:15–09:45 the sweeper front-loads one pass of the full universe; per strike compare live baseline (prev-close packets + first sweep) vs bhav `OpnIntrst`/close. Output `parity_open_<date>.json`: per-symbol match rate. Symbol < 98% match → **quarantine set** for the day: excluded from live structure, ΔOI, and alerts; HUD shows `⚠ MAP` chip (U8). Quarantine is per-day; a persistent quarantine (≥ 2 days) is a mapping bug ticket.

## 7. live_compute changes — all 215 names

1. Catalog = full WS manifest (not `select_covered_names` top-60) — `TOP_N_LIVE_OPTIONS` retired.
2. **Staleness gate (N8):** exclude a strike's IV when `spot_tick_ts − option_tick_ts > IV_STALENESS_SECS` (default 300 s) *or* option LTP predates a > 0.5% spot move; the strike keeps OI weight for walls. Prevents dead-strike IV from moving `iv_avg`/`IV_EVENT`.
3. **T→0 guard (N6):** for expiry-day series, floor `T` at 30 minutes and cap per-strike |GEX| contribution at a configurable multiple of the next-largest strike; near-expiry gamma spikes must not teleport walls.
4. Cycle budget: greeks < 2 s + walls/GEX/regime < 1 s + diff < 0.5 s ⇒ **< 5 s total** (PRD §8); cycle overrun logs a `SLOW_CYCLE` warning and skips to fresh data (never queues).
5. Per-cycle output appended to `data/live/live_structure_<date>.parquet` (symbol, ts, walls, flip, gex, iv, regime, live_pcr, Δ aggregates) — the research layer's intraday dataset.

## 8. Performance budgets (measured, not assumed)

| Path | Budget | Verification |
|---|---|---|
| `normalize()` + store write per tick | < 20 µs | micro-bench in tests |
| Open-auction burst | 5k ticks/s sustained 60 s, journal lag < 5 s | replay harness at 10× speed |
| Compute cycle (12.5k strikes, 215 names) | < 5 s | timed in-cycle, logged |
| Snapshot serialize + write | < 100 ms | timed |
| Daemon RSS | < 500 MB | logged hourly |

Replay harness: feed recorded journals (`data/live/ticks_YYYYMMDD/`) through the full stack off-hours — the primary test vehicle for burst behavior, state transitions, and parity logic without a live session.

Journal schema fix (V5): `TickJournal` must write an **explicit, stable column set** (`seg, sid, ts, ltp, vol, atp, oi`) rather than inferring columns from whichever tick dicts happen to be in a flush batch — otherwise OI-bearing replays are impossible and parquet parts have inconsistent schemas across the day.

## 9. Snapshot schema v2 & bridge

```jsonc
{
  "ts": 1789538700.1,            // writer clock (loop alive)
  "feed_ts": 1789538699.8,       // last tick (feed alive) — liveness judge (U1)
  "session_state": "LIVE",       // PRE_OPEN | LIVE | DEGRADED | CLOSED_FROZEN — server-computed
  "session_date": "2026-07-17",
  "eod_version": "2026-07-16",   // latest compiled EOD date → HUD EOD-REFRESH toast
  "market_open": true,
  "coverage": {"subscribed": 12480, "target": 12480, "conns_alive": 3, "conns_target": 3,
                "oi_covered_pct": 99.5, "quarantined": ["XYZ"]},
  "n": 214,
  "quotes":    {"SYM": {"ltp": 0, "chg": 0, "oi": 0, "vol": 0, "age": 2.1}},
  "flow":      {"SYM": {"d_ce_oi": 0, "d_pe_oi": 0, "live_pcr": 0, "fut_doi": 0,
                          "buildup": "LONG_BUILDUP", "oi_age": 140}},
  "structure": {"SYM": {"call_wall": 0, "put_wall": 0, "gamma_flip": 0, "gex": 0,
                          "gex_intensity": 0, "iv_avg": 0, "iv_skew": 0,
                          "gamma_regime": "LONG_GAMMA", "computed_at": 0}},
  "structure_validated": true,
  "events": [ /* trigger_engine + live_compute + COVERAGE_GAP, newest first */ ]
}
```

- Symbol-level only (~215 × 3 blocks ≈ 100–150 KB) — per-strike ladders are **not** in the 5 s snapshot; the dossier fetches `/ladder/<symbol>` on demand (new bridge route reading the diff engine's latest cycle).
- `session_state` is computed **server-side** from calendar + feed_ts + conns; the HUD renders it and applies only the freshness sub-gate it already has. One source of truth (PRD §5).
- Bridge hardening (U3): snapshot read into memory and served from cache; on missing/corrupt file serve last-good with `"stale": true`; atomic snapshot writes (temp + rename). Port conflict at startup → clear error naming the PID holding :8787.
- **CLOSED_FROZEN mechanics:** at 15:30 the daemon writes one final snapshot with `session_state=CLOSED_FROZEN`, stops mutating quotes/flow/structure, and keeps *serving* (bridge stays up off-hours; the loop stops OI diffing). U4: on next daemon start, `session_date` changes → HUD drops frozen overlay, enters PRE_OPEN.

## 10. HUD changes (template.html) — PRD §5 implementation

- Replace the boolean live-badge logic with a 5-state renderer keyed on `snapshot.session_state` (+ existing client freshness check as an AND-gate for LIVE styling). States map to the PRD §5 table: badge, styling class on `<body>` (`state-live`, `state-frozen`, …), and per-panel gating.
- CLOSED_FROZEN: live spans keep final values, pulse animation removed, `● ` dot swapped for `■ `; trigger/wall-break logs remain rendered from the frozen snapshot.
- EOD-REFRESH: when `snapshot.eod_version` > baked `SESSIONS[last]`, show a persistent (non-toast-timeout) banner with a reload link. Never auto-reload (the trader may be mid-analysis).
- DEGRADED: command-bar shows `conns_alive/target` + live-map %, per-symbol fallback to EOD styling when that symbol's `quotes[sym].age` exceeds the gate.
- Quarantine chip (U8): `coverage.quarantined` symbols get `⚠ MAP` next to the symbol in scanner + dossier; their `flow`/`structure` blocks are withheld server-side (defense in depth).
- Time-travel gate unchanged (U7): any non-latest `SDATE` suppresses every live element.

## 11. Nightly chain & ops (PRD §7, N1)

- One orchestrator script (`scripts/nightly.sh` or launchd chain): `poll_eod → daily_compiler → build_hud (atomic rename, U6) → build_ws_manifest → token_check`; each step appends to `data/live/nightly_<date>.log`; non-zero exit fires `alert_sink` (macOS notification).
- **Token workflow (N1, decided 2026-07-17):** the trader refreshes the Dhan token in `.env` daily before 09:00. Consequences the daemon must honor:
  - `.env` is **re-read at every daemon-window entry** (09:10), never cached across days — a long-running launchd process must not hold yesterday's token in memory.
  - Auth probe runs at **09:05** (moved earlier from 09:10): failure fires an immediate macOS notification ("token invalid — update .env") leaving ~10 min to fix before open; the probe retries every 60 s and hot-starts the feed the moment auth succeeds, so a late token costs minutes, not the session.
  - The nightly `token_check` is demoted to a reminder ("token will be refreshed manually tomorrow ≤ 09:00") rather than a 3-day expiry forecast.
  - Missed-refresh is the expected failure mode, not an edge case: PRE-OPEN UI shows "AUTH FAILED" state (PRD U-N1) until the token lands.
- Daemon under `launchd` with `KeepAlive`: crash → restart → PRE_OPEN → resubscribe. Startup always logs manifest size + conn plan to the daily log (the 2026-07-16 "430 instruments" incident becomes impossible to miss).
- Journal disk guard (N14): on write failure switch to in-memory ring (last 50k ticks) + alert; never block the feed on I/O.

## 12. Testing

| Layer | Tests |
|---|---|
| Manifest builder | Unit: coverage math, buffer, rollover (N6), schema-change abort (N10), bounds (N11), unmapped-row abort. Fixture bhavs incl. a corrupted one |
| Vectorized greeks | F0 parity vs brentq on full historical chain; convergence fuzz (deep ITM/OTM, T→0); perf bench |
| Diff engine | Unit: baseline diff, born_today, unknown-vs-zero age semantics |
| Sweeper | Token-bucket pacing test (mock clock); 429 backoff; handshake quarantine on a synthetic corporate action |
| State machine | Unit: server-side state derivation for every row of PRD §5/§6 tables; replay-harness fault injection: kill a conn (N2), stall feed (U1), delete snapshot (U3), overnight boundary (U4) |
| End-to-end | Replay a recorded session at 10×: assert parity outputs, event one-shots, budgets (§8) |
| Existing suites | `run_tests.py` stays green; `SKIP_LIVE_TESTS=1` honored — no network in CI (AGENTS.md rule) |

## 13. Migration & rollback

- Feature-flag `LIVE_FULLMAP=1` in `src/live/config.py`: off → current M2 behavior (top-60 near-ATM) untouched. Each F-phase ships dark behind the flag; rollback is unsetting it.
- Snapshot v2 is additive — the current HUD ignores unknown keys, so bridge/HUD can deploy independently.
- The EOD pipeline is untouched except: (a) optional vectorized IV after F0 parity, (b) manifest step appended to the nightly chain. `data/compiled/` write rules per AGENTS.md unchanged.
