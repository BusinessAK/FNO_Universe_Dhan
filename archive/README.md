# archive/ — the live/intraday (Fyers) layer

This directory holds the **real-time intraday stack** that was retired when the
terminal became EOD-only (2026-07-27). Nothing here is imported by the active
codebase; it's preserved verbatim (original repo paths mirrored under
`archive/`) so it can be restored with a straight reverse-move.

## What's here

| Area | Files |
|------|-------|
| Live engine | `vanguard/live/` — feed handler, subscription mgr, live_compute (Greeks/GEX/walls), trigger engine, snapshot, state store, tick journal, bridge shim, manifest, calendar, universe, alert sink |
| Broker | `vanguard/data/fyers_client.py`, `vanguard/data/instrument_master.py` |
| Live config | `vanguard/config/live.py` |
| Live research | `vanguard/research/live_trigger_replay.py` |
| Scripts | `scripts/run_live.py`, `start_day.sh`, `fyers_login.py`, `verify_bridge.py`, `live_probe.py`, `live_capture_test.py`, `build_fyers_map.py`, `build_ws_manifest.py`, `simulator.py`, `live_parity_check.py` |
| Tests | `tests/test_live_compute.py`, `test_live_state_keying.py`, `test_trigger_engine.py`, `test_tick_journal_schema.py`, `test_e2e_snapshot_bridge.py`, `test_ws_manifest.py` |

The archived tests keep their `vanguard.live.*` import paths, so they will only
pass once the code is restored. They live under `archive/tests/` (not `tests/`)
so neither `run_tests.py` (`start_dir="tests"`) nor pytest (`testpaths=["tests"]`)
collects them.

## What replaced it on the EOD side

- **Serving:** the live bridge (`run_live.py` → `Bridge`) served the HUD. The EOD
  terminal now serves the same HUD + `/session/latest` via `scripts/serve_hud.py`
  (static, no broker socket). The `/snapshot` overlay endpoint was removed from
  `vanguard/serve/api.py`.
- **Two helpers that were genuinely EOD-grade were relocated OUT of the live layer
  before archiving, so EOD keeps working:**
  - `get_nifty50_constituents` / `INDEX_SYMBOLS` → `vanguard/pipeline/context/nifty50_universe.py`
    (scanner universe scoping in `export_service`).
  - `_direction` (trigger-vs-invalidation direction) → canonical home in
    `vanguard/rules/setup_positions.py`.
- **HUD:** the client-side live overlay (snapshot polling, LIVE badge, Live
  Triggers / Live Wall Breaks panels, live LTP on scanner rows) was removed from
  `hud/template.html`.

## To restore the live layer

```sh
# move the package code back
mv archive/vanguard/live            vanguard/live
mv archive/vanguard/config/live.py  vanguard/config/live.py
mv archive/vanguard/data/*.py       vanguard/data/
mv archive/vanguard/research/live_trigger_replay.py vanguard/research/
mv archive/scripts/*                scripts/
mv archive/tests/*                  tests/
```

Then re-point `export_service` / `verify_hud` back to `vanguard.live.universe`
+ `vanguard.config.live` if you want the old single-source, restore the
`/snapshot` endpoint in `serve/api.py`, and re-add the live overlay block to
`hud/template.html` (see git history for the removed block). `requirements.txt`
still carries the Fyers SDK dependency, so no dependency changes are needed.
