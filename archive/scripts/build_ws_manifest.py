#!/usr/bin/env python3
"""
Nightly WS manifest builder (TRD_fullmap_live_v1 §2). Runs after the EOD
compile; emits data/live/ws_manifest_<date>.parquet + a JSON coverage report.

On ANY failure it reuses the newest previous manifest (a stale map beats an
empty or half-built one — N10/N11) and exits non-zero so the nightly chain
alerts.

    python3 scripts/build_ws_manifest.py             # latest bhav in data/raw
    python3 scripts/build_ws_manifest.py --bhav data/raw/FO_...csv
"""
import argparse
import glob
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd                                    # noqa: E402

from vanguard.live import config as C                       # noqa: E402
from vanguard.live.manifest import build_manifest, ManifestError  # noqa: E402
from vanguard.data.instrument_master import InstrumentMaster      # noqa: E402


def latest_bhav() -> str:
    files = sorted(glob.glob(str(ROOT / "data/raw/FO_BhavCopy_NSE_FO_*.csv")))
    if not files:
        raise ManifestError("no bhav files in data/raw")
    return files[-1]


def previous_manifest() -> Path | None:
    prev = sorted(C.LIVE_DIR.glob("ws_manifest_*.parquet"))
    return prev[-1] if prev else None


def load_context():
    import duckdb
    con = duckdb.connect(str(ROOT / "data/compiled/vanguard.duckdb"), read_only=True)
    try:
        latest = con.execute("SELECT MAX(date) FROM daily_market_structure").fetchone()[0]
        universe = {r[0] for r in con.execute(
            "SELECT DISTINCT symbol FROM daily_market_structure WHERE date=?", [latest]).fetchall()}
        closes = dict(con.execute(
            "SELECT symbol, spot_close FROM daily_market_structure WHERE date=?", [latest]).fetchall())
        armed = {r[0] for r in con.execute(
            "SELECT DISTINCT symbol FROM daily_setups WHERE date="
            "(SELECT MAX(date) FROM daily_setups)").fetchall()}
    finally:
        con.close()
    return universe, closes, armed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bhav", default=None)
    ap.add_argument("--coverage", type=float, default=None)
    args = ap.parse_args()

    try:
        bhav_path = args.bhav or latest_bhav()
        print(f"[manifest] bhav: {bhav_path}")
        bhav = pd.read_csv(bhav_path, low_memory=False)
        universe, closes, armed = load_context()
        im = InstrumentMaster()
        mf, report = build_manifest(bhav, im, universe, closes, armed,
                                    today=date.today(), coverage=args.coverage)
        out = C.LIVE_DIR / f"ws_manifest_{date.today().strftime('%Y%m%d')}.parquet"
        C.LIVE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp")
        mf.to_parquet(tmp, index=False)
        tmp.rename(out)                                 # atomic (U6 discipline)
        (out.with_suffix(".report.json")).write_text(json.dumps(report, indent=2))
        print(f"[manifest] wrote {out.name}: {report['total']} instruments "
              f"({report['by_kind']}) / {report['connections_needed']} conns "
              f"/ coverage {report['coverage_used']}")
        return 0
    except Exception as e:
        prev = previous_manifest()
        print(f"[manifest] FAILED: {e}", file=sys.stderr)
        if prev:
            print(f"[manifest] falling back to previous manifest: {prev.name} "
                  f"(STALE — daemon will warn)", file=sys.stderr)
        else:
            print("[manifest] no previous manifest to fall back to", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
