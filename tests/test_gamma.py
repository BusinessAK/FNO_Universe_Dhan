import unittest

import pandas as pd

from vanguard.engines.gamma import GammaAnalyzer


class TestCalculateGexIvWeighting(unittest.TestCase):
    """calculate_gex()'s IV column must be OI-weighted, not a naive per-strike
    mean — an unweighted mean lets a low-OI/high-IV dust strike distort the
    aggregate as much as the liquid strike actually driving the chain (this
    was a real bug: vanguard/live/live_compute.py's iv_avg ran systematically
    hotter than the EOD figure for the same symbol, confirmed against a real
    live options chain where illiquid deep ITM/OTM strikes showed IV swinging
    30-60% on near-zero premiums)."""

    def test_iv_is_oi_weighted_not_a_naive_mean(self):
        analyzer = GammaAnalyzer()
        df = pd.DataFrame([
            # Liquid, near-ATM strike: huge OI, modest IV.
            {"SYMBOL": "TEST", "STRIKE_PR": 100.0, "OPTION_TYP": "CE",
             "GAMMA": 0.01, "OPEN_INT": 1_000_000, "IV": 0.20, "CHG_IN_OI": 0.0},
            # Illiquid dust strike: tiny OI, wildly higher IV (stale premium).
            {"SYMBOL": "TEST", "STRIKE_PR": 500.0, "OPTION_TYP": "CE",
             "GAMMA": 0.001, "OPEN_INT": 100, "IV": 2.00, "CHG_IN_OI": 0.0},
        ])
        summary = analyzer.calculate_gex(df, {"TEST": 100.0})
        iv = summary.set_index("SYMBOL").loc["TEST", "IV"]

        naive_mean = (0.20 + 2.00) / 2  # 1.10 — what the old bug produced
        oi_weighted = (0.20 * 1_000_000 + 2.00 * 100) / (1_000_000 + 100)  # ~0.2002

        self.assertLess(iv, naive_mean, "IV must not equal the naive unweighted mean")
        self.assertAlmostEqual(iv, oi_weighted, places=6)

    def test_zero_total_oi_does_not_divide_by_zero(self):
        analyzer = GammaAnalyzer()
        df = pd.DataFrame([
            {"SYMBOL": "TEST", "STRIKE_PR": 100.0, "OPTION_TYP": "CE",
             "GAMMA": 0.01, "OPEN_INT": 0, "IV": 0.20, "CHG_IN_OI": 0.0},
        ])
        summary = analyzer.calculate_gex(df, {"TEST": 100.0})
        self.assertEqual(summary.set_index("SYMBOL").loc["TEST", "IV"], 0.0)


if __name__ == "__main__":
    unittest.main()
