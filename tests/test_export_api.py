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
                  "breadth", "cm_breadth", "nifty", "dhan_map"):
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

    def test_bridge_shim_still_exports_handler(self):
        from vanguard.live import bridge
        self.assertIs(bridge._Handler, api._Handler)
        self.assertIs(bridge.Bridge, api.Bridge)


if __name__ == "__main__":
    unittest.main()
