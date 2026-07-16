# PRD — Vanguard v2: Migration Intelligence & Strategy Desk

| | |
|---|---|
| **Product** | Vanguard — EOD F&O dealer-positioning terminal |
| **Version** | v2.0 |
| **Author** | Quant/Platform (drafted with Claude) |
| **Date** | 14 Jul 2026 |
| **Status** | DRAFT — pending approval |

---

## 1. Background & Problem

Vanguard compiles NSE F&O bhavcopies (T vs T-1) into dealer-positioning structure: option walls, gamma flip, GEX, OI migrations, and structural-regime classification. The core operating thesis: **significant day-over-day migrations in dealer inventory precede tradeable moves.**

Empirical validation (257 sessions, 215 symbols, clean post-recompile data) shows:

| Finding | Evidence |
|---|---|
| Migration events do **not** reliably predict *direction* | fwd-3d drift after events: −0.07% … +0.14% vs ±2.4% typical daily range — noise |
| Migration events **do** predict *movement magnitude* | wall expansion: 3d abs-move **3.15% vs 2.41% baseline (+31%)**; regime flips +25%; pinches +10% |
| Stock-swing expression of these signals loses money | 33k-trade backtest: LONG −0.47%/trade, SHORT −0.42% after 20 bps costs |

**Problem statement:** the platform detects genuine volatility-expansion signals but expresses them through the wrong instrument (directional stock swings) and buries them under legacy features. The trade expression that matches the signal — **defined-risk option structures anchored on the walls themselves** — does not exist in the product.

## 2. Goals

1. **G1 — Signal quality:** every migration alert carries quantified significance (ATR-relative shift, OI mass moved, novelty) and its historical base rate, so the trader sees *evidence, not vibes*.
2. **G2 — Trade expression:** a deterministic **Strategy Desk** converts each qualified signal into a concrete option structure (legs, strikes from actual walls, premiums from actual bhav closes, risk/reward, sizing).
3. **G3 — Trust through validation:** no strategy template earns a "recommended" badge until the option-P&L backtest shows positive expectancy for its trigger bucket.
4. **G4 — Focus:** remove dead/overkill subsystems so the daily pipeline computes only what the trader uses.

### Non-goals (v2)

- Intraday/live data (platform stays EOD; Dhan live feed remains a separate branch effort).
- Automated order execution.
- ML-based prediction (the decommissioned ML gate stays decommissioned; deterministic rules only, so results remain explainable and backtestable).
- Multi-user / auth / cloud deployment.

## 3. Users

Single primary persona: **the operator-trader** (owner of this repo). Reviews the deck post-EOD (~18:30 IST after bhav publication), picks 1–5 names for the next session, needs: what changed, how unusual is it, what structure to put on, and what invalidates it.

## 4. Success Metrics

| Metric | Target |
|---|---|
| Backtested expectancy of at least one Strategy Desk template bucket | > 0 after 20 bps + option spread cost assumptions, ≥ 100 trades |
| Signal Feed precision | top-10 significance-ranked events show ≥ 1.2× baseline abs-move in forward validation |
| Pipeline runtime (incremental daily) | no regression > 10% vs current |
| Dead code removed | `main.py` signal pipeline, ML remnants, dead setups — 0 references remaining |

---

## 5. Scope — Phased Requirements

### Phase 1 — Cleanup & Refactor (P0, prerequisite)

| ID | Requirement | Detail |
|---|---|---|
| 1.1 | Remove Kinetic Score pipeline | Delete `main.py` + `src/signal_generator.py`; `signals.csv` verified unused by any renderer. `poll_eod.py` drops the `main.py` step. Greeks export moves fully into compiler path (already there via `intelligence.py`). |
| 1.2 | Remove ML remnants | Delete `src/ml/`, `src/core/regime_gate.py`; strip `macro_regime_prob` reads from UI (`cards.py`) and research scripts (keep DB column for schema compat). |
| 1.3 | Retire `DEALER_DEFENSE` setup | 1 hit / 257 sessions. Remove rule + playbook branch; PINCH_ZONE covers the pin-defense case. |
| 1.4 | Remove dead `suggest_strategy()` in `intelligence.py` | Compiler override makes it unreachable. |
| 1.5 | Archive `scratch/` → `archive/scratch/`; delete stale root `vanguard.duckdb` | Hygiene; stale DB caused a real incident. |
| 1.6 | Keep Streamlit terminal | Deep-dive/research UI. Decision on convergence deferred to post-v2. |

**Acceptance:** test suite green; incremental compile output byte-identical for unaffected tables; `grep` finds zero references to removed modules.

### Phase 2 — Migration Significance Engine (P0, core thesis)

| ID | Requirement | Detail |
|---|---|---|
| 2.1 | **Significance score per event** | For every `daily_changes` event compute: (a) `shift_atr` = wall shift ÷ 14-day ATR of the underlying; (b) `oi_mass` = OI at the new wall strike ÷ total side OI (how much conviction sits behind the new level); (c) `novelty` = 1 if first occurrence of this event type for the symbol in 5 sessions, else decays. `significance = f(shift_atr, oi_mass, novelty)` normalized 0–100. New columns on `daily_changes`. |
| 2.2 | **Event base-rate table** | New DB table `event_stats(type, n, fwd1, fwd3, fwd5, up3_pct, absmove3, absmove_base)` recomputed each compile from full history. |
| 2.3 | **Evidence badges in Signal Feed** | Each alert shows: significance meter + "typical 3d move X% vs Y% base". Feed default-sorted by significance. |
| 2.4 | **Futures buildup classification** | `fut_buildup ∈ {LONG_BUILDUP, SHORT_BUILDUP, SHORT_COVERING, LONG_UNWINDING, FLAT}` from sign(futures_oi_chg) × sign(spot_change_pct) with minimum thresholds (|ΔOI| > 2% of OI, |Δspot| > 0.25%). Column on `daily_market_structure`; scanner column + dossier tile + Flip Radar context. |
| 2.5 | **Confluence score replaces `priority_score` as default sort** | `confluence = w1·significance(best event) + w2·flip_confidence + w3·streak_strength + w4·iv_rank_percentile_alignment + w5·sector_alignment`. Weights fixed and documented; current `priority_score` formula (which rewards *low* movement) is retired from UI but kept in DB one release for comparison. |

**Acceptance:** unit tests for each component score; spot-check: top-decile significance events show ≥ 1.2× baseline forward abs-move on historical data.

### Phase 3 — Strategy Desk: the Derivative Agent (P0, headline)

**Principle: deterministic core, optional AI narration.** Every recommendation is reproducible from the DB row; the LLM never picks strikes.

| ID | Requirement | Detail |
|---|---|---|
| 3.1 | **Inputs** | Per qualified symbol-day (confluence ≥ threshold or top-N): direction + conviction, IV rank & IV shift, gamma regime, wall corridor (CW/PW/flip), event class (vol-expansion vs directional vs pinned), days-to-expiry of front/next series, lot size, per-strike option closes + OI from `greeks.csv`. |
| 3.2 | **Decision matrix** | See §6. Output is one primary + one alternative template per symbol. |
| 3.3 | **Concrete construction** | Legs = (expiry, strike, CE/PE, BUY/SELL, close premium, lots). Strikes snap to actual traded strikes nearest the wall/flip levels; premiums from bhav closes (no theoretical pricing for entry). Derived: net debit/credit, max risk, max reward, breakevens, reward:risk, POP proxy (short-strike delta), margin class (debit / defined-risk credit). |
| 3.4 | **Sizing** | Given `RISK_BUDGET_PER_TRADE` (config, default ₹10,000): lots = floor(budget ÷ max risk per lot). Refuse (size 0 + reason) when 1 lot exceeds budget. |
| 3.5 | **Persistence** | New table `daily_strategies(date, symbol, template, direction, legs_json, net_premium, max_risk, max_reward, breakeven_lo, breakeven_hi, pop_proxy, size_lots, rationale, confluence, source_event)`. |
| 3.6 | **HUD integration** | New **DESK PICKS** panel (top strategies by confluence, cards with payoff mini-diagram) + full construction in the symbol dossier replacing the current one-line "Desk Line". Time-travel aware. |
| 3.7 | **Guardrails** | No recommendation when: DTE < 3 (gamma/pin risk on entry day), option premium < ₹0.5 (illiquid dust), strike OI at short leg < threshold, or walls missing. Every refusal is logged with reason (visible in dossier). |
| 3.8 | **Multi-agent desk (optional, key-gated)** | See §6A. A four-agent LLM committee (Gemini Pro via existing `GEMINI_API_KEY` plumbing; provider-pluggable) reviews each deterministic pick: structure read → vol stance → strategy selection among legal candidates → adversarial risk veto. Agents may re-rank or veto toward safety; they may never widen risk, invent strikes, or bypass guardrails. No key → pure deterministic output, pipeline never blocks. |

### Phase 4 — Option-Strategy Backtest (P1, trust layer)

| ID | Requirement | Detail |
|---|---|---|
| 4.1 | Replay engine | For each historical `daily_strategies` row (generated by running the desk over full history): entry at recorded closes; exit at min(DTE, hold horizon); P&L from payoff-at-exit using underlying move + vega adjustment from realized `iv_shift`. Costs: 20 bps underlying-equivalent + 1 tick per leg. |
| 4.2 | Expectancy report | By template × event class × IV-rank bucket; same `min_trades ≥ 10` gate as swing backtester. |
| 4.3 | **Evidence badges** | Templates with positive validated expectancy get a badge in DESK PICKS; everything else displays "unvalidated". No badge without data. |

---

## 6. Strategy Desk Decision Matrix (normative)

| Signal class | IV rank | Direction conviction | Primary template | Strike anchors |
|---|---|---|---|---|
| Vol-expansion event (wall expansion, pinch, regime flip) | < 40 | any | **Long straddle/strangle** | ATM at gamma flip; strangle wings 1 strike out |
| Vol-expansion event | ≥ 40 | present | **Debit spread** (direction of confluence) | Long ATM, short at target wall |
| Vol-expansion event | ≥ 40 | absent | **No trade** (buying rich vol without direction = the losing swing trade in options form) | — |
| Directional (dual-wall migration, buildup + flip alignment) | ≥ 60 | bullish | **Bull put credit spread** | Short strike AT put wall, long 1–2 strikes below |
| Directional | ≥ 60 | bearish | **Bear call credit spread** | Short strike AT call wall, long 1–2 strikes above |
| Directional | < 60 | bullish/bearish | **Debit vertical** | Long 1 strike ITM-side of spot, short at target wall |
| Pinned (long gamma, high GEX-I, walls wide & static) | ≥ 50 | none | **Iron condor** | Shorts at both walls, wings 1–2 strikes outside |
| Pinned | < 50 | none | **No trade** (condor premium too thin) | — |

Rationale anchored in platform data: walls are where dealer hedging defends price — short strikes placed *at* walls monetize that defense; vol-expansion events (the only statistically validated signal) map to long-gamma structures bought before the move.

## 6A. Multi-Agent Desk Architecture (Phase 3.8)

**Governing rule:** the deterministic engine (§6 matrix + §3.3 construction + §3.7 guardrails) produces the *legal candidate set*. Agents deliberate **within** it. An agent can reject, re-rank, or shrink a position — never enlarge it, never leave the candidate set.

```
compiled DB row + wall trail + events + catalysts
        │
        ▼
┌─ 1. STRUCTURE ANALYST ─────────────────────────────┐
│ in : ms row, 30-session wall trail, event stack    │
│ out: {direction, conviction 0-100, key_levels,     │
│       invalidation_condition, one_line_read}       │
└────────────────────────────────────────────────────┘
        ▼
┌─ 2. VOL DESK ──────────────────────────────────────┐
│ in : iv, iv_rank, iv_shift, event class, DTE       │
│ out: {vol_stance: BUY|SELL|NEUTRAL, richness_note} │
└────────────────────────────────────────────────────┘
        ▼
┌─ 3. STRATEGY ARCHITECT ────────────────────────────┐
│ in : legal candidate templates (from §6 engine)    │
│      + outputs of 1 & 2                            │
│ out: {chosen_template, alternative, strike_choice  │
│       FROM candidate strike set only, rationale}   │
└────────────────────────────────────────────────────┘
        ▼
┌─ 4. RISK OFFICER (adversarial) ────────────────────┐
│ in : chosen structure + liquidity data + same-day  │
│      catalysts + sizing                            │
│ out: {verdict: APPROVE|SHRINK|VETO, reasons[],     │
│       desk_note (3 sentences)}                     │
└────────────────────────────────────────────────────┘
        ▼
daily_strategies row (+ agent_log JSON: every agent's
output, disagreements with the deterministic default)
```

| Aspect | Spec |
|---|---|
| Provider | `GEMINI_API_KEY` (existing `.env` plumbing from catalyst service). Model routing: **Gemini Pro** for Architect + Risk Officer (judgment), **Flash** for Analyst + Vol Desk (extraction). Provider-pluggable behind a thin `llm_router.py` so an Anthropic key can slot in later. |
| Contracts | Strict JSON schemas per agent, temperature 0.1, one retry on parse failure, then deterministic fallback for that symbol. |
| Scope | Top-N confluence symbols only (default N=20) → ≤ 80 calls per EOD run. |
| Authority | VETO/SHRINK only. Any deviation from the deterministic default is recorded in `agent_log` — this diff stream is research data. |
| Validation (Phase 4) | Backtest runs **A/B: deterministic-only vs agent-adjusted** picks. The committee earns its place with measured expectancy delta, same as every other feature. |
| Failure mode | Any agent error → that symbol ships deterministic-only, tagged `agents:skipped`. The EOD pipeline never blocks on an API. |

## 7. Data Model Changes

```
daily_changes        + significance FLOAT, shift_atr FLOAT, oi_mass FLOAT, novelty FLOAT
daily_market_structure + fut_buildup VARCHAR, confluence FLOAT
event_stats          (new)  type, n, fwd1, fwd3, fwd5, up3_pct, absmove3, absmove_base
daily_strategies     (new)  see §3.5
```

All additive; existing readers unaffected. HUD build exports the new columns.

## 8. Rollout

1. Phase 1 lands alone (pure deletion) → test suite + one daily cycle green.
2. Phase 2 lands with `--force` recompile (new columns need history) — run overnight.
3. Phase 3 ships behind config flag `STRATEGY_DESK=1` for the first week; HUD shows picks marked **UNVALIDATED**.
4. Phase 4 report reviewed together → decide which templates get badges → flag removed.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Option closes in bhav are stale/wide for illiquid strikes → misleading premiums | Liquidity guardrail (3.7); prefer strikes with OI + volume floors |
| Payoff-at-exit approximation misprices early exits of long-gamma structures | Conservative vega adjustment; flag straddle results as approximate in report |
| Overfitting the decision matrix to 257 sessions | Matrix is theory-first (dealer mechanics), data only *validates*; buckets under 100 trades stay unvalidated |
| LLM nondeterminism contaminates a testable system | Agents constrained to veto/shrink within legal candidates; temp 0.1; full agent_log; Phase 4 A/B measures whether the committee adds or subtracts expectancy |
| API cost/latency creep | Batch EOD only, top-20 symbols, ≤ 80 calls/day, Flash for extraction roles |
| Removing `main.py` breaks an unknown consumer | Grep + one full daily cycle in Phase 1 acceptance before Phase 2 starts |

## 10. Open Questions (need your call)

1. `RISK_BUDGET_PER_TRADE` default — ₹10,000 per trade acceptable, or set your own?
2. Multi-agent desk (§6A) — **CONFIRMED in scope** (user adding Gemini Pro key). Confirm exact model IDs to pin (default: `gemini-3.5-pro` for judgment roles, `gemini-3.5-flash` for extraction — same family the catalyst service already uses).
3. Strategy universe — stocks only, or include NIFTY/BANKNIFTY index structures (weeklies make DTE logic richer; suggest **stocks-only v2**, indices v2.1)?
4. Phase 4 hold horizon for replay — suggest exit at min(5 sessions, expiry−1); confirm.

## 11. Out of Scope, Explicitly

Live Dhan feed integration, order routing, portfolio margin optimization, multi-leg Greeks risk dashboard, mobile layout. All deferred; none blocked by this design.
