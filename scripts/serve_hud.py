#!/usr/bin/env python3
"""
Serve the baked HUD + EOD payload on http://127.0.0.1:8787/ (foreground).

This is the EOD-terminal replacement for the archived live daemon
(scripts/run_live.py, now under archive/live/): no broker socket, no live
compute — just the static HUD and /session/latest served off the last compile.

    python3 scripts/build_hud.py     # bake the HUD against the latest compile
    python3 scripts/serve_hud.py     # then serve it

Ctrl-C to stop.
"""
from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vanguard.config.paths import BRIDGE_HOST, BRIDGE_PORT  # noqa: E402
from vanguard.serve.api import Bridge, HUD_FILE  # noqa: E402


def main() -> int:
    if not HUD_FILE.exists():
        print(f"[serve_hud] {HUD_FILE} not found — run "
              f"`python3 scripts/build_hud.py` first.")
        return 1
    url = f"http://{BRIDGE_HOST}:{BRIDGE_PORT}/"
    try:
        webbrowser.open(url)
    except Exception:
        pass
    Bridge().serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
