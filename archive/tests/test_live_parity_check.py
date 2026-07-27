"""
Tests for scripts/live_parity_check.py (M2's EOD-parity trust gate). Loaded by
file path since scripts/ isn't a package — avoids adding one just for tests.
"""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("live_parity_check", ROOT / "scripts" / "live_parity_check.py")
lpc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lpc)


class TestClose(unittest.TestCase):
    def test_within_epsilon_is_close(self):
        self.assertTrue(lpc._close(100.0, 100.005))

    def test_beyond_epsilon_is_not_close(self):
        self.assertFalse(lpc._close(100.0, 101.0))

    def test_none_treated_as_zero(self):
        self.assertTrue(lpc._close(None, 0.0))


class TestRun(unittest.TestCase):
    def _patch_and_run(self, live, eod_date, eod):
        with patch.object(lpc, "load_live_structure", return_value=live), \
             patch.object(lpc, "load_eod_structure", return_value=(eod_date, eod)), \
             tempfile.TemporaryDirectory() as tmp:
            with patch.object(lpc.C, "LIVE_DIR", Path(tmp)):
                return lpc.run()

    def test_passes_when_walls_gex_iv_all_within_gates(self):
        live = {"TESTCO": {"call_wall": 110.0, "put_wall": 90.0, "gex": 100000.0, "iv_avg": 0.25}}
        eod = {"TESTCO": {"call_wall": 110.0, "put_wall": 90.0, "gex": 105000.0, "iv": 0.252}}
        report = self._patch_and_run(live, "2026-07-16", eod)
        self.assertTrue(report["passed"])
        self.assertEqual(report["wall_match_pct"], 1.0)

    def test_fails_on_wall_mismatch_below_target(self):
        live = {"A": {"call_wall": 110.0, "put_wall": 90.0, "gex": 0, "iv_avg": 0.25},
                "B": {"call_wall": 200.0, "put_wall": 90.0, "gex": 0, "iv_avg": 0.25}}  # call_wall wrong
        eod = {"A": {"call_wall": 110.0, "put_wall": 90.0, "gex": 0, "iv": 0.25},
               "B": {"call_wall": 210.0, "put_wall": 90.0, "gex": 0, "iv": 0.25}}
        report = self._patch_and_run(live, "2026-07-16", eod)
        self.assertEqual(report["wall_match_pct"], 0.5)
        self.assertFalse(report["passed"])   # 50% < 90% target

    def test_fails_on_gex_delta_beyond_target(self):
        live = {"TESTCO": {"call_wall": 110.0, "put_wall": 90.0, "gex": 100000.0, "iv_avg": 0.25}}
        eod = {"TESTCO": {"call_wall": 110.0, "put_wall": 90.0, "gex": 100000.0 * 2, "iv": 0.25}}  # 50% off
        report = self._patch_and_run(live, "2026-07-16", eod)
        self.assertFalse(report["passed"])

    def test_no_overlapping_symbols_fails_cleanly(self):
        report = self._patch_and_run({"ONLYLIVE": {}}, "2026-07-16", {"ONLYEOD": {}})
        self.assertFalse(report["passed"])
        self.assertEqual(report["n_compared"], 0)

    def test_writes_parity_json_file(self):
        live = {"TESTCO": {"call_wall": 110.0, "put_wall": 90.0, "gex": 100000.0, "iv_avg": 0.25}}
        eod = {"TESTCO": {"call_wall": 110.0, "put_wall": 90.0, "gex": 100000.0, "iv": 0.25}}
        with patch.object(lpc, "load_live_structure", return_value=live), \
             patch.object(lpc, "load_eod_structure", return_value=("2026-07-16", eod)), \
             tempfile.TemporaryDirectory() as tmp:
            with patch.object(lpc.C, "LIVE_DIR", Path(tmp)):
                lpc.run()
                self.assertTrue((Path(tmp) / "parity_20260716.json").exists())


if __name__ == "__main__":
    unittest.main()
