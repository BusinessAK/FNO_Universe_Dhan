# PRD — Vanguard Platform v1: Multi-Engine Live Trading Terminal

| | |
|---|---|
| **Product** | Vanguard — live, backtested, multi-horizon NSE trading terminal |
| **Version** | Platform v1.0 |
| **Author** | Quant/Platform (drafted with Claude — senior-architect + institutional-trader review) |
| **Date** | 15 Jul 2026 |
| **Status** | 🔒 **LOCKED — Baseline v1.0** (15 Jul 2026). Scope frozen as the implementation baseline; material changes require re-approval + version bump. Build begins on explicit go-ahead. |
| **Supersedes** | Folds in `PRD_vanguard_v2.md` (Strategy Desk) and `PRD_realtime_v1.md` (realtime options) as sub-components, not standalone tracks |

---

## 1. Product DNA (the one rule every component obeys)

> **Every setup, in every section, is a detector with a backtested win-probability, enriched with OI / Greeks / gamma exposure where the instrument allows — surfaced in one unified tagged feed, wired to Dhan charts, executable via assisted one-click orders.**

Nothing ships as a "signal" without a backtest. This is not new discipline — it is the exact rule we already enforced on structure flips (killed for negative edge) and setups (thresholds tuned on measured distributions). Platform v1 makes it the universal contract.

### Scope decisions (locked via scoping Q&A, 15 Jul)
| Decision | Answer |
|---|---|
| Data source | **Dhan API only** (market data + trading). No fundamentals feed. |
| Long-Term fundamentals | **Plug-in slot for later** — ships technical + positioning; fundamentals provider added post-v1. |
| Product structure | **Unified scanner + tags** — one idea feed; every row tagged {horizon, methodology, universe, validation}. |
| Order layer | **Assisted one-click** — pre-filled qty (risk-%) + SL/target (setup levels); human confirms every order. |
| Build first | **Foundation + Market Breadth / Sector Strength**. |
| Realtime scope | **Everything live**, **reusing the existing bhav pipeline** as historical/backtest/parity backbone. |
| Chart patterns | **Split by type** — VCP/bases/breakouts algorithmically detected + backtested; SMC/ICT as visual overlays (no edge claims). |

### 1.1 Universe tiers (defined ONCE; sections reference a tier)

The platform has **three concentric universes, not six.** The earlier confusion came from
naming a universe per section — instead we define the tiers once and each section points at
one. Because the tiers are strict subsets (T2 ⊂ T1 ⊂ T0 by security), a **single** full-NSE
spot subscription physically covers all price needs, which also simplifies the live feed.

| Tier | Name | Members | Role | Used by |
|---|---|---|---|---|
| **T0** | Breadth universe | Full NSE EQ (~2,000) | Market-wide *participation* stats only — **never a trade list** | Market Breadth, Sector Strength |
| **T1** | Tradable universe | Nifty 500 | Everything actually scanned and traded | Swing, Intraday, Long-Term |
| **T2** | Options universe | F&O (~215, dynamic) | The T1 subset with liquid options | Options Desk; OI/Greeks/gamma **enrichment** on any T1 setup whose symbol is here |

**Why not one universe everywhere:** breadth *is* a whole-market measure (McClellan/A-D over
just Nifty 500 would be a different, narrower statistic), so T0 stays full-NSE. But you only
ever put on a position in a liquid name, so every *tradable* section lives in T1, and options
structure only exists for T2. Enrichment attaches by *symbol membership*, not by section — a
T1 swing breakout on an F&O name shows its dealer-positioning context; a non-F&O name shows "—".
Open item: whether Long-Term should widen beyond Nifty 500 once fundamentals arrive (§12).

---

## 2. Architecture — reuse the pipeline, stream on top

### 2.1 Two-layer model — why EOD survives "everything live"

"Everything live" applies to *scanning, triggering, and enrichment* — **not** to the system
of record. The two layers do different jobs; neither is redundant.

| Layer | Cadence | Job | Authority |
|---|---|---|---|
| **EOD backbone** (existing pipeline, repurposed) | nightly | canonical corrected history · backtest corpus · DMA/McClellan baselines · nightly win-prob refresh · 15:35 parity referee | **system of record** |
| **Realtime surface** (new) | live | scan T0–T2 · fire triggers · enrich with live Greeks/GEX · feed the scanner | **provisional** until EOD finalizes |

Live prices are provisional (last tick ≠ official settlement; illiquid strikes go stale) and
EOD is the only thing that can *audit* the live layer via the 15:35 parity check. A realtime
outage costs nothing because the next-morning EOD compile fills the gap. **Going realtime makes
the EOD compile more important, not less** — it is now also the referee that keeps live honest.

### 2.2 Data & compute flow

```
        ┌───────────────────────── EXISTING PIPELINE (repurposed) ─────────────────────────┐
        │  poll_eod → daily_compiler → DuckDB + session_history + parquet                    │
        │  cash_market_builder → cash_market_prices.parquet                                  │
        │  intelligence.py (GreeksEngine · GammaAnalyzer · walls/flip/GEX)                    │
        │  breadth.py · cash_market_breadth.py · classifier · longitudinal · playbook         │
        │  ► NEW ROLE: nightly historical corpus + DMA/McClellan baselines + 15:35 parity     │
        └───────────────────────────────────────┬───────────────────────────────────────────┘
                                                 │ baselines, history, validated setups
                                                 ▼
   Dhan WS (×N)     ┌───────────────────┐   ┌────────────────────────────────────────────┐
  spot/opts/fut ──▶ │ feed_handler      │──▶│ live state store (in-mem) + tick journal   │
                    │ (async daemon)    │   │  quotes · OI · 1-min bars · session stats   │
                    └───────────────────┘   └───────┬─────────────────────┬───────────────┘
                                                    │                     │
                              ┌─────────────────────▼──┐   ┌──────────────▼──────────────────┐
                              │ live compute engine     │   │ setup + backtest framework      │
                              │ 30s: walls/GEX/IV/regime │   │  · Setup contract (detector +   │
                              │ breadth/sector (REUSES   │   │    backtest def + enrichment)   │
                              │ existing engines)        │   │  · unified backtest engine      │
                              └───────────┬─────────────┘   │    (generalizes swing/flip)     │
                                          │                 │  · win-prob per setup, cached   │
                              ┌───────────▼─────────────┐   └──────────────┬──────────────────┘
                              │ trigger engine          │                  │
                              │ armed levels, per-bar    │                  ▼
                              └───────────┬─────────────┘   ┌──────────────────────────────────┐
                                          │                 │ UNIFIED SCANNER FEED (tagged)     │
                          ┌───────────────▼───────────┐     │  row = {sym, horizon, method,     │
                          │ alert sink + order layer   │     │  setup, win_prob, levels, OI/gex, │
                          │ (assisted one-click, Dhan  │◀────┤  validation badge, live status}   │
                          │ trading API)               │     └──────────────┬───────────────────┘
                          └────────────────────────────┘                    │ 5s poll
                                                                     HUD (live surface) +
                                                                     Streamlit (deep-dive/EOD)
```

**Load-bearing principle:** the live compute engine imports and calls the *same* `GreeksEngine`, `GammaAnalyzer`, `MarketBreadthEngine`, `CashMarketBreadthEngine`, `StructureClassifier`, and `build_playbook` used at EOD — fed streaming inputs instead of bhav rows. One math source, zero drift. The 15:35 parity job proves live == batch daily.

### 2.3 Connection budget ("everything live" feasibility)

Because the tiers are subsets, **one** spot subscription streams the entire breadth *and*
tradable universe; options structure is the only thing needing a second connection.

| Conn | Subscription | Count | Powers |
|---|---|---|---|
| 1 | **T0** full-NSE EQ spot (Quote) | ~2,000 | Breadth, Sector, and all Swing/Intraday/Long-Term prices + triggers (T1 ⊂ T0) |
| 2 | **T2** F&O futures + scoped near-ATM options | ~2,000 | Options Desk, live Greeks/GEX, gamma enrichment |
| 3 | Index + index options (weeklies) | ~500 | Index rows, index structure/breadth |
| 4–5 | Spare / reconnect failover / manual-web headroom | — | resilience + growth |

Within Dhan's 5×5,000 limit. Full deep option chains for all 215 exceed budget → **scoped
near-ATM windows** with dynamic re-centering (per `PRD_realtime_v1.md §2`).

### 2.4 Dhan API surface (verified against docs, 15 Jul 2026)

| Capability | What Dhan provides | PRD use | Limit |
|---|---|---|---|
| **Live Feed** (WebSocket) | Ticker/Quote/OI/Full packets: price, OHLC, volume, OI, 5-level depth. **No Greeks/IV.** | Live scanning, triggers, spot/OI | 5 conn × 5,000; 100/subscribe msg |
| **Option Chain** (REST) | Per-strike OI, volume, LTP, bid/ask, **Greeks + IV** | Slow-lane IV sanity vs local BS | **1 req / 3 s**, one underlying+expiry |
| **Historical — Intraday** (REST) | 1/5/15/25/60-min OHLC + Volume + OI(opt), **last 5 years** | **Backfill intraday backtest corpus** | 90-day window/request; Data 5/s |
| **Historical — Daily** (REST) | OHLC + Volume + OI(opt), **back to inception** | Swing/Long-Term corpus far beyond our 257-session bhav | Data 5/s |
| **Orders** (REST) | Market/Limit/SL + **Bracket, Cover, Super Order** (entry+target+SL legs) + Forever/GTT | Assisted one-click with native SL+target | 10/s · 250/min · 7,000/day · 25 mods/order |
| **Positions/Funds/Margin** (REST) | Holdings, positions, funds, margin calc | Risk caps, portfolio heat, sizing | Non-Trading 20/s |
| **Scrip master** (CSV) | Security IDs, symbols, lot sizes, segments | WS subscription + `build_dhan_map.py` (done) | daily refresh |
| **Official SDK** | `dhanhq` Python client (dhan-oss/DhanHQ-py) wraps feed/data/orders | Cuts feed-handler + order build risk | pin version |

**Two findings that change the PRD:**
1. **Intraday history exists (5 yr, 90-day chunks)** → the Intraday Centre is *backtestable from day one* by backfilling — **not** "insufficient history for weeks." (Corrects an earlier caveat.)
2. **Daily history to inception** → the price-based backtest corpus (Swing/Long-Term) extends *years* beyond our 257-session bhav set. The bhav pipeline stays the source for *options-structure* history (per-strike GEX/walls, which candles can't reconstruct cheaply); Dhan historical becomes the *price* history for pattern setups. Both feed the one backtest engine.

---

## 3. The Setup Contract (the universal abstraction — build FIRST)

Every setup in every section is a registered object implementing one interface. This is the platform's backbone and the reason "backtested win-prob everywhere" is achievable rather than 50 bespoke features.

```
Setup:
  id, name, section {breadth|sector|swing|intraday|longterm|opt_buy|opt_sell|opt_strategy},
  universe, methodology {options|pattern|positioning|breadth},
  detect(state) -> None | {fires: bool, direction, trigger, invalidation, target, evidence{}}
  backtest_def  -> {entry_rule, exit_rule, horizon, cost_model}
  enrich(state) -> {oi, greeks, gex, gamma_regime}   # where instrument has options, else {}
  validation    -> {win_rate, expectancy, n_trades, by_bucket, badge}  # from backtest cache
  live_status   -> WAITING | TRIGGERED | INVALIDATED | EXPIRED
```

| Step | Requirement |
|---|---|
| 3.1 | **Setup registry** — central catalog; each section registers its setups. Extends existing `src/config/setup_registry.py`. |
| 3.2 | **Unified backtest engine** — generalize `swing_backtester.py` + `flip_backtester.py` into one engine any Setup plugs into: forward-return by horizon, cost-adjusted expectancy, win rate, bucketed stats, `min_trades` gate. Runs nightly over a **three-source corpus**: (a) bhav → options-structure history (walls/GEX/OI), (b) Dhan historical candles → price/pattern history (daily to inception, intraday 5 yr), (c) accumulated tick journal → live-native microstructure events. |
| 3.3 | **Validation badge** — `VALIDATED` (positive cost-adjusted expectancy, n ≥ 100), `THIN` (positive, 30–100), `UNVALIDATED` (< 30), `NEGATIVE` (fails). Badge is computed, never asserted. A `NEGATIVE` setup is shown struck-through or hidden by default — the flip lesson, institutionalized. |
| 3.4 | **Win-prob surface** — every live scanner row shows its setup's historical win rate + expectancy + sample size + freshness of the backtest. |
| 3.5 | **Enrichment layer** — for F&O names, attach live OI/Greeks/GEX/gamma-regime to any setup regardless of section (a swing breakout on an F&O name shows its options context). Non-F&O names show `—`. |

**Acceptance:** the current 10 options setups + the structure-flip detector re-expressed as registered Setups reproduce their existing backtested numbers through the new engine (proves the abstraction is faithful before new setups are added).

---

## 4. Sections — step-by-step components

### 4.1 Market Breadth (Phase 1 — build first)
| Step | Requirement |
|---|---|
| B.1 | Live full-NSE breadth from Conn-1 spot ticks: advancers/decliners, A/D ratio, % up/down, net advances — recomputed 30s. **Reuses** `MarketBreadthEngine` structure and `CashMarketBreadthEngine` for A/D. |
| B.2 | Live DMA participation / McClellan / new-highs-lows: DMAs and 52w extremes need history → seed from `cash_market_prices.parquet` (EOD baseline) + today's live close proxy; McClellan EMAs continue from EOD anchor. This is the "reuse pipeline" pattern made concrete. |
| B.3 | Live NIFTY overlay + intraday breadth-divergence flag (the June/July divergence read, live). |
| B.4 | HUD panel = the enhanced Net Breadth + Cash Internals we already built, now on live data with a ● LIVE badge; 15:35 parity vs EOD compile. |
| **Accept** | Live breadth at 15:29 reconstructs next-morning EOD breadth within tolerance. |

### 4.2 Sector Strength (Phase 1)
| Step | Requirement |
|---|---|
| S.1 | Live sector aggregation via `src/config/sector_mapping.py get_sector`: per-sector advancers, avg change, breadth, relative strength vs NIFTY — 30s. |
| S.2 | Sector rotation view: leaders/laggards, intraday RS shift, capital-rotation ranking (reuses the EOD sector-flow table logic, live). |
| S.3 | For F&O sectors, overlay aggregate sector OI/GEX tilt (enrichment layer). |
| **Accept** | Sector ranks match EOD sector-flow table at close within tolerance. |

### 4.3 Swing Centre (Phase 2 — first setup+pattern section)
| Step | Requirement |
|---|---|
| SW.1 | **Chart-pattern engine** (see §5) supplies objective setups: VCP, flat/ascending base breakouts, pullback-to-MA, 52w-high momentum, relative-strength leaders. |
| SW.2 | Each registered as a Setup with backtest_def (entry next-open, exit at N-day/target/stop) → win-prob badge. |
| SW.3 | Positioning enrichment for F&O names: is the swing breakout supported by dealer walls / bullish OI flow? (confluence with the options core). |
| SW.4 | Universe **T1** (Nifty 500); live prices drive live status (WAITING→TRIGGERED on breakout level); T2 names additionally carry options enrichment. |
| **Accept** | Backtest report per swing setup; only positive-expectancy setups get VALIDATED badge; SMC/ICT appear as overlays, unbadged. |

### 4.4 Options Desk (Phase 3) — three books
Reuses the entire current options core (`intelligence.py`, walls/flip/GEX, `build_playbook`, v2 Strategy Desk decision matrix).
| Book | Content |
|---|---|
| **Option Buying** | Long-premium setups: GAMMA_SQUEEZE, COIL/PINCH breaks, IV-cheap directional — where being long gamma/vega is the edge. Each backtested on option-payoff replay (v2 Phase 4 engine). |
| **Option Selling** | Short-premium setups: wall-anchored credit spreads, iron condors in pinned regimes, IV-rich mean-reversion. Short strikes at GEX walls (dealer-defense monetization). |
| **Strategies (both legs)** | Defined-risk structures: verticals, straddles/strangles, condors — the v2 Strategy Desk decision matrix (§6 of that PRD), now live with streaming premiums. |
| OD.* | Every pick carries live Greeks/GEX/gamma-regime, backtested win-prob by template×IV-bucket, and assisted-order legs (strikes snap to live-traded strikes, premiums from live mids). |
| **Accept** | Live walls/GEX parity ≥ 90% strike-exact vs EOD; option-payoff backtest gates each template's badge. |

### 4.5 Intraday Centre (Phase 4)
| Step | Requirement |
|---|---|
| IN.1 | Live-native setups: opening-range break, VWAP reclaim/reject, gamma-flip crossover (REGIME_CROSS), coil-firing (RV expansion), OI-blast follow. Reuses realtime event vocabulary from `PRD_realtime_v1.md §4`. |
| IN.2 | **Candle setups** (ORB, VWAP, gamma-cross) backtested on **Dhan intraday history backfilled at build** (5 yr of 1/5/15-min bars) → win-probs available from day one. **Microstructure setups** (OI-blast, sub-minute) still accrue from the go-live tick journal (candle history can't reconstruct them). |
| IN.3 | Gamma-aware for F&O names: intraday setups show live dealer positioning as context/filter. |
| **Accept** | Candle setups carry a validated win-prob at launch (5-yr backfill); microstructure setups show "accruing" until ≥ N live sessions; all setups replay deterministically over recorded sessions. |

### 4.6 Long-Term (Phase 5)
| Step | Requirement |
|---|---|
| LT.1 | Weekly/monthly technical setups: stage-analysis (Weinstein), long-base breakouts, multi-month RS leaders, long-horizon trend structure. |
| LT.2 | Long-horizon positioning: multi-week OI trend, sustained gamma regime, sector-tailwind alignment. |
| LT.3 | **Fundamentals slot**: interface defined + stubbed; section ships technical+positioning; wired when a fundamentals provider is added (Screener/Tijori/Trendlyne/Tickertape). Clearly labeled "fundamentals pending". |
| **Accept** | Weekly-setup backtest on the long OHLC history; fundamentals slot has a documented contract and a no-op default. |

### 4.7 Index-Specific (cross-cutting, threaded through sections)
| Step | Requirement |
|---|---|
| IX.1 | Dedicated NIFTY/BANKNIFTY/FINNIFTY/MIDCPNIFTY views: weekly-expiry-aware option structure, index gamma flip, index-level breadth/regime. |
| IX.2 | Expiry-day handling reuses the existing `intelligence.py` weekly-rollover filter (already battle-tested). |
| IX.3 | Index setups (buy/sell/strategy) as their own tagged rows in the unified feed. |

---

## 5. Chart-Pattern Engine (split-by-type, feeds Swing/Intraday/Long-Term)

| Tier | Patterns | Treatment |
|---|---|---|
| **Objective (backtested, badged)** | VCP (contraction sequence + volume dry-up + pivot), flat/ascending/cup bases, breakout-from-consolidation, pullback-to-rising-MA, 52w-high proximity, inside-bar/NR7 compression | Algorithmic detectors → registered Setups → forward-return backtest → VALIDATED/NEGATIVE badge. Ships only what validates. |
| **Discretionary (overlay, unbadged)** | SMC/ICT: order blocks, fair-value gaps, liquidity sweeps, break-of-structure, change-of-character | Detected + drawn as **visual overlays** on the Dhan/HUD chart context. **No win-prob claim.** Labeled "visual aid — not backtested." Optional per-user toggle. |
| **Universe** | Nifty 500 daily/weekly for swing/long-term; F&O/Nifty500 intraday bars for intraday patterns | |

**Rationale (trader hat):** VCP and base breakouts have decades of documented, codifiable edge — we can prove or kill them. SMC/ICT are discretionary frameworks whose edge is trader-dependent and resists honest backtesting; presenting them with a fake win-% would violate the platform's core promise. Overlay-only keeps them useful without lying.

---

## 6. Unified Scanner Feed (the product surface)

| Step | Requirement |
|---|---|
| UF.1 | Single feed; each row = `{symbol, horizon, methodology, universe, setup, direction, win_prob, expectancy, n_trades, validation_badge, live_status, trigger, invalidation, target, oi/greeks/gex (if F&O), sector, chart_link}`. |
| UF.2 | Free-filter by any tag; default sort by validated expectancy × live-status urgency. |
| UF.3 | Live status transitions (WAITING→TRIGGERED→INVALIDATED) drive alerts. |
| UF.4 | Row → dossier (existing HUD dossier, extended) → Dhan chart (existing integration) → assisted order. |
| UF.5 | `NEGATIVE`/unvalidated setups hidden by default, revealable via filter (transparency without noise). |

---

## 7. Order + Risk Layer (Phase 6 — assisted one-click)

**Governing stance: human confirms every order; the system never auto-sends in v1.**
| Step | Requirement |
|---|---|
| OR.1 | Dhan **Trading API** integration (separate from data API): order placement, positions, funds, margins. Confirm token/permissions (open question). |
| OR.2 | **Pre-fill from setup**: quantity = floor(risk_budget ÷ per-unit risk to invalidation); stop = setup invalidation; target = setup target; all editable before send. |
| OR.3 | **Risk framework (config)**: `RISK_PER_TRADE` (₹ or % of capital), `MAX_OPEN_RISK` (portfolio heat cap), `MAX_POSITIONS`, per-sector concentration cap. Order refused (with reason) if it breaches a cap. |
| OR.4 | **Order types**: Dhan-native **Super Order** (entry + target + stop-loss legs, modifiable) and Bracket/Cover so risk is defined at entry; **Forever/GTT** for resting swing/long-term orders. Options orders build the exact legs from the desk pick. Uses the official `dhanhq` SDK. |
| OR.5 | **Confirmation gate**: a review card (instrument, side, qty, SL, target, max risk ₹, margin, portfolio-heat-after) → explicit confirm → send. Every order logged. |
| OR.6 | **No auto-execution, no algo loop** in v1. Full automation is a separate future PRD with its own risk review. |
| **Accept** | Paper/small-size live test: pre-fills correct, caps enforced, SL/target attach, refusals logged; zero un-confirmed sends. |

---

## 8. Phasing (aligned to "Foundation + Breadth first")

**Feed-live and section-shipped are decoupled.** Phase 0 stands up the *full* live feed (all
tiers streaming); sections then light up progressively **on top of already-live data**. So
"everything live" is true from Phase 0, even though the Options Desk UI or Intraday Centre
arrive later. Options Desk (Phase 3) reuses the most existing code and *may* be parallel-tracked
with Breadth if capacity allows — but the committed critical path is Foundation → Breadth first.

| Phase | Deliverable | Depends on |
|---|---|---|
| **0 — Foundation** | Feed daemon (reuse `build_dhan_map` for IDs+lots), tick journal, live state store, live compute engine wired to existing engines, **Setup contract + unified backtest engine**, 15:35 parity job | Dhan data API token |
| **1 — Breadth + Sector** | Live Market Breadth (full NSE) + Sector Strength; HUD live mode | Phase 0 |
| **2 — Swing Centre** | Pattern engine (objective badged + SMC/ICT overlay) + swing setups on Nifty 500; unified scanner feed goes live | Phase 0–1 |
| **3 — Options Desk** | Buy / Sell / Strategy books on F&O 215, live Greeks/GEX, option-payoff backtest (v2 Phase 4) | Phase 0; folds in v2 |
| **4 — Intraday Centre** | Live intraday setups; backtested on accrued tick journal | Phase 0 + ≥ N weeks of ticks |
| **5 — Long-Term** | Weekly/monthly setups + positioning; fundamentals slot stubbed | Phase 0 |
| **6 — Order + Risk** | Assisted one-click via Dhan trading API, risk caps, confirmation gate | All sections + live-forward trust |
| **Pre-req** | `PRD_vanguard_v2.md` Phase-1 cleanup (delete `main.py`/`signal_generator`) lands first — realtime P0 touches the same startup scripts | — |

---

## 9. Data model (all additive)
```
data/live/ticks_*.parquet          raw normalized packets (research + intraday backtest)
data/live/bars1m_*.parquet         1-min bars (kept indefinitely)
data/live/live_snapshot.json       current state for HUD (ephemeral)
data/live/live_events_*.jsonl      events/alerts/triggers (kept — research)
setup_registry (code)              every setup + backtest metadata
backtest_cache (parquet/duckdb)    per-setup win-prob, refreshed nightly
orders_log_*.jsonl                 every order + risk decision (audit)
DuckDB / compiled parquet          UNCHANGED — historical corpus + baselines
```

## 10. Risks
| Risk | Mitigation |
|---|---|
| "Everything live" over connection budget | Scoped option windows; full NSE spot fits 1 conn; documented in §2 |
| Backtest-everywhere invites overfitting | Theory-first setups; `min_trades` gate; out-of-sample as tick history grows; NEGATIVE badge is honored, not hidden |
| Intraday win-prob trust | Largely resolved: candle setups backfilled from Dhan's 5-yr intraday history; only sub-minute microstructure events show "accruing" until enough live sessions |
| Fundamentals promised but absent | Explicitly slotted-for-later; section labeled; no fake fundamental scores |
| Order routing on unproven setups | Assisted-only (human confirm); risk caps; automation deferred to separate PRD |
| SMC/ICT presented as validated | Overlay-only, unbadged, labeled visual aid |
| Live-vs-EOD silent divergence | 15:35 parity gate; INDICATIVE watermark on failure |
| Scope = multi-quarter | Strict phase gates; each section ships independently on the shared foundation |

## 11. Success metrics
| Metric | Target |
|---|---|
| Setup framework fidelity | current setups reproduce existing backtest numbers through new engine |
| Live parity (breadth/walls/GEX) | ≥ 90% strike-exact walls; breadth within tolerance at close |
| Trigger latency | ≤ 2s bar-close → alert |
| Validated-setup coverage | each shipped section has ≥ 1 VALIDATED setup before it's promoted from "beta" |
| Order safety | zero un-confirmed sends; 100% risk-cap enforcement |
| The honest one | at 4 weeks per section: setups the operator actually acted on / found decision-relevant; zero-score setups cut |

## 12. Remaining open questions (refinement-level; not blocking the PRD)

*Resolved during scoping (no longer open): product structure = unified tagged scanner;
index-specific = threaded as tagged rows (not a separate top section); universe = the T0/T1/T2
tiers in §1.1.*

1. **Dhan Trading API** — order-placement permissions/token confirmed on your account? (Blocks Phase 6 only.)
2. **Risk defaults** — `RISK_PER_TRADE` (₹ amount or % of capital?), `MAX_OPEN_RISK`, `MAX_POSITIONS` — your numbers.
3. ~~**Intraday history**~~ — **RESOLVED:** Dhan provides 5 yr of intraday candles; we backfill at build, so candle-based intraday setups have win-probs from day one. (Only sub-minute microstructure events accrue from go-live.)
4. **Setup catalog per section** — do you have specific setups in mind, or should I propose the starter catalog (VCP/bases/RS for swing; ORB/VWAP/gamma-cross for intraday; Weinstein-stage for long-term) for you to prune?
5. **Long-Term universe** — stay at T1 (Nifty 500) for v1, or widen to small/midcaps once the fundamentals provider is added? (T0/T1/T2 tiers otherwise confirmed via §1.1.)
6. **HUD vs Streamlit** — HUD as the live multi-section surface, Streamlit retained for deep-dive/research, or converge to one?
```
```
