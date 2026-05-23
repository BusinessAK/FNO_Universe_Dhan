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
    echo "  VANGUARD EOD MODE — BhavCopy Pipeline"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "[1/2] Running BhavCopy signal pipeline..."
    python3 main.py
    echo ""
    echo "[2/2] Launching Streamlit dashboard..."
    streamlit run dashboard.py --server.port 8501
    ;;

  # ── Live Mode: NSE Polling in background + Dashboard ───────────────────────
  live)
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  VANGUARD LIVE MODE — NSE Real-Time Bridge"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "[*] Starting NSE live polling in background..."
    python3 run_live_nse.py > data/processed/live_bridge.log 2>&1 &
    BRIDGE_PID=$!
    echo "[OK] Live bridge started (PID: $BRIDGE_PID)"
    echo "[*] Tail logs: tail -f data/processed/live_bridge.log"
    echo ""
    echo "[*] Launching Streamlit dashboard (toggle AUTO REFRESH ON)..."
    trap "echo '[*] Stopping live bridge...'; kill $BRIDGE_PID 2>/dev/null" EXIT
    streamlit run dashboard.py --server.port 8501
    ;;

  # ── Dash Mode: Launch dashboard only ───────────────────────────────────────
  dash)
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  VANGUARD DASHBOARD — Using existing processed data"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    streamlit run dashboard.py --server.port 8501
    ;;

  *)
    echo "Usage: ./start.sh [eod|live|dash]"
    echo ""
    echo "  eod   → Download latest BhavCopy, process signals, launch dashboard"
    echo "  live  → Start NSE live polling bridge + launch dashboard"
    echo "  dash  → Launch dashboard only (data already exists)"
    exit 1
    ;;
esac
