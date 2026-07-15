# TECH — Vanguard Platform v1: Technical Design & Implementation Plan

| | |
|---|---|
| **Companion to** | `PRD_platform_v1.md` (the what/why). This is the how. |
| **Author** | Platform engineering (drafted with Claude — architect + trader review) |
| **Date** | 15 Jul 2026 |
| **Status** | 🔒 **LOCKED — Baseline v1.0** (15 Jul 2026). Design frozen as the implementation baseline; material changes require re-approval + version bump. Build begins on explicit go-ahead. |

---

## 0. The derivatives-coverage question (read first)

> **"Did you factor in price + OI + Greeks for every strike of all derivatives instruments?"**

**No — because it is physically impossible on Dhan, and unnecessary for correctness.** This is the load-bearing decision of the whole design, so it is stated up front.

### 0.1 The physics
- NSE F&O ≈ **215 underlyings**. Each has multiple expiries (stocks: monthly ×2–3; indices: weekly + monthly), each expiry has 30–100+ strikes × 2 (CE/PE).
- Full live chain ≈ **50,000–100,000+ option instruments**.
- Dhan WebSocket ceiling = **5 conn × 5,000 = 25,000 instruments.**
- **Streaming every strike of every instrument live is impossible by a factor of 2–4×.** No architecture changes this — it's a vendor limit.

### 0.2 Why it's also unnecessary
Gamma (hence GEX and wall mass) is negligible for strikes far from spot — a strike 20% OTM contributes ≈ 0 to dealer gamma. Streaming deep tails burns the instrument budget on data that doesn't move walls, GEX, or the flip. Institutions window the chain precisely because the signal lives near ATM.

### 0.3 The three-tier options data strategy (full-chain accuracy without 100k streams)

| Tier | Source | Coverage | Cadence | Purpose |
|---|---|---|---|---|
| **T-Live** | WebSocket, scoped **near-ATM window** (±12 strikes, front expiry, dynamic re-center) | ~10–12k instruments (2 conns) | 30 s | Live walls / GEX / flip / regime — the strikes that carry the gamma |
| **T-Sweep** | **Option Chain REST** (1 req / 3 s, rotate underlyings) | **Full chain, every strike, all 215** | ~11 min full cycle | Catch wall relocations to strikes *outside* the live window; vendor-Greek cross-check |
| **T-EOD** | Bhav (existing pipeline) | **Full chain, every strike, authoritative** | nightly | System of record; walls/GEX from the complete settled chain; parity referee |

**Coverage guarantee:** any strike that matters for live GEX is in T-Live (30 s fresh). Any strike that *becomes* material (a wall jumping to a far strike on a block trade) is caught within one T-Sweep cycle (≤ 11 min) and pulls the T-Live window to re-center on it. The complete chain is reconciled every night by T-EOD. So the answer to "every strike" is: **yes for the strikes that matter, live; yes for the full chain, on an 11-minute rolling refresh; yes for the authoritative full chain, nightly** — a layered guarantee, not a single impossible firehose.

### 0.4 Strike-window sizing (concrete)
- Per underlying, front expiry: ATM ± 12 strikes = 25 strikes × 2 (CE/PE) = **50 contracts**.
- Stocks: 215 × 50 ≈ **10,750** (front expiry).
- Indices (NIFTY/BANKNIFTY/FINNIFTY/MIDCPNIFTY): weekly, denser → wider window (±20), still small count.
- **Total T-Live ≈ 11–12k instruments → conn #2 + #3.** Conn #1 = full-NSE spot (T0). Conn #4–5 spare.
- Window **re-centers** when spot drifts > 0.5 window-width from center: unsubscribe far wing, subscribe near wing (100-instrument batched messages). Also rebuilt daily from the scrip master (expiry rollovers).

---

## 1. System architecture

```
                          ┌──────────────────────── DHAN ────────────────────────┐
                          │  WebSocket ×3   ·   REST (historical/chain/orders)     │
                          └───────┬───────────────────────┬───────────────┬───────┘
                                  │ ticks                 │ chain sweep   │ orders
     ┌────────────────────────────▼───────┐   ┌───────────▼─────┐  ┌──────▼────────┐
     │ feed_handler (asyncio daemon)       │   │ chain_sweeper   │  │ order_manager │
     │  auth · subscribe · heartbeat/pong  │   │ (REST, 1/3s     │  │ (Super Order, │
     │  reconnect(manifest) · normalize    │   │  rotate 215)    │  │  risk caps)   │
     └───────┬──────────────────┬──────────┘   └───────┬─────────┘  └──────▲────────┘
             │ tick_bus (in-proc pub/sub)               │ full-chain         │ confirmed
     ┌───────▼───────┐  ┌───────▼────────┐      ┌───────▼─────────┐          │
     │ tick_journal  │  │ state_store    │◀─────┤ (far-strike      │   ┌──────┴────────┐
     │ (parquet/day) │  │ (in-mem: quote │      │  wall relocate)  │   │ risk_engine    │
     └───────────────┘  │ ·OI·1m bars)   │      └──────────────────┘   │ (size, heat)   │
                        └───┬────────┬───┘                             └────────────────┘
              ┌─────────────▼──┐  ┌──▼───────────────────────┐
              │ trigger_engine │  │ live_compute (30s)       │   reuses:
              │ armed levels,  │  │  walls·GEX·flip·regime·IV │   GreeksEngine, GammaAnalyzer,
              │ per-1m-bar     │  │  breadth·sector           │   MarketBreadthEngine,
              └───────┬────────┘  └──────────┬───────────────┘   CashMarketBreadthEngine,
                      │ events               │ live structure    StructureClassifier, build_playbook
              ┌───────▼────────┐   ┌─────────▼──────────────────┐
              │ event_bus →    │   │ bridge (localhost HTTP)     │
              │ alert_sink     │   │ live_snapshot.json          │
              │ (notif/tg)     │   └─────────┬───────────────────┘
              └────────────────┘             │ 5s poll
                                       HUD (live) + Streamlit (EOD/deep-dive)

   ── nightly ──▶ EOD backbone (poll_eod → daily_compiler → DuckDB) + historical_backfill
                  + backtest engine (win-prob refresh) + 15:35 parity
```

**Runtime model:** one long-lived async daemon (`run_live.py`) owns all Dhan connections; everything else is in-process (single-user scale needs no Kafka/Redis — in-proc pub/sub + in-mem store suffices; Redis noted as optional scale-out). The daemon is the *only* consumer of the trading token — the multi-tab websocket-starvation class of bug is impossible by construction.

---

## 2. Module layout (new code + reuse)

```
src/
  live/
    feed_handler.py       async Dhan WS: auth, (re)subscribe, heartbeat, normalize → tick_bus
    subscription_mgr.py   manifest builder; near-ATM window; dynamic re-center; daily rebuild
    tick_bus.py           in-process async pub/sub
    state_store.py        in-mem quotes/OI/bars keyed by security_id
    tick_journal.py       append-only parquet writer (batched)
    bar_aggregator.py     1-min OHLCV+OI bars from ticks
    live_compute.py       30s cadence; CALLS existing engines on live state
    chain_sweeper.py      REST Option-Chain rotation (T-Sweep), far-wall detection
    trigger_engine.py     armed-level evaluation on 1m-bar close
    event_bus.py          event emission + live_events jsonl
    bridge.py             localhost HTTP serving live_snapshot.json
  data/
    dhan_client.py        thin wrapper over dhanhq SDK (historical, chain, orders, funds)
    historical_backfill.py  daily(to-inception) + intraday(5y/90d-chunk) → parquet
  setups/
    base.py               Setup ABC (detect/backtest_def/enrich/validation/live_status)
    registry.py           central registry; section tagging
    breadth/ sector/ swing/ intraday/ longterm/ options/   setup implementations
  backtest/
    corpus.py             three-source loader (bhav · dhan-historical · tick-journal)
    engine.py             generalized from swing_backtester + flip_backtester
    report.py             win-prob / expectancy / bucketed stats; badge assignment
  orders/
    risk_engine.py        position sizing, portfolio heat, caps, refusals
    order_manager.py      assisted construction, Super Order legs, confirm gate, audit log
scripts/
  run_live.py             daemon entrypoint (market-hours scheduler)
  backfill_history.py     one-time + nightly Dhan historical pull
  build_dhan_map.py       (exists) extend: emit security_id + lot_size + segment

REUSED AS-IS / lightly adapted:
  src/processor.py · greeks_engine.py · analyzer.py · intelligence.py
  src/core/{breadth,cash_market_breadth,classifier,longitudinal,playbook,setups,config}.py
  src/services/database_service.py · daily_compiler.py · scripts/build_hud.py · hud/template.html
```

---

## 3. Component designs

### 3.1 feed_handler + subscription_mgr
- **Auth:** `dhanhq` SDK with `DHAN_CLIENT_ID` + `DHAN_ACCESS_TOKEN` from `.env`; validate token expiry at boot, refuse start if < 1 day.
- **Connections:** conn1 = T0 spot (Quote mode); conn2/3 = T-Live options + futures (Quote+OI); manifests from `subscription_mgr`.
- **Heartbeat:** respond to server ping (10 s); watchdog fires if no tick > 60 s in market hours.
- **Reconnect:** exponential backoff (1→60 s, jitter); on reconnect, resubscribe from the current manifest; alert after 3 consecutive failures.
- **Normalize:** packet → `{security_id, ts, ltp, oi?, ohlc?, depth?}` → `tick_bus`.
- **subscription_mgr:** builds the daily manifest from scrip master (`build_dhan_map` extended with security_id/lot/segment); maintains per-underlying strike window; emits subscribe/unsubscribe deltas (≤100/msg) on spot drift.

### 3.2 state_store + bar_aggregator + tick_journal
- **state_store:** dict keyed by security_id → latest quote, OI, session OHLC, rolling 1-min bars; O(1) reads for compute/trigger; thread-safe (async single-writer).
- **bar_aggregator:** closes 1-min bars on the minute boundary; emits `bar_close` events (trigger engine subscribes).
- **tick_journal:** batched append to `data/live/ticks_YYYYMMDD.parquet` (flush every N ticks / 5 s); this is the research + intraday-backtest substrate.

### 3.3 live_compute (30 s) — the reuse core
For each covered underlying, from state_store:
1. Build a live "greeks_slice" DataFrame (same shape `GreeksEngine`/`GammaAnalyzer` already consume).
2. Solve IV from option mids (existing BS), compute Greeks, GEX per strike.
3. Walls / gamma flip via the **exact** `intelligence.py:209-227` logic (max CE-GEX, max |PE-GEX|, overlap flip).
4. Gamma regime via `src/core/config` thresholds; classifier via `StructureClassifier`.
5. Breadth via `MarketBreadthEngine`; cash breadth via `CashMarketBreadthEngine` (DMA/McClellan seeded from `cash_market_prices.parquet` + live close proxy); sector via `get_sector`.
6. Write results to state_store; diff vs prior cycle → emit `REGIME_CROSS`/`WALL_RELOCATED`/`IV_EVENT`.
- **Same functions as EOD** → zero formula drift → 15:35 parity is meaningful.

### 3.4 chain_sweeper (T-Sweep)
- Rotates the 215 underlyings through the Option-Chain REST at 1 req/3 s (≈ 11 min/cycle).
- Detects walls forming on strikes outside the live window → instructs `subscription_mgr` to re-center that name; provides vendor Greeks for a cross-check gauge.
- Purely additive; failure degrades to T-Live + T-EOD only.

### 3.5 trigger_engine
- Loads the **armed book** at boot: yesterday's `daily_setups` + today's registered live setups' levels.
- On each `bar_close`: evaluate only armed levels (O(armed)) → status machine WAITING→TRIGGERED→INVALIDATED with debounce + one-shot/day.
- Confirmation on **1-min bar close**, not raw tick (kills stop-hunt noise). Emits events → alert_sink.
- **Replay mode:** same engine over a recorded tick_journal → deterministic event log = the test harness *and* the intraday backtest executor.

### 3.6 Setup framework + backtest engine
- `Setup` ABC (PRD §3): `detect(state) · backtest_def · enrich(state) · validation · live_status`.
- `backtest/engine.py` generalizes the two existing backtesters: pluggable entry/exit/horizon/cost; forward returns; cost-adjusted expectancy; win rate; bucketed stats; `min_trades` gate; badge assignment (VALIDATED/THIN/UNVALIDATED/NEGATIVE).
- `corpus.py` serves three sources (bhav / Dhan-historical / tick-journal) behind one interface.
- **Fidelity gate:** the current 10 options setups + flip detector, re-expressed as `Setup`s, must reproduce their existing backtested numbers before new setups are added.

### 3.7 order_manager + risk_engine (assisted one-click)
- `risk_engine`: qty = floor(`RISK_PER_TRADE` ÷ per-unit risk to invalidation); enforce `MAX_OPEN_RISK` (portfolio heat), `MAX_POSITIONS`, sector cap; **refuse with reason** on breach.
- `order_manager`: builds a **Super Order** (entry + target + SL legs) via `dhanhq` SDK; options build exact legs from the desk pick; **review card → explicit human confirm → send**; every order + risk decision logged to `orders_log`. No auto-send in v1.

### 3.8 bridge + HUD
- `bridge.py`: localhost HTTP serving `live_snapshot.json` (quotes, live structure, armed statuses, events).
- HUD polls 5 s, shows ● LIVE, live prices/structure/triggers; degrades to EOD view when bridge absent. Streamlit stays EOD/deep-dive.

---

## 4. Tech stack
- **Language:** Python 3.11 (existing). `asyncio` for the daemon.
- **Dhan:** official `dhanhq` SDK + `websockets`; REST via SDK.
- **Storage:** DuckDB + parquet (existing); in-mem dict/Polars for live state. **No new infra** at single-user scale (Redis/Kafka optional future scale-out).
- **UI:** existing HUD (plain HTML/JS) as live surface; Streamlit retained.
- **Testing:** pytest (existing suite); deterministic replay harness.
- **Scheduling:** IST market-hours scheduler + NSE holiday calendar in `run_live.py`.

---

## 5. Implementation plan (step-by-step, dependency-ordered)

Legend: **⟳** reuses existing code · **★** new · effort {S,M,L}.

### Phase 0 — Foundation (feed + framework)
| # | Task | Notes | Eff |
|---|---|---|---|
| 0.1 | Confirm Dhan **data + trading** token; `.env` plumbing; token-expiry guard | blocks all | S |
| 0.2 | Extend `build_dhan_map.py` → security_id + lot_size + segment ⟳ | scrip master already downloaded | S |
| 0.3 | `dhan_client.py` over `dhanhq` SDK (historical, chain, orders, funds) ★ | thin wrapper | M |
| 0.4 | `historical_backfill.py`: daily→inception + intraday 5y/90d-chunk → parquet ★ | one-time + nightly incremental | M |
| 0.5 | `feed_handler` + `subscription_mgr`: 1 conn spot, heartbeat, reconnect, manifest ★ | de-risk WS first | L |
| 0.6 | `tick_bus` + `state_store` + `bar_aggregator` + `tick_journal` ★ | in-proc substrate | M |
| 0.7 | `Setup` ABC + `registry` + `backtest/engine.py` (generalize existing) ★⟳ | fidelity gate vs current setups | L |
| 0.8 | Add options T-Live conns + `chain_sweeper` (T-Sweep) ★ | three-tier options data | L |
| **Gate** | full session recorded gap-free; kill→reconnect<10s; backtest engine reproduces current setup numbers; live token independent of Dhan web session | | |

### Phase 1 — Breadth + Sector (first shipped modules)
| # | Task | Eff |
|---|---|---|
| 1.1 | `live_compute` breadth path ⟳ (MarketBreadthEngine + CashMarketBreadthEngine on live state) | M |
| 1.2 | Sector aggregation ⟳ (`get_sector`), live RS vs NIFTY | M |
| 1.3 | `bridge.py` + HUD live mode (● LIVE, 5s poll) ★⟳ | M |
| 1.4 | 15:35 parity job (live snapshot vs next-day EOD) ★ | M |
| **Gate** | live breadth/sector reconstruct EOD within tolerance | |

### Phase 2 — Swing Centre + pattern engine + unified feed
| # | Task | Eff |
|---|---|---|
| 2.1 | Pattern detectors: VCP, bases, breakout, pullback-to-MA, RS-leader ★ | L |
| 2.2 | Register as Setups; backtest on Dhan daily history (to inception) ⟳ | M |
| 2.3 | SMC/ICT overlay drawers (unbadged) ★ | M |
| 2.4 | Unified scanner feed (tagged rows) + HUD surface ★ | L |
| 2.5 | Options enrichment join for T2 names ⟳ | S |
| **Gate** | only positive-expectancy swing setups badged VALIDATED | |

### Phase 3 — Options Desk (buy / sell / strategy)
| # | Task | Eff |
|---|---|---|
| 3.1 | Live structure per T2 name (walls/GEX/flip/regime, IV) ⟳ | M |
| 3.2 | Three books; reuse `build_playbook` + v2 decision matrix ⟳ | L |
| 3.3 | Option-payoff backtest (v2 Phase 4 engine) → per-template badges ★ | L |
| 3.4 | Live premium tracking on desk legs | M |
| **Gate** | live walls/GEX parity ≥90% strike-exact; templates badged by payoff backtest | |

### Phase 4 — Intraday Centre
| # | Task | Eff |
|---|---|---|
| 4.1 | Candle setups (ORB/VWAP/gamma-cross) ★ | M |
| 4.2 | Backtest on **backfilled 5y intraday** history ⟳ (win-prob at launch) | M |
| 4.3 | Microstructure events (OI-blast) from tick journal (accruing) ★ | M |
| **Gate** | candle setups validated at launch; replay-deterministic | |

### Phase 5 — Long-Term
| # | Task | Eff |
|---|---|---|
| 5.1 | Weekly/monthly setups (stage analysis, long bases) + positioning ★ | M |
| 5.2 | Fundamentals slot: interface + no-op default ★ | S |
| **Gate** | weekly-setup backtest on long daily history | |

### Phase 6 — Order + Risk layer
| # | Task | Eff |
|---|---|---|
| 6.1 | `risk_engine` (sizing, caps, heat) ★ | M |
| 6.2 | `order_manager` Super Order + confirm gate + audit ★ | L |
| 6.3 | Small-size live validation | M |
| **Gate** | caps enforced; SL/target attach; zero un-confirmed sends | |

**Critical path:** 0 → 1 (committed first). 2/3/4/5 parallelizable on the foundation. 6 last (after live-forward trust). v2 Phase-1 cleanup (`main.py`/`signal_generator` deletion) lands before 0.5 (shared startup scripts).

---

## 6. Data model (additive)
```
data/live/ticks_YYYYMMDD.parquet        raw normalized ticks
data/live/bars1m_YYYYMMDD.parquet       1-min bars
data/live/live_snapshot.json            ephemeral live state (bridge)
data/live/live_events_YYYYMMDD.jsonl    events/alerts/triggers
data/history/daily/{symbol}.parquet     Dhan daily backfill (to inception)
data/history/intraday/{tf}/{symbol}.parquet  Dhan intraday backfill (5y)
backtest_cache.duckdb                   per-setup win-prob/expectancy (nightly)
orders_log_YYYYMMDD.jsonl               order + risk audit
DuckDB / compiled parquet               UNCHANGED (EOD system of record)
```

## 7. Testing & correctness
- **Replay harness:** trigger_engine over recorded tick_journal → deterministic event log (regression + intraday backtest).
- **Parity job (15:35):** live walls/GEX/IV/breadth vs next-morning EOD; alarm on drift; INDICATIVE watermark if parity fails.
- **Setup fidelity gate:** current setups reproduce existing backtest numbers through the new engine.
- **Unit tests:** per detector, per risk-cap, per order construction (pytest, extend current suite).
- **Backfill validation:** Dhan daily vs bhav closes cross-check on overlap window (catches vendor/adjustment differences).

## 8. Ops & failure
- Market-hours scheduler + NSE holiday calendar; expiry-day manifest rebuild.
- Monitoring: per-conn packet rate, last-tick-age/symbol, compute-cycle duration, event counts, chain-sweep progress.
- **Failure stance:** live layer may die without corrupting anything; EOD authoritative; HUD degrades to EOD; daemon auto-restarts and rebuilds from ticks + EOD baseline.

## 9. Performance budget
| Path | Target |
|---|---|
| tick → state_store | < 50 ms |
| trigger check (bar close → alert) | ≤ 2 s |
| live_compute full covered-universe pass | ≤ 5 s (30 s cadence) |
| chain_sweep full cycle | ~11 min (vendor 1/3s) |
| HUD poll | 5 s |

## 10. Open technical questions
1. Trading-token permissions provisioned (Phase 6)? — account setting.
2. `dhanhq` SDK feature-complete for our WS+order needs, or thin custom client where it's gappy?
3. Intraday backfill timeframe priority (5-min primary?) and retention of raw ticks (recommend 30-day rolling raw; 1-min bars forever).
4. Strike-window width per underlying — fixed ±12, or volatility-scaled? (recommend vol-scaled: wider for high-IV names.)
5. Redis/scale-out ever needed, or single-process in-mem is the permanent target?
