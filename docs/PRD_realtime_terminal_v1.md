# PRD — Realtime Conversion of the Vanguard EOD Terminal

| | |
|---|---|
| **Product** | Vanguard — convert the existing EOD options terminal to realtime |
| **Version** | Realtime-Terminal v1.0 |
| **Author** | Platform (drafted with Claude — architect + institutional-trader review) |
| **Date** | 15 Jul 2026 |
| **Status** | DRAFT — awaiting approval. Build begins only on explicit go-ahead. |
| **Scope note** | This is the **first** thing to build — *before* `PRD_platform_v1.md` (the multi-engine platform). It takes **only what already exists** (the F&O dealer-positioning terminal) and makes it live. The breadth/sector/swing/long-term/order-desk expansion stays out of scope here; that's PRD 2. |

---

## 1. Objective

Everything the platform computes today — walls, gamma flip, GEX, gamma regime, IV, PCR, OI flow, IFS, the 10 setups and their trigger/invalidation levels — is currently derived **once per day** from EOD bhavcopies. This PRD makes those same outputs **live during market hours**, with intraday triggers and alerts, **without rewriting the math and without retiring EOD.**

**Guiding principle — ARM at EOD, TRIGGER live:** EOD stays the deliberate analysis pass (system of record, backtest corpus, the referee that audits live). The live layer watches the pre-committed levels and recomputes structure intraday. Nothing validated is thrown away; the live layer is additive.

### In scope
Live spot/OI/futures for F&O 215 + indices; live walls/GEX/flip/regime/IV per name; live setup status (WAITING→TRIGGERED→INVALIDATED) + alerts; HUD live mode; 15:35 EOD-parity check.

### Out of scope (→ PRD 2)
Breadth/sector/swing/long-term sections, chart patterns, order placement, fundamentals. No brand-new *analytics* — this is a conversion. (It does produce live-native *events* — regime crossings, wall relocations, coil breaks — but those are the existing signals observed intraday, not new analysis.)

### 1.1 What goes live, what stays EOD, what must NOT be ported
*(reconciled with `PRD_realtime_v1.md §4` — "make it realtime" is not "make everything realtime")*

| Current output | Disposition | Why |
|---|---|---|
| Walls / gamma flip / GEX | **LIVE (30 s, OI-floored ~3 min)** | the core inventory map; intraday wall *relocation* is itself information |
| Gamma regime | **LIVE + crossover alert** (`REGIME_CROSS`) | spot crossing the flip changes hedging flow *now* — the single most actionable live event |
| 10 setups (trigger/invalidation) | **ARM at EOD + LIVE TRIGGER** | EOD detects (as validated), live watches the levels; cheapest high-value conversion — levels already exist in `daily_setups` |
| — GAMMA_SQUEEZE | live-enhanced | wall breach **+ live CE-OI falling** = confirmed trigger (EOD can't do this) |
| — VOLATILITY_COIL / PINCH_ZONE | live-enhanced (`COIL_FIRING`) | the tradeable event is the *break* (realized-vol expansion) — inherently intraday |
| — FLOOR_BOUNCE | live-enhanced | wall-touch-and-hold beats the EOD proximity check |
| — IV_SPIKE / IV_CRUSH | **LIVE** (`IV_EVENT`) | vol events are intraday; EOD detection is always too late to act |
| — IV_SKEW_ACCUMULATION | **LIVE, better math** | true per-side IV skew replaces the crude CE/PE close-ratio proxy |
| — INVENTORY_MIGRATION | KEEP-EOD + live `WALL_RELOCATED` sibling | day-over-day wall shift is definitionally EOD |
| — DEALER_DEFENSE | port as-is (PRD 2 may retire it) | don't over-invest in a signal slated for review |
| IFS / net inventory flow | **LIVE but DISPLAY-ONLY** | valuable session context, but OI 3-min lag + noisy open auction → **never a trigger source in v1** |
| **Structure flips + confidence** | **DO NOT PORT** ⚠ | backtested *inversely* predictive (STRONG −0.11%/3d, 47.9% hit); realtime would amplify the churn that makes it bad. Stays EOD-context only. **Realtime must not become a faster way to see a broken number.** |
| Persistence / conviction / priority | **KEEP-EOD** | multi-day constructs; intraday recompute is meaningless |
| Catalysts (news) | KEEP-EOD | intraday news polling is separate scope |

**Live-native events** (alerts, never auto-trades): `REGIME_CROSS` (spot crosses flip, debounced), `SETUP_TRIGGERED`/`SETUP_INVALIDATED` (armed level, 1-min-bar confirmed), `WALL_RELOCATED` (GEX wall moves ≥1 strike, holds 2 cycles), `COIL_FIRING` (armed coil + RV expansion + range break), `IV_EVENT` (near-ATM IV ±2 pts vs open). Two **stretch/optional** genuinely-new detections — `OI_BLAST` (single-strike OI Δ > X% of side OI in one cycle) and `WALL_DEFENSE` (≥2 rejected touches of a wall) — are flagged as M3-optional since they're new analytics, not conversions.

---

## 2. Strike coverage & rate-limit strategy  ⟵ **the core question, answered**

> *"How will you handle rate limits, there are so many strikes?"*

There are **two different limits**, and they're often conflated. Both are solved by design, not by luck.

### 2.1 Limit A — WebSocket *subscription cap* (the "so many strikes" problem)

This is not a rate limit — it's a hard cap on how many instruments you can subscribe to at once.

| Fact | Number |
|---|---|
| Full F&O option chain (215 underlyings × expiries × 30–100+ strikes × CE/PE) | **50,000–100,000+ instruments** |
| Dhan WebSocket ceiling (5 conn × 5,000) | **25,000** |
| **Verdict** | Streaming every strike live is **impossible by 2–4×.** No code changes this. |

**Why it's also unnecessary:** gamma — and therefore GEX, walls, and the flip — is negligible for strikes far from spot. A strike 20% OTM contributes ≈ 0 to dealer gamma. Streaming the deep tails would burn the budget on data that never moves a wall. Institutions window the chain for exactly this reason.

**The solution — concentrate live bandwidth on what's active, sweep the rest:**

| Tier | Source | Coverage | Instruments | Fresh |
|---|---|---|---|---|
| **T-Live** | WebSocket | Near-ATM (±10–12 strikes) of **active names**: all indices + top-N by OI + every name with an armed setup today | ~3,000–5,000 | 30 s |
| **T-Sweep** | Option-Chain REST | **Full chain, every strike, all 215** (rotating) | full | ~11 min rolling |
| **T-EOD** | Bhav (existing) | **Full chain, every strike, authoritative** | full | nightly |

- **T-Live** captures the strikes that carry the gamma, only for the names you're actually watching/trading right now — comfortably inside 1–2 connections.
- **T-Sweep** covers *every* strike of *every* name on an 11-minute rolling refresh (§2.2) — it catches walls relocating to strikes outside the live window and refreshes the deep-OTM OI that T-Live skips.
- **T-EOD** reconciles the complete chain nightly and is the parity referee.
- Window **re-centers** on spot drift (unsubscribe far wing, subscribe near wing, 100-instrument batches) and **rebuilds daily** from the scrip master (expiry rollovers). Window width is **volatility-scaled** — wider for high-IV names whose gamma is more spread out.

**Coverage guarantee:** any strike that matters for live GEX is in T-Live (30 s). Any strike that *becomes* material is caught within one T-Sweep cycle (≤ 11 min) and pulls T-Live to re-center. The full chain is reconciled nightly. "Every strike" is answered as a layered guarantee, not one impossible firehose.

### 2.2 Limit B — REST *rate limits* (how we stay under them by design)

| Endpoint | Documented limit | Our usage | Headroom |
|---|---|---|---|
| **Option Chain** | **1 req / 3 s**, one underlying+expiry | T-Sweep: a **token-bucket scheduler** paced to exactly 1 req/3 s, rotating all 215 → **215 × 3 s ≈ 10.75 min** per full cycle | paced to the limit, never bursts |
| Historical Data | 5 req/s | one-time/nightly backfill only (not live) | huge |
| Quote (REST) | 1 req/s | **not used** — live prices come from WebSocket, not REST | n/a |
| Non-Trading (funds/margin) | 20 req/s | occasional | huge |

**We never hit a rate limit because we pace to it deliberately:**
- A single **token-bucket limiter** governs Option-Chain calls at 1 per 3 s. The sweeper rotates the universe; it cannot exceed the rate because the bucket refills at the documented rate.
- **Priority within the sweep:** names with an active setup, or spot sitting near a wall, are swept more often (bumped up the rotation); dormant names less often. So the ~11-min average shrinks to seconds for the names that matter.
- **429 handling:** exponential backoff with jitter (defensive — shouldn't trigger given the pacing).
- **Live prices are pull-free:** they arrive by WebSocket push, which has *no* rate limit (only the subscription cap of §2.1). So the high-frequency data path is never rate-limited at all.

### 2.3 The unavoidable floor (honest constraint)
NSE disseminates **OI on a ~3-minute cycle**. So every OI-derived metric (walls, GEX, flow) is at best ~3-min-fresh **regardless of how fast we compute** — a physical limit on NSE's side, not ours. Price/regime-vs-flip updates are near-instant (tick-driven); OI-structure updates are 3-min-floored. The UI labels OI-derived values with their data age so "live" is never oversold.

### 2.4 Which metric comes from which tier (no ambiguity)
| Metric | Source | Cadence |
|---|---|---|
| Spot, %chg, futures price | T-Live (WebSocket) | tick |
| Gamma regime (spot vs flip) | T-Live | tick (flip level from last structure pass) |
| Walls, GEX, gamma flip, IV, per-strike Greeks | T-Live near-ATM + T-Sweep tails | 30 s (OI 3-min floored) |
| Total OI, PCR, full-chain metrics | T-Sweep / T-EOD (needs deep strikes) | 11 min / nightly |
| Setup trigger/invalidation status | T-Live spot vs armed levels | per 1-min bar |

---

## 3. Architecture (reuse-first)

```
   Dhan WS (1–2 conn)         Dhan REST (paced)
  spot/fut + near-ATM opts   Option-Chain sweep
        │                          │
        ▼                          ▼
  ┌─────────────┐          ┌───────────────┐
  │ feed_handler│──ticks──▶│ state_store   │◀── far-strike tails ── chain_sweeper
  │ (asyncio)   │          │ (in-mem)      │        (token-bucket 1/3s)
  └─────────────┘          └───┬───────┬───┘
                               │       │
                   ┌───────────▼─┐  ┌──▼──────────────────────┐
                   │trigger_engine│  │ live_compute (30s)       │  REUSES:
                   │ armed levels │  │ walls·GEX·flip·regime·IV │  GreeksEngine, GammaAnalyzer,
                   └──────┬───────┘  │ (existing math)          │  intelligence.py wall/flip,
                          │          └──────────┬───────────────┘  StructureClassifier, build_playbook
                 ┌────────▼───────┐   ┌─────────▼────────────┐
                 │ alert_sink     │   │ bridge (localhost)   │
                 │ (macOS notif)  │   │ live_snapshot.json   │
                 └────────────────┘   └────────┬─────────────┘
                                               │ 5s poll
                                        HUD (live mode)
   ── nightly ──▶ EOD backbone (poll_eod → daily_compiler → DuckDB) + 15:35 parity referee
```

One always-on async daemon owns all Dhan connections (the *only* consumer of the token — the 7-tab starvation bug is impossible by construction). Everything else is in-process; no Redis/Kafka at single-user scale.

### Reused as-is (the ~90%)
`src/greeks_engine.py`, `src/analyzer.py`, wall/flip/GEX logic in `src/intelligence.py:209-227`, `src/core/{classifier,longitudinal,playbook,config}.py`, `src/services/database_service.py`, `scripts/build_dhan_map.py`, the whole EOD pipeline, and the HUD.

### New (the ~10%)
`src/live/`: `feed_handler`, `subscription_mgr`, `state_store`, `tick_journal`, `bar_aggregator`, `live_compute`, `chain_sweeper`, `trigger_engine`, `bridge`; `src/data/dhan_client.py`; `scripts/run_live.py`.

---

## 4. Milestones (implementation plan — build in this order)

### M0 — Access & foundation
- Dhan Data API token in `.env` (`DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN`); boot-time expiry guard.
- Extend `build_dhan_map.py` → security_id + lot_size + segment per symbol.
- `dhan_client.py` (thin wrapper, ideally over official `dhanhq` SDK); NSE market-hours + holiday scheduler in `run_live.py`.
- **Gate:** daemon authenticates, token-independent of any Dhan web session.

### M1 — Live tape (the "it's alive" proof)
- One WS connection: F&O 215 + indices spot + futures (Quote+OI mode).
- `state_store` + `bar_aggregator` + `tick_journal`; `bridge` serving `live_snapshot.json`.
- HUD **live mode**: live price/%chg on scanner/matrix/dossier, ● LIVE badge; degrades to EOD when daemon off.
- **Gate:** HUD quotes match Dhan app within 1 tick/1 s across 10 names; kill→reconnect < 10 s.

### M2 — Live structure
- `subscription_mgr` scoped near-ATM options (T-Live) on conn #2; `chain_sweeper` (T-Sweep, token-bucket 1/3 s).
- `live_compute` (30 s): reuse `GreeksEngine`/`GammaAnalyzer`/wall-flip logic → live walls/GEX/flip/regime/IV per covered name; emit `REGIME_CROSS`, `WALL_RELOCATED`, `IV_EVENT`.
- Dossier LIVE panel: live corridor (spot vs live walls), live IV vs EOD IV, live regime chip, data-age labels.
- **15:35 parity job:** live snapshot vs next-morning EOD compile.
- **Gate:** walls ≥ 90% strike-exact vs EOD; GEX within 15%; IV within 1 vol pt; else structure ships watermarked **INDICATIVE**.

### M3 — Live triggers (the payoff)
- Load today's armed book from `daily_setups` (levels already exist).
- `trigger_engine`: evaluate armed levels on **1-min bar close** (not raw tick — kills stop-hunt noise); status machine + one-shot/day + debounce.
- `alert_sink`: macOS notification (Telegram optional later). `live_events` journal.
- **Replay harness:** trigger_engine over a recorded tick journal → deterministic event log (regression test + the seed of intraday backtesting).
- **Gate:** replay of ≥ 3 recorded sessions matches expected triggers; alert latency ≤ 2 s from bar close; zero duplicate alerts.

**After M3 the current terminal is fully live.** PRD 2 then builds on this foundation.

---

## 5. Data model (additive; DuckDB/EOD unchanged)
```
data/live/ticks_YYYYMMDD.parquet        raw normalized ticks (research + future intraday backtest)
data/live/bars1m_YYYYMMDD.parquet       1-min bars
data/live/live_snapshot.json            ephemeral live state (HUD bridge)
data/live/live_events_YYYYMMDD.jsonl    triggers/alerts/events
data/live/parity_YYYYMMDD.json          15:35 live-vs-EOD parity report
```

## 6. Ops & failure
- Market-hours scheduler + NSE holiday calendar; expiry-day manifest rebuild.
- Heartbeat/pong (Dhan pings 10 s, disconnects at 40 s silence); watchdog alerts on > 60 s tick silence in market hours.
- Reconnect: exponential backoff + jitter, resubscribe from manifest, alert after 3 fails.
- **Failure stance:** live layer may die without corrupting anything — EOD is authoritative, HUD degrades to EOD view, daemon auto-restarts and rebuilds from ticks + EOD baseline.

## 7. Success metrics
| Metric | Target |
|---|---|
| Trigger alert latency (bar close → notify) | ≤ 2 s p95 |
| EOD parity (M2 gate) | walls ≥ 90% strike-exact · GEX ±15% · IV ±1 pt |
| Daemon uptime, market hours | ≥ 99% over 20 sessions |
| Rate-limit violations | **0** (paced by token bucket) |
| Reused code | ≥ 90% of compute is existing engines, unchanged |

## 8. Risks
| Risk | Mitigation |
|---|---|
| "So many strikes" overruns the WS budget | Concentrate T-Live on active names; full chain via T-Sweep/EOD (§2.1) |
| Option-Chain rate limit | Token-bucket paced to 1/3 s; live prices are push (no REST) (§2.2) |
| OI 3-min lag oversells "live" | Data-age labels on OI-derived metrics; price/regime is tick-fresh (§2.3) |
| Live ≠ EOD silently | 15:35 parity gate; INDICATIVE watermark on failure |
| Feed handler owns a fragile broker session | One daemon, heartbeat + backoff + resubscribe; EOD unaffected on failure |
| Scope creep into PRD 2 territory | This PRD is *conversion only* — no new signals, no new sections |

## 9. Open questions (need your call before build)
1. **Dhan Data API subscription active + token available for `.env`?** — the one hard blocker; M0 can't start without it.
2. **T-Live active-name set** — all indices + top-N-by-OI + armed-setup names (recommended N≈60), or a hand-picked list?
3. **Strike-window width** — fixed ±10, or volatility-scaled (recommended)?
4. **Alert channel** — macOS notifications for v1 (recommended), Telegram later?
5. **Localhost bridge daemon** acceptable during market hours (HUD live mode depends on it)?
6. **Tick retention** — keep raw ticks 30 days rolling (recommended), 1-min bars forever?
