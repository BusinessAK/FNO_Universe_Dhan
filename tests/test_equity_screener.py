"""
Table-driven tests for the 5 active equity setup rules (vanguard/rules/
equity_screener.py) — mirrors tests/test_setup_screener.py's pattern: each
case flips exactly one condition across its threshold.

Thresholds retuned 2026-07-21 after the E4 backtest gate — see
vanguard/config/equity.py for the data-grounded rationale per setup.
DMA_RECLAIM dropped the same day (see equity_screener.py's module docstring).
"""
import unittest

from vanguard.rules.equity_screener import EquitySetupInputs, screen


def base(**over) -> EquitySetupInputs:
    """A quiet symbol that fires NOTHING (verified by test_base_fires_nothing)."""
    d = dict(
        close=100.0, dma20=95.0, dma50=90.0,
        rsi14=50.0, roc_5d=0.0, roc_20d=0.0, roc_63d=0.0,
        natr14=3.0, money_flow_20d=0.0, volume_ratio_20d=1.0,
        delivery_pct_ratio_20d=1.0, deliverable_vol_ratio_20d=1.0,
        high_52w=120.0, cm_pct_above_50dma=50.0, cm_pct_oversold_30=10.0,
        roc_5d_window=[0.0] * 10, volume_ratio_window=[1.0] * 10,
        natr14_window=[3.0] * 63,
    )
    d.update(over)
    return EquitySetupInputs(**d)


class TestBase(unittest.TestCase):
    def test_base_fires_nothing(self):
        self.assertEqual(screen(base()), [])


class TestMomentumBuildup(unittest.TestCase):
    def test_arm(self):
        i = base(close=100.0, dma20=95.0, dma50=90.0, roc_5d=3.1, rsi14=60.0, volume_ratio_20d=1.3)
        self.assertIn("MOMENTUM_BUILDUP", screen(i))

    def test_not_trend_aligned(self):
        i = base(close=100.0, dma20=90.0, dma50=95.0,  # dma20 < dma50, not aligned
                 roc_5d=3.1, rsi14=60.0, volume_ratio_20d=1.3)
        self.assertNotIn("MOMENTUM_BUILDUP", screen(i))

    def test_rsi_too_high_already_overbought(self):
        i = base(close=100.0, dma20=95.0, dma50=90.0, roc_5d=3.1, rsi14=75.0, volume_ratio_20d=1.3)
        self.assertNotIn("MOMENTUM_BUILDUP", screen(i))

    def test_rsi_too_low_now(self):
        # rsi14=52 used to qualify (floor was 50) — tightened floor to 55 excludes it
        i = base(close=100.0, dma20=95.0, dma50=90.0, roc_5d=3.1, rsi14=52.0, volume_ratio_20d=1.3)
        self.assertNotIn("MOMENTUM_BUILDUP", screen(i))

    def test_volume_too_low(self):
        i = base(close=100.0, dma20=95.0, dma50=90.0, roc_5d=3.1, rsi14=60.0, volume_ratio_20d=1.1)
        self.assertNotIn("MOMENTUM_BUILDUP", screen(i))

    def test_roc_too_weak_now(self):
        # roc_5d=1.0 used to qualify (floor was "> 0") — tightened floor to 3.0 excludes it
        i = base(close=100.0, dma20=95.0, dma50=90.0, roc_5d=1.0, rsi14=60.0, volume_ratio_20d=1.3)
        self.assertNotIn("MOMENTUM_BUILDUP", screen(i))


class TestImbalanceConsolidation(unittest.TestCase):
    def test_arm(self):
        window = [0.0] * 8 + [6.0, 0.5]  # an imbalance day 2 sessions ago, quiet since
        vol_window = [1.0] * 8 + [2.0, 0.3]
        natr_window = [5.0] * 63          # today's natr14 (1.0) is well below all of these
        i = base(natr14=1.0, volume_ratio_20d=0.3,
                 roc_5d_window=window, volume_ratio_window=vol_window, natr14_window=natr_window)
        self.assertIn("IMBALANCE_CONSOLIDATION", screen(i))

    def test_no_imbalance_in_lookback_does_not_arm(self):
        i = base(natr14=1.0, volume_ratio_20d=0.3,
                 roc_5d_window=[0.0] * 10, volume_ratio_window=[1.0] * 10,
                 natr14_window=[5.0] * 63)
        self.assertNotIn("IMBALANCE_CONSOLIDATION", screen(i))

    def test_not_currently_consolidating_does_not_arm(self):
        window = [0.0] * 8 + [6.0, 0.5]
        vol_window = [1.0] * 8 + [2.0, 0.3]
        # today's natr14 is high, not in the bottom percentile of its own window
        i = base(natr14=9.0, volume_ratio_20d=0.3,
                 roc_5d_window=window, volume_ratio_window=vol_window, natr14_window=[5.0] * 63)
        self.assertNotIn("IMBALANCE_CONSOLIDATION", screen(i))

    def test_suppressed_by_migration_analogue_volume_too_high(self):
        window = [0.0] * 8 + [6.0, 0.5]
        vol_window = [1.0] * 8 + [2.0, 0.3]
        i = base(natr14=1.0, volume_ratio_20d=1.5,  # above CONSOLIDATION_MAX_VOLUME_RATIO
                 roc_5d_window=window, volume_ratio_window=vol_window, natr14_window=[5.0] * 63)
        self.assertNotIn("IMBALANCE_CONSOLIDATION", screen(i))


class TestBreadthDivergenceReversal(unittest.TestCase):
    def test_arm(self):
        # close (90) below dma20 (95) -- a genuine, still-in-progress dip
        i = base(close=90.0, dma20=95.0, rsi14=25.0, cm_pct_oversold_30=10.0, roc_5d=-5.0)
        self.assertIn("BREADTH_DIVERGENCE_REVERSAL", screen(i))

    def test_broad_selloff_not_a_divergence(self):
        i = base(close=90.0, dma20=95.0, rsi14=25.0, cm_pct_oversold_30=35.0, roc_5d=-5.0)
        self.assertNotIn("BREADTH_DIVERGENCE_REVERSAL", screen(i))

    def test_not_oversold_enough(self):
        i = base(close=90.0, dma20=95.0, rsi14=35.0, cm_pct_oversold_30=10.0, roc_5d=-5.0)
        self.assertNotIn("BREADTH_DIVERGENCE_REVERSAL", screen(i))

    def test_already_stabilizing_not_sharp_enough_now(self):
        # roc_5d=+0.3 used to qualify (no roc_5d condition before) — new ceiling
        # of -3.0 excludes "already stabilizing" names, keeping only sharp declines
        i = base(close=90.0, dma20=95.0, rsi14=25.0, cm_pct_oversold_30=10.0, roc_5d=0.3)
        self.assertNotIn("BREADTH_DIVERGENCE_REVERSAL", screen(i))

    def test_price_already_above_dma20_is_a_stale_refire_not_a_real_dip(self):
        """The production bug this fixes: close (122) already well above
        dma20 (95, still lagging low from an earlier crash) — RSI<30 firing
        here means a stale re-trigger long after the real bottom, not a
        genuine in-progress dip. Must not arm."""
        i = base(close=122.0, dma20=95.0, rsi14=25.0, cm_pct_oversold_30=10.0, roc_5d=-5.0)
        self.assertNotIn("BREADTH_DIVERGENCE_REVERSAL", screen(i))


class TestFiftyTwoWeekBreakout(unittest.TestCase):
    def test_arm(self):
        i = base(close=121.0, high_52w=120.0, volume_ratio_20d=1.3, deliverable_vol_ratio_20d=1.3)
        self.assertIn("FIFTYTWO_WEEK_BREAKOUT", screen(i))

    def test_below_high_does_not_arm(self):
        i = base(close=119.0, high_52w=120.0, volume_ratio_20d=1.3, deliverable_vol_ratio_20d=1.3)
        self.assertNotIn("FIFTYTWO_WEEK_BREAKOUT", screen(i))

    def test_thin_delivery_does_not_arm(self):
        i = base(close=121.0, high_52w=120.0, volume_ratio_20d=1.3, deliverable_vol_ratio_20d=0.8)
        self.assertNotIn("FIFTYTWO_WEEK_BREAKOUT", screen(i))


class TestRsiExtremeRebound(unittest.TestCase):
    def test_arm(self):
        i = base(rsi14=20.0, volume_ratio_20d=1.6, cm_pct_above_50dma=45.0)
        self.assertIn("RSI_EXTREME_REBOUND", screen(i))

    def test_weak_breadth_does_not_arm(self):
        i = base(rsi14=20.0, volume_ratio_20d=1.6, cm_pct_above_50dma=30.0)
        self.assertNotIn("RSI_EXTREME_REBOUND", screen(i))


class TestMissingDataNeverCrashes(unittest.TestCase):
    def test_nan_inputs_fire_nothing(self):
        i = base(rsi14=float("nan"), natr14=float("nan"), volume_ratio_20d=float("nan"),
                 dma50=float("nan"), roc_5d=float("nan"), roc_20d=float("nan"))
        self.assertEqual(screen(i), [])


if __name__ == "__main__":
    unittest.main()
