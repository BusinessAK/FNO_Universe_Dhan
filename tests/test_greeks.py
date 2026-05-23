import unittest
import numpy as np
import pandas as pd
from src.greeks_engine import GreeksEngine

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

if __name__ == '__main__':
    unittest.main()
