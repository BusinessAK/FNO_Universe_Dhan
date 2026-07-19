#!/usr/bin/env python3
"""Build the Vanguard Orbital Deck HUD (static export path).

Bakes vanguard.store.export_service.build_payload() — the same builder
vanguard/serve/api.py serves live at /session/latest — into hud/template.html
and writes the self-contained hud/vanguard_hud.html. Kept as the offline/
file:// fallback artifact; when the HUD is served by the bridge it fetches
the payload instead (see template.html's __boot loader).

Usage:
    python3 scripts/build_hud.py [--db PATH] [--out PATH] [--sessions 30]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vanguard.store.export_service import build_payload  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "compiled" / "vanguard.duckdb"))
    ap.add_argument("--out", default=str(ROOT / "hud" / "vanguard_hud.html"))
    ap.add_argument("--sessions", type=int, default=30)
    args = ap.parse_args()

    data = build_payload(db_path=args.db, sessions=args.sessions)
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False)

    template = (ROOT / "hud" / "template.html").read_text()
    html = template.replace("__VANGUARD_DATA__", payload)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")            # atomic replace (fullmap U6)
    tmp.write_text(html)
    tmp.rename(out)
    sessions = data["meta"]["sessions"]
    print(f"sessions {sessions[0]} → {sessions[-1]} ({len(sessions)}) | "
          f"ms {len(data['market_structure']['rows'])} rows | "
          f"setups {len(data['setups']['rows'])} | signals {len(data['changes']['rows'])}")
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
