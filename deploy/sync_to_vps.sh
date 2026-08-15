#!/usr/bin/env bash
# One-time sync: bring the VPS's code and data up to parity with local.
#
# Two independent gaps this closes:
#   1. CODE  — local commits aren't deployed yet.
#   2. DATA  — the VPS's DuckDB only has ~3 sessions (poll_eod.py has no
#              backfill; it only ever fetches the current day's bhavcopy).
#
# This does NOT touch NVIDIA_API_KEY — that's a secret and per DEPLOY.md §4
# is copied out of band by you, not scripted. Add it to the VPS .env by hand:
#   ssh <host> 'echo "NVIDIA_API_KEY=..." >> /opt/vanguard/.env'
#
# Usage: ./deploy/sync_to_vps.sh <vps-tailscale-hostname>
set -euo pipefail

HOST="${1:?Usage: sync_to_vps.sh <vps-tailscale-hostname>}"
REMOTE_DIR="/opt/vanguard"
LOCAL_DB="data/compiled/vanguard.duckdb"
REMOTE_DB="$REMOTE_DIR/data/compiled/vanguard.duckdb"

if [ ! -f "$LOCAL_DB" ]; then
  echo "!! $LOCAL_DB not found — run from repo root" >&2
  exit 1
fi

echo "==> 1/5  Pulling latest code on $HOST"
ssh "$HOST" "cd $REMOTE_DIR && git pull --ff-only"

echo "==> 2/5  Stopping vanguard-serve.service (avoid reading a half-written DB)"
ssh "$HOST" "sudo systemctl stop vanguard-serve.service"

echo "==> 3/5  Backing up existing VPS DB before overwrite"
ssh "$HOST" "test -f $REMOTE_DB && cp $REMOTE_DB ${REMOTE_DB}.bak.\$(date +%Y%m%d%H%M%S) || echo '(no existing DB to back up)'"

echo "==> 4/5  Copying local DB ($(du -h "$LOCAL_DB" | cut -f1)) to VPS"
scp "$LOCAL_DB" "$HOST:$REMOTE_DB"

echo "==> 5/5  Rebuilding HUD and restarting service"
ssh "$HOST" "cd $REMOTE_DIR && ./venv/bin/python3 scripts/build_hud.py"
ssh "$HOST" "sudo systemctl start vanguard-serve.service"
ssh "$HOST" "systemctl is-active vanguard-serve.service"

cat <<EOF

Done. One thing still needs your hand, not this script:
  - a one-off manual trigger of briefing.py, since poll_eod.py short-circuits
    when today's bhavcopy already exists:
      ssh $HOST 'cd $REMOTE_DIR && ./venv/bin/python3 briefing.py && ./venv/bin/python3 scripts/build_hud.py'
EOF
