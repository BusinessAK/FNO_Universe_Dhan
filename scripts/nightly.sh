#!/usr/bin/env bash
# Evening EOD sync — the automated form of `./start.sh full` (tests -> EOD
# pipeline -> HUD parity), anticipated but never built per
# docs/TRD_fullmap_live_v1.md.
#
# Invoked repeatedly by launchd (com.vanguard.eod-sync, StartCalendarInterval
# firing every ~15 min across the evening window) rather than once at a fixed
# time: poll_eod.py is single-shot — it checks once whether NSE has published
# today's bhavcopy yet and exits 1 if not ("will retry in next poll"), so the
# retry loop has to live outside it. poll_eod.py's own already-exists
# short-circuit (skips work if today's file is already on disk) makes
# repeated fires after a successful day cheap/harmless — this script does NOT
# duplicate that check.
#
# Deliberately not `set -e`: poll_eod.py's exit 1 (bhavcopy not published
# yet) is an expected, routine outcome on most fires, not a script failure.
set -uo pipefail
cd "$(dirname "$0")/.."

LOG_DIR="data/live"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/nightly_$(date +%Y%m%d).log"

echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') nightly poll ===" >>"$LOG"
python3 poll_eod.py >>"$LOG" 2>&1
STATUS=$?

alert() {
  # Best-effort Telegram alert — never allowed to fail the nightly run itself
  # (notify_telegram.py already fails soft, this is belt-and-suspenders).
  python3 scripts/notify_telegram.py "[vanguard nightly] $1" >>"$LOG" 2>&1 || true
}

if [ "$STATUS" -eq 0 ]; then
  echo "[nightly] bhavcopy processed — running tests + HUD parity check" >>"$LOG"
  python3 run_tests.py >>"$LOG" 2>&1 \
    || { echo "[nightly] WARNING: tests failed after a successful EOD compile" >>"$LOG"; \
         alert "tests FAILED after EOD compile on $(date +%Y-%m-%d) — check nightly_$(date +%Y%m%d).log"; }
  python3 scripts/verify_hud.py --url "file://$(pwd)/hud/vanguard_hud.html" >>"$LOG" 2>&1 \
    || { echo "[nightly] WARNING: HUD parity check failed" >>"$LOG"; \
         alert "HUD parity check FAILED on $(date +%Y-%m-%d) — check nightly_$(date +%Y%m%d).log"; }
  echo "[nightly] done" >>"$LOG"
elif [ "$STATUS" -eq 1 ]; then
  echo "[nightly] bhavcopy not published yet — will retry next interval" >>"$LOG"
  if [ "$(date +%H:%M)" = "21:00" ]; then
    alert "bhavcopy STILL not published as of 21:00 on $(date +%Y-%m-%d) — last retry window of the evening"
  fi
else
  echo "[nightly] poll_eod.py failed with status $STATUS" >>"$LOG"
  alert "poll_eod.py CRASHED (exit $STATUS) on $(date +%Y-%m-%d) — check nightly_$(date +%Y%m%d).log"
fi
