#!/usr/bin/env python3
"""
NSE context-layer poller (C1). Nightly companion to poll_eod — see
docs/PRD_TRD_nse_context_layer_v1.md.

    python3 scripts/poll_context.py                          # today
    python3 scripts/poll_context.py --date 2026-07-16
    python3 scripts/poll_context.py --only index_close delivery
    python3 scripts/poll_context.py --backfill 2025-07-19 2026-07-18 --pace 2

Weekends are skipped automatically; holidays surface as 'absent' (404) and
are fine. Any 'error:' status exits non-zero so the nightly chain alerts.
"""
import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vanguard.pipeline.context.client import NseClient          # noqa: E402
from vanguard.pipeline.context.datasets import DATASETS         # noqa: E402
from vanguard.pipeline.context.ingest import ingest_date        # noqa: E402
from vanguard.pipeline.context.api_datasets import ingest_api_datasets  # noqa: E402
from vanguard.pipeline.context.fpi_sector_flow import ingest_fpi_sector_flow  # noqa: E402
from vanguard.pipeline.context.industry_map import ingest_industry_map        # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default today)")
    ap.add_argument("--backfill", nargs=2, metavar=("START", "END"))
    ap.add_argument("--only", nargs="*", choices=sorted(DATASETS))
    ap.add_argument("--pace", type=float, default=2.0, help="seconds between requests")
    args = ap.parse_args()

    client = NseClient(pace_secs=args.pace)
    if args.backfill:
        start, end = (date.fromisoformat(x) for x in args.backfill)
        days = [start + timedelta(n) for n in range((end - start).days + 1)]
    else:
        days = [date.fromisoformat(args.date) if args.date else date.today()]

    worst = 0
    if not args.backfill and not args.only:
        import duckdb
        from vanguard.config.paths import DB
        con = duckdb.connect(str(DB))
        try:
            api_status = ingest_api_datasets(client, con)
        finally:
            con.close()
        print("[context] api " + " · ".join(f"{k}={v}" for k, v in api_status.items()), flush=True)
        if any(v.startswith("error") for v in api_status.values()):
            worst = 1
        con = duckdb.connect(str(DB))
        try:
            fpi_status = ingest_fpi_sector_flow(client, con)
        except Exception as e:                                # noqa: BLE001 — isolation, matches api_datasets
            fpi_status = f"error:{e}"
        finally:
            con.close()
        print(f"[context] fpi_sector_flow {fpi_status}", flush=True)
        if fpi_status.startswith("error"):
            worst = 1
        con = duckdb.connect(str(DB))
        try:
            industry_status = ingest_industry_map(client, con)
        except Exception as e:                                # noqa: BLE001 — isolation, matches fpi_sector_flow
            industry_status = f"error:{e}"
        finally:
            con.close()
        print(f"[context] industry_map {industry_status}", flush=True)
        if industry_status.startswith("error"):
            worst = 1
    for d in days:
        if d.weekday() >= 5:
            continue
        status = ingest_date(d, client=client, only=args.only)
        line = " · ".join(f"{k}={v}" for k, v in status.items())
        print(f"[context] {d} {line}", flush=True)
        if any(v.startswith("error") for v in status.values()):
            worst = 1
    return worst


if __name__ == "__main__":
    sys.exit(main())
