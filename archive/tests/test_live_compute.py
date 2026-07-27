"""
Tests for vanguard/live/live_compute.py (M2 — live structure engine) and the shared
compute_walls_and_flip/gamma_regime helpers it reuses from vanguard/intelligence.py.
"""
import time
import unittest

import pandas as pd

from vanguard.intelligence import InstitutionalIntelligence
from vanguard.live import live_compute as lc
from vanguard.live.state_store import StateStore
from vanguard.live import alert_sink

SYM = "TESTCO"


def greeks_row(strike, opt_type, oi):
    return {"SYMBOL": SYM, "STRIKE_PR": strike, "OPTION_TYP": opt_type, "OPEN_INT": oi}


class TestComputeWallsAndFlip(unittest.TestCase):
    def test_call_wall_is_max_raw_ce_oi_strike(self):
        # Raw OI, not Gamma-weighted (see compute_walls_and_flip's docstring
        # for why the Gamma weighting was retired 2026-07-24) — strike 110
        # has the largest CE OI, so it should win call_wall regardless of
        # distance from spot.
        df = pd.DataFrame([
            greeks_row(100, "CE", 1000),
            greeks_row(110, "CE", 5000),   # largest CE OI
            greeks_row(90, "PE", 4000),
            greeks_row(80, "PE", 1000),
        ])
        out = InstitutionalIntelligence.compute_walls_and_flip(df)
        self.assertEqual(out[SYM]["call_wall"], 110.0)
        self.assertEqual(out[SYM]["put_wall"], 90.0)

    def test_gamma_flip_is_max_overlap_of_ce_and_pe_oi(self):
        # Strike 100 has both meaningful CE and PE OI (the overlap min is
        # largest there); strike 120 has huge CE OI but ~0 PE OI, so it must
        # NOT win the flip despite having the single largest CE number.
        df = pd.DataFrame([
            greeks_row(100, "CE", 3000),
            greeks_row(100, "PE", 3000),
            greeks_row(120, "CE", 10000),   # huge CE OI, but...
            greeks_row(120, "PE", 100),     # ...negligible PE OI here
        ])
        out = InstitutionalIntelligence.compute_walls_and_flip(df)
        self.assertEqual(out[SYM]["gamma_flip"], 100.0)

    def test_empty_frame_returns_empty_dict(self):
        self.assertEqual(InstitutionalIntelligence.compute_walls_and_flip(pd.DataFrame()), {})

    def test_no_positive_oi_side_falls_back_to_zero(self):
        df = pd.DataFrame([greeks_row(100, "CE", 0)])
        out = InstitutionalIntelligence.compute_walls_and_flip(df)
        self.assertEqual(out[SYM]["call_wall"], 0.0)
        self.assertEqual(out[SYM]["put_wall"], 0.0)
        self.assertEqual(out[SYM]["gamma_flip"], 0.0)


class TestGammaRegime(unittest.TestCase):
    def test_within_band_is_transition(self):
        # 0.8% band around gamma_flip=100 -> [99.2, 100.8]
        self.assertEqual(InstitutionalIntelligence.gamma_regime(100.5, 100.0, 0), "TRANSITION_REGIME")

    def test_above_flip_is_long_gamma(self):
        self.assertEqual(InstitutionalIntelligence.gamma_regime(110.0, 100.0, 0), "LONG_GAMMA")

    def test_below_flip_is_short_gamma(self):
        self.assertEqual(InstitutionalIntelligence.gamma_regime(90.0, 100.0, 0), "SHORT_GAMMA")

    def test_no_flip_strike_falls_back_to_gex_thresholds(self):
        self.assertEqual(InstitutionalIntelligence.gamma_regime(100.0, 0.0, 250000), "LONG_GAMMA")
        self.assertEqual(InstitutionalIntelligence.gamma_regime(100.0, 0.0, -20000), "SHORT_GAMMA")
        self.assertEqual(InstitutionalIntelligence.gamma_regime(100.0, 0.0, 0), "TRANSITION_REGIME")


class TestBuildOptionFrame(unittest.TestCase):
    def setUp(self):
        self.store = StateStore()
        self.key_to_meta = {
            (2, 1): {"symbol": SYM, "strike": 100.0, "option_type": "CE", "expiry": "2026-07-31"},
            (2, 2): {"symbol": SYM, "strike": 100.0, "option_type": "PE", "expiry": "2026-07-31"},
        }

    def test_untouched_instrument_is_skipped(self):
        # (2,1) never ticked -> must not appear in the frame at all
        self.store.ingest({"seg": 2, "sid": 2, "ts": time.time(), "ltp": 5.0, "oi": 1000})
        df = lc.build_option_frame(self.store, self.key_to_meta, {})
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["OPTION_TYP"], "PE")

    def test_oi_falls_back_to_baseline_when_no_live_oi_tick(self):
        self.store.ingest({"seg": 2, "sid": 1, "ts": time.time(), "ltp": 8.0, "oi": None})
        baseline = {(SYM, 100.0, "CE"): 42000.0}
        df = lc.build_option_frame(self.store, self.key_to_meta, baseline)
        self.assertEqual(df.iloc[0]["OPEN_INT"], 42000.0)
        self.assertEqual(df.iloc[0]["CHG_IN_OI"], 0.0)

    def test_chg_in_oi_reflects_live_oi_vs_baseline(self):
        self.store.ingest({"seg": 2, "sid": 1, "ts": time.time(), "ltp": 8.0, "oi": 50000})
        baseline = {(SYM, 100.0, "CE"): 42000.0}
        df = lc.build_option_frame(self.store, self.key_to_meta, baseline)
        self.assertEqual(df.iloc[0]["OPEN_INT"], 50000.0)
        self.assertEqual(df.iloc[0]["CHG_IN_OI"], 8000.0)

    def test_empty_store_yields_empty_frame(self):
        df = lc.build_option_frame(self.store, self.key_to_meta, {})
        self.assertTrue(df.empty)


class TestLiveStructureEngineEventDiffing(unittest.TestCase):
    def _result(self, call_wall, put_wall, gamma_flip, regime, iv):
        return {SYM: {"call_wall": call_wall, "put_wall": put_wall, "gamma_flip": gamma_flip,
                      "gex": 0.0, "gex_intensity": 0.0, "iv_avg": iv,
                      "gamma_regime": regime, "computed_at": time.time()}}

    def test_no_event_on_first_cycle_seen(self):
        eng = lc.LiveStructureEngine({}, {})
        events = eng._diff_events(self._result(110, 90, 100, "LONG_GAMMA", 0.25))
        self.assertEqual(events, [])

    def test_regime_cross_fires_on_change_only(self):
        eng = lc.LiveStructureEngine({}, {})
        eng._diff_events(self._result(110, 90, 100, "LONG_GAMMA", 0.25))
        same = eng._diff_events(self._result(110, 90, 100, "LONG_GAMMA", 0.25))
        self.assertEqual([e for e in same if e["type"] == "REGIME_CROSS"], [])
        changed = eng._diff_events(self._result(110, 90, 100, "SHORT_GAMMA", 0.25))
        cross = [e for e in changed if e["type"] == "REGIME_CROSS"]
        self.assertEqual(len(cross), 1)
        self.assertEqual(cross[0]["from"], "LONG_GAMMA")
        self.assertEqual(cross[0]["to"], "SHORT_GAMMA")

    def test_wall_relocated_needs_two_consecutive_cycles(self):
        eng = lc.LiveStructureEngine({}, {})
        eng._diff_events(self._result(110, 90, 100, "LONG_GAMMA", 0.25))          # baseline: call_wall=110
        one = eng._diff_events(self._result(115, 90, 100, "LONG_GAMMA", 0.25))    # candidate 115, streak 1
        self.assertEqual([e for e in one if e["type"] == "WALL_RELOCATED"], [])
        two = eng._diff_events(self._result(115, 90, 100, "LONG_GAMMA", 0.25))    # streak 2 -> fires
        relocated = [e for e in two if e["type"] == "WALL_RELOCATED"]
        self.assertEqual(len(relocated), 1)
        self.assertEqual(relocated[0]["side"], "call")
        self.assertEqual(relocated[0]["from"], 110.0)
        self.assertEqual(relocated[0]["to"], 115.0)

    def test_wall_candidate_reverting_never_fires(self):
        eng = lc.LiveStructureEngine({}, {})
        eng._diff_events(self._result(110, 90, 100, "LONG_GAMMA", 0.25))
        eng._diff_events(self._result(115, 90, 100, "LONG_GAMMA", 0.25))   # candidate 115, streak 1
        back = eng._diff_events(self._result(110, 90, 100, "LONG_GAMMA", 0.25))  # reverts before confirming
        self.assertEqual([e for e in back if e["type"] == "WALL_RELOCATED"], [])
        # candidate cleared -> a later re-approach to 115 must start its streak over
        one_again = eng._diff_events(self._result(115, 90, 100, "LONG_GAMMA", 0.25))
        self.assertEqual([e for e in one_again if e["type"] == "WALL_RELOCATED"], [])

    def test_iv_event_fires_once_per_direction_per_session(self):
        eng = lc.LiveStructureEngine({}, {})
        eng._diff_events(self._result(110, 90, 100, "LONG_GAMMA", 0.20))          # session open IV = 0.20
        spike = eng._diff_events(self._result(110, 90, 100, "LONG_GAMMA", 0.23))  # +3 pts -> fires "up"
        iv_events = [e for e in spike if e["type"] == "IV_EVENT"]
        self.assertEqual(len(iv_events), 1)
        self.assertEqual(iv_events[0]["direction"], "up")
        again = eng._diff_events(self._result(110, 90, 100, "LONG_GAMMA", 0.24))  # still up, must not refire
        self.assertEqual([e for e in again if e["type"] == "IV_EVENT"], [])

    def test_iv_event_does_not_fire_below_threshold(self):
        eng = lc.LiveStructureEngine({}, {})
        eng._diff_events(self._result(110, 90, 100, "LONG_GAMMA", 0.20))
        small = eng._diff_events(self._result(110, 90, 100, "LONG_GAMMA", 0.208))  # +0.8 pt, below 2pt threshold
        self.assertEqual([e for e in small if e["type"] == "IV_EVENT"], [])


class TestSelectCoveredNames(unittest.TestCase):
    def test_indices_always_included_alongside_nifty50_constituents(self):
        class FakeCon:
            def execute(self, sql, params=None):
                class R:
                    def fetchone(_): return ("2026-07-16",)
                    def fetchall(_): return [("RELIANCE",), ("TCS",)]
                return R()
        names = lc.select_covered_names(FakeCon(), constituents=["RELIANCE", "TCS", "NOT_IN_UNIVERSE"])
        self.assertIn("RELIANCE", names)
        self.assertIn("TCS", names)
        # a constituent absent from the compiled F&O universe is excluded,
        # not fabricated into coverage
        self.assertNotIn("NOT_IN_UNIVERSE", names)
        from vanguard.live import config as C
        for idx in C.INDEX_SYMBOLS:
            self.assertIn(idx, names)


class TestComputeIntegration(unittest.TestCase):
    def test_compute_end_to_end_on_synthetic_chain(self):
        now = pd.Timestamp.now()
        expiry = now + pd.Timedelta(days=5)
        df = pd.DataFrame([
            {"INSTRUMENT": "STO", "SYMBOL": SYM, "STRIKE_PR": 95.0, "OPTION_TYP": "CE",
             "EXPIRY_DT": expiry, "TIMESTAMP": now, "CLOSE": 8.0, "OPEN_INT": 50000,
             "CHG_IN_OI": 1000, "VOLUME": 500},
            {"INSTRUMENT": "STO", "SYMBOL": SYM, "STRIKE_PR": 95.0, "OPTION_TYP": "PE",
             "EXPIRY_DT": expiry, "TIMESTAMP": now, "CLOSE": 3.0, "OPEN_INT": 40000,
             "CHG_IN_OI": -500, "VOLUME": 300},
        ])
        out = lc.compute(df, {SYM: 100.0})
        self.assertIn(SYM, out)
        self.assertIn(out[SYM]["gamma_regime"], ("LONG_GAMMA", "SHORT_GAMMA", "TRANSITION_REGIME"))
        self.assertGreaterEqual(out[SYM]["iv_avg"], 0.0)

    def test_compute_on_empty_frame_returns_empty(self):
        self.assertEqual(lc.compute(pd.DataFrame(), {}), {})


class TestPerfRegression(unittest.TestCase):
    """Guards against a future change to the shared GreeksEngine silently
    breaking the 30s live cadence. Generous margin (not a tight benchmark) —
    see the M2 plan for the actual grounding numbers (top-60 ~1.4s observed)."""

    def test_top60_shaped_frame_stays_well_under_cycle_budget(self):
        import numpy as np
        from vanguard.greeks_engine import GreeksEngine

        rng = np.random.default_rng(7)
        n_symbols = 60
        strikes_per_side = 25
        rows = []
        now = pd.Timestamp.now()
        expiry = now + pd.Timedelta(days=5)
        for i in range(n_symbols):
            sym = f"PERFSYM{i}"
            spot = rng.uniform(100, 5000)
            strikes = np.linspace(spot * 0.85, spot * 1.15, strikes_per_side)
            for k in strikes:
                for opt_type in ("CE", "PE"):
                    price = max(0.5, abs(spot - k) * rng.uniform(0.02, 0.08) + rng.uniform(1, 20))
                    rows.append({
                        "INSTRUMENT": "STO", "SYMBOL": sym, "STRIKE_PR": round(k, 1),
                        "OPTION_TYP": opt_type, "EXPIRY_DT": expiry, "TIMESTAMP": now,
                        "OPEN_INT": int(rng.uniform(1000, 500000)),
                        "CHG_IN_OI": int(rng.uniform(-50000, 50000)),
                        "CLOSE": round(price, 2), "VOLUME": int(rng.uniform(0, 100000)),
                    })
        df = pd.DataFrame(rows)
        spot_prices = {f"PERFSYM{i}": float(df[df.SYMBOL == f"PERFSYM{i}"].STRIKE_PR.median())
                       for i in range(n_symbols)}

        eng = GreeksEngine()
        t0 = time.time()
        out = eng.process_dataframe(df, spot_prices)
        elapsed = time.time() - t0
        self.assertFalse(out.empty)
        # 10s is a generous ceiling vs the ~1.4s observed in the plan's benchmark —
        # this catches a real regression, not machine-speed noise.
        self.assertLess(elapsed, 10.0,
                         f"process_dataframe took {elapsed:.2f}s for a top-60-shaped frame "
                         f"({len(df)} rows) — the 30s live cadence needs headroom beyond this.")


class TestAlertSinkStructureEvents(unittest.TestCase):
    """live_compute's events have a "type" key; trigger_engine's don't — the
    shared AlertSink must dispatch correctly on both without either shape
    needing to change (M3's shape is already shipped and must stay stable)."""

    def test_regime_cross_message(self):
        title, msg = alert_sink._event_message(
            {"symbol": SYM, "type": "REGIME_CROSS", "from": "LONG_GAMMA", "to": "SHORT_GAMMA"})
        self.assertIn(SYM, title)
        self.assertIn("REGIME CROSS", title)

    def test_wall_relocated_message(self):
        title, msg = alert_sink._event_message(
            {"symbol": SYM, "type": "WALL_RELOCATED", "side": "call", "from": 110.0, "to": 115.0})
        self.assertIn("CALL WALL", title)
        self.assertIn("115", msg)

    def test_iv_event_message(self):
        title, msg = alert_sink._event_message(
            {"symbol": SYM, "type": "IV_EVENT", "direction": "up", "iv": 0.23, "open_iv": 0.20, "delta": 0.03})
        self.assertIn("IV UP", title)

    def test_trigger_event_shape_unaffected(self):
        # no "type" key -> must still take the original M3 branch
        title, msg = alert_sink._event_message(
            {"symbol": SYM, "setup_type": "GAMMA_SQUEEZE", "to": "TRIGGERED", "level": 110.0, "spot": 112.0})
        self.assertIn("GAMMA_SQUEEZE", title)
        self.assertIn("TRIGGERED", title)


if __name__ == "__main__":
    unittest.main()
