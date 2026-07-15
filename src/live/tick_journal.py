"""
Tick journal — append-only parquet per session. This is the research substrate
and (critically) the ONLY source for intraday-microstructure backtests, so it
must be lossless. Batched writes keep it off the hot path.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from src.live import config as C


class TickJournal:
    def __init__(self, date_str: str | None = None):
        self.date = date_str or datetime.now().strftime("%Y%m%d")
        self.path = C.LIVE_DIR / f"ticks_{self.date}.parquet"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._buf: list[dict] = []

    def append(self, tick: dict):
        self._buf.append(tick)

    def flush(self):
        """Append the buffer to the day's parquet. Safe to call on a timer."""
        if not self._buf:
            return
        df = pd.DataFrame(self._buf)
        self._buf = []
        if self.path.exists():
            prior = pd.read_parquet(self.path)
            df = pd.concat([prior, df], ignore_index=True)
        df.to_parquet(self.path, index=False)

    def close(self):
        self.flush()
