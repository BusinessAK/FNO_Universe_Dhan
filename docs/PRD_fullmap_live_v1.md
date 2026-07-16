# PRD — Full-Map Live Coverage v1 ("the bhav-informed tape")

**Status:** Draft for review · **Owner:** Aniket · **Doc pair:** [TRD_fullmap_live_v1.md](TRD_fullmap_live_v1.md)
**Builds on:** [PRD_realtime_terminal_v1.md](PRD_realtime_terminal_v1.md) (M0–M2 shipped: spot/futures tape, near-ATM live structure for top-60+indices, HUD live overlay)

---

## 1. Problem

The live layer today covers **LTP for all 215 names** but **OI/greeks for only ~64 names × near-ATM strikes**. The trader cannot:

- compare **today's live OI against yesterday's bhav** across the full chain (per-strike buildup, live PCR, live total OI);
- see a wall forming **outside** the ±12-strike live window;
- trust the HUD **after market close** — live overlays currently vanish on staleness, discarding the day's picture during the review hours when it is most needed.

Naive fix ("subscribe everything") is impossible: 80,071 listed option instruments vs Dhan's hard 25,000 WebSocket cap. But measured on the 2026-07-15 bhav, **58% of listed strikes carry zero OI**, and **12,052 strikes carry 99.5% of all OI**. The full *economic* map fits in ~3 of 5 connections.

## 2. Objective

Stream the full economic option map (99.5% of open interest) over the existing Dhan WebSocket, compute IV/greeks/walls/GEX **on the fly for all 215 names**, diff every OI tick against the previous bhav, and give the HUD an explicit **session state machine** so data is trustworthy during market hours, after close, and through the nightly EOD fetch/compile.

### In scope (v1)
1. **Nightly WS manifest builder** — bhav-selected subscription set (99.5% OI coverage ≈ 12k) + zero-OI ATM buffer (±5 strikes/name) + spot + front futures.
2. **Multi-connection feed** (up to 3 data connections; 2 held in reserve).
3. **Vectorized IV/greeks** — hard prerequisite; per-row Brent solve does not scale to 12k strikes/30s.
4. **Live vs bhav diff engine** — per-strike ΔOI, live PCR, live total OI, full-chain walls for all 215 names.
5. **Thin REST chain sweep** — safety net only: full-universe rotation ≤ 60 min; catches OI born outside the WS set; feeds the morning parity handshake.
6. **Morning parity handshake** — first live baseline vs yesterday's bhav across the subscribed map; mismatches quarantine the symbol, never silently pass.
7. **HUD session state machine** — PRE-OPEN / LIVE / DEGRADED / CLOSED-FROZEN / EOD-REFRESH (spec in §5).
8. **Intraday persistence** — live structure + sweep results written to parquet for the research layer.

### Out of scope (v1)
- Streamlit dashboard live integration (stays EOD research console).
- Auto-trading, order routing of any kind.
- Adaptive intraday re-subscription (v1 logs `COVERAGE_GAP` events; acting on them is v1.1).
- Back-month expiries beyond front (+ next-expiry blend near rollover, which **is** in scope — §6.7).
- Structure-flip confidence live (backtested inversely predictive; permanent exclusion per PRD v1).

## 3. Users & value

Single user (the trader). Value, ranked:
1. **Full-chain live OI buildup vs yesterday** — the intraday version of the EOD inventory analysis; today it does not exist at all.
2. **Walls/GEX/regime live for all 215 names** — today 64.
3. **A HUD that is honest in every session phase** — no frozen "LIVE" badges, no vanished evening data, no half-compiled EOD flashes.

## 4. Coverage requirements

| ID | Requirement |
|---|---|
| C1 | WS manifest = all strikes covering ≥ 99.5% of prior-day total OI, per side, plus ±5 zero-OI strikes around prior close per name, plus spot + front futures for all names + indices. Target ≤ 15,000 instruments; hard abort > 15,000 (rebuild with 99% threshold). |
| C2 | Manifest rebuilt nightly after EOD compile; **must** also rebuild from the morning scrip master if instrument master is newer than the manifest (expiry rollovers, new listings). |
| C3 | Any strike outside the WS set that gains material OI (sweep-detected, > 0.5% of that symbol's side OI) raises a `COVERAGE_GAP` event visible in the HUD trigger feed. It is included in tomorrow's manifest automatically. |
| C4 | Sweep guarantees full-universe refresh ≤ 60 min; names with armed setups or spot within 1% of a wall refresh ≤ 10 min. |
| C5 | OI freshness is never overstated: every OI-derived value in the UI carries its data age; NSE's ~3-min OI dissemination floor is documented in the UI (existing behavior, retained). |

## 5. UI: session state machine (the core UX requirement)

The HUD must always display exactly one of five states, driven by the snapshot (`session_state` field) — never inferred client-side from wall-clock alone.

| State | When | Badge | Data shown |
|---|---|---|---|
| **PRE-OPEN** | Daemon up, 09:10–09:15, or open but no tick yet | `◌ PRE-OPEN` (grey) | EOD everything; quotes seeded from prev close, rendered dimmed, no % change claims; parity handshake progress ("map verified 11,842/12,052") |
| **LIVE** | Market open, `feed_ts` fresh (< 15 s), ≥ target conns alive | `● LIVE n` (green, pulse) | Full live overlay: LTP, ΔOI vs bhav, live structure, triggers, wall breaks |
| **DEGRADED** | Market open but feed stale, or 1+ data connection down, or parity quarantine > 5% of names | `▲ DEGRADED · 2/3 conn` (amber) | LTP/structure only for instruments with fresh ticks; stale symbols fall back to EOD styling; a visible coverage fraction ("live map 63%") — partial data must **look** partial |
| **CLOSED-FROZEN** | After 15:30 until the next EOD compile lands | `■ SESSION CLOSED · as of 15:30` (grey, no pulse) | The day's **final** live snapshot frozen: last LTPs, final ΔOI, full trigger/wall-break logs. Nothing vanishes. Frozen values styled distinctly (no pulse, muted live-dot) so they cannot be mistaken for ticking data |
| **EOD-REFRESH** | New EOD compile completed for today | toast: `EOD compiled for 16 Jul — reload deck` | Current view untouched until user reloads; reload serves the freshly built HUD with today as the latest session and live overlays cleared |

### State-transition rules (negative-path behavior)

| # | Scenario | Required behavior |
|---|---|---|
| U1 | Feed thread stalls but daemon loop keeps writing snapshots | Judge liveness on `feed_ts` only (existing two-clock rule). LIVE → DEGRADED within 15 s. **Never** a green badge over frozen prices |
| U2 | Bridge down / HUD opened via `file://` | All live UI absent; HUD is a complete EOD terminal on its own (existing, retained) |
| U3 | Snapshot JSON missing/corrupt mid-session | Bridge serves last-good cached copy with `stale: true`; HUD treats as DEGRADED. A deleted file (observed 2026-07-16) must not blank the UI |
| U4 | Browser left open overnight | CLOSED-FROZEN persists; at next 09:10 daemon start the snapshot's new `session_date` tells the HUD to drop yesterday's frozen overlay and enter PRE-OPEN. No stale Tuesday data on Wednesday morning |
| U5 | EOD compile fails or bhav never arrives (NSE late/holiday) | HUD stays CLOSED-FROZEN on the last live state, with the *previous* EOD as baked baseline; command bar shows "EOD pending — last compile 15 Jul". Never a partially compiled dataset |
| U6 | User reloads during the compile/HUD-rebuild window | Served `vanguard_hud.html` is replaced **atomically** (temp file + rename). A reload mid-compile gets the old complete file, never a half-written one |
| U7 | Historical session selected (time travel) | All live overlays suppressed regardless of state (existing gate, retained — live data only ever decorates the latest session) |
| U8 | Parity handshake quarantines a symbol | Its live fields render as EOD-only with a `⚠ MAP` chip; quarantine reason available in the dossier |

## 6. Negative scenarios — product-level handling

(Engineering detail in TRD §7; this table defines *required outcomes*.)

| # | Scenario | Required outcome |
|---|---|---|
| N1 | Dhan token expired/invalid at 09:10 | Daemon refuses to start feed; macOS notification + HUD PRE-OPEN shows "AUTH FAILED — feed offline"; EOD view fully usable. Token expiry checked **nightly** with ≥ 3-day advance warning |
| N2 | 1 of 3 WS connections drops | Auto-reconnect with backoff; DEGRADED with coverage fraction while down; instruments on surviving conns stay live |
| N3 | All connections drop (network loss, laptop sleep) | DEGRADED → after wake/reconnect, full resubscribe from manifest; session OHLC rebuilt from journal where possible; prev-close reseeded |
| N4 | Duplicate daemon started | Second instance detects lockfile and exits loudly. Two daemons double-subscribe and can get both kicked by Dhan |
| N5 | NSE OI dissemination stalls (prices tick, OI frozen exchange-wide) | OI-age labels go amber past 6 min; walls/GEX keep computing on last OI with age shown; no false DEGRADED (price feed is healthy) |
| N6 | Expiry day / rollover | Manifest builder rolls to next expiry at T-1 close for dying series; near-expiry greeks guarded (T→0 instability, TRD §7.6); parity handshake ignores expired series |
| N7 | Corporate action (split/bonus → strike remap, security_id change) | Morning handshake catches OI/close mismatch at scale → symbol quarantined (U8) for the day; manifest note for permanent remap |
| N8 | Strike with stale LTP (last trade hours old) | IV solve discarded when option tick age vs spot tick age exceeds gate; strike contributes OI to walls but not to IV aggregates. Garbage IV must never move a wall or fire `IV_EVENT` |
| N9 | Sweep rate-limited (429) despite pacing | Token bucket + exponential backoff with jitter; sweep silently slows — it is a safety net, not a dependency |
| N10 | Bhav file format change / new column names (NSE does this) | Manifest builder + compiler fail loudly with a schema diff report; previous manifest reused (with a staleness warning in the HUD) rather than an empty one |
| N11 | Manifest builder produces < 8,000 instruments (suspiciously small) | Abort and reuse previous manifest + alert. A silently tiny map is worse than a stale one |
| N12 | Live structure contradicts EOD at 15:35 parity check | Existing parity referee stands; failures re-arm the `INDICATIVE` watermark for live structure the next day |
| N13 | `COVERAGE_GAP` storm (many strikes born outside the set — e.g. crash day, new strikes listed intraday) | Events coalesced per symbol (max 1/symbol/15 min); HUD banner "map coverage degrading — N names affected"; next-day manifest picks all of them up |
| N14 | Disk full / journal write fails | Journal drops to memory-only ring buffer + alert; snapshot writes continue (smaller); feed never blocked by disk I/O |

## 7. EOD boundary — the nightly sequence (explicit contract)

```
15:30  close → daemon freezes final snapshot (session_state=CLOSED_FROZEN), stops OI diffing
15:35  live parity referee runs (existing live_parity_check) → parity_*.json
~18:00+ poll_eod fetches bhav (retry loop; N10/U5 if absent)
        daily_compiler → DuckDB (new session date)
        build_hud → vanguard_hud.html rebuilt ATOMICALLY (U6)
        manifest_builder → ws_manifest_<tomorrow>.parquet + coverage report (C1, N11)
        snapshot gets eod_version=<today> → HUD shows EOD-REFRESH toast
09:10  next day: daemon reads new manifest; PRE-OPEN; parity handshake (C-series)
```

Requirement: every step in this chain logs to `data/live/nightly_<date>.log` and any failure fires a macOS notification — the trader must never *discover* at 09:15 that last night silently failed.

## 8. Success metrics

| Metric | Target |
|---|---|
| OI coverage of subscribed map vs next-day bhav truth | ≥ 99.0% of total OI, measured daily by the handshake |
| Morning parity handshake pass rate (strikes matching bhav) | ≥ 99.5% of subscribed strikes; quarantines < 5 symbols/day |
| Live walls vs EOD referee (15:35) | ≥ 90% strike-exact · GEX ± 15% · IV ± 1 pt (unchanged gate, now for all 215) |
| Session uptime (LIVE state as % of market hours) | ≥ 98% over rolling 10 sessions |
| Compute cycle (12k strikes → greeks → walls, all 215) | < 5 s per 30 s cycle (TRD perf budget) |
| False/duplicate alerts | < 5/day; every alert one-shot server-side |
| UI state correctness | Zero observed instances of live-styled stale data (manually audited during soak) |

## 9. Rollout & gates

| Phase | Content | Gate to proceed |
|---|---|---|
| F0 | Vectorized IV/greeks engine | Parity vs `brentq` ± 1e-4 IV on full EOD chain; 12k rows < 2 s |
| F1 | Manifest builder + multi-conn feed (data only, no compute widening) | 3 sessions: coverage metric ≥ 99%, no conn instability |
| F2 | live_compute widened to all 215 + ΔOI diff engine | 15:35 referee passes on ≥ 90% of names, 3 consecutive sessions |
| F3 | Thin sweep + morning handshake + quarantine | Handshake pass rate ≥ 99.5%, 3 sessions |
| F4 | HUD state machine + CLOSED-FROZEN + EOD-REFRESH | Manual state-transition audit (all rows of §5 table exercised, incl. U3–U6 fault injection) |
| F5 | Soak | 10 consecutive sessions meeting §8 before any live number is treated as decision-grade |

## 10. Risks

| Risk | Mitigation |
|---|---|
| Dhan changes WS caps/packet formats | Feed constants centralized (`src/live/config.py`); normalize() unit-tested against recorded packets; manifest degrades to 99% set if cap shrinks |
| 12k-instrument tick volume overwhelms one Python process | Deep strikes rarely tick (that's why they're cheap); measured budget in TRD §8; per-conn threads write disjoint key sets |
| Vectorized IV subtly diverges from EOD brentq | F0 parity gate + same engine class used by both paths |
| Complexity creep in HUD states | State comes from the server snapshot; HUD only renders it. One source of truth |
| The trader trusts live numbers before soak completes | `INDICATIVE` watermark discipline retained; §8 metrics visible in HUD footer during soak |

## 11. Open questions

1. Should `COVERAGE_GAP` auto-promote strikes intraday (v1.1 adaptive mode) or stay next-day-only? (v1 ships next-day-only per decision 2026-07-16.)
2. Alerting channel beyond macOS notifications (Telegram?) — deferred; alert_sink is pluggable.
3. Weekly index expiry days: is front+next blending (N6/TRD §7.6) enough, or should indices get all listed weeklies within 14 days? Revisit with F2 parity data.
