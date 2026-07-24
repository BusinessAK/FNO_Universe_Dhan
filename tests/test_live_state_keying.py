"""
Live-layer instrument keying.

Under the old Dhan feed, security_id alone was NOT unique across segments —
two real collisions existed in the F&O 215 (sid 13 = NIFTY(IDX) + ABB(NSE_EQ);
sid 25 = BANKNIFTY(IDX) + ADANIENT(NSE_EQ)), and keying live state by
security_id alone made each pair share one SecurityState: the equity vanished
from the snapshot and its ticks corrupted the index's LTP/chg%/OHLC/bars
(observed live: NIFTY reading 7230.0 at -69.94%).

Fyers keys instruments by a ticker string (e.g. "NSE:NIFTY50-INDEX") that is
already globally unique, so this specific collision can no longer occur in
practice — feed_handler._key() now hardcodes seg=0 for every Fyers tick
(nothing computes a real segment from the packet anymore). The (seg, sid)
tuple shape is kept in StateStore/snapshot only for generality; these tests
exercise the underlying invariant (two distinct instruments' state must never
merge) using two distinct fake sids rather than a real segment collision,
since that's what actually flows through the system today.
"""
import tempfile
import unittest
from pathlib import Path

from vanguard.live import config as C
from vanguard.live.feed_handler import normalize
from vanguard.live.snapshot import build_key_symbol_map, write_snapshot
from vanguard.live.state_store import StateStore

NIFTY_KEY = (0, "NSE:NIFTY50-INDEX")   # NIFTY spot
ABB_KEY = (0, "NSE:ABB-EQ")            # ABB equity — distinct ticker, same seg (0, always, under Fyers)

NIFTY_CLOSE, ABB_CLOSE = 24052.0, 7280.0
NIFTY_LTP, ABB_LTP = 24074.85, 7230.0


def tick(seg, sid, ltp, ts=1_784_100_000.0):
    return {"seg": seg, "sid": sid, "ts": ts, "ltp": ltp}


class _FakeMaster:
    """Minimal InstrumentMaster stand-in, Fyers-ticker-shaped."""

    _ROWS = {
        "NIFTY": {"security_id": "NSE:NIFTY50-INDEX", "feed_segment": 0},
        "ABB": {"security_id": "NSE:ABB-EQ", "feed_segment": 0},
        "BANKNIFTY": {"security_id": "NSE:NIFTYBANK-INDEX", "feed_segment": 0},
        "ADANIENT": {"security_id": "NSE:ADANIENT-EQ", "feed_segment": 0},
        "RELIANCE": {"security_id": "NSE:RELIANCE-EQ", "feed_segment": 0},
    }

    def spot(self, symbol):
        return dict(self._ROWS[symbol]) if symbol in self._ROWS else None


class TestNormalizeKeepsSegment(unittest.TestCase):
    def test_quote_packet_is_keyed_by_ticker(self):
        t = normalize({"symbol": "NSE:ABB-EQ", "ltp": 7230.00})
        self.assertEqual(t["seg"], 0)
        self.assertEqual(t["sid"], "NSE:ABB-EQ")

    def test_oi_packet_is_keyed_by_ticker(self):
        t = normalize({"symbol": "NSE:ABB-EQ", "open_interest": 4200})
        self.assertEqual(t["seg"], 0)
        self.assertEqual(t["oi"], 4200)

    def test_packet_without_symbol_is_dropped(self):
        # An unkeyable tick must never be silently attributed to another instrument.
        self.assertIsNone(normalize({"ltp": 7230.00}))


class TestDistinctInstrumentsStayIsolated(unittest.TestCase):
    def setUp(self):
        self.store = StateStore()

    def test_distinct_sids_keep_separate_state(self):
        self.store.ingest(tick(*NIFTY_KEY, NIFTY_LTP))
        self.store.ingest(tick(*ABB_KEY, ABB_LTP))

        n, a = self.store.get(*NIFTY_KEY), self.store.get(*ABB_KEY)
        self.assertIsNot(n, a)
        self.assertEqual(n.ltp, NIFTY_LTP)
        self.assertEqual(a.ltp, ABB_LTP)

    def test_distinct_sids_keep_separate_session_ohlc(self):
        self.store.ingest(tick(*NIFTY_KEY, NIFTY_LTP))
        self.store.ingest(tick(*ABB_KEY, ABB_LTP))

        n = self.store.get(*NIFTY_KEY)
        self.assertEqual(n.l, NIFTY_LTP)   # ABB's 7230 must not become NIFTY's low
        self.assertEqual(n.h, NIFTY_LTP)

    def test_distinct_sids_keep_separate_bars(self):
        # Two minutes of NIFTY ticks; an ABB tick in between must not enter
        # NIFTY's bar (M3's trigger engine fires on 1-min bar close).
        self.store.ingest(tick(*NIFTY_KEY, NIFTY_LTP, ts=60.0))
        self.store.ingest(tick(*ABB_KEY, ABB_LTP, ts=61.0))
        self.store.ingest(tick(*NIFTY_KEY, NIFTY_LTP + 5, ts=125.0))

        bars = self.store.get(*NIFTY_KEY).bars
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0]["l"], NIFTY_LTP)

    def test_prev_close_seed_is_segment_scoped(self):
        self.store.seed_prev_close(*ABB_KEY, ABB_CLOSE)
        self.store.seed_prev_close(*NIFTY_KEY, NIFTY_CLOSE)
        self.store.ingest(tick(*NIFTY_KEY, NIFTY_LTP))
        self.store.ingest(tick(*ABB_KEY, ABB_LTP))

        self.assertAlmostEqual(self.store.get(*NIFTY_KEY).chg_pct, 0.09, delta=0.05)
        self.assertAlmostEqual(self.store.get(*ABB_KEY).chg_pct, -0.69, delta=0.05)


class TestSnapshotKeying(unittest.TestCase):
    def test_map_keeps_both_distinct_symbols(self):
        m = build_key_symbol_map(_FakeMaster(), ["ABB", "NIFTY", "ADANIENT", "BANKNIFTY"])
        self.assertEqual(len(m), 4)
        self.assertEqual(m[NIFTY_KEY], "NIFTY")
        self.assertEqual(m[ABB_KEY], "ABB")

    def test_snapshot_reports_both_distinct_symbols(self):
        store = StateStore()
        store.seed_prev_close(*NIFTY_KEY, NIFTY_CLOSE)
        store.seed_prev_close(*ABB_KEY, ABB_CLOSE)
        store.ingest(tick(*NIFTY_KEY, NIFTY_LTP))
        store.ingest(tick(*ABB_KEY, ABB_LTP))

        key_symbol = build_key_symbol_map(_FakeMaster(), ["ABB", "NIFTY"])
        with tempfile.TemporaryDirectory() as d:
            snap = write_snapshot(store, key_symbol, path=Path(d) / "snap.json")

        self.assertEqual(snap["n"], 2)
        self.assertEqual(snap["quotes"]["NIFTY"]["ltp"], NIFTY_LTP)
        self.assertEqual(snap["quotes"]["ABB"]["ltp"], ABB_LTP)


class TestSnapshotLiveness(unittest.TestCase):
    """The snapshot must expose feed liveness separately from writer liveness.

    Since the daemon loop is exception-guarded it keeps writing snapshots even
    if the feed thread stalls, so `ts` (write time) is always fresh and proves
    nothing. Only `feed_ts` (last tick) can drop the HUD's LIVE badge.
    """

    def _write(self, store, symbols=("NIFTY",)):
        km = build_key_symbol_map(_FakeMaster(), list(symbols))
        with tempfile.TemporaryDirectory() as d:
            return write_snapshot(store, km, path=Path(d) / "snap.json")

    def test_feed_ts_is_last_tick_not_write_time(self):
        store = StateStore()
        store.ingest(tick(*NIFTY_KEY, NIFTY_LTP, ts=1_784_100_000.0))
        snap = self._write(store)

        self.assertEqual(snap["feed_ts"], 1_784_100_000.0)
        self.assertNotEqual(snap["feed_ts"], snap["ts"])
        self.assertGreater(snap["ts"], snap["feed_ts"])   # writer alive, feed stale

    def test_feed_ts_tracks_the_most_recent_tick(self):
        store = StateStore()
        store.ingest(tick(*NIFTY_KEY, NIFTY_LTP, ts=1_784_100_000.0))
        store.ingest(tick(*ABB_KEY, ABB_LTP, ts=1_784_100_042.0))
        snap = self._write(store, ["NIFTY", "ABB"])

        self.assertEqual(snap["feed_ts"], 1_784_100_042.0)

    def test_feed_ts_is_zero_when_nothing_has_ticked(self):
        # No ticks -> the HUD must treat the feed as stale, not as "just started".
        snap = self._write(StateStore())
        self.assertEqual(snap["n"], 0)
        self.assertEqual(snap["feed_ts"], 0.0)


class TestRealUniverseHasNoKeyCollisions(unittest.TestCase):
    """Guards the real scrip master: the F&O 215 + indices must yield one
    distinct key per symbol. Skipped when the master parquet isn't built."""

    def test_every_symbol_gets_a_distinct_key(self):
        if not C.INSTRUMENT_MASTER.exists():
            self.skipTest("instrument_master.parquet not built")
        from vanguard.data.instrument_master import InstrumentMaster

        im = InstrumentMaster(C.INSTRUMENT_MASTER)
        symbols = sorted({s for s in im.df[im.df.kind.isin(["EQ", "INDEX"])].underlying
                          if s in set(C.INDEX_SYMBOLS)} | {"ABB", "ADANIENT", "RELIANCE"})
        m = build_key_symbol_map(im, symbols)
        self.assertEqual(len(m), len(symbols),
                         "security_id collision — keys must include the segment")


if __name__ == "__main__":
    unittest.main()
