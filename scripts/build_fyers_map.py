#!/usr/bin/env python3
"""Build the compiled-DB symbol -> Fyers ticker-fragment map used by HUD chart
deep links (my.fyers.in/?symbol=NSE:<fragment>-EQ / -INDEX).

Unlike Dhan, Fyers doesn't need a separate "display name" lookup — the deep
link takes the same ticker vanguard/data/instrument_master.py already parses
from Fyers' own scrip master. This script only exists because a handful of
underlyings don't map 1:1 onto the compiled DB's symbol spelling (Fyers calls
Nifty 50's ticker fragment "NIFTY50" and Bank Nifty's "NIFTYBANK", while the
compiled DB — and this platform's NIFTY/BANKNIFTY naming throughout — uses
"NIFTY"/"BANKNIFTY"). Reuses InstrumentMaster rather than re-parsing Fyers'
CSV a second time with its own hardcoded column indices.

Usage:
    python3 scripts/build_fyers_map.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vanguard.data.instrument_master import InstrumentMaster  # noqa: E402

OUT = ROOT / "data" / "compiled" / "fyers_symbol_map.json"


def _bare_symbol(ticker: str) -> str:
    """'NSE:NIFTYBANK-INDEX' -> 'NIFTYBANK'; 'NSE:RELIANCE-EQ' -> 'RELIANCE'."""
    s = ticker.split(":", 1)[-1]
    for suf in ("-EQ", "-INDEX"):
        if s.endswith(suf):
            return s[: -len(suf)]
    return s


def main() -> None:
    im = InstrumentMaster()

    try:
        import duckdb
        con = duckdb.connect(str(ROOT / "data" / "compiled" / "vanguard.duckdb"), read_only=True)
        syms = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM daily_market_structure").fetchall()]
        con.close()
    except Exception as e:
        print(f"[!] could not read compiled DB symbols: {e}")
        syms = []

    mapping = {}
    missing = []
    for sym in syms:
        row = im.spot(sym)
        if row:
            mapping[sym] = _bare_symbol(row["trading_symbol"])
        else:
            missing.append(sym)
    if missing:
        print(f"[!] {len(missing)} compiled symbols not in Fyers instrument master: {missing[:10]}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(mapping, indent=0, sort_keys=True))
    print(f"[*] Wrote {len(mapping)} mappings -> {OUT}")


if __name__ == "__main__":
    main()
