#!/usr/bin/env python3
"""
Download NSE cash-market bhavcopies for dates already present in FO raw data.

Usage:
    python3 scripts/fetch_cm_history.py --limit 20
    python3 scripts/fetch_cm_history.py --start-date 2025-06-25 --end-date 2026-06-23 --build
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.data_fetcher import NSEDataFetcher
from src.research.cash_market_builder import build_cash_market_prices


FO_RE = re.compile(r"FO_BhavCopy_NSE_FO_0_0_0_(\d{8})_F_0000\.csv$")
CM_NAME = "CM_BhavCopy_NSE_CM_0_0_0_{date_str}_F_0000.csv"


def discover_fo_dates(raw_dir: str) -> list[str]:
    dates = []
    for path in Path(raw_dir).glob("FO_BhavCopy_NSE_FO_0_0_0_*_F_0000.csv"):
        match = FO_RE.match(path.name)
        if match:
            dates.append(match.group(1))
    return sorted(set(dates))


def filter_dates(dates: list[str], start_date: str | None, end_date: str | None) -> list[str]:
    if start_date:
        start_key = start_date.replace("-", "")
        dates = [d for d in dates if d >= start_key]
    if end_date:
        end_key = end_date.replace("-", "")
        dates = [d for d in dates if d <= end_key]
    return dates


def init_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(NSEDataFetcher.HEADERS)
    try:
        session.get("https://www.nseindia.com/all-reports", timeout=10)
    except Exception as exc:
        print(f"[!] Warning: NSE session warmup failed: {exc}")
    return session


def download_cm_date(session: requests.Session, raw_dir: str, date_str: str, sleep_s: float) -> bool:
    expected_path = Path(raw_dir) / CM_NAME.format(date_str=date_str)
    if expected_path.exists():
        print(f"[*] Exists: {expected_path.name}")
        return True

    url = NSEDataFetcher.CM_URL.format(date_str=date_str)
    print(f"[*] Fetching CM {date_str}: {url}")
    try:
        response = session.get(url, timeout=20)
        if response.status_code == 404:
            print(f"[!] 404 unavailable: {date_str}")
            return False
        response.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            for filename in zf.namelist():
                if filename.endswith(".csv"):
                    with open(expected_path, "wb") as f:
                        f.write(zf.read(filename))
                    print(f"[SUCCESS] Saved {expected_path}")
                    time.sleep(sleep_s)
                    return True
        print(f"[!] No CSV found inside zip for {date_str}")
        return False
    except Exception as exc:
        print(f"[!] Failed {date_str}: {exc}")
        return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch NSE CM bhavcopies for existing FO dates.")
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--start-date", default=None, help="Inclusive YYYY-MM-DD or YYYYMMDD.")
    parser.add_argument("--end-date", default=None, help="Inclusive YYYY-MM-DD or YYYYMMDD.")
    parser.add_argument("--limit", type=int, default=None, help="Download at most N missing dates.")
    parser.add_argument("--reverse", action="store_true", help="Download newest dates first.")
    parser.add_argument("--sleep", type=float, default=0.8, help="Delay between successful downloads.")
    parser.add_argument("--build", action="store_true", help="Build cash_market_prices.parquet after downloads.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    os.makedirs(args.raw_dir, exist_ok=True)

    dates = filter_dates(discover_fo_dates(args.raw_dir), args.start_date, args.end_date)
    if args.reverse:
        dates = list(reversed(dates))
    if args.limit:
        missing = [d for d in dates if not (Path(args.raw_dir) / CM_NAME.format(date_str=d)).exists()]
        selected_missing = set(missing[:args.limit])
        dates = [d for d in dates if d in selected_missing or (Path(args.raw_dir) / CM_NAME.format(date_str=d)).exists()]

    if not dates:
        raise SystemExit("[!] No FO dates found to mirror. Check data/raw.")

    print(f"[*] Candidate dates: {len(dates)}")
    print(f"[*] Range: {datetime.strptime(min(dates), '%Y%m%d').date()} to {datetime.strptime(max(dates), '%Y%m%d').date()}")

    session = init_session()
    ok = 0
    failed = 0
    for date_str in dates:
        if download_cm_date(session, args.raw_dir, date_str, args.sleep):
            ok += 1
        else:
            failed += 1

    print(f"[*] CM fetch complete. Available/success: {ok}, failed/unavailable: {failed}")

    if args.build:
        prices = build_cash_market_prices(args.raw_dir)
        print(f"[SUCCESS] Built cash market OHLC dataset with {len(prices):,} rows.")


if __name__ == "__main__":
    main()
