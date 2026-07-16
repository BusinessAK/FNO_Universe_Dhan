"""
V5 regression (TRD_fullmap_live_v1 §8): every journal part must carry the
full stable schema — including `oi` — regardless of which fields the ticks in
that flush batch happened to have. Inferred schemas made OI replays impossible.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src.live import config as C
from src.live.tick_journal import TickJournal, JOURNAL_COLS


class TestJournalSchema(unittest.TestCase):
    def test_every_part_has_stable_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(C, "LIVE_DIR", Path(tmp)):
                j = TickJournal(date_str="19700101")
                # batch 1: price-only ticks (no oi key anywhere)
                j.append({"seg": 1, "sid": 10, "ts": 1.0, "ltp": 100.0, "vol": 5, "atp": 99.9})
                j.flush()
                # batch 2: an OI tick (ltp None) + a full tick
                j.append({"seg": 2, "sid": 20, "ts": 2.0, "ltp": None, "oi": 5000})
                j.append({"seg": 2, "sid": 21, "ts": 2.1, "ltp": 55.5, "vol": 1,
                          "atp": 55.0, "oi": 7000})
                j.flush()

                parts = sorted(j.dir.glob("part_*.parquet"))
                self.assertEqual(len(parts), 2)
                for p in parts:
                    df = pd.read_parquet(p)
                    self.assertEqual(list(df.columns), JOURNAL_COLS,
                                     f"{p.name} schema drifted")
                # the OI made it to disk
                d2 = pd.read_parquet(parts[1])
                self.assertEqual(d2.oi.dropna().tolist(), [5000.0, 7000.0])

    def test_flush_never_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(C, "LIVE_DIR", Path(tmp)):
                j = TickJournal(date_str="19700101")
                j.append({"seg": 1, "sid": 1, "ts": 1.0, "ltp": 1.0,
                          "weird_extra_key": object()})   # unserializable extra
                j.flush()                                  # must not raise


if __name__ == "__main__":
    unittest.main()
