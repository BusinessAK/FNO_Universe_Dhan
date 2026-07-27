"""
Nifty50 constituent list + the index symbol set — scopes the HUD's Symbol
Scanner to Nifty50 + indices. Fetched from NSE's own index-constituent
archive (same URL family/shape as industry_map.py's Nifty 500 fetch), cached
per calendar day so repeated EOD/HUD builds don't hit NSE and a network
hiccup doesn't block a build.

Relocated here from vanguard/live/universe.py when the live/intraday layer was
archived: the fetch is a daily EOD-grade lookup with nothing intraday about it,
and the EOD payload (store.export_service) still needs it to keep the scanner
scoped exactly as before.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import date
from pathlib import Path

from vanguard.config.paths import LIVE
from vanguard.pipeline.context.client import NseClient

# Kept alongside the old on-disk cache location so previously-cached lists are
# still found after the relocation.
CACHE_DIR = LIVE / "universe"
URL = "https://archives.nseindia.com/content/indices/ind_nifty50list.csv"
MIN_EXPECTED = 45  # sanity floor — a parse gone wrong from an NSE shape drift
                    # should never silently deliver a near-empty universe

INDEX_SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"]


def _cache_path(today: date) -> Path:
    return CACHE_DIR / f"nifty50_{today.isoformat()}.json"


def get_nifty50_constituents(today: date | None = None,
                              client: NseClient | None = None) -> list[str]:
    """Today's Nifty50 constituent symbols, cached per calendar day.

    Falls back to the most recent cache on disk (any date) if today's fetch
    fails — a stale-but-real list beats crashing a build over a transient NSE
    archive hiccup."""
    today = today or date.today()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = _cache_path(today)
    if cache.exists():
        return json.loads(cache.read_text())

    try:
        client = client or NseClient()
        raw = client.get_bytes(URL)
        text = raw.decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None or "Symbol" not in reader.fieldnames:
            raise RuntimeError(f"ind_nifty50list.csv header changed: {reader.fieldnames}")
        symbols = [row["Symbol"].strip() for row in reader if row["Symbol"].strip()]
        if len(symbols) < MIN_EXPECTED:
            raise RuntimeError(f"parsed only {len(symbols)} symbols, expected ~50")
        cache.write_text(json.dumps(symbols))
        return symbols
    except Exception as e:
        older = sorted(CACHE_DIR.glob("nifty50_*.json"))
        if older:
            print(f"[universe] Nifty50 fetch failed ({e}) — using last cached "
                  f"list from {older[-1].name}")
            return json.loads(older[-1].read_text())
        raise RuntimeError(f"Nifty50 constituent fetch failed and no cache exists: {e}")
