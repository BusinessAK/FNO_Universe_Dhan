#!/usr/bin/env python3
"""
Send a Telegram message via the Bot API. Used by nightly.sh to alert on
pipeline failures (bhavcopy never published, compile crash, HUD parity
mismatch) so a failed nightly run doesn't just sit silently in a log file.

Requires two env vars (set in .env or the systemd unit's Environment=):
    TELEGRAM_BOT_TOKEN   from @BotFather
    TELEGRAM_CHAT_ID     your numeric chat id (see docs/DEPLOY.md for how
                          to get both)

Usage:
    python3 scripts/notify_telegram.py "message text"

Fails soft: missing config or a network error prints a warning to stderr
and exits 0, so a broken alert channel never breaks the nightly pipeline
it's supposed to be monitoring.
"""
from __future__ import annotations

import os
import sys
import urllib.request
import urllib.parse


def main() -> int:
    if len(sys.argv) < 2:
        print("[notify_telegram] usage: notify_telegram.py <message>", file=sys.stderr)
        return 0

    message = sys.argv[1]
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[notify_telegram] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — skipping alert", file=sys.stderr)
        return 0

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10) as resp:
            resp.read()
    except Exception as e:
        print(f"[notify_telegram] failed to send alert: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
