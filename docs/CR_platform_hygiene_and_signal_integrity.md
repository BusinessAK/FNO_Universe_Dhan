# CR — Platform Hygiene, Signal Integrity & Trader-Facing Gaps

| | |
|---|---|
| **Product** | Vanguard — EOD F&O dealer-positioning terminal |
| **Type** | Change Request (audit-driven, tactical) |
| **Author** | Quant/Platform (drafted with Claude) |
| **Date** | 16 Jul 2026 |
| **Status** | DRAFT — pending review |
| **Relationship to PRD v2** | Complements `docs/PRD_vanguard_v2.md`. Does not replace it. See §1. |

---

## 1. Purpose & relationship to PRD v2

`docs/PRD_vanguard_v2.md` (14 Jul, DRAFT) already lays out a strategic rebuild — Migration Significance Engine, Strategy Desk, option-P&L backtest. This CR is narrower and came from a different direction: a full read of every core engine (`intelligence.py`, `greeks_engine.py`, `analyzer.py`, `classifier.py`, `longitudinal.py`, `breadth.py`, `cash_market_breadth.py`, `catalyst_rules.py`, `playbook.py`, `setups.py`, `watchlist_screener.py`, `signal_generator.py`, `narrative.py`, `historical_engine.py`) cross-referenced against every column in `vanguard.duckdb` and every UI file that reads them, done to answer one question: **of everything this pipeline computes, what does a derivatives trader actually see, and what's dead weight or missing?**

Three of this CR's findings independently reproduce PRD v2 §1 items — that's a good cross-check, not a duplication, and each is noted below. Everything else is net-new: specific dead columns, a discard-after-use pattern the PRD doesn't mention, and a couple of prerequisite gaps for PRD v2's own Phase 2.

**How to use this document:** §3–4 are immediately actionable hygiene, independent of whether PRD v2 ships. §5 is context (this session's signal-integrity work) relevant to how PRD v2 Phase 2's `fut_buildup`/confluence work should be validated. §6 flags gaps PRD v2 doesn't cover. §7 proposes sequencing against PRD v2's existing phases.

**Verification method:** every claim below was checked directly — repo-wide greps (not directory-restricted; an earlier pass that scoped greps to specific directories missed real files and produced one wrong finding), direct reads of the current file contents at the referenced lines, direct DB queries against the actual column values (not just schema), and one live timing measurement — rather than inferred from memory or a partial search. This pass caught and corrected two errors from an earlier draft: DW-1 was originally characterized as dead legacy code, and turned out to be a live, mandatory, pipeline-fragile step (§3); DW-4 was originally claimed to be an unused pair of columns, and turned out to be actively rendered in a chart the first search missed. Both corrections are documented in place, not silently fixed, so the audit trail is visible.

---

## 2. Baseline — work completed this session

For context on what state the platform is actually in as of this CR:

| Item | Status | Note |
|---|---|---|
| `ce_interp`/`pe_interp` premium-verified flow classifier | **Shipped, tested** | Replaces spot-proxy heuristic with the option's own premium direction (`classify_oi_flow`, 30 unit tests). |
| `FLOOR_BOUNCE` playbook gate | **Shipped, tested** | Suppresses "Bull Put Spread" when the put wall's OI was bought, not written (`playbook.py:279-286`). |
| Wall/gamma-flip 15%-distance filter fix | **Shipped, tested** | `GreeksEngine.process_dataframe` was silently excluding large-OI strikes >15% from spot from wall/gamma-flip detection entirely (not deprioritizing — excluding). Fixed via top-N-by-OI carve-out; regression test reproduces the excluded case. |
| IV aggregation OI-weighting fix | **Shipped, tested** | `get_detailed_metrics` averaged IV unweighted, letting a hardcoded 0.20 dust-fallback IV dominate. Now OI-weighted; regression test proves the old code would have failed it. |
| `verified_oi_flow` (premium-corrected `NET_BULL_INV_SHIFT`/IFS) | **Built, tested, empirically rejected, reverted** | Economically well-derived (verified against all 8 OI-direction × premium-direction states), but a full 55,891-row forward-return backtest against the existing `flip_backtester.py` methodology showed it **fails** the same monotonicity gate the current (cruder) formula **passes**. Kept as a tested, documented method (not wired into production) — same treatment PRD v2's own precedent gives shelved variants. Full result: `data/research/ifs_verified_flow_validation.md`. |
| Full recompile with the four shipped fixes | **Complete, verified** | Backups taken (`vanguard_pre_force_backup_20260716.duckdb`, `session_history_pre_force_backup_20260716.json`) before running. Post-recompile checks: 85/85 tests pass; SONACOMS 2026-07-14 confirmed live with corrected labels; FLOOR_BOUNCE gate correct on all 201 affected rows; NIFTY IV matches hand-computed OI-weighted value exactly; wall-filter fix confirmed changing the *selected* wall on 68 symbol-days that were structurally impossible pre-fix. |

The IFS backtest result matters for §5 and for how PRD v2 Phase 2's `fut_buildup` should be treated.

---

## 3. Findings — Dead weight (remove)

### DW-1 — `signal_generator.py` / `main.py`: not dead, worse — live, redundant, and pipeline-fragile

**This entry is corrected from an earlier draft of this CR, which called `main.py` a "legacy entry point" that `poll_eod.py` never calls. That was wrong** — checked by reading `start.sh` and the top of `poll_eod.py` only, without reading `poll_eod.py` to its end. Full re-read of `poll_eod.py:89-106` shows the actual EOD sequence is:

```
daily_compiler.py  (check=True)
main.py            (check=True)   ← calls SignalGenerator, unused output
briefing.py        (check=False)
scripts/build_hud.py (check=False)
```

Verified facts, not inference:
- `main.py` runs **every EOD cycle**, unconditionally, with `check=True` — if it raises, `poll_eod.py` aborts before reaching `briefing.py` or `build_hud.py`, meaning **a failure in code whose output nothing displays can silently prevent the HUD and the watchlist briefing from being generated that day.**
- `main.py`'s `SignalGenerator.generate_signals()` calls `InstitutionalIntelligence().analyze_market_structure()` **a second time** on the same T/T-1 file pair `daily_compiler.py` just processed. Timed directly on real data: **27.0 seconds** per call with the current codebase. That's ~27 seconds of pure redundant compute added to every EOD run, for a result that overwrites `data/processed/greeks.csv` with (deterministically) the same values already written moments earlier.
- `main.py` also runs its **own independent NSE download/session-init logic** (`src.data_fetcher.NSEDataFetcher`, same `BASE_URL` pattern `poll_eod.py` already used) — a second, separate fetch path hitting the same NSE endpoint `poll_eod.py` just successfully called.
- What the original draft got right: `signals.csv`'s content is genuinely never rendered (`dashboard.py`'s `signals_df` is loaded via `load_base_signals` and never read again — that trace holds), and neither `briefing.py` nor `scripts/build_hud.py` read it either (checked directly).

**Net finding:** this isn't inert legacy code to tidy up — it's a live, mandatory, ~27-second-plus-network step that computes a value nothing shows and can take down the rest of the EOD pipeline if it errors. That raises this item's priority relative to how PRD v2 §1.1 frames it (pure hygiene); recommend treating it as a reliability fix, not just cleanup, and testing one full `poll_eod.py eod` cycle after removal per PRD v2's own §1 acceptance criteria (which already anticipates this: "`poll_eod.py` drops the `main.py` step").

| ID | Item | Evidence | PRD v2 overlap |
|---|---|---|---|
| **DW-2** | `intelligence.py`'s `suggest_strategy()` / `SUGGESTED_STRATEGY` column | Traced precisely, re-verified against the current file: `daily_compiler.py` passes it as `build_playbook(base_strategy=...)` at line 434, but `build_playbook`'s strategy-override block (`playbook.py:268-328`) is an exhaustive if/elif/else — every branch reassigns `s_strat`, including the terminal `else`. Confirmed the one seemingly-open branch (`REGIME_SHIFT`) can't leave `base_strategy` unset either: its `playbook["bias"]` is hardcoded to `"Regime Transition"` two blocks earlier (`playbook.py:192`), making its own inner if/elif exhaustive too. **`base_strategy` never survives to the persisted `daily_market_structure.suggested_strategy` column, under any setup combination.** Re-checked line-by-line against `daily_compiler.py:370-437` directly (not from memory): nothing reads `day_data["suggested_strategy"]` between its initial assignment (line 379) and its overwrite by `s_strat` (line 437). Note: this session added a Put-Writing/Call-Writing check to this exact function (§2) before this trace was done — logically sound, unit-tested, but confirmed inert for the live DB. Safe to delete alongside. | **Confirms and sharpens PRD v2 §1.4** (PRD v2 asserts this without the branch-by-branch trace; this CR provides it). |
| **DW-3** | `daily_inventory` table, 5 of 7 columns | `put_wall_shift`, `call_wall_shift`, `regime_change`, `put_wall_pct_change`, `call_wall_pct_change` — repo-wide grep (not directory-restricted) finds zero reads outside their own write-site (`daily_compiler.py`/`longitudinal.py`); confirmed `database_service.py` doesn't even `SELECT` them. Cross-checked against the DB directly: these are not stub/always-default values — `regime_change` is `True` on 23,030/55,891 rows, `put_wall_shift` splits realistically across "Stable"/"Higher"/"Lower" (40,615/7,840/7,436), so this is real, varying, discarded signal, not dead-by-triviality. Only `bullish_persistence`/`bearish_persistence` are actually used (matrix.py badges). | Net new. |
| **DW-4** | ~~`total_ce_oi` / `total_pe_oi` columns~~ — **retracted, this claim was wrong** | Original draft claimed these are never displayed. Re-verification found `src/charts/chronology.py:render_cumulative_oi_chart` reads both directly, and it's called from `dashboard.py:372` inside the always-visible "📅 MONTHLY CHRONOLOGY" tab (`dashboard.py:363-374`, no feature flag, no historical-only gate) — a real, live stacked-area "Multi-Day F&O Inventory Accumulation Profile" chart. The original grep scope (`dashboard.py`, `src/ui/*.py`, `hud/template.html`, `src/services/*.py`) missed `src/charts/*.py` entirely, which is a real, separate directory `dashboard.py` imports five chart functions from. No action needed on this item. | — |
| **DW-5** | `BreadthState`, `PlaybookState`, `SetupState` dataclasses (`src/models/states.py`) | Repo-wide grep, zero instantiations outside their own definitions. | Net new. |
| **DW-6** | `SignalState` / `session_cache.get_normalized_signal()` | Repo-wide grep, zero callers anywhere. Also silently omits `smart_money_persistence` from its field list — moot while dead, but a landmine if ever revived without noticing the gap. | Net new. |
| **DW-7** | `analyzer.py`'s `advanced_analysis()` (cost-of-carry, OI-concentration wall) | Repo-wide grep, zero callers anywhere in the repo. | Net new. |
| **DW-8** (verify, don't act yet) | `DEALER_DEFENSE` setup | PRD v2 §1.3 claims 1 hit / 257 sessions and proposes retiring it. Not independently re-verified in this scan — recommend confirming against the post-recompile database (once Phase 4 of this session's work lands) before executing PRD v2's own retirement plan, since the recompile changes wall/gamma-flip detection (Greeks fix, §2) and could shift how often this setup fires. | Flags a dependency on PRD v2's own item. |

---

## 4. Findings — Computed, then discarded (surface, don't recompute)

A repeated pattern: a genuinely useful metric is computed as a **local variable inside `daily_compiler.py`**, used once to feed a binary setup-detection threshold, then thrown away instead of persisted.

| ID | Item | Evidence | Note |
|---|---|---|---|
| **CD-1** | `iv_rank` (IV percentile vs recent history) | Computed at `daily_compiler.py:257` (`(iv_t - iv_min)/(iv_max-iv_min)*100`), consumed only by the `IV_SPIKE`/`IV_CRUSH` gates (`iv_shift>0.045 and iv_rank>70`, etc. at lines 311/315). Never written to a DB column, never displayed. | **Relevant to PRD v2 §2.5**, which specifies a confluence-score term `iv_rank_percentile_alignment` — that term has no data source today. This CR flags `iv_rank` persistence as an implicit prerequisite for PRD v2 Phase 2.5 that isn't called out in the PRD's own data-model changes (§7). |
| **CD-2** | `skew_slope` (CE avg price / PE avg price, a skew proxy) | Computed at `daily_compiler.py:265`, consumed only by the `IV_SKEW_ACCUMULATION` gate (`>1.15`/`<0.85` thresholds). Never persisted or shown as its own number, despite put/call skew being a first-class signal traders watch independent of any setup firing. | Net new. |

Both are cheap to fix — the math already runs every session; this is a persistence + display change, not a new computation.

---

## 5. Signal integrity — context for PRD v2's confluence work

This session's central finding (§2, `verified_oi_flow`) is directly relevant to how PRD v2 Phase 2 should be executed, not just a standalone bug fix:

- **The root cause**: `NET_BULL_INV_SHIFT` and IFS's OI terms assume rising PE OI is always bullish (written puts) and rising CE OI is always bearish (written calls), with no check of whether that OI was bought or written. Correcting for premium direction flips polarity on 32.8% of `net_bull_inv_shift` rows and 18.5% of IFS rows historically.
- **The finding that matters for PRD v2**: the economically-correct fix **empirically underperforms** the naive one on forward returns (full-history backtest, methodology reused from `flip_backtester.py`). "Looks more correct" was not sufficient evidence to trust it in production.
- **Why this matters for PRD v2 §2.4**: `fut_buildup` is defined on **futures** OI × price sign, not options OI — futures don't have the same buy/write ambiguity options do (a long or short futures position is symmetric), so `fut_buildup` is structurally immune to the specific trap IFS fell into. That's a point in favor of the PRD's approach. But it doesn't mean `fut_buildup` is automatically predictive — this CR recommends PRD v2 Phase 2 apply the **same forward-return validation gate** (`attach_forward`, quintile monotonicity) to `fut_buildup` and the `confluence` score before either earns default-sort status, rather than assuming "no options-OI ambiguity" implies "predictive." The infrastructure to do this already exists (`src/research/flip_backtester.py`, and this session's `src/research/ifs_verified_flow_backtest.py` as a second working example of the same pattern).

---

## 6. Missing capabilities — trader's-eye gaps not in PRD v2

| ID | Gap | PRD v2 status |
|---|---|---|
| **MC-1** | Strike-level unusual options activity (e.g., one specific OTM strike seeing 10x normal volume) | **Not addressed.** Checked `matrix.py`'s `vol_ratio` specifically since it looked like a candidate: it's `abs(delta_volume)/(total_volume+1)*100` — a **symbol-level** net-directional-volume indicator (the matrix cell's bottom micro-bar), not a per-strike anomaly detector. Every layer in both the current pipeline and PRD v2's Strategy Desk (confluence, `fut_buildup`, template selection) operates at symbol+side aggregate. A single-strike volume/OI anomaly — often the highest-conviction raw signal for a derivatives trader — is structurally invisible once collapsed to that level. Candidate addition to PRD v2 Phase 2. |
| **MC-2** | Computed "days-to-expiry" shown prominently on the card, independent of any strategy recommendation | **Partially addressed, more nuanced than first stated.** Checked `cards.py:362-366` directly: the Greeks Ledger (a secondary tab, one row per contract) does show each contract's raw `EXPIRY_DT` formatted as a date (e.g. "28 Aug") — so expiry information isn't entirely absent from the UI. What's still missing: no **computed days-remaining countdown**, and nothing on the primary structure card/dossier (the first thing a trader sees) — a trader has to open the Greeks ledger and mentally subtract dates. PRD v2 §3.1 lists "days-to-expiry of front/next series" as a Strategy Desk *input* but doesn't call for it as an independently visible field. Recommend surfacing a computed DTE on the primary card regardless of whether Strategy Desk ships. |
| **MC-3** | Max pain | Checked directly — zero references anywhere in the repo (`max_pain`/`maxpain`, case-insensitive search). Not in PRD v2 either. Lower priority — PRD v2's wall/gamma-based framing is already a more defensible reference level than max pain, so this is optional, not a gap that blocks anything. |
| **MC-4** | Sizing / risk-per-trade guidance | **Fully covered by PRD v2 §3.4** (`RISK_BUDGET_PER_TRADE`, lot sizing, refuse-if-exceeds-budget). No separate action needed — noting only so this CR's scan doesn't look like it missed it. |

---

## 7. Recommended sequencing against PRD v2's phases

- **DW-1 is a reliability fix, not hygiene — recommend pulling it ahead of everything else, independent of PRD v2's approval timeline.** It's not "delete unused code when convenient"; it's "a mandatory, `check=True`, ~27-second-plus-network step that computes a value nothing shows, and can silently stop the HUD/briefing from regenerating if it errors." That risk exists on every EOD run today, right now, regardless of whether PRD v2 ships. PRD v2 §1.1 already specifies the fix (remove the `main.py` step from `poll_eod.py`); this CR's evidence is why it shouldn't wait.
- **DW-2, DW-3, DW-5, DW-6, DW-7** slot into PRD v2's existing **Phase 1 — Cleanup & Refactor** table as additional line items (DW-2 is the same item as PRD v2 §1.4, now traced to the exact branch; DW-3/5/6/7 are net-new). Same acceptance criteria apply (`grep` finds zero references; test suite green). DW-4 needs no action — retracted.
- **§4 (CD-1, CD-2)** are a prerequisite note for PRD v2 **Phase 2.5** (`confluence` score) — recommend landing these two as a small, independent, no-recompile-logic-change patch (persist two already-computed local variables) either just before or bundled into PRD v2 Phase 2's own recompile, so Phase 2.5's `iv_rank_percentile_alignment` term has data to read from day one.
- **§5** is a methodology note for whoever implements PRD v2 Phase 2 — apply the same forward-return gate to `fut_buildup`/`confluence` that this session applied to IFS, before trusting either as a default sort.
- **§6 (MC-1, MC-2)** are candidate scope additions for PRD v2 Phase 2/3 — need an explicit accept/reject from whoever owns that PRD, not assumed in scope.

---

## 8. Open questions / decisions needed

1. **DW-1**: authorize removing the `main.py` step from `poll_eod.py` (and deleting `main.py` + `src/signal_generator.py`) as an immediate fix, ahead of PRD v2 approval, given the pipeline-abort risk? Verification would be one full `poll_eod.py eod` cycle post-removal, per PRD v2's own §1 acceptance criteria.
2. Execute the rest of §3's dead-weight removal (DW-2, DW-3, DW-5, DW-6, DW-7) as an independent hygiene pass now, or fold into PRD v2 Phase 1 and wait for that PRD's approval? DW-2 is already approved in principle (PRD v2 §1.4); DW-3/5/6/7 are net-new and would need the same sign-off.
3. Persist `iv_rank`/`skew_slope` (§4) now, independent of PRD v2 timing, since they're cheap and PRD v2 Phase 2.5 needs them regardless of when that phase lands?
4. DW-8 (`DEALER_DEFENSE` retirement) — confirm re-checking its firing rate against the post-recompile database before executing PRD v2's existing retirement plan, given this session's wall/gamma-flip detection fix could shift it.
5. MC-1 (strike-level UOA) and MC-2 (computed DTE on the primary card) — accept as PRD v2 scope additions, defer to a later version, or reject?
