#!/usr/bin/env bash
# ============================================================
#  Vanguard Quantitative Terminal — Startup Script
#  Usage:
#    ./start.sh eod     → Process latest BhavCopy + launch dashboard
#    ./start.sh full    → Full nightly chain: tests → poll_eod → verify_hud (no dashboard)
#    ./start.sh live    → Live NSE polling + launch dashboard (split terminals)
#    ./start.sh dash    → Launch dashboard only (data already processed)
# ============================================================

set -e
cd "$(dirname "$0")"

MODE="${1:-dash}"

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
    # Check if port 8502 is already occupied by a running Streamlit instance
    if lsof -Pi :8502 -sTCP:LISTEN -t >/dev/null ; then
      echo "⚡ Streamlit dashboard is already active on port 8502!"
      echo "🚀 The database update has successfully triggered a dynamic hot-reload in your browser."
      echo "🔗 Open http://localhost:8502 to view the compiled data instantly!"
    else
      echo "[2/2] Launching Streamlit dashboard..."
      streamlit run dashboard.py --server.port 8502
    fi
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
    echo "[*] Launching Streamlit dashboard (toggle AUTO REFRESH ON)..."
    trap "echo '[*] Stopping live bridge...'; kill $BRIDGE_PID 2>/dev/null" EXIT
    streamlit run dashboard.py --server.port 8502
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

  # ── Dash Mode: Launch dashboard only ───────────────────────────────────────
  dash)
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  VANGUARD DASHBOARD — Using existing processed data"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    streamlit run dashboard.py --server.port 8502
    ;;

  *)
    echo "Usage: ./start.sh [eod|full|live|brief|dash]"
    echo ""
    echo "  eod         → Download latest BhavCopy, process signals, launch dashboard"
    echo "  full        → Tests → EOD pipeline → HUD parity check (no dashboard)"
    echo "  full DATE   → Same, for a specific date (e.g. 20260721)"
    echo "  live        → Start NSE live polling bridge + launch dashboard"
    echo "  brief       → Generate Tomorrow's Watchlist briefing (latest date)"
    echo "  brief DATE  → Generate briefing for a specific date (e.g. 2026-06-25)"
    echo "  dash        → Launch dashboard only (data already exists)"
    exit 1
    ;;
esac
