# Vanguard — Platform Architecture (canonical plan)

**Approved 2026-07-19.** This document is the single reference for the platform's
target shape and the migration waves getting us there. PRDs reference this; when
they disagree, this wins.

## Principle

> **One store, one API, one UI, one runtime — two cadences by design.**

The EOD plane (bhav → compiler → DuckDB) stays authoritative; the live plane
(Dhan WS → state store → snapshot) stays indicative until the parity referee
validates it. "One platform" merges the *access* — never the truth.

## Target structure

```
FNO_BHAV/
├── pyproject.toml            installable package; no sys.path hacks
├── vanguard/                 THE package
│   ├── cli.py                (wave 7) vanguard daemon|compile|backfill|probe|brief
│   ├── config/               ONE config home: paths.py, eod.py, live.py,
│   │                         sectors.py (sector_mapping), setups.py (setup_registry)
│   ├── engines/              pure math, no I/O: greeks, gamma (analyzer), flow/
│   │                         intelligence, classifier, longitudinal, breadth, cash_breadth
│   ├── rules/                trading opinions: setup_screener (R1), playbook
│   ├── pipeline/             EOD plane: compiler, normalize (processor), poll_eod,
│   │                         backfill, context/ (NSE datasets C1–C5)
│   ├── live/                 realtime plane (moved intact — newest, best-tested code)
│   ├── store/                db.py (one connection manager), schema, views (parquet→DuckDB),
│   │                         export_service (ONE payload builder: baked or served)
│   ├── serve/                api.py (bridge grown up: /snapshot /session/<d> /ladder /events)
│   ├── research/             backtesters + outcomes.py (shared signal→outcome join)
│   ├── services/             TRANSITIONAL — dissolves in wave 6 (ui_state/session_cache die
│   │                         with Streamlit; briefing moves to pipeline/)
│   └── ui/hud/               (wave 3) template + build; Streamlit deleted in wave 6
├── tests/                    mirrors package + fixtures/ + e2e/
├── scripts/                  thin wrappers; shrinks as cli.py absorbs them
└── docs/  data/              unchanged (data layout is fine)
```

Directory semantics are the enforcement mechanism: a diff in `rules/` is a
strategy change and gets reviewed as one; `engines/` must stay I/O-free;
anything new lands wired through `store/export_service.py` exactly once.

## Migration rules

1. **Move-commits never contain logic changes.** `git mv` + imports only; the
   test suite must be green before and after every wave.
2. Old import paths keep one-line re-export shims for one release.
3. `live/` moves as a sealed directory.

## Waves

| Wave | Content | Gate |
|---|---|---|
| 0 | Delete orphan pre-DuckDB pipeline (main.py, data_fetcher, signal_generator, comparer); fix `start.sh live` → scripts/run_live.py | tests green |
| 1a | `src/` → `vanguard/`; pyproject.toml; rewrite imports; kill sys.path-to-src hacks | tests green; manifest + HUD builds reproduce |
| 1b | Reshuffle into engines/rules/pipeline/store/config with backward shims; add config/paths.py + store/db.py | tests green |
| 2 (R1) | Extract the 10 setup rules → rules/setup_screener.py; kill duplicated skew predicate; persist skew_slope, iv_rank, losing-setup biases; table-driven rule tests | recompile parity vs pre-refactor |
| 3 (P1) | store/export_service.py + serve/api.py `/session/<date>`; HUD fetches when served, baked fallback | HUD identical from both paths |
| 4 | C1–C2 NSE context (fetchers in pipeline/context/), wired once through export_service | NSE PRD gates |
| 5 | C3–C5 (ban gate=exclude, events annotate-only, participant OI display+research) | NSE PRD gates |
| 6 (P2–P3) | store/views.py parquet views; dashboard freeze → port keeper views to dossier tabs → delete Streamlit + services/ui layer | 1 week HUD-only first |
| 7 (F1–F5 + P4) | Fullmap live per its PRD; cli.py daemon owns the market clock | fullmap gates |
| ∥ R4/R5 | compile_version + compile state into DuckDB (with wave 4); engines/gamma + calendar + subscription_mgr tests | — |

## Standing decisions

- Streamlit retires at wave 6 (single-UI decision, confirmed).
- Ban-arming gate default `exclude`; event windows annotate-only in v1.
- Participant-OI is display + research until backtested.
- Skew columns ride with wave 2.
- Live numbers never overwrite EOD numbers; INDICATIVE until parity — permanent.
