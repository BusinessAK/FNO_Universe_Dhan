"""
Tests for src/live/trigger_engine.py — the armed-setup live watcher.

Covers: direction inference from the trigger/invalidation pair (both shapes +
the degenerate equal-levels case), one-shot semantics, multi-setup-per-symbol
independence, and that alert_sink.notify_macos never raises.
"""
import unittest
from unittest.mock import patch

from src.live.trigger_engine import TriggerEngine, _direction
from src.live import alert_sink

KEY = (2, 1001)   # (NSE_FNO segment, arbitrary security_id)
SYM = "TESTCO"


def bar(c):
    return {"t": 0, "o": c, "h": c, "l": c, "c": c}


class TestDirectionInference(unittest.TestCase):
    def test_trigger_above_invalidation_is_up(self):
        self.assertEqual(_direction(110.0, 90.0), "up")

    def test_trigger_below_invalidation_is_down(self):
        self.assertEqual(_direction(90.0, 110.0), "down")

    def test_equal_levels_is_degenerate_none(self):
        # playbook.py:259-265 nudges trigger/invalidation apart before they ever
        # reach daily_setups, but the engine must fail safe (skip, not guess)
        # if an equal pair recurs.
        self.assertIsNone(_direction(100.0, 100.0))


class TestUpShapeTransitions(unittest.TestCase):
    def setUp(self):
        book = {SYM: [{"setup_type": "GAMMA_SQUEEZE", "bias": "Bullish Breakout",
                       "trigger_strike": 110.0, "invalidation_strike": 90.0,
                       "status": "WAITING"}]}
        self.eng = TriggerEngine(book, {KEY: SYM})

    def test_no_fire_inside_band(self):
        fired = self.eng.on_bar_close(KEY, bar(105.0))
        self.assertEqual(fired, [])
        self.assertEqual(self.eng.armed_book[SYM][0]["status"], "WAITING")

    def test_fires_triggered_above_buffered_trigger(self):
        fired = self.eng.on_bar_close(KEY, bar(112.0))   # > 110*1.01=111.1
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0]["to"], "TRIGGERED")
        self.assertEqual(fired[0]["level"], 110.0)
        self.assertEqual(self.eng.armed_book[SYM][0]["status"], "TRIGGERED")

    def test_fires_invalidated_below_buffered_invalidation(self):
        fired = self.eng.on_bar_close(KEY, bar(89.0))   # < 90*0.99=89.1
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0]["to"], "INVALIDATED")
        self.assertEqual(fired[0]["level"], 90.0)

    def test_boundary_just_under_trigger_buffer_does_not_fire(self):
        fired = self.eng.on_bar_close(KEY, bar(111.0))   # exactly 110*1.01, not >
        self.assertEqual(fired, [])


class TestDownShapeTransitions(unittest.TestCase):
    def setUp(self):
        book = {SYM: [{"setup_type": "FLOOR_BOUNCE", "bias": "Bearish",
                       "trigger_strike": 90.0, "invalidation_strike": 110.0,
                       "status": "WAITING"}]}
        self.eng = TriggerEngine(book, {KEY: SYM})

    def test_fires_triggered_below_buffered_trigger(self):
        fired = self.eng.on_bar_close(KEY, bar(88.0))   # < 90*0.99=89.1
        self.assertEqual(fired[0]["to"], "TRIGGERED")
        self.assertEqual(fired[0]["level"], 90.0)

    def test_fires_invalidated_above_buffered_invalidation(self):
        fired = self.eng.on_bar_close(KEY, bar(112.0))   # > 110*1.01=111.1
        self.assertEqual(fired[0]["to"], "INVALIDATED")
        self.assertEqual(fired[0]["level"], 110.0)


class TestOneShotSemantics(unittest.TestCase):
    def setUp(self):
        book = {SYM: [{"setup_type": "GAMMA_SQUEEZE", "bias": "Bullish Breakout",
                       "trigger_strike": 110.0, "invalidation_strike": 90.0,
                       "status": "WAITING"}]}
        self.eng = TriggerEngine(book, {KEY: SYM})

    def test_never_refires_once_triggered(self):
        first = self.eng.on_bar_close(KEY, bar(112.0))
        self.assertEqual(len(first), 1)
        second = self.eng.on_bar_close(KEY, bar(120.0))
        self.assertEqual(second, [])
        third = self.eng.on_bar_close(KEY, bar(80.0))   # even a huge reversal
        self.assertEqual(third, [])
        self.assertEqual(self.eng.armed_book[SYM][0]["status"], "TRIGGERED")

    def test_events_log_accumulates(self):
        self.eng.on_bar_close(KEY, bar(112.0))
        self.assertEqual(len(self.eng.events), 1)


class TestMultiSetupIndependence(unittest.TestCase):
    def test_two_setups_same_symbol_transition_independently(self):
        book = {SYM: [
            {"setup_type": "GAMMA_SQUEEZE", "bias": "Bullish Breakout",
             "trigger_strike": 110.0, "invalidation_strike": 90.0, "status": "WAITING"},
            {"setup_type": "FLOOR_BOUNCE", "bias": "Bearish",
             "trigger_strike": 100.0, "invalidation_strike": 115.0, "status": "WAITING"},
        ]}
        eng = TriggerEngine(book, {KEY: SYM})
        fired = eng.on_bar_close(KEY, bar(112.0))
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0]["setup_type"], "GAMMA_SQUEEZE")
        self.assertEqual(book[SYM][0]["status"], "TRIGGERED")
        self.assertEqual(book[SYM][1]["status"], "WAITING")

    def test_unknown_key_returns_empty(self):
        book = {SYM: [{"setup_type": "GAMMA_SQUEEZE", "bias": "Bullish Breakout",
                       "trigger_strike": 110.0, "invalidation_strike": 90.0,
                       "status": "WAITING"}]}
        eng = TriggerEngine(book, {KEY: SYM})
        self.assertEqual(eng.on_bar_close((99, 99999), bar(200.0)), [])

    def test_symbol_with_no_armed_setups_returns_empty(self):
        eng = TriggerEngine({}, {KEY: SYM})
        self.assertEqual(eng.on_bar_close(KEY, bar(200.0)), [])


class TestLoadArmedBookSkipsNullLevels(unittest.TestCase):
    def test_rows_with_null_trigger_or_invalidation_are_skipped(self):
        from src.live.trigger_engine import load_armed_book

        class FakeCon:
            def execute(self, sql, params=None):
                class R:
                    def fetchone(_): return ("2026-07-16",)
                    def fetchall(_):
                        return [
                            ("GOOD", "GAMMA_SQUEEZE", "Bullish Breakout", 110.0, 90.0),
                            ("BADTRIG", "FLOOR_BOUNCE", "Bearish", None, 90.0),
                            ("BADINV", "FLOOR_BOUNCE", "Bearish", 90.0, None),
                        ]
                return R()

        book = load_armed_book(FakeCon())
        self.assertIn("GOOD", book)
        self.assertNotIn("BADTRIG", book)
        self.assertNotIn("BADINV", book)


class TestAlertSinkNeverRaises(unittest.TestCase):
    def test_notify_macos_swallows_subprocess_error(self):
        with patch("subprocess.run", side_effect=OSError("no osascript")):
            self.assertFalse(alert_sink.notify_macos("t", "m"))

    def test_notify_macos_swallows_timeout(self):
        import subprocess as sp
        with patch("subprocess.run", side_effect=sp.TimeoutExpired(cmd="osascript", timeout=5)):
            self.assertFalse(alert_sink.notify_macos("t", "m"))

    def test_fire_appends_to_recent_even_if_notify_fails(self):
        with patch("src.live.alert_sink.notify_macos", return_value=False):
            sink = alert_sink.AlertSink()
            sink.fire({"symbol": SYM, "setup_type": "GAMMA_SQUEEZE", "to": "TRIGGERED",
                       "level": 110.0, "spot": 112.0})
            self.assertEqual(len(sink.recent), 1)


if __name__ == "__main__":
    unittest.main()
