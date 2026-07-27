"""
Tests for vanguard/rules/equity_playbook.py.

Two things pinned here, in the order the bugs were found:
1. No tautological triggers — a setup's trigger must not be satisfied by the
   exact close that caused the row to exist (found via
   test_equity_setups_pipeline.py's integration test).
2. Volatility-adaptive risk sizing — the E4 root-cause fix: risk/target
   width must scale with each stock's own NATR14, not a fixed percentage,
   so a more volatile stock gets a proportionally wider band (found via the
   backtest gate + a direct F&O comparison showing Equity's DMA anchors
   overshoot 5-80%+ on the exact days these setups fire, vs F&O's
   structural anchors overshooting only 0.2-1.5%).
"""
import unittest

from vanguard.config.equity import NATR_SL_MULT, NATR_TRIGGER_MULT
from vanguard.rules.equity_playbook import build_equity_playbook
from vanguard.rules.setup_positions import _direction

_IC_TRIGGER_MULT = NATR_TRIGGER_MULT["IMBALANCE_CONSOLIDATION"]
_IC_SL_MULT = NATR_SL_MULT["IMBALANCE_CONSOLIDATION"]

ALL_SETUP_TYPES = [
    "MOMENTUM_BUILDUP", "IMBALANCE_CONSOLIDATION",
    "BREADTH_DIVERGENCE_REVERSAL", "FIFTYTWO_WEEK_BREAKOUT", "RSI_EXTREME_REBOUND",
]

_SCENARIOS = {
    "MOMENTUM_BUILDUP":            dict(close=100.3, dma20=100.0, dma50=95.0, prev_high_52w=110.0, natr14=3.0),
    "IMBALANCE_CONSOLIDATION":     dict(close=100.15, dma20=100.0, dma50=99.0, prev_high_52w=110.0, natr14=3.0,
                                        range_high_10d_prev=100.2),
    "BREADTH_DIVERGENCE_REVERSAL": dict(close=92.0, dma20=100.0, dma50=98.0, prev_high_52w=110.0, natr14=3.0),
    "FIFTYTWO_WEEK_BREAKOUT":      dict(close=110.5, dma20=105.0, dma50=100.0, prev_high_52w=110.0, natr14=3.0),
    "RSI_EXTREME_REBOUND":         dict(close=90.0, dma20=100.0, dma50=98.0, prev_high_52w=110.0, natr14=3.0),
}


class TestSchemaContract(unittest.TestCase):
    def test_every_setup_uses_the_exact_keys_setup_positions_reads(self):
        for st in ALL_SETUP_TYPES:
            pb = build_equity_playbook(st, **_SCENARIOS[st])
            self.assertIn("trigger_strike", pb, st)
            self.assertIn("invalidation_strike", pb, st)
            self.assertIn("bias", pb, st)
            self.assertNotIn("trigger_price", pb, st)
            self.assertNotIn("suggested_strategy", pb, st)


class TestNoTautologicalTriggers(unittest.TestCase):
    def test_trigger_not_satisfied_by_the_firing_days_own_close(self):
        for st in ALL_SETUP_TYPES:
            scenario = _SCENARIOS[st]
            pb = build_equity_playbook(st, **scenario)
            firing_day_spot = scenario["close"]
            self.assertLess(firing_day_spot, pb["trigger_strike"],
                            f"{st}: trigger already satisfied by the same close that fired it")

    def test_direction_infers_up_for_every_setup(self):
        for st in ALL_SETUP_TYPES:
            pb = build_equity_playbook(st, **_SCENARIOS[st])
            self.assertEqual(_direction(pb["trigger_strike"], pb["invalidation_strike"]), "up", st)


class TestFiftyTwoWeekBreakoutUsesPriorHigh(unittest.TestCase):
    def test_trigger_derived_from_prev_high_52w_not_todays_close(self):
        pb = build_equity_playbook("FIFTYTWO_WEEK_BREAKOUT", close=115.0, dma20=105.0,
                                   dma50=100.0, prev_high_52w=110.0, natr14=3.0)
        self.assertAlmostEqual(pb["trigger_strike"], 110.0 * (1 + 0.25 * 0.03))
        self.assertNotAlmostEqual(pb["trigger_strike"], 115.0 * 1.01)


class TestVolatilityAdaptiveSizing(unittest.TestCase):
    """The E4 fix itself: risk width must scale with NATR14."""

    def test_higher_natr_widens_the_invalidation_band(self):
        for st in ALL_SETUP_TYPES:
            scenario = dict(_SCENARIOS[st])
            calm = build_equity_playbook(st, **{**scenario, "natr14": 1.0})
            volatile = build_equity_playbook(st, **{**scenario, "natr14": 8.0})
            calm_risk = abs(calm["trigger_strike"] - calm["invalidation_strike"])
            volatile_risk = abs(volatile["trigger_strike"] - volatile["invalidation_strike"])
            self.assertGreater(volatile_risk, calm_risk, st)

    def test_missing_natr_falls_back_to_a_sane_default(self):
        for st in ALL_SETUP_TYPES:
            pb_missing = build_equity_playbook(st, **{**_SCENARIOS[st], "natr14": None})
            pb_fallback = build_equity_playbook(st, **{**_SCENARIOS[st], "natr14": 3.0})
            self.assertAlmostEqual(pb_missing["trigger_strike"], pb_fallback["trigger_strike"], msg=st)

    def test_zero_or_nan_natr_also_falls_back(self):
        import math
        for st in ALL_SETUP_TYPES:
            for bad in (0.0, float("nan"), -1.0):
                pb = build_equity_playbook(st, **{**_SCENARIOS[st], "natr14": bad})
                self.assertTrue(math.isfinite(pb["trigger_strike"]), f"{st} natr14={bad}")
                self.assertTrue(math.isfinite(pb["invalidation_strike"]), f"{st} natr14={bad}")


class TestImbalanceConsolidationRangeAnchor(unittest.TestCase):
    """2026-07-21 second-pass fix: the E4 backtest gate found 79% of
    IMBALANCE_CONSOLIDATION's "TARGET_HIT" rows already had their actual
    entry AT OR PAST the nominal target on day one — dma50 lags too far
    behind price for a setup that screens for a fast break away from a quiet
    range. Both trigger AND invalidation now anchor to range_high_10d_prev
    (a split trigger/dma50-invalidation anchor was tried first and reverted
    — it silently flipped ~2/3 of positions to "down" by breaking the
    trigger > invalidation invariant _direction() relies on)."""

    def test_trigger_and_invalidation_both_track_range_high_not_dma50(self):
        pb = build_equity_playbook("IMBALANCE_CONSOLIDATION", close=205.0, dma20=180.0,
                                   dma50=150.0, prev_high_52w=250.0, natr14=3.0,
                                   range_high_10d_prev=200.0)
        self.assertAlmostEqual(pb["trigger_strike"], 200.0 * (1 + _IC_TRIGGER_MULT * 0.03))
        self.assertAlmostEqual(pb["invalidation_strike"], 200.0 * (1 - _IC_SL_MULT * 0.03))

    def test_missing_range_high_falls_back_to_dma50_for_both_anchors(self):
        pb = build_equity_playbook("IMBALANCE_CONSOLIDATION", close=205.0, dma20=180.0,
                                   dma50=150.0, prev_high_52w=250.0, natr14=3.0,
                                   range_high_10d_prev=None)
        self.assertAlmostEqual(pb["trigger_strike"], 150.0 * (1 + _IC_TRIGGER_MULT * 0.03))
        self.assertAlmostEqual(pb["invalidation_strike"], 150.0 * (1 - _IC_SL_MULT * 0.03))

    def test_zero_or_negative_range_high_also_falls_back(self):
        for bad in (0.0, -5.0, float("nan")):
            pb = build_equity_playbook("IMBALANCE_CONSOLIDATION", close=205.0, dma20=180.0,
                                       dma50=150.0, prev_high_52w=250.0, natr14=3.0,
                                       range_high_10d_prev=bad)
            self.assertAlmostEqual(pb["trigger_strike"], 150.0 * (1 + _IC_TRIGGER_MULT * 0.03), msg=bad)

    def test_trigger_always_above_invalidation_regardless_of_dma50_relationship(self):
        """The bug this guards against: with a single shared anchor,
        trigger > invalidation holds for any positive anchor value,
        independent of where dma20/dma50 happen to sit. Direction must
        always infer "up" for this setup."""
        from vanguard.rules.setup_positions import _direction
        # dma50 deliberately ABOVE the range high -- would have inverted
        # direction under the old split-anchor design.
        pb = build_equity_playbook("IMBALANCE_CONSOLIDATION", close=105.0, dma20=95.0,
                                   dma50=140.0, prev_high_52w=200.0, natr14=3.0,
                                   range_high_10d_prev=100.0)
        self.assertGreater(pb["trigger_strike"], pb["invalidation_strike"])
        self.assertEqual(_direction(pb["trigger_strike"], pb["invalidation_strike"]), "up")


class TestDegenerateInputsDoNotCrash(unittest.TestCase):
    def test_zero_dma_and_high_do_not_raise(self):
        for st in ALL_SETUP_TYPES:
            build_equity_playbook(st, close=0.0, dma20=0.0, dma50=0.0, prev_high_52w=0.0, natr14=3.0)

    def test_unknown_setup_type_raises(self):
        with self.assertRaises(ValueError):
            build_equity_playbook("NOT_A_REAL_SETUP", 100.0, 95.0, 90.0, 120.0)


if __name__ == "__main__":
    unittest.main()
