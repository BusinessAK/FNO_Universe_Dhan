#!/usr/bin/env python3
"""Build the NSE-ticker → Dhan display-symbol map used by HUD chart deep links.

Dhan's TradingView terminal (tv.dhan.co) resolves instruments by its Symbol
Search symbology — "{TRADING_SYMBOL}-{SERIES}" for equities (BHARTIARTL-EQ)
and the index trading symbol for indices (NIFTY, NIFTY BANK). A bare NSE
ticker or a display name in ?symbol= sets the pane label but never resolves
data. This script derives the mapping from Dhan's public scrip master and
writes data/compiled/dhan_symbol_map.json, which scripts/build_hud.py embeds
into the HUD payload.

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

# NSE F&O index tickers used in the compiled DB → Dhan index trading symbols.
# Dhan's index segment uses the F&O tickers verbatim (verified in scrip master),
# so this is an identity map — indices take no -EQ suffix.
INDEX_NAMES = {
    "NIFTY": "NIFTY",
    "BANKNIFTY": "BANKNIFTY",
    "FINNIFTY": "FINNIFTY",
    "MIDCPNIFTY": "MIDCPNIFTY",
    "NIFTYNXT50": "NIFTYNXT50",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=None, help="Path to a pre-downloaded scrip master CSV")
    args = ap.parse_args()

    src = args.csv or SCRIP_URL
    print(f"[*] Loading scrip master: {src}")
    df = pd.read_csv(src, low_memory=False)

    eq = df[(df["SEM_EXM_EXCH_ID"] == "NSE") & (df["SEM_SEGMENT"] == "E")
            & (df["SEM_SERIES"] == "EQ")]
    mapping = {str(t): f"{t}-EQ" for t in eq["SEM_TRADING_SYMBOL"]}
    # Validate the index symbols exist in the NSE index segment before mapping
    idx_syms = set(df[(df["SEM_EXM_EXCH_ID"] == "NSE") & (df["SEM_SEGMENT"] == "I")]
                   ["SEM_TRADING_SYMBOL"].astype(str))
    for k, v in INDEX_NAMES.items():
        if v not in idx_syms:
            print(f"[!] index symbol '{v}' (for {k}) not found in scrip master")
        mapping[k] = v

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
