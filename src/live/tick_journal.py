"""
Tick journal — append-only parquet *dataset* (one part file per flush) per
session. Writing a new part each flush is O(1) and corruption-proof, versus
re-reading + rewriting a single growing file (which is O(n^2) and can wedge the
daemon). Read the whole day with pd.read_parquet(dir) or duckdb.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from src.live import config as C

# Explicit, stable schema (TRD_fullmap_live_v1 §8 / V5): inferring columns from
# whichever tick dicts land in a flush batch produced parquet parts with
# inconsistent schemas — an all-price batch silently dropped the oi column for
# the whole part, making OI-bearing replays impossible.
JOURNAL_COLS = ["seg", "sid", "ts", "ltp", "vol", "atp", "oi"]


class TickJournal:
    def __init__(self, date_str: str | None = None):
        self.date = date_str or datetime.now().strftime("%Y%m%d")
        self.dir = C.LIVE_DIR / f"ticks_{self.date}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._buf: list[dict] = []
        self._part = 0

    def append(self, tick: dict):
        self._buf.append(tick)

    def flush(self):
        """Write the buffer to a fresh part file — never re-reads prior data."""
        if not self._buf:
            return
        rows, self._buf = self._buf, []
        self._part += 1
        try:
            df = pd.DataFrame(rows, columns=JOURNAL_COLS)
            df.to_parquet(self.dir / f"part_{self._part:05d}.parquet", index=False)
        except Exception as e:                 # never let journaling kill the daemon
            print(f"[tick_journal] flush error (dropping {len(rows)} ticks): {e}")

    def close(self):
        self.flush()

    @property
    def path(self):                            # back-compat: the dataset dir
        return self.dir
