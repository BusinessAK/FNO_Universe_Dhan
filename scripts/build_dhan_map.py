#!/usr/bin/env python3
"""Build the NSE-ticker → Dhan display-symbol map used by HUD chart deep links.

tv.dhan.co's ?symbol= param feeds the TradingView widget's initial symbol
(verified 2026-07 by deobfuscating bundle3.0.7.js), and the string its
datafeed resolves is the Dhan DISPLAY name (scrip master SEM_CUSTOM_SYMBOL:
"Dixon Technologies", "Nifty 50") — the DESCRIPTION column in Symbol Search
and the legend text on a resolved chart. "{TRADING_SYMBOL}-{SERIES}"
(MOTHERSON-EQ) sets the pane label but returns no data. This script derives
ticker → SEM_CUSTOM_SYMBOL from Dhan's public scrip master and writes
data/compiled/dhan_symbol_map.json, which scripts/build_hud.py embeds into
the HUD payload.

Usage:
    python3 scripts/build_dhan_map.py [--csv PATH]   # PATH skips the download
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SCRIP_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
OUT = ROOT / "data" / "compiled" / "dhan_symbol_map.json"

# NSE F&O index tickers used in the compiled DB. Values resolve to the index's
# SEM_CUSTOM_SYMBOL from the scrip master ("Nifty 50", "Nifty Bank").
INDEX_TICKERS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=None, help="Path to a pre-downloaded scrip master CSV")
    args = ap.parse_args()

    src = args.csv or SCRIP_URL
    print(f"[*] Loading scrip master: {src}")
    df = pd.read_csv(src, low_memory=False)

    eq = df[(df["SEM_EXM_EXCH_ID"] == "NSE") & (df["SEM_SEGMENT"] == "E")
            & (df["SEM_SERIES"] == "EQ")]
    mapping = {str(t): str(c) for t, c in
               zip(eq["SEM_TRADING_SYMBOL"], eq["SEM_CUSTOM_SYMBOL"]) if pd.notna(c)}
    # Indices: display name from the NSE index segment
    idx = df[(df["SEM_EXM_EXCH_ID"] == "NSE") & (df["SEM_SEGMENT"] == "I")]
    idx_map = {str(t): str(c) for t, c in
               zip(idx["SEM_TRADING_SYMBOL"], idx["SEM_CUSTOM_SYMBOL"]) if pd.notna(c)}
    for k in INDEX_TICKERS:
        if k not in idx_map:
            print(f"[!] index '{k}' not found in scrip master index segment")
        mapping[k] = idx_map.get(k, k)

    # sanity: warn on compiled F&O symbols we cannot map
    try:
        import duckdb
        con = duckdb.connect(str(ROOT / "data" / "compiled" / "vanguard.duckdb"), read_only=True)
        syms = [r[0] for r in con.execute(
            "SELECT DISTINCT symbol FROM daily_market_structure").fetchall()]
        con.close()
        missing = sorted(s for s in syms if s not in mapping)
        if missing:
            print(f"[!] {len(missing)} compiled symbols not in map: {missing[:10]}")
    except Exception:
        pass

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(mapping, indent=0, sort_keys=True))
    print(f"[*] Wrote {len(mapping)} mappings → {OUT}")


if __name__ == "__main__":
    main()
