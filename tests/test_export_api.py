"""
Wave 3 / P1 gate: baked and served HUD payloads must be the same bytes from
the same builder (vanguard/store/export_service.py), and the API must serve
them at /session/latest. Skips when no compiled DB exists (CI without data).
"""
import json
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

from vanguard.config.paths import DB, ROOT
from vanguard.serve import api
from vanguard.store.export_service import build_payload, payload_json

HAVE_DB = DB.exists()


@unittest.skipUnless(HAVE_DB, "no compiled DB")
class TestExportService(unittest.TestCase):
    def test_payload_shape(self):
        p = build_payload(sessions=3)
        for k in ("meta", "market_structure", "setups", "changes",
                  "breadth", "cm_breadth", "nifty"):
            self.assertIn(k, p)
        self.assertEqual(p["meta"]["session"], p["meta"]["sessions"][-1])
        self.assertEqual(p["meta"]["sessions"], sorted(p["meta"]["sessions"]))
        # flip_repeat appended by the exporter, not stored in the DB
        self.assertIn("flip_repeat", p["market_structure"]["cols"])

    def test_served_equals_built(self):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), api._Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.server_address[1]
        try:
            body = urllib.request.urlopen(
                f"http://127.0.0.1:{port}/session/latest", timeout=60).read()
            body2 = urllib.request.urlopen(
                f"http://127.0.0.1:{port}/session/latest", timeout=60).read()
        finally:
            srv.shutdown()
        self.assertEqual(body, body2, "cache instability")
        served = json.loads(body)
        self.assertEqual(served["meta"], build_payload()["meta"])
        # exact-bytes identity with what build_hud would bake
        self.assertEqual(body.decode("utf-8"), payload_json())


class TestTemplateBootWrap(unittest.TestCase):
    def test_template_has_single_placeholder_inside_loader(self):
        t = (ROOT / "hud" / "template.html").read_text()
        self.assertEqual(t.count("__VANGUARD_DATA__"), 1)
        self.assertIn("function __boot(VG){", t)
        self.assertIn('fetch("/session/latest"', t)
        # loader must come AFTER the boot function so hoisting isn't relied on
        self.assertLess(t.index("function __boot(VG){"),
                        t.index("let data=__VANGUARD_DATA__"))


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(HAVE_DB, "no compiled DB")
class TestContextDegradation(unittest.TestCase):
    def test_payload_without_context_tables(self):
        """PRD degradation contract: a pre-C1 DB (no context tables) must
        still build a full payload — context keys absent, nothing raises."""
        import tempfile, duckdb
        from pathlib import Path
        core = ["daily_market_structure", "daily_confluence_setups", "daily_changes",
                "daily_market_breadth", "daily_cm_breadth"]
        with tempfile.TemporaryDirectory() as tmp:
            db2 = Path(tmp) / "no_context.duckdb"
            con = duckdb.connect(str(db2))
            con.execute(f"ATTACH '{DB}' AS prod (READ_ONLY)")
            for t in core:
                con.execute(f"CREATE TABLE {t} AS SELECT * FROM prod.{t}")
            con.close()
            p = build_payload(db_path=db2, sessions=2)
        for k in ("positioning", "vix", "delivery", "setup_positions",
                  "equity_setup_positions", "track_record"):
            self.assertNotIn(k, p)
        self.assertIn("market_structure", p)

    def test_context_blocks_present_on_real_db(self):
        p = build_payload(sessions=2)
        self.assertIn("positioning", p)
        self.assertIn("vix", p)
        self.assertIn("delivery", p)
        # positioning: 4 participants per date
        parts = {r[1] for r in p["positioning"]["rows"]}
        self.assertEqual(parts, {"CLIENT", "DII", "FII", "PRO"})
        # index-option legs ride along (options tilt on the HUD); values sane
        cols = p["positioning"]["cols"]
        for c in ("opt_idx_call_long", "opt_idx_call_short",
                  "opt_idx_put_long", "opt_idx_put_short"):
            self.assertIn(c, cols)
        ci = {c: i for i, c in enumerate(cols)}
        fii = next(r for r in p["positioning"]["rows"] if r[ci["participant"]] == "FII")
        self.assertGreater(fii[ci["opt_idx_call_long"]], 0)

    def test_setup_positions_present_and_point_in_time_consistent(self):
        p = build_payload(sessions=2)
        self.assertIn("setup_positions", p)
        cols = p["setup_positions"]["cols"]
        ci = {c: i for i, c in enumerate(cols)}
        for c in ("symbol", "sector", "setup_type", "bias", "direction",
                  "trigger_date", "trigger_price", "sl_price", "target_price",
                  "status", "resolved_date", "resolved_price"):
            self.assertIn(c, cols)
        sessions = p["meta"]["sessions"]
        for r in p["setup_positions"]["rows"]:
            status, resolved_date = r[ci["status"]], r[ci["resolved_date"]]
            # Export filter contract: every exported row must be either still
            # OPEN, or resolved at/after the earliest exported session — a
            # row resolved entirely before the window would be irrelevant to
            # any date the HUD can currently display (see export_service.py).
            self.assertTrue(status == "OPEN" or resolved_date >= sessions[0])
            # STALE/resolved rows always carry a resolved_price; OPEN never does.
            if status == "OPEN":
                self.assertIsNone(r[ci["resolved_price"]])
            else:
                self.assertIsNotNone(r[ci["resolved_price"]])

    def test_equity_setup_positions_present_and_point_in_time_consistent(self):
        """Track B mirror of the setup_positions test above — same column
        shape and point-in-time filter contract, separate DB table/block
        (see export_service.py's _context_blocks comment on why)."""
        p = build_payload(sessions=2)
        self.assertIn("equity_setup_positions", p)
        cols = p["equity_setup_positions"]["cols"]
        ci = {c: i for i, c in enumerate(cols)}
        for c in ("symbol", "sector", "setup_type", "bias", "direction",
                  "trigger_date", "trigger_price", "sl_price", "target_price",
                  "status", "resolved_date", "resolved_price"):
            self.assertIn(c, cols)
        sessions = p["meta"]["sessions"]
        for r in p["equity_setup_positions"]["rows"]:
            status, resolved_date = r[ci["status"]], r[ci["resolved_date"]]
            self.assertTrue(status == "OPEN" or resolved_date >= sessions[0])
            if status == "OPEN":
                self.assertIsNone(r[ci["resolved_price"]])
            else:
                self.assertIsNotNone(r[ci["resolved_price"]])

    def test_track_record_present_both_tracks_resolved_only(self):
        p = build_payload(sessions=2)
        self.assertIn("track_record", p)
        cols = p["track_record"]["cols"]
        self.assertEqual(cols, ["track", "setup_type", "n", "win_rate", "avg_r", "total_r"])
        ci = {c: i for i, c in enumerate(cols)}
        tracks = {r[ci["track"]] for r in p["track_record"]["rows"]}
        # Both tracks have resolved positions in the real compiled DB.
        self.assertEqual(tracks, {"fno", "equity"})
        for r in p["track_record"]["rows"]:
            self.assertGreater(r[ci["n"]], 0)          # summarize_by_group drops empty groups
            self.assertIsInstance(r[ci["win_rate"]], (int, float))
            self.assertIsInstance(r[ci["avg_r"]], (int, float))
            self.assertIsInstance(r[ci["total_r"]], (int, float))
        # A known-PASS Track B setup type should show up with a real win rate.
        eq_types = {r[ci["setup_type"]] for r in p["track_record"]["rows"] if r[ci["track"]] == "equity"}
        self.assertIn("MOMENTUM_BUILDUP", eq_types)
