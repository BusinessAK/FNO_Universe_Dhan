#!/usr/bin/env bash
# One-command trading-day startup.
#
#   ./scripts/start_day.sh
#
# Does, in order: (1) verify the Fyers token still works, running the
# interactive login flow only if it doesn't; (2) rebuild the HUD so it's
# baked against the latest compiled EOD data; (3) a --dry-run sanity check
# (manifest size, auth, armed setups) so a bad config aborts loudly before
# any socket opens; (4) start the live daemon in the foreground and open the
# HUD in your browser once the Bridge answers.
#
# Ctrl-C stops the daemon directly (this script hands off to it via `exec`).
set -euo pipefail
cd "$(dirname "$0")/.."

BRIDGE_URL="http://127.0.0.1:8787/"

check_auth() {
  python3 -c "
from vanguard.data.fyers_client import FyersClient
import sys
try:
    ok, msg = FyersClient().check_auth()
except Exception as e:
    ok, msg = False, str(e)
print(f'[auth] {\"OK\" if ok else \"FAIL\"} — {msg}')
sys.exit(0 if ok else 1)
"
}

echo "=== [1/4] Checking Fyers auth ==="
if ! check_auth; then
  echo "Token missing or expired — running the login flow now."
  echo "(Opens a browser; log in, then paste the auth_code back here.)"
  python3 scripts/fyers_login.py
  echo
  echo "Re-checking auth..."
  if ! check_auth; then
    echo "[FATAL] Auth still failing after login — aborting." >&2
    exit 1
  fi
fi

echo
echo "=== [2/4] Rebuilding the HUD against the latest compiled EOD data ==="
python3 scripts/build_hud.py

echo
echo "=== [3/4] Dry-run sanity check (manifest size, auth, armed setups) ==="
echo "(Doesn't check EOD-database staleness — the real run below does, and"
echo " aborts loudly if yesterday's compile is missing.)"
python3 scripts/run_live.py --dry-run

echo
echo "=== [4/4] Starting the live daemon ==="
EXISTING_PID="$(lsof -tiTCP:8787 -sTCP:LISTEN 2>/dev/null || true)"
if [ -n "$EXISTING_PID" ]; then
  echo "Port 8787 is already in use (PID $EXISTING_PID) — almost certainly a"
  echo "leftover run_live.py from an earlier session. Stopping it so the"
  echo "live daemon can bind the port."
  kill $EXISTING_PID 2>/dev/null || true
  sleep 1
fi
echo "Bridge + HUD will be at $BRIDGE_URL — opening it once it answers."
(
  for _ in $(seq 1 30); do
    if curl -s -o /dev/null "$BRIDGE_URL"; then
      open "$BRIDGE_URL" 2>/dev/null || true
      break
    fi
    sleep 1
  done
) &

exec python3 scripts/run_live.py
