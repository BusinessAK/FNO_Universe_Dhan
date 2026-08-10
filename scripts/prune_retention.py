#!/usr/bin/env python3
"""
Rolling 1-year retention. Three independent mechanisms, matched to how each
table is actually populated (verified by inspecting each compiler, not
assumed):

1. daily_compiler.py is INCREMENTAL, not stateless: it persists
   data/compiled/session_history.json and skips any date already present
   in it, regardless of whether the raw bhavcopy file still exists on disk.
   daily_market_structure / daily_setups / daily_changes / daily_inventory /
   daily_market_breadth are all flattened from session_history.json on
   every run. Deleting raw files alone does NOT shrink these — confirmed by
   testing (274 sessions survived a raw-file-only prune). This script must
   both prune session_history.json (so the *next* compile doesn't resurrect
   old dates) AND DELETE directly from these tables (so the DB is correct
   immediately, not just after tomorrow's compile).

2. equity_compiler.py / cash_market_builder.py / CashMarketBreadthEngine
   (daily_equity_technicals, daily_equity_setups,
   daily_equity_setup_positions, daily_cm_breadth) ARE genuinely stateless —
   full CREATE OR REPLACE TABLE from data/raw's CM files on every run, no
   skip-logic found. Raw-file pruning alone correctly bounds these on the
   next compile; no direct DELETE needed for them here.

3. Tables fed by scripts/poll_context.py (NSE history APIs) are additive
   upserts, not raw-file rebuilds, so they need an explicit DELETE here too.

Safe to run standalone or from poll_eod.py after the nightly compile.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vanguard.config.paths import DB

RAW_DIR = "data/raw"
COMPILED_DIR = "data/compiled"
SESSION_HISTORY_PATH = os.path.join(COMPILED_DIR, "session_history.json")
DEFAULT_RETENTION_DAYS = 365

# table -> date column, for tables NOT covered by session_history.json pruning
_PRUNE_TABLES = {
    "daily_participant_oi": "date",
    "daily_index_close": "date",
    "daily_delivery": "date",
    "daily_ban": "date",
    "daily_fii_dii": "date",
    "daily_catalysts": "date",
    "corporate_events": "event_date",
}

# tables flattened straight from session_history.json by daily_compiler.py —
# pruned there AND here so the DB reflects the new window immediately
_SESSION_HISTORY_TABLES = {
    "daily_market_structure": "date",
    "daily_setups": "date",
    "daily_changes": "date",
    "daily_inventory": "date",
    "daily_market_breadth": "date",
}

_DATE_RE = re.compile(r"(\d{8})")


def prune_raw_files(cutoff: datetime, raw_dir: str = RAW_DIR, dry_run: bool = False) -> int:
    if not os.path.isdir(raw_dir):
        return 0
    removed = 0
    for fname in os.listdir(raw_dir):
        if "BhavCopy" not in fname:
            continue
        m = _DATE_RE.search(fname)
        if not m:
            continue
        try:
            fdate = datetime.strptime(m.group(1), "%Y%m%d")
        except ValueError:
            continue
        if fdate < cutoff:
            path = os.path.join(raw_dir, fname)
            if dry_run:
                print(f"[DRY-RUN] would remove {path}")
            else:
                os.remove(path)
            removed += 1
    return removed


def prune_session_history(cutoff: datetime, path: str = SESSION_HISTORY_PATH,
                           dry_run: bool = False) -> tuple:
    """Drop date entries older than cutoff from every symbol's history so the
    *next* daily_compiler.py run doesn't resurrect them. Returns
    (dates_removed_total, symbols_dropped_entirely)."""
    if not os.path.exists(path):
        return 0, 0
    with open(path) as f:
        history = json.load(f)

    cutoff_str = cutoff.strftime("%Y-%m-%d")
    removed = 0
    dropped_symbols = 0
    pruned = {}
    for symbol, by_date in history.items():
        kept = {d: v for d, v in by_date.items() if d >= cutoff_str}
        removed += len(by_date) - len(kept)
        if kept:
            pruned[symbol] = kept
        else:
            dropped_symbols += 1

    if not dry_run and removed:
        with open(path, "w") as f:
            json.dump(pruned, f, indent=4)
    return removed, dropped_symbols


def _prune_tables(cutoff: datetime, tables: dict, db_path: str, dry_run: bool) -> dict:
    import duckdb

    cutoff_str = cutoff.strftime("%Y-%m-%d")
    results = {}
    conn = duckdb.connect(db_path, read_only=dry_run)
    try:
        existing = {r[0] for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchall()}
        for table, col in tables.items():
            if table not in existing:
                continue
            count = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {col} < ?", [cutoff_str]
            ).fetchone()[0]
            if count == 0:
                results[table] = 0
                continue
            if not dry_run:
                conn.execute(f"DELETE FROM {table} WHERE {col} < ?", [cutoff_str])
            results[table] = count
    finally:
        conn.close()
    return results


def prune_db_tables(cutoff: datetime, db_path: str = DB, dry_run: bool = False) -> dict:
    results = _prune_tables(cutoff, _PRUNE_TABLES, db_path, dry_run)
    results.update(_prune_tables(cutoff, _SESSION_HISTORY_TABLES, db_path, dry_run))
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--retention-days", type=int, default=DEFAULT_RETENTION_DAYS)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cutoff = datetime.now() - timedelta(days=args.retention_days)
    print(f"[*] Retention cutoff: {cutoff.strftime('%Y-%m-%d')} ({args.retention_days}d window)")

    removed = prune_raw_files(cutoff, dry_run=args.dry_run)
    print(f"[*] Raw bhavcopy files {'to remove' if args.dry_run else 'removed'}: {removed}")

    hist_removed, hist_dropped = prune_session_history(cutoff, dry_run=args.dry_run)
    verb = "would remove" if args.dry_run else "removed"
    print(f"[*] session_history.json: {verb} {hist_removed} date entries"
          f"{f' ({hist_dropped} symbols dropped entirely)' if hist_dropped else ''}")

    db_results = prune_db_tables(cutoff, dry_run=args.dry_run)
    for table, count in db_results.items():
        if count:
            verb = "would delete" if args.dry_run else "deleted"
            print(f"[*] {table}: {verb} {count} rows")

    print("[SUCCESS] Retention prune complete." + (" (dry run, nothing changed)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
