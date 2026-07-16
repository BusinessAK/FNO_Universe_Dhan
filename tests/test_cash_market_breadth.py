import unittest
import pandas as pd
import numpy as np
from src.core.cash_market_breadth import _build_adjusted_close, CashMarketBreadthEngine

class TestCashMarketBreadth(unittest.TestCase):
    def test_corporate_action_adjustment(self):
        # Create mock data with a corporate action split (1:1 bonus, price halves)
        # Symbol A: Normal stock, no corporate actions
        # Symbol B: Splits on Day 3 (Price drops from 100 to 50, but ex-prev close is 100)
        data = {
            "symbol": ["A", "A", "A", "A", "B", "B", "B", "B"],
            "date": [
                pd.Timestamp("2026-06-01"), pd.Timestamp("2026-06-02"), pd.Timestamp("2026-06-03"), pd.Timestamp("2026-06-04"),
                pd.Timestamp("2026-06-01"), pd.Timestamp("2026-06-02"), pd.Timestamp("2026-06-03"), pd.Timestamp("2026-06-04")
            ],
            "close": [100.0, 102.0, 104.0, 106.0, 200.0, 204.0, 105.0, 107.0],
            "prev_close": [98.0, 100.0, 102.0, 104.0, 196.0, 200.0, 204.0, 105.0],
            "open": [99.0, 101.0, 103.0, 105.0, 198.0, 202.0, 102.0, 106.0],
            "volume": [1000, 1100, 1200, 1300, 500, 600, 700, 800],
            "turnover": [100000, 110000, 120000, 130000, 100000, 120000, 70000, 85000]
        }
        df = pd.DataFrame(data)
        
        # Run adjustment
        adj_df = _build_adjusted_close(df)
        
        # Symbol A should have no adjustments (factor = 1.0)
        a_df = adj_df[adj_df["symbol"] == "A"].sort_values("date")
        np.testing.assert_array_almost_equal(a_df["adj_close"], [100.0, 102.0, 104.0, 106.0])
        
        # Symbol B splits on 2026-06-03 (drop from 204.0 to 105.0 is ~48.5%, triggering adjustment)
        b_df = adj_df[adj_df["symbol"] == "B"].sort_values("date")
        # ex-date open was 102.0, prev_close was 204.0. Ratio is 102 / 204 = 0.5.
        # So close on Day 1 and Day 2 should be scaled by 0.5 (200 -> 100, 204 -> 102).
        np.testing.assert_array_almost_equal(b_df["adj_close"], [100.0, 102.0, 105.0, 107.0])
        
        # Verify Corporate Action flags
        self.assertTrue(b_df.iloc[2]["ca_adjusted"]) # Split date is flagged
        self.assertFalse(b_df.iloc[0]["ca_adjusted"])
        
    def test_empty_dataframe_breadth(self):
        engine = CashMarketBreadthEngine()
        row = engine._empty_row("2026-06-01")
        self.assertEqual(row["cm_total_symbols"], 0)
        self.assertEqual(row["cm_advances"], 0)
        self.assertTrue(np.isnan(row["cm_pct_above_20dma"]))
        self.assertTrue(np.isnan(row["cm_pct_overbought_70"]))
        self.assertTrue(np.isnan(row["cm_pct_oversold_30"]))

    def test_rsi_extreme_bounds(self):
        # Build synthetic universe directly via engine._cm
        # Spans 20 daily rows for 2 symbols:
        # Symbol UPTREND: strictly monotonic uptrend (RSI should saturate at 100)
        # Symbol DOWNTREND: strictly monotonic downtrend (RSI should floor at 0)
        dates = pd.date_range("2026-06-01", periods=20)
        rows = []
        for idx, dt in enumerate(dates):
            rows.append({
                "symbol": "UPTREND",
                "date": dt,
                "close": 100.0 + idx, # always gains
                "prev_close": 99.0 + idx,
                "open": 100.0 + idx,
                "volume": 1000,
                "ca_adjusted": False
            })
            rows.append({
                "symbol": "DOWNTREND",
                "date": dt,
                "close": 100.0 - idx, # always losses
                "prev_close": 101.0 - idx,
                "open": 100.0 - idx,
                "volume": 1000,
                "ca_adjusted": False
            })
            
        df = pd.DataFrame(rows)
        # Set adjusted close and prev cols directly
        df["adj_close"] = df["close"]
        df["adj_prev_close"] = df["prev_close"]
        
        engine = CashMarketBreadthEngine()
        engine._cm = df.sort_values(["symbol", "date"]).reset_index(drop=True)
        engine._precompute_dmas()
        
        last_date_str = dates[-1].strftime("%Y-%m-%d")
        day_metrics = engine._compute_day(last_date_str)
        
        # In a 2-symbol universe, 1 stock has RSI=100 (overbought) and 1 has RSI=0 (oversold)
        # So 1/2 = 50% for each
        self.assertEqual(day_metrics["cm_pct_overbought_70"], 50.0)
        self.assertEqual(day_metrics["cm_pct_oversold_30"], 50.0)

if __name__ == "__main__":
    unittest.main()
