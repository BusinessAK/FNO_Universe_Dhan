"""
Integration test for vanguard/pipeline/equity_setups_pipeline.py — a small,
fully-controlled synthetic technicals frame (not routed through
build_equity_technicals, so the setup-firing conditions are exact and
legible) confirming the screener->playbook->derive_positions() chain
produces schema-valid rows, same contract as the F&O side's
test_export_api.py::test_setup_positions_present_and_point_in_time_consistent.

Important mechanic, found while writing this test (not documented until
now): derive_positions() only ever checks a day's trigger against that SAME
day's own spot — a snapshot from an earlier day is never reconsidered on a
later day unless the screener condition ALSO fires again that later day
(giving a fresh snapshot with a freshly-recomputed trigger). There is no
"pending order" state. So a position only opens on a day where the
screening condition is true AND that same day's price already clears that
same day's trigger — never via "wait N days for an earlier trigger."
"""
import unittest

import pandas as pd

from vanguard.pipeline.equity_setups_pipeline import build_equity_setups_and_positions

_COLS = [
    "date", "symbol", "close", "adj_close", "dma20", "dma50", "rsi14", "roc_5d", "roc_20d", "roc_63d",
    "natr14", "money_flow_20d", "volume_ratio_20d", "delivery_pct_ratio_20d",
    "deliverable_vol_ratio_20d", "high_52w",
]


def _row(date, symbol, close, dma20, dma50=None, **over):
    """close doubles as adj_close (no corporate action in these fixtures) —
    the pipeline reads adj_close as its "spot" (2026-07-21 fix; see
    equity_setups_pipeline.py's module docstring)."""
    d = dict(date=date, symbol=symbol, close=close, adj_close=close, dma20=dma20, dma50=dma50 or dma20 * 0.95,
             rsi14=50.0, roc_5d=0.0, roc_20d=0.0, roc_63d=0.0, natr14=3.0, money_flow_20d=0.0,
             volume_ratio_20d=1.0, delivery_pct_ratio_20d=1.0, deliverable_vol_ratio_20d=1.0,
             high_52w=close * 1.2)
    d.update(over)
    return d


class TestScreenerToPositionsChain(unittest.TestCase):
    def test_rsi_extreme_rebound_opens_same_day_when_trigger_already_cleared(self):
        """close (100) already >= dma20 (95) on the firing day itself — the
        NATR-scaled trigger (dma20*(1-0.5*0.03)=93.575, natr14=3.0 default;
        trigger sits BELOW the anchor for this setup, see
        vanguard/config/equity.py's NATR_TRIGGER_MULT) is cleared same-day,
        a realistic V-shaped one-day reversal. invalidation =
        dma20*(1-0.75*0.03) = 92.8625. risk/target are sized off the ACTUAL
        entry price (100.0). risk = 100.0 - 92.8625 = 7.1375;
        target = 100.0 + 2 * 7.1375 = 114.275."""
        rows = [
            _row("2026-01-01", "XXX", 90.0, dma20=100.0),
            _row("2026-01-02", "XXX", 100.0, dma20=95.0, rsi14=20.0, volume_ratio_20d=1.6),  # fires + clears same day
            _row("2026-01-03", "XXX", 120.0, dma20=97.0),   # clears the 114.275 target
        ]
        technicals = pd.DataFrame(rows, columns=_COLS)
        breadth = pd.DataFrame([
            {"date": "2026-01-02", "cm_pct_above_50dma": 45.0, "cm_pct_oversold_30": 5.0},
        ])
        df_setups, position_rows = build_equity_setups_and_positions(technicals, breadth)

        self.assertEqual(len(df_setups), 1)
        self.assertEqual(df_setups.iloc[0]["setup_type"], "RSI_EXTREME_REBOUND")
        self.assertAlmostEqual(df_setups.iloc[0]["trigger_strike"], 93.575)

        self.assertEqual(len(position_rows), 1)
        p = position_rows[0]
        self.assertEqual(p["symbol"], "XXX")
        self.assertEqual(p["direction"], "up")
        self.assertEqual(p["trigger_date"], "2026-01-02")     # same day as firing
        self.assertEqual(p["status"], "TARGET_HIT")
        self.assertEqual(p["resolved_date"], "2026-01-03")
        self.assertIsNotNone(p["resolved_price"])

    def test_trigger_not_cleared_same_day_and_condition_does_not_refire_never_opens(self):
        """dma20 (105) is ABOVE the firing day's own close (90) -> trigger
        not cleared that day. RSI recovers on later days (condition doesn't
        refire), so per the mechanic above, this setup never gets another
        chance to open — zero position rows, not a delayed one."""
        rows = [
            _row("2026-01-01", "YYY", 100.0, dma20=100.0),
            _row("2026-01-02", "YYY", 90.0, dma20=105.0, rsi14=20.0, volume_ratio_20d=1.6),  # fires, not cleared
            _row("2026-01-03", "YYY", 110.0, dma20=103.0),   # closes above 105 later, but condition is dead
        ]
        technicals = pd.DataFrame(rows, columns=_COLS)
        breadth = pd.DataFrame([
            {"date": "2026-01-02", "cm_pct_above_50dma": 45.0, "cm_pct_oversold_30": 5.0},
        ])
        df_setups, position_rows = build_equity_setups_and_positions(technicals, breadth)
        self.assertEqual(len(df_setups), 1)          # the screener DID fire...
        self.assertEqual(len(position_rows), 0)       # ...but never became a tracked position

    def test_no_breadth_data_suppresses_breadth_dependent_setups(self):
        rows = [
            _row("2026-01-01", "ZZZ", 100.0, dma20=100.0),
            _row("2026-01-02", "ZZZ", 100.0, dma20=95.0, rsi14=20.0, volume_ratio_20d=1.6),
        ]
        technicals = pd.DataFrame(rows, columns=_COLS)
        df_setups, position_rows = build_equity_setups_and_positions(
            technicals, pd.DataFrame())  # no breadth at all
        self.assertEqual(len(df_setups), 0)
        self.assertEqual(len(position_rows), 0)

    def test_open_vs_resolved_shape_matches_fo_contract(self):
        """Every row must be either OPEN (resolved_price is None) or resolved
        (resolved_price is not None) — same invariant test_export_api.py
        already checks for the F&O side. Target is 95.0 (see the docstring
        two tests up); day 3's close (94.5) stays between the SL (92.8625)
        and target (95.0), so the position stays OPEN."""
        rows = [
            _row("2026-01-01", "WWW", 90.0, dma20=100.0),
            _row("2026-01-02", "WWW", 100.0, dma20=95.0, rsi14=20.0, volume_ratio_20d=1.6),  # opens same-day
            _row("2026-01-03", "WWW", 94.5, dma20=96.0),   # between SL and target -> still open
        ]
        technicals = pd.DataFrame(rows, columns=_COLS)
        breadth = pd.DataFrame([
            {"date": "2026-01-02", "cm_pct_above_50dma": 45.0, "cm_pct_oversold_30": 5.0},
        ])
        _, position_rows = build_equity_setups_and_positions(technicals, breadth)
        self.assertEqual(len(position_rows), 1)
        p = position_rows[0]
        self.assertEqual(p["status"], "OPEN")
        self.assertIsNone(p["resolved_price"])
        self.assertIsNone(p["resolved_date"])


if __name__ == "__main__":
    unittest.main()
