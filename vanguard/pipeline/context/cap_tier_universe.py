"""
Symbol → market-cap tier map (large / mid / small / micro), for
tier-segmented Cash Internals breadth.

Large = Nifty50 + Next50, Mid = Midcap150, Small = Smallcap250,
Micro = Microcap250 — all four fetched from NSE's index-constituent archive,
same URL family, day-cache, and stale-fallback pattern as
nifty50_universe.py.

2026-08-14: originally Micro was a catch-all "micro_other" for every symbol
outside the top-500 (~1,959 of ~2,459 valid symbols) — technically correct
(NSE has no official index below Smallcap250 covering that many names) but
useless for breadth reading: that bucket was 80% of the universe by count,
a grab-bag of legitimate micro-caps mixed with illiquid/thin-history names,
and its size visually swamped the three real tiers. Switched to NSE's actual
Nifty Microcap250 index (`ind_niftymicrocap250_list.csv` — note the
underscore before "list", unlike the other three URLs) so Micro is a
comparable ~250-name cohort like the others. Symbols outside all four lists
(~1,700 illiquid/unclassified names) are simply excluded from the tier map
now, not dumped into a leftover bucket — callers should treat "not in
tier_map" as "not covered by this breakdown", not as a fifth tier.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import date
from pathlib import Path

from vanguard.config.paths import COMPILED, LIVE
from vanguard.pipeline.context.client import NseClient
from vanguard.pipeline.context.nifty50_universe import get_nifty50_constituents

CACHE_DIR = LIVE / "universe"
TIER_MAP_PATH = COMPILED / "cap_tier_map.csv"

_NEXT50_URL = "https://archives.nseindia.com/content/indices/ind_niftynext50list.csv"
_MIDCAP150_URL = "https://archives.nseindia.com/content/indices/ind_niftymidcap150list.csv"
_SMALLCAP250_URL = "https://archives.nseindia.com/content/indices/ind_niftysmallcap250list.csv"
# Note the underscore before "list" — inconsistent with the other 3 URLs in
# this file, confirmed by direct fetch (2026-08-14); ind_niftymicrocap250list.csv
# (no underscore, matching the others' pattern) 404s.
_MICROCAP250_URL = "https://archives.nseindia.com/content/indices/ind_niftymicrocap250_list.csv"

# Sanity floors — a parse gone wrong from an NSE shape drift should never
# silently deliver a near-empty tier.
_MIN_EXPECTED = {"next50": 45, "midcap150": 130, "smallcap250": 220, "microcap250": 220}


def _cache_path(prefix: str, today: date) -> Path:
    return CACHE_DIR / f"{prefix}_{today.isoformat()}.json"


def _fetch_constituents(
    prefix: str, url: str, min_expected: int, today: date, client: NseClient | None
) -> list[str]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = _cache_path(prefix, today)
    if cache.exists():
        return json.loads(cache.read_text())

    try:
        client = client or NseClient()
        raw = client.get_bytes(url)
        text = raw.decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None or "Symbol" not in reader.fieldnames:
            raise RuntimeError(f"{prefix} csv header changed: {reader.fieldnames}")
        symbols = [row["Symbol"].strip() for row in reader if row["Symbol"].strip()]
        if len(symbols) < min_expected:
            raise RuntimeError(f"parsed only {len(symbols)} symbols, expected ~{min_expected}+")
        cache.write_text(json.dumps(symbols))
        return symbols
    except Exception as e:
        older = sorted(CACHE_DIR.glob(f"{prefix}_*.json"))
        if older:
            print(f"[cap_tier] {prefix} fetch failed ({e}) — using last cached "
                  f"list from {older[-1].name}")
            return json.loads(older[-1].read_text())
        raise RuntimeError(f"{prefix} constituent fetch failed and no cache exists: {e}")


def get_next50_constituents(today: date | None = None, client: NseClient | None = None) -> list[str]:
    today = today or date.today()
    return _fetch_constituents("next50", _NEXT50_URL, _MIN_EXPECTED["next50"], today, client)


def get_midcap150_constituents(today: date | None = None, client: NseClient | None = None) -> list[str]:
    today = today or date.today()
    return _fetch_constituents("midcap150", _MIDCAP150_URL, _MIN_EXPECTED["midcap150"], today, client)


def get_smallcap250_constituents(today: date | None = None, client: NseClient | None = None) -> list[str]:
    today = today or date.today()
    return _fetch_constituents("smallcap250", _SMALLCAP250_URL, _MIN_EXPECTED["smallcap250"], today, client)


def get_microcap250_constituents(today: date | None = None, client: NseClient | None = None) -> list[str]:
    today = today or date.today()
    return _fetch_constituents("microcap250", _MICROCAP250_URL, _MIN_EXPECTED["microcap250"], today, client)


def get_symbol_tier_map(
    universe_symbols: list[str] | None = None,
    today: date | None = None,
    client: NseClient | None = None,
) -> dict[str, str]:
    """symbol -> "large" / "mid" / "small" / "micro". `universe_symbols` is
    accepted for backward-compat call sites but no longer used to fabricate a
    catch-all tier — a symbol outside all four NSE lists just isn't in the
    returned map at all (caller's job to skip it, not lump it in).

    If any single constituent-list fetch fails with no cache to fall back on,
    that tier is simply empty for this run (logged, not raised) — a missing
    mid-cap list shouldn't block the whole breadth build. Also persists the
    resulting map to `data/compiled/cap_tier_map.csv` for inspection/reuse.
    """
    today = today or date.today()
    large: set[str] = set()
    mid: set[str] = set()
    small: set[str] = set()
    micro: set[str] = set()

    for label, fn, bucket in (
        ("nifty50", get_nifty50_constituents, large),
        ("next50", get_next50_constituents, large),
        ("midcap150", get_midcap150_constituents, mid),
        ("smallcap250", get_smallcap250_constituents, small),
        ("microcap250", get_microcap250_constituents, micro),
    ):
        try:
            bucket |= set(fn(today, client))
        except Exception as e:
            print(f"[cap_tier] {label} unavailable ({e}) — that tier will be under-populated this run")

    tier_map: dict[str, str] = {}
    for sym in large:
        tier_map[sym] = "large"
    for sym in mid:
        tier_map.setdefault(sym, "mid")
    for sym in small:
        tier_map.setdefault(sym, "small")
    for sym in micro:
        tier_map.setdefault(sym, "micro")

    TIER_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    with TIER_MAP_PATH.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["symbol", "tier"])
        for sym, tier in sorted(tier_map.items()):
            writer.writerow([sym, tier])

    return tier_map
