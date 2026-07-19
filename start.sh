#!/usr/bin/env bash
# ============================================================
#  Vanguard Quantitative Terminal — Startup Script
#  Usage:
#    ./start.sh eod     → Process latest BhavCopy + launch dashboard
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
    # Check if port 8501 is already occupied by a running Streamlit instance
    if lsof -Pi :8501 -sTCP:LISTEN -t >/dev/null ; then
      echo "⚡ Streamlit dashboard is already active on port 8501!"
      echo "🚀 The database update has successfully triggered a dynamic hot-reload in your browser."
      echo "🔗 Open http://localhost:8501 to view the compiled data instantly!"
    else
      echo "[2/2] Launching Streamlit dashboard..."
      streamlit run dashboard.py --server.port 8501
    fi
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
    streamlit run dashboard.py --server.port 8501
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
    streamlit run dashboard.py --server.port 8501
    ;;

  *)
    echo "Usage: ./start.sh [eod|live|brief|dash]"
    echo ""
    echo "  eod         → Download latest BhavCopy, process signals, launch dashboard"
    echo "  live        → Start NSE live polling bridge + launch dashboard"
    echo "  brief       → Generate Tomorrow's Watchlist briefing (latest date)"
    echo "  brief DATE  → Generate briefing for a specific date (e.g. 2026-06-25)"
    echo "  dash        → Launch dashboard only (data already exists)"
    exit 1
    ;;
esac
