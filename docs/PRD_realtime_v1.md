# PRD — Vanguard Live: Realtime Market Structure & Trigger Engine

| | |
|---|---|
| **Product** | Vanguard — F&O dealer-positioning terminal, realtime track |
| **Version** | Live v1.0 |
| **Author** | Quant/Platform (drafted with Claude — senior-architect + institutional options-trader review) |
| **Date** | 15 Jul 2026 |
| **Status** | DRAFT — pending approval. **No code until approved.** |
| **Relationship** | Companion to `PRD_vanguard_v2.md` (EOD Strategy Desk). v2 explicitly deferred live data to "a separate branch effort" — this is that effort, specified. |

---

## 1. Operating Thesis — what realtime is FOR

The platform's own evidence (v2 PRD §1, 257 sessions) says: **migration signals predict movement *magnitude*, not *direction*, and their profitable expression is defined-risk option structures anchored on walls.** The flip backtest (15 Jul) added: accelerating a noisy signal makes it noisier — STRONG flips were *inversely* predictive.

An institution would read those two findings and conclude that realtime's job here is **not** "compute the same signals faster." It is:

> **ARM at EOD, TRIGGER intraday.**
> EOD analysis (validated, deliberate, backtestable) decides *what* to trade and *at which levels*. The realtime layer watches those pre-committed levels live and fires **execution triggers, invalidations, and risk alerts** — plus the handful of phenomena that only exist intraday (regime crossings, IV events, coil breaks, OI blasts).

This preserves everything validated, adds no new unvalidated "signal factory," and converts the platform's existing assets (every `daily_setups` row already carries `trigger_strike` and `invalidation_strike`) into live machinery.

### Goals
1. **G1 — Trigger fidelity:** every armed EOD setup gets live status (WAITING → TRIGGERED / INVALIDATED) within 2s of the qualifying tick, with an alert.
2. **G2 — Live structure:** walls, gamma flip, GEX, gamma regime, and IV recomputed intraday (30s cadence) so regime crossings and wall relocations are seen when they happen, not at 18:30.
3. **G3 — Correctness proof:** the live engine's 15:29 snapshot must reconstruct the next morning's EOD compile within tolerance — the live layer is trusted only because it converges to the audited batch layer.
4. **G4 — Research capture:** every tick journaled, so intraday backtesting becomes possible for the first time (today's platform cannot answer "would this trigger have worked?" — after v1 it can).
5. **G5 — Zero regression:** the EOD pipeline (`poll_eod` → compiler → DuckDB → briefing) remains the system of record, untouched. Live state is ephemeral until it folds into EOD.

### Non-goals (v1)
- Automated order execution (alerts only; the human trades).
- Tick-by-tick UI (5s UI refresh is the target; this is a decision terminal, not an HFT screen).
- Realtime for signals the data says don't work (structure flips) or that are inherently multi-day (persistence, conviction).
- Options streaming for the cash-market breadth universe (2,400 symbols — optional Phase 5 ticker-only).

---

## 2. Verified platform constraints (checked against Dhan docs, 15 Jul 2026)

| Constraint | Value | Consequence |
|---|---|---|
| WebSocket connections per user | **5** (6th kicks the 1st with code 805) | Budget: 1 spot + 2 options + 1 spare + 1 reserved for manual Dhan web usage headroom |
| Instruments per connection | **5,000** | Options universe must be scoped (near-ATM window), not full-chain |
| Instruments per subscribe message | **100** | Subscription manager batches |
| WS packet types | Ticker (LTP), Quote (OHLC/vol/buy-sell qty), OI, Full (depth) | **No Greeks / IV on the feed** — computed locally |
| Greeks via REST option-chain | 1 request / **3 seconds**, one underlying+expiry per call | Full universe sweep = ~11 min → useless for realtime; usable only as slow-lane IV sanity check |
| Server heartbeat | ping every 10s; disconnect at 40s silence | Feed handler must pong; watchdog + auto-resubscribe mandatory |
| NSE OI dissemination | ~3-minute exchange update cycle | OI-derived metrics (walls, GEX, flow) have a floor cadence of ~3 min regardless of our compute speed — set expectations accordingly |
| Dhan Data API | Paid subscription + access token (expiry-managed) | **Open question #1: confirm subscription + token plumbing** |

**Universe sizing math** (options streaming, Phase 3):

| Scope | Instruments | Connections |
|---|---|---|
| Spot: 215 stocks + 5 indices, Quote mode | 220 | well inside 1 |
| Options v1: top-60 stocks by OI × front expiry × ±6 strikes ×2 sides + 5 indices × nearest weekly × ±10 strikes ×2 | ≈ 1,960 | 1 |
| Options full: 215 stocks × front+next × ±8 strikes ×2 + indices | ≈ 15,500 | 4 (over budget with spares — **v1 ships the scoped tier**) |

The subscription manager re-centers each symbol's strike window when spot drifts > 1% from window center (unsubscribe far wing, subscribe near wing — 100-instrument batched messages).

---

## 3. Target architecture

```
                       ┌────────────────────────────────────────────────┐
   Dhan WS (×2-3)      │  feed_handler (async daemon, market hours)     │
  spot / options  ───▶ │  · auth, subscribe, heartbeat, reconnect       │
                       │  · normalizes packets → tick bus               │
                       └──────────┬─────────────────────┬───────────────┘
                                  │                     │
                        ┌─────────▼────────┐   ┌────────▼─────────┐
                        │  tick journal    │   │  live state store │
                        │  (parquet/day,   │   │  (in-memory:      │
                        │   research)      │   │   quotes, OI,     │
                        └──────────────────┘   │   1-min bars)     │
                                               └───┬───────────┬───┘
                                 ┌─────────────────▼──┐   ┌────▼─────────────────┐
                                 │ trigger_engine     │   │ compute_engine       │
                                 │ per-tick, armed    │   │ 30s/60s cadence:     │
                                 │ levels only:       │   │ IV (BS solve on mid) │
                                 │ · setup breaches   │   │ Greeks, GEX, walls,  │
                                 │ · flip crossings   │   │ flip, regime, flow   │
                                 │ · wall touches     │   │ (reuses GreeksEngine │
                                 └───────┬────────────┘   │  / analyzer math)    │
                                         │                └────┬─────────────────┘
                              ┌──────────▼─────┐   ┌───────────▼──────────────┐
                              │ alert_sink     │   │ live snapshot (JSON +    │
                              │ macOS notif /  │   │ live_events log) served  │
                              │ Telegram       │   │ by local bridge (HTTP)   │
                              └────────────────┘   └───────────┬──────────────┘
                                                               │  poll 5s
   EOD (unchanged): poll_eod → daily_compiler → DuckDB ◀── 15:35 handoff/parity check
                                                               │
                                                        HUD **LIVE mode**
```

**Key design decisions (architect hat):**

| Decision | Rationale |
|---|---|
| Separate daemon, not inside Streamlit/HUD | UI lifecycles can't own a broker session; one process = one token = no repeat of the 7-tab websocket-starvation incident |
| Compute reuses existing engines | `GreeksEngine` (BS/IV), `analyzer.calculate_gex`, wall/flip logic from `intelligence.py:209-227`, classifier/regime thresholds from `src/core/config.py` — same math, streaming inputs. No forked formulas to drift |
| Trigger engine is per-tick but only on **armed levels** | O(armed setups) comparisons per tick ≈ trivial; the heavy structure recompute stays on the 30s clock. Institutions separate the "hot path" (level breaches) from the "warm path" (analytics) exactly this way |
| Live state is ephemeral; DuckDB stays EOD-only | System of record unchanged; if the live layer dies mid-session nothing is corrupted — restart resubscribes and rebuilds from ticks + EOD baseline |
| 15:35 parity check is a hard acceptance gate | Live-vs-compiled divergence = silent wrongness; we measure it daily and alarm on drift |
| HUD (plain HTML) is the live surface, Streamlit stays EOD | Streamlit reruns can't do push; the HUD already rebuilt for density/time-travel and can poll a local JSON at 5s trivially |

---

## 4. Signal-by-signal realtime disposition (trader hat)

Legend: **KEEP-EOD** (no realtime version) · **ARM+TRIGGER** (EOD detects, live watches levels) · **REBUILD-RT** (recomputed live) · **NEW-RT** (only exists live) · **RETIRE/DEFER**.

| Signal | Disposition | Institutional rationale |
|---|---|---|
| **Walls / Gamma flip / GEX** | **REBUILD-RT** (30s, OI-floor ~3 min) | The core inventory map. On event days it is stale by 10:00. Intraday wall *relocation* is itself information (dealer re-hedging in progress) — EOD only sees the aftermath. |
| **Gamma regime (LONG/SHORT/TRANSITION)** | **REBUILD-RT** + crossover alert | Spot crossing the flip intraday is the single most actionable live event on this platform: it changes hedging flow direction *now*. EOD regime is yesterday's regime. |
| **10 setup types** | **ARM+TRIGGER** (universally) | EOD detection stays exactly as validated. Live layer loads the morning's `daily_setups`, watches `trigger_strike`/`invalidation_strike` per tick, transitions status, alerts. The levels already exist — this is the cheapest high-value conversion in the whole PRD. |
| — GAMMA_SQUEEZE | ARM+TRIGGER, enhanced | Breach of call wall + **live CE OI falling** (short covering confirmation from OI packets) = qualified trigger; breach without OI confirmation = flagged as unconfirmed. EOD can never do this. |
| — VOLATILITY_COIL / PINCH_ZONE | ARM+TRIGGER, enhanced | The EOD signal finds the coil; the *tradeable event is the break*, which is inherently intraday. Add a realized-vol trigger: 15-min RV > 2× coil-period baseline + range expansion ⇒ "COIL FIRING" alert. Consistent with v2's magnitude-not-direction finding — the alert says *moving*, the direction comes from which side broke. |
| — FLOOR_BOUNCE | ARM+TRIGGER | Wall-touch + hold logic (touch put wall, hold 15 min above) beats EOD proximity check. |
| — INVENTORY_MIGRATION | **KEEP-EOD** + NEW-RT sibling | Day-over-day wall shift is definitionally EOD. Its live sibling is *intraday wall relocation* (below). |
| — REGIME_SHIFT | superseded intraday by the live flip-crossover alert; EOD version remains for the compiled record | |
| — IV_SPIKE / IV_CRUSH | **REBUILD-RT** | Vol events are intraday phenomena (event prints, news); detecting them at 18:30 is always too late to sell rich vol or harvest crush. Live IV from local BS on option mids. This is where realtime most improves an existing signal. |
| — IV_SKEW_ACCUMULATION | **REBUILD-RT, better math** | EOD proxies skew with a crude CE/PE close-price ratio. Live: true skew from per-side near-ATM IVs. Strictly superior measurement; keep thresholds until re-validated. |
| — DEALER_DEFENSE | **DEFER to v2 decision** | v2 retires it (PINCH covers it). Don't port a signal scheduled for deletion. |
| **Structure flips + confidence** | **DO NOT PORT** | Backtested inversely predictive (STRONG −0.11%/3d, 47.9% hit); realtime would amplify exactly the churn that makes it bad. Stays EOD-context only; revisit only as an explicit fade study. Realtime must not become a faster way to see a broken number. |
| **IFS / net inventory flow** | **REBUILD-RT with guardrails** | Intraday IFS vs yesterday-EOD OI baseline is valuable session-flow context, but: OI is ~3-min delayed, first ~45 min of OI data is structurally noisy (overnight adjustments), and IFS scale issues are known. Ship as a *display metric* ("session flow"), never as a trigger source in v1. Persistence streaks stay EOD-fed only. |
| **Persistence / conviction / priority scores** | **KEEP-EOD** | Multi-day constructs; intraday recomputation is semantically meaningless. v2 replaces priority with confluence anyway. |
| **F&O breadth (bull/bear/coil %)** | **NEW-RT lite version** | Live advancers/decliners across the 215 (price-based, from spot ticks) + live NIFTY overlay = intraday breadth-divergence read (the June/July divergence story, live). OI-based IFS breadth stays EOD. |
| **Cash-market breadth (2,400 syms)** | **KEEP-EOD**, optional Phase 5 | One connection could stream all 2,400 in Ticker mode for a live A/D line; nice-to-have, not v1. McClellan/DMA stay EOD by definition. |
| **Playbooks / Strategy Desk picks (v2)** | **ARM+TRIGGER** (Phase 5, after v2 Phase 3) | Live premium tracking of desk-pick legs; alert when entry conditions met or short strike threatened. The realtime layer becomes the desk's execution assistant. |
| **Catalysts (news)** | KEEP-EOD cadence in v1 | Intraday news polling is a separate scope; the existing EOD catalyst run is unaffected. |
| **Watchlist screener** | Absorbed | The armed-setups board with live statuses *is* the intraday watchlist; the current screener remains the EOD/briefing version. |

### New realtime-native events (v1 event vocabulary)

| Event | Definition | Why a trader cares |
|---|---|---|
| `REGIME_CROSS` | Spot crosses gamma flip (with 0.2% debounce band + 5-min dwell) | Hedging flow flips sign — volatility character changes now |
| `SETUP_TRIGGERED` / `SETUP_INVALIDATED` | Armed level breached (close-of-1-min-bar confirmation, not raw tick, to kill stop-hunt noise) | The execution moment for yesterday's plan |
| `WALL_RELOCATED` | Intraday GEX wall moves ≥ 1 strike and holds 2 compute cycles | Dealers re-anchoring defense intraday — corridor changed mid-session |
| `COIL_FIRING` | Armed coil/pinch + RV expansion + range break | Magnitude signal firing in the only window it's tradeable |
| `IV_EVENT` | Near-ATM IV ± 2 vol pts vs session open (spike/crush) | Premium rich/cheap *while structurable* |
| `OI_BLAST` | Single strike OI Δ > X% of side OI in one dissemination cycle | Institutional block placed — walls about to move |
| `WALL_DEFENSE` | ≥ 2 touches of a wall strike rejected within N minutes | Live confirmation the level is being defended (credit-spread anchor evidence) |

Every event carries symbol, timestamp, level, and evidence fields, written to `live_events` (journaled) and pushed to the alert sink. **All v1 events are alerts, not auto-trades.**

---

## 5. Phased delivery — step by step

### Phase 0 — Foundations (no market data product yet)
| Step | Detail |
|---|---|
| 0.1 | Confirm Dhan Data API subscription; access-token storage in `.env` (`DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN`); token-expiry check + renewal reminder at daemon start |
| 0.2 | Extend `scripts/build_dhan_map.py` to also emit **security IDs + lot sizes + exchange segment** per symbol (columns already in the scrip master it downloads) — the WS subscribes by security ID |
| 0.3 | NSE market calendar (holidays + special sessions) module; daemon runs 09:10–15:35 IST on trading days only |
| 0.4 | `feed_handler` skeleton: single connection, spot Quote-mode for 220 instruments, heartbeat/pong, exponential-backoff reconnect with full resubscribe, structured logging |
| 0.5 | Tick journal: append-only parquet per session (`data/live/ticks_YYYYMMDD.parquet`), 1-min bar aggregation table |
| **Accept** | One full session recorded end-to-end; forced kill mid-session → auto-reconnect < 10s with resubscribe; journal has no gaps > 60s; zero interference with a concurrently open Dhan web session (verifies API token vs web session independence) |

### Phase 1 — Live tape on the HUD
| Step | Detail |
|---|---|
| 1.1 | Local bridge: tiny HTTP server (localhost) serving `live_snapshot.json` (quotes, session OHLC, % chg for 220 instruments + live F&O A/D counts) |
| 1.2 | HUD **LIVE badge + mode**: when bridge responds, scanner/matrix/dossier show live price/чg (5s poll); command bar clock gains ● LIVE; graceful fallback to EOD-only when bridge absent |
| 1.3 | Live NIFTY + net-advancers strip on the Net Breadth panel (intraday divergence read) |
| **Accept** | HUD quotes match Dhan app within 1 tick/1s spot-check across 10 symbols; HUD works unchanged when daemon is off |

### Phase 2 — Armed-setup trigger engine (the heart of v1)
| Step | Detail |
|---|---|
| 2.1 | At daemon start: load today's armed book = yesterday's `daily_setups` (+ `daily_strategies` when v2 Phase 3 ships) |
| 2.2 | Per-tick evaluation on 1-min-bar close confirmation; status machine WAITING → TRIGGERED → (later) INVALIDATED; debounce + one-shot semantics per setup per day |
| 2.3 | Alert sink: macOS `osascript` notification (v1 default) + optional Telegram bot (config-gated) — **open question #2** |
| 2.4 | `live_events` log + HUD armed-setups board (live status chips replacing the static WAITING computed at build time) |
| 2.5 | **Replay harness**: run trigger engine over a recorded tick journal → deterministic event log (this is the test suite for everything above, and the seed of intraday backtesting) |
| **Accept** | Replay of ≥ 3 recorded sessions produces expected trigger logs (hand-verified sample); live alert latency ≤ 2s from qualifying bar close; zero duplicate alerts |

### Phase 3 — Options streaming + live structure
| Step | Detail |
|---|---|
| 3.1 | Subscription manager: scoped options universe (top-60 by OI + 5 indices, front expiry, dynamic ±6/±10 strike window re-centering on drift) ≈ 2k instruments on connection #2 |
| 3.2 | Local IV solve (BS on option mid from Quote packets, existing `GreeksEngine` math) + Greeks + GEX per strike, 30s cadence |
| 3.3 | Live walls / gamma flip / regime per covered symbol (identical formulas to `intelligence.py`); `REGIME_CROSS`, `WALL_RELOCATED`, `IV_EVENT`, `OI_BLAST`, `WALL_DEFENSE` events wired |
| 3.4 | HUD dossier LIVE panel: live corridor (spot vs live walls), live IV vs EOD IV, live regime chip |
| 3.5 | **Parity job at 15:35**: snapshot live walls/GEX/IV → next morning compare vs compiled EOD values; report to log + HUD diagnostics |
| **Accept** | Parity: walls match EOD strike-exactly ≥ 90% of covered symbols; GEX within 15%; IV within 1 vol pt (differences documented — bhav close vs last-mid basis); OI floor behavior documented |
| **Gate** | If parity fails persistently, live structure ships as "INDICATIVE" watermark until resolved — never silently trusted |

### Phase 4 — Live flow metrics (display-grade)
| Step | Detail |
|---|---|
| 4.1 | Session IFS / net-inventory vs EOD baseline with first-45-min damping; "SESSION FLOW" tile in dossier (display only, no triggers) |
| 4.2 | Live per-side skew from IV (replaces close-ratio proxy intraday); IV_SKEW live context |
| 4.3 | Coil RV trigger (`COIL_FIRING`) armed from EOD coil/pinch list |
| **Accept** | Flow metrics visibly damped in open auction window; COIL_FIRING replay-validated on recorded sessions containing known coil breaks |

### Phase 5 — Optional extensions (each its own go/no-go)
- Cash universe live A/D (2,400 tickers, connection #3, Ticker mode) → live McClellan preview.
- Desk-pick monitor (needs v2 Phase 3): live leg premiums, short-strike threat alerts.
- Full 215-symbol options coverage (needs connection budget review or window narrowing).
- Intraday backtest suite over the accumulated tick journals (the research payoff of G4).

### Sequencing vs PRD v2
- v2 **Phase 1 (cleanup)** should land first — it deletes `main.py`/`signal_generator` which `poll_eod` still calls; realtime P0 touches the same startup scripts.
- Realtime **P0–P2 are independent** of v2 Phases 2–3 and can run in parallel.
- Realtime P5 desk-monitor explicitly depends on v2 Phase 3 (Strategy Desk).

---

## 6. Cadence & latency budget

| Path | Budget | Notes |
|---|---|---|
| Tick ingest → state store | < 50 ms | async, no compute on hot path |
| Armed-level trigger check | per 1-min bar close, alert ≤ 2 s | confirmation-on-bar kills tick-noise false fires |
| Structure recompute (walls/GEX/IV) | every 30 s (OI floor ~3 min from NSE) | full covered-universe pass ≤ 5 s compute target |
| Flow metrics | every 60 s | |
| HUD refresh | 5 s poll | decision terminal, not tape-watching |
| EOD handoff / parity | 15:35 once | |

## 7. Storage & schema (all additive)

```
data/live/ticks_YYYYMMDD.parquet      raw normalized packets (~0.5–2 GB/day scoped universe; retention: open question #6)
data/live/bars1m_YYYYMMDD.parquet     1-min bars (small, kept indefinitely)
data/live/live_snapshot.json          current state for HUD bridge (ephemeral)
data/live/live_events_YYYYMMDD.jsonl  event/alert log (kept — this is research data)
```
DuckDB/compiled tables: **unchanged**. A future `live_events` fold-in to DuckDB is Phase 5 research work.

## 8. Ops & reliability

| Concern | Handling |
|---|---|
| Token expiry | Startup validation + N-days-left warning; daemon refuses to start with < 1 day validity |
| Reconnect storms | Exponential backoff (1s→60s cap), jitter, resubscribe-from-manifest; alert after 3 consecutive failures |
| Session-token conflicts | API tokens are separate from web logins (verified in P0 acceptance); daemon is the only WS consumer of the API token — the 7-tab incident cannot recur by construction |
| Clock/calendar | IST-pinned scheduling; holiday calendar; expiry-day awareness (weekly index expiries change the option universe at open — subscription manifest rebuilt daily from scrip master) |
| Monitoring | Per-connection packet-rate gauge, last-tick-age per symbol, compute-cycle duration, event counts; a stalled feed (> 60s silence in market hours) is itself an alert |
| Failure stance | Live layer may die without corrupting anything; EOD remains authoritative; HUD degrades to EOD view |

## 9. Success metrics

| Metric | Target |
|---|---|
| Trigger alert latency (bar close → notification) | ≤ 2 s p95 |
| EOD parity (Phase 3 gate) | walls ≥ 90% strike-exact; GEX ± 15%; IV ± 1 pt |
| Daemon uptime during market hours | ≥ 99% over 20 sessions |
| False-trigger rate (alerts later shown wrong on replay) | < 2% |
| The honest one | after 4 weeks: count of alerts the operator actually acted on / found decision-relevant — reviewed together, features that score zero get cut (same discipline as v2 badges) |

## 10. Risks

| Risk | Mitigation |
|---|---|
| OI dissemination lag makes "live GEX" look more live than it is | Label OI-derived metrics with data age; 3-min floor documented in UI tooltip |
| Local IV from mids diverges from EOD bhav-close IV | Parity report quantifies it; IV events use *session-relative* deltas (self-consistent basis) |
| Scoped universe misses a move outside top-60 options coverage | Spot triggers (Phase 2) cover ALL 215; only live *structure* is scoped — spot-level setup triggers never miss |
| Alert fatigue → ignored terminal | One-shot semantics, severity tiers, daily alert budget review in the 4-week metric |
| Dhan API changes/throttles | Feed handler isolates the vendor surface; packet parsing versioned; SDK pinned |
| Scope creep into auto-trading | Explicit non-goal; any order-routing PRD is a separate document with its own risk review |

## 11. Open questions (need your call before build)

1. **Dhan Data API subscription** — active on your account? Token available for `.env`? (Blocks P0.)
2. **Alert channel** — macOS notifications, Telegram bot, or both? (P2.3)
3. **Options coverage v1** — top-60 by OI + indices (recommended), or a hand-picked list, or all 215 (connection budget review needed)?
4. **Expiries** — front-only v1 (recommended) or front+next for stocks?
5. **Localhost bridge daemon** acceptable during market hours (HUD live mode depends on it)?
6. **Tick retention** — keep raw ticks (0.5–2 GB/day) for N days? (1-min bars kept forever regardless; recommend raw = 30 days rolling.)
7. **Sequencing** — v2 Phase 1 cleanup first (recommended), then realtime P0 in parallel with v2 Phase 2+?
