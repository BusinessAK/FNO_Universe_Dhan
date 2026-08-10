#!/usr/bin/env bash
# ============================================================
#  Vanguard Quantitative Terminal — Startup Script
#  Usage:
#    ./start.sh eod     → Process latest BhavCopy + open HUD
#    ./start.sh full    → Full nightly chain: tests → poll_eod → verify_hud (no HUD launch)
#    ./start.sh live    → Live NSE polling + open HUD
#    ./start.sh dash    → Open HUD only (data already processed)
# ============================================================

set -e
cd "$(dirname "$0")"

MODE="${1:-dash}"

# Open the HUD in the default browser. `open` is macOS-only and this runs
# under `set -e`, so on Linux a bare `open` would abort the script — after a
# successful pipeline in `eod`, or right after starting the bridge in `live`
# (where the EXIT trap would then kill it). Never fail the caller: the HUD is
# a file on disk either way, so fall back to printing the path.
open_hud() {
  local page="hud/vanguard_hud.html"
  if command -v open >/dev/null 2>&1; then
    open "$page"
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$page"
  else
    echo "[*] HUD ready — open file://$(pwd)/$page"
    echo "    (or serve it: python3 scripts/serve_hud.py)"
  fi
}

case "$MODE" in

  # ── EOD Mode: Download + Process BhavCopy → Dashboard ──────────────────────
  eod)
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  VANGUARD EOD MODE — EOD Downloader & Compiler Pipeline"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    if [ -n "$2" ]; then
      python3 poll_eod.py "$2"
    else
      python3 poll_eod.py
    fi
    echo "[2/2] Opening HUD..."
    open_hud
    ;;

  # ── Full Mode: offline tests → EOD pipeline → HUD parity check ─────────────
  # Nightly slot per scripts/verify_hud.py's own docstring: poll_eod ->
  # daily_compiler -> build_hud -> verify_hud. Tests run first so a broken
  # build never gets the chance to touch live NSE endpoints or overwrite data/compiled/.
  # Stops at the first failure (set -e).
  full)
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  VANGUARD FULL CHAIN — Tests → EOD Pipeline → HUD Parity"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "[1/3] Offline unit tests..."
    python3 run_tests.py

    echo ""
    echo "[2/3] EOD pipeline (fetch → compile → briefing → HUD)..."
    if [ -n "$2" ]; then
      python3 poll_eod.py "$2"
    else
      python3 poll_eod.py
    fi

    echo ""
    echo "[3/3] HUD DB↔DOM parity check..."
    python3 scripts/verify_hud.py --url "file://$(pwd)/hud/vanguard_hud.html"

    echo ""
    echo "✅ Full chain complete: tests passed, pipeline ran, HUD verified."
    ;;

  # ── Live Mode: NSE Polling in background + Dashboard ───────────────────────
  live)
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  VANGUARD LIVE MODE — NSE Real-Time Bridge"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "[*] Starting NSE live polling in background..."
    python3 scripts/run_live.py > data/live/daemon_stdout.log 2>&1 &
    BRIDGE_PID=$!
    echo "[OK] Live bridge started (PID: $BRIDGE_PID)"
    echo "[*] Tail logs: tail -f data/live/daemon_stdout.log"
    echo ""
    echo "[*] Opening HUD..."
    trap "echo '[*] Stopping live bridge...'; kill $BRIDGE_PID 2>/dev/null" EXIT
    open_hud
    wait $BRIDGE_PID
    ;;

  # ── Brief Mode: Generate Tomorrow's Watchlist for a given date ─────────────
  brief)
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  VANGUARD BRIEFING — Tomorrow's Watchlist"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    if [ -n "$2" ]; then
      python3 briefing.py "$2"
    else
      python3 briefing.py
    fi
    ;;

  # ── Dash Mode: Open HUD only ─────────────────────────────────────────────
  dash)
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  VANGUARD HUD — Using existing processed data"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    open_hud
    ;;

  *)
    echo "Usage: ./start.sh [eod|full|live|brief|dash]"
    echo ""
    echo "  eod         → Download latest BhavCopy, process signals, open HUD"
    echo "  full        → Tests → EOD pipeline → HUD parity check (no HUD launch)"
    echo "  full DATE   → Same, for a specific date (e.g. 20260721)"
    echo "  live        → Start NSE live polling bridge + open HUD"
    echo "  brief       → Generate Tomorrow's Watchlist briefing (latest date)"
    echo "  brief DATE  → Generate briefing for a specific date (e.g. 2026-06-25)"
    echo "  dash        → Open HUD only (data already exists)"
    exit 1
    ;;
esac
