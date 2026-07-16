"""
Replay harness for src/live/trigger_engine.py.

Feeds a recorded tick_journal dataset (data/live/ticks_YYYYMMDD/) back through
StateStore + TriggerEngine in timestamp order, reproducing the exact event log
the live daemon would have journaled that day. This is the trigger engine's
test suite against real market data (the PRD's explicit "replay harness"
requirement) and the seed of future intraday backtesting.

    python3 -m src.research.live_trigger_replay 20260716
    python3 -m src.research.live_trigger_replay 20260716 2026-07-15   # replay
        against a different day's armed setups, e.g. to sanity-check the rule
        against a session recorded before daily_setups existed for that date
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.live import config as C                      # noqa: E402
from src.live.state_store import StateStore            # noqa: E402
from src.live.trigger_engine import TriggerEngine, load_armed_book  # noqa: E402
from src.live.snapshot import build_key_symbol_map      # noqa: E402
from src.data.instrument_master import InstrumentMaster  # noqa: E402


def load_ticks(date_str: str) -> pd.DataFrame:
    tick_dir = C.LIVE_DIR / f"ticks_{date_str}"
    if not tick_dir.exists():
        raise FileNotFoundError(f"no tick journal for {date_str}: {tick_dir}")
    df = pd.read_parquet(tick_dir)
    return df.sort_values("ts").reset_index(drop=True)


def _clean(v):
    """NaN (from pandas' column union across heterogeneous ticks) must read as
    "field absent", same as it would live — never as a real zero/near-zero OI."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return v


def _row_to_tick(row: dict) -> dict:
    return {
        "seg": int(row["seg"]), "sid": int(row["sid"]), "ts": float(row["ts"]),
        "ltp": _clean(row.get("ltp")), "oi": _clean(row.get("oi")),
        "vol": _clean(row.get("vol")), "atp": _clean(row.get("atp")),
    }


def replay(date_str: str, db_date: str | None = None) -> list[dict]:
    """Replay one recorded session's ticks through StateStore + TriggerEngine.
    Returns the resulting event log (same shape the live daemon journals).
    `db_date` lets the armed book come from a different day than the ticks —
    default is the tick file's own date, formatted for daily_setups (date col)."""
    ticks = load_ticks(date_str)

    db = ROOT / "data" / "compiled" / "vanguard.duckdb"
    con = duckdb.connect(str(db), read_only=True)
    try:
        date_for_book = db_date or f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        book = load_armed_book(con, date=date_for_book)
    finally:
        con.close()

    im = InstrumentMaster()
    key_symbol = build_key_symbol_map(im, list(book.keys()))

    store = StateStore()
    engine = TriggerEngine(book, key_symbol)
    events: list[dict] = []

    for row in ticks.to_dict("records"):
        tick = _row_to_tick(row)
        if tick["ltp"] is None:
            continue
        closed = store.ingest(tick)
        if closed:
            key = (tick["seg"], tick["sid"])
            st = store.get(*key)
            events.extend(engine.on_bar_close(key, st.bars[-1]))
    return events


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python3 -m src.research.live_trigger_replay YYYYMMDD [armed_book_date YYYY-MM-DD]")
        sys.exit(1)
    date_arg = sys.argv[1]
    db_date_arg = sys.argv[2] if len(sys.argv) > 2 else None
    ev = replay(date_arg, db_date_arg)
    print(f"[replay] {date_arg}: {len(ev)} trigger events")
    for e in ev:
        print(f"  {e['symbol']:<12} {e['setup_type']:<20} {e['from']}->{e['to']} "
              f"level={e['level']:.2f} spot={e['spot']:.2f}")
