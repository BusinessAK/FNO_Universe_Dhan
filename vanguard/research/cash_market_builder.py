#!/usr/bin/env python3
"""
Build a cash-market OHLCV research dataset from NSE CM UDiFF bhavcopies.

Expected raw files are named like:
    data/raw/CM_BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv

The builder is intentionally tolerant of UDiFF column drift. It maps the common
NSE columns used in recent bhavcopies and leaves optional delivery fields blank
when they are not present.
"""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

import pandas as pd


RAW_PATTERN = "CM_*.csv"
DEFAULT_RAW_DIR = "data/raw"
DEFAULT_OUTPUT = "data/compiled/cash_market_prices.parquet"


COLUMN_MAP = {
    "TradDt": "date",
    "TckrSymb": "symbol",
    "SctySrs": "series",
    "OpnPric": "open",
    "HghPric": "high",
    "LwPric": "low",
    "ClsPric": "close",
    "LastPric": "last",
    "PrvsClsgPric": "prev_close",
    "TtlTradgVol": "volume",
    "TtlTrfVal": "turnover",
    "TtlNbOfTxsExctd": "trades",
    "ISIN": "isin",
    "FinInstrmTp": "instrument",
    # Delivery columns vary across NSE archives/vendors. These are optional.
    "DelivQty": "deliverable_qty",
    "DlvryQty": "deliverable_qty",
    "DeliverableQty": "deliverable_qty",
    "DelivPer": "delivery_pct",
    "DlvryPer": "delivery_pct",
    "PctDlvryQtyToTradedQty": "delivery_pct",
}


def extract_date_from_filename(path: Path) -> str | None:
    match = re.search(r"\d{8}", path.name)
    if not match:
        return None
    value = match.group(0)
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


def normalize_cash_file(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df.rename(columns={k: v for k, v in COLUMN_MAP.items() if k in df.columns})

    if "date" not in df.columns:
        file_date = extract_date_from_filename(path)
        if not file_date:
            raise ValueError(f"Could not infer trading date for {path}")
        df["date"] = file_date

    required = ["date", "symbol", "open", "high", "low", "close", "volume"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"{path} missing required CM columns after mapping: {missing}")

    if "series" in df.columns:
        df = df[df["series"].astype(str).str.strip().eq("EQ")].copy()
    if "instrument" in df.columns:
        instrument = df["instrument"].astype(str).str.strip()
        equity_like = instrument.isin(["STK", "ST", "EQUITY", ""])
        if equity_like.any():
            df = df[equity_like].copy()

    keep = [
        "date", "symbol", "series", "isin", "open", "high", "low", "close",
        "last", "prev_close", "volume", "turnover", "trades",
        "deliverable_qty", "delivery_pct",
    ]
    for col in keep:
        if col not in df.columns:
            df[col] = pd.NA

    out = df[keep].copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["symbol"] = out["symbol"].astype(str).str.strip().str.upper()
    for col in ["open", "high", "low", "close", "last", "prev_close", "volume", "turnover", "trades", "deliverable_qty", "delivery_pct"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out = out.dropna(subset=["date", "symbol", "open", "high", "low", "close"])
    out = out[out["close"] > 0]
    return out


def build_cash_market_prices(raw_dir: str = DEFAULT_RAW_DIR, output_path: str = DEFAULT_OUTPUT) -> pd.DataFrame:
    paths = sorted(Path(raw_dir).glob(RAW_PATTERN))
    if not paths:
        raise FileNotFoundError(f"No CM bhavcopy files found in {raw_dir!r} matching {RAW_PATTERN!r}")

    frames = []
    errors = []
    for path in paths:
        try:
            frames.append(normalize_cash_file(path))
        except Exception as exc:
            errors.append(f"{path}: {exc}")

    if not frames:
        raise RuntimeError("No CM files could be normalized:\n" + "\n".join(errors[:20]))

    prices = pd.concat(frames, ignore_index=True)
    prices = prices.sort_values(["symbol", "date"]).drop_duplicates(["symbol", "date"], keep="last")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    prices.to_parquet(output_path, index=False)

    if errors:
        err_path = os.path.splitext(output_path)[0] + "_errors.txt"
        with open(err_path, "w") as f:
            f.write("\n".join(errors))

    return prices


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build cash-market OHLCV parquet from CM bhavcopies.")
    parser.add_argument("--raw-dir", default=DEFAULT_RAW_DIR)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    prices = build_cash_market_prices(args.raw_dir, args.output)
    print("[SUCCESS] Cash-market research dataset built.")
    print(f"rows: {len(prices):,}")
    print(f"symbols: {prices['symbol'].nunique():,}")
    print(f"date range: {prices['date'].min().date()} to {prices['date'].max().date()}")
    print(f"output: {args.output}")


if __name__ == "__main__":
    main()

