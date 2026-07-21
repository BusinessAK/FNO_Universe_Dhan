"""
NSE Nifty 500 Industry classification — per-symbol sector/industry tag for
Track B (Cash/Equity), completing the E6 phase of docs/PRD_TRD_dual_track_
signals_v1.md. Feeds the `sector` column in daily_equity_setup_positions
(previously always NULL — "industry tagging is E6, not built yet"), and
shares its taxonomy with fpi_sector_flow.py's `sector` dimension (verified
2026-07-21: 18/20 category names match NSE's Industry column exactly; the
other 2 differ only by a missing comma, normalized in _normalize_industry()
below — NSDL's few extra buckets like "Sovereign"/"Others" simply don't
apply to individual equities and are expected to have no match here).

Single static CSV, not a fortnightly report like fpi_sector_flow — no
<select> dropdown to walk. Nifty 500 constituents are reconstituted
periodically (semi-annually), so this is refreshed on an as_of_date
snapshot basis: idempotent per calendar day, re-fetched next time
poll_context.py runs on a day without today's snapshot already present.
"""
from __future__ import annotations

import csv
import io
from datetime import date
from pathlib import Path

import pandas as pd

from vanguard.config.paths import RAW
from vanguard.pipeline.context.client import NseClient

URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
RAW_DIR = RAW / "context" / "industry_map"

DDL = """CREATE TABLE IF NOT EXISTS equity_industry_map (
    as_of_date DATE, symbol VARCHAR, company_name VARCHAR,
    industry VARCHAR, isin VARCHAR)"""

# The only two NSDL/NSE taxonomy spellings that differ (comma placement) —
# normalized to fpi_sector_flow's spelling so a plain join on `sector`/
# `industry` needs no separate mapping table. Anything not listed here
# passes through unchanged (already identical, per the 2026-07-21 audit).
_NORMALIZE = {
    "Oil Gas & Consumable Fuels": "Oil, Gas & Consumable Fuels",
    "Media Entertainment & Publication": "Media, Entertainment & Publication",
}


class ApiShapeDrift(RuntimeError):
    pass


def _normalize_industry(industry: str) -> str:
    return _NORMALIZE.get(industry, industry)


def parse_industry_map(raw: bytes, as_of_date: date) -> pd.DataFrame:
    """Company Name,Industry,Symbol,Series,ISIN Code -> one row per symbol."""
    text = raw.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    required = {"Company Name", "Industry", "Symbol", "ISIN Code"}
    if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
        raise ApiShapeDrift(
            f"ind_nifty500list.csv header changed, expected columns {required}, "
            f"got {reader.fieldnames}")
    out = []
    for row in reader:
        symbol = row["Symbol"].strip()
        if not symbol:
            continue
        out.append({
            "as_of_date": as_of_date,
            "symbol": symbol,
            "company_name": row["Company Name"].strip(),
            "industry": _normalize_industry(row["Industry"].strip()),
            "isin": row["ISIN Code"].strip(),
        })
    if not out:
        raise ApiShapeDrift("parsed 0 symbol rows from ind_nifty500list.csv")
    return pd.DataFrame(out)


def ingest_industry_map(client: NseClient | None = None, con=None,
                        today: date | None = None) -> str:
    """Idempotent per calendar day: no-ops if today's as_of_date snapshot is
    already present. Failure-isolated — exceptions are the caller's problem
    to catch, matching fpi_sector_flow.py's single call site in
    poll_context.py."""
    client = client or NseClient()
    today = today or date.today()

    con.execute(DDL)
    already = con.execute(
        "SELECT COUNT(*) FROM equity_industry_map WHERE as_of_date = ?",
        [today]).fetchone()[0]
    if already:
        return "ok:0 (up to date)"

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache = RAW_DIR / f"{today.isoformat()}.csv"
    if cache.exists():
        raw = cache.read_bytes()
    else:
        raw = client.get_bytes(URL)
        cache.write_bytes(raw)

    df = parse_industry_map(raw, today)
    con.execute("DELETE FROM equity_industry_map WHERE as_of_date = ?", [today])
    con.execute("INSERT INTO equity_industry_map SELECT * FROM df")
    return f"ok:{len(df)}"


def latest_symbol_industry_map(con) -> dict[str, str]:
    """symbol -> industry using the most recent as_of_date snapshot in the
    table. Returns {} if the table doesn't exist or is empty yet (matches
    the platform's "degrade visibly, don't fabricate" contract — callers
    get an empty map, not a stale or guessed one)."""
    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    if "equity_industry_map" not in tables:
        return {}
    latest = con.execute("SELECT MAX(as_of_date) FROM equity_industry_map").fetchone()[0]
    if latest is None:
        return {}
    rows = con.execute(
        "SELECT symbol, industry FROM equity_industry_map WHERE as_of_date = ?",
        [latest]).fetchall()
    return {sym: industry for sym, industry in rows}
