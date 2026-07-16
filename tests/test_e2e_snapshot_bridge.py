"""
End-to-end (offline): SDK-shaped packets -> feed_handler.normalize ->
StateStore -> write_snapshot -> Bridge over real HTTP -> client-side freshness
gate semantics. Exercises the exact data path the HUD consumes, on an
ephemeral port with a temp snapshot file — no network, no market.
"""
import json
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from src.live import config as C
from src.live import bridge as bridge_mod
from src.live.feed_handler import normalize
from src.live.snapshot import write_snapshot
from src.live.state_store import StateStore


def sdk_quote(seg, sid, ltp, vol=100, oi=None):
    d = {"type": "Quote Data", "exchange_segment": seg, "security_id": sid,
         "LTP": str(ltp), "volume": vol, "avg_price": str(ltp)}
    if oi is not None:
        d["OI"] = oi
    return d


def sdk_oi(seg, sid, oi):
    return {"type": "OI Data", "exchange_segment": seg, "security_id": sid, "OI": oi}


class TestE2ESnapshotBridge(unittest.TestCase):
    def test_packets_to_http_snapshot(self):
        store = StateStore()
        # NIFTY(IDX sid 13) and ABB(EQ sid 13): the collision pair — must stay distinct
        key_symbol = {(0, 13): "NIFTY", (1, 13): "ABB", (2, 999): "RELFUT"}
        store.seed_prev_close(0, 13, 24000.0)
        store.seed_prev_close(1, 13, 5000.0)

        # SDK-shaped packets through the real normalize()
        for raw in (sdk_quote(0, 13, 24120.5),          # NIFTY +0.5%
                    sdk_quote(1, 13, 4950.0),           # ABB -1%
                    sdk_quote(2, 999, 101.0, oi=777),   # future WITH OI (Full mode)
                    sdk_oi(2, 999, 888)):               # then a standalone OI update
            tick = normalize(raw)
            self.assertIsNotNone(tick, f"normalize dropped {raw['type']}")
            store.ingest(tick)

        events = [{"ts": time.time(), "symbol": "NIFTY", "type": "REGIME_CROSS",
                   "from": "SHORT_GAMMA", "to": "LONG_GAMMA"}]
        structure = {"NIFTY": {"call_wall": 24500, "put_wall": 23800,
                               "gamma_flip": 24100, "gex": 1e9, "gex_intensity": 3.2,
                               "iv_avg": 0.14, "gamma_regime": "LONG_GAMMA",
                               "computed_at": time.time()}}

        with tempfile.TemporaryDirectory() as tmp:
            snap_path = Path(tmp) / "live_snapshot.json"
            with patch.object(C, "SNAPSHOT_JSON", snap_path), \
                 patch.object(bridge_mod.C, "SNAPSHOT_JSON", snap_path):
                write_snapshot(store, key_symbol, events=events, structure=structure)

                # real HTTP on an ephemeral port
                srv = ThreadingHTTPServer(("127.0.0.1", 0), bridge_mod._Handler)
                threading.Thread(target=srv.serve_forever, daemon=True).start()
                port = srv.server_address[1]
                try:
                    body = urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/snapshot", timeout=5).read()
                finally:
                    srv.shutdown()

        s = json.loads(body)
        # symbol-keyed quotes; collision pair distinct; chg from seeded prev close
        self.assertAlmostEqual(s["quotes"]["NIFTY"]["ltp"], 24120.5)
        self.assertAlmostEqual(s["quotes"]["NIFTY"]["chg"], 0.5, places=2)
        self.assertAlmostEqual(s["quotes"]["ABB"]["ltp"], 4950.0)
        self.assertAlmostEqual(s["quotes"]["ABB"]["chg"], -1.0, places=2)
        # OI flowed: Full-packet OI then OI-Data update wins
        self.assertEqual(s["quotes"]["RELFUT"]["oi"], 888)
        # events + structure passed through verbatim
        self.assertEqual(s["events"][0]["type"], "REGIME_CROSS")
        self.assertEqual(s["structure"]["NIFTY"]["call_wall"], 24500)
        # two-clock rule: feed_ts present and fresh -> the HUD's LIVE gate opens
        self.assertGreater(s["feed_ts"], 0)
        self.assertLess(time.time() - s["feed_ts"], C.SNAPSHOT_CADENCE + 15)

    def test_bridge_serves_fallback_when_snapshot_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope.json"
            with patch.object(bridge_mod.C, "SNAPSHOT_JSON", missing):
                srv = ThreadingHTTPServer(("127.0.0.1", 0), bridge_mod._Handler)
                threading.Thread(target=srv.serve_forever, daemon=True).start()
                port = srv.server_address[1]
                try:
                    s = json.loads(urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/snapshot", timeout=5).read())
                finally:
                    srv.shutdown()
        # U3: a missing snapshot must yield a valid "not live" JSON, never a 500
        self.assertFalse(s["market_open"])
        self.assertEqual(s["quotes"], {})


if __name__ == "__main__":
    unittest.main()
