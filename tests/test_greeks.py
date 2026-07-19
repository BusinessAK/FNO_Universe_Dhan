import unittest
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
from vanguard.greeks_engine import GreeksEngine

class TestGreeksEngine(unittest.TestCase):
    def setUp(self):
        self.engine = GreeksEngine(risk_free_rate=0.07)

    def test_bs_pricing(self):
        # Call pricing
        c_price = self.engine.bs_price(S=100.0, K=100.0, T=1.0, sigma=0.2, option_type='CE')
        self.assertTrue(c_price > 0.0)
        # Put pricing
        p_price = self.engine.bs_price(S=100.0, K=100.0, T=1.0, sigma=0.2, option_type='PE')
        self.assertTrue(p_price > 0.0)

    def test_all_greeks(self):
        greeks = self.engine.all_greeks(S=100.0, K=100.0, T=1.0, sigma=0.2, option_type='CE')
        self.assertEqual(greeks['DELTA'], greeks['DELTA'])  # Not NaN
        self.assertTrue(greeks['GAMMA'] > 0)
        self.assertTrue(greeks['VEGA'] > 0)
        self.assertTrue(greeks['THETA'] < 0)

    def test_charm_deep_itm_zero_leak(self):
        # Deep ITM Call should have 0 Charm decay
        greeks = self.engine.all_greeks(S=500.0, K=100.0, T=1.0, sigma=0.2, option_type='CE')
        self.assertAlmostEqual(greeks['CHARM'], 0.0, places=5)

    def test_calculate_iv(self):
        market_price = 11.54147  # Exact B-S price for 100 strike CE with S=100, T=1, r=0.07, sig=0.2
        iv = self.engine.calculate_iv(market_price, S=100.0, K=100.0, T=1.0, option_type='CE')
        self.assertAlmostEqual(iv, 0.2, delta=0.001)

class TestProcessDataframeWallCandidates(unittest.TestCase):
    """
    Regression for the IDEA case: a strike >15% from spot with real, large OI
    must not be silently excluded from Greeks computation just because it's
    far away — that would make it invisible to the wall/gamma-flip detection
    built on top of this output. Small-OI strikes at the same distance should
    still be skipped, so the original dust-skipping optimization still holds.
    """

    def setUp(self):
        self.engine = GreeksEngine(risk_free_rate=0.07)
        self.expiry = datetime(2026, 9, 24)
        self.trade_date = datetime(2026, 7, 15)

    def _row(self, symbol, strike, opt_type, close, open_int, chg_in_oi=0, volume=10):
        return {
            'SYMBOL': symbol, 'INSTRUMENT': 'STO', 'STRIKE_PR': strike,
            'OPTION_TYP': opt_type, 'CLOSE': close, 'OPEN_INT': open_int,
            'CHG_IN_OI': chg_in_oi, 'VOLUME': volume,
            'EXPIRY_DT': self.expiry, 'TIMESTAMP': self.trade_date,
        }

    def test_large_oi_strike_beyond_15_pct_is_included(self):
        spot = 10.13  # IDEA-like low-priced stock
        df = pd.DataFrame([
            self._row('IDEA', 10.0, 'CE', 0.30, 500_000),   # near spot, always included
            self._row('IDEA', 12.0, 'CE', 34.25, 770_714_925),  # 18.5% out, huge OI
        ])
        out = self.engine.process_dataframe(df, {'IDEA': spot})
        self.assertTrue(
            ((out.SYMBOL == 'IDEA') & (out.STRIKE_PR == 12.0)).any(),
            "large-OI strike beyond 15% must still get Greeks computed",
        )

    def _filler_rows(self, symbol, opt_type, strikes_near_spot):
        """>wall_candidates (5) near-spot rows so nlargest(5) is a real cut, not
        a no-op from having fewer candidates than the slot count."""
        return [self._row(symbol, k, opt_type, 5.0, oi)
                for k, oi in zip(strikes_near_spot, [1000, 2000, 3000, 4000, 5000, 6000])]

    def test_small_oi_strike_beyond_15_pct_still_excluded(self):
        spot = 100.0
        df = pd.DataFrame(
            self._filler_rows('TESTCO', 'CE', [95, 96, 97, 98, 99, 101]) +
            [self._row('TESTCO', 130.0, 'CE', 0.05, 200)]  # 30% out, weakest OI in the book
        )
        out = self.engine.process_dataframe(df, {'TESTCO': spot})
        self.assertFalse(
            ((out.SYMBOL == 'TESTCO') & (out.STRIKE_PR == 130.0)).any(),
            "genuinely negligible far-OTM dust should still be skipped",
        )

    def test_wall_candidates_are_per_symbol_and_per_side(self):
        # A huge PE OI wall in one symbol must not consume the CE wall-candidate
        # slots of a different symbol, or of the other side in the same symbol.
        df = pd.DataFrame(
            self._filler_rows('A', 'CE', [95, 96, 97, 98, 99, 101]) +
            [self._row('A', 130.0, 'CE', 30.0, 900_000)] +          # A's CE wall, 30% out
            self._filler_rows('A', 'PE', [95, 96, 97, 98, 99, 101]) +
            [self._row('A', 70.0, 'PE', 25.0, 10)] +                # A's PE, weakest OI, 30% out — excluded
            self._filler_rows('B', 'CE', [48, 49, 50, 51, 52, 53]) +
            [self._row('B', 65.0, 'CE', 12.0, 800_000)]             # B's CE wall, 30% out
        )
        out = self.engine.process_dataframe(df, {'A': 100.0, 'B': 50.0})
        self.assertTrue(((out.SYMBOL == 'A') & (out.STRIKE_PR == 130.0)).any())
        self.assertTrue(((out.SYMBOL == 'B') & (out.STRIKE_PR == 65.0)).any())
        self.assertFalse(((out.SYMBOL == 'A') & (out.STRIKE_PR == 70.0) & (out.OPTION_TYP == 'PE')).any())


if __name__ == '__main__':
    unittest.main()
