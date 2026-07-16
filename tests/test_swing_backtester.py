import unittest
import tempfile

import pandas as pd

from src.research.swing_backtester import (
    BacktestConfig,
    classify_long_candidate,
    compute_alpha_score,
    simulate_trades,
    summarize_trades,
)


class TestSwingBacktester(unittest.TestCase):
    def test_classify_long_candidate_excludes_indices_and_bearish_setups(self):
        index_row = pd.Series({
            "symbol": "NIFTY",
            "bias": "Bullish Breakout",
            "expected_behavior": "Trend Extension",
            "suggested_strategy": "Bull Call Spread",
            "setup_type": "GAMMA_SQUEEZE",
            "ifs_score": 40.0,
        })
        bearish_row = pd.Series({
            "symbol": "ABCAPITAL",
            "bias": "Bearish Breakdown",
            "expected_behavior": "Downside Skew Chase",
            "suggested_strategy": "Bear Put Spread",
            "setup_type": "IV_SKEW_ACCUMULATION",
            "ifs_score": -35.0,
        })
        bullish_row = pd.Series({
            "symbol": "RELIANCE",
            "bias": "Bullish Accumulation",
            "expected_behavior": "Support Floor Rise",
            "suggested_strategy": "Bull Put Spread",
            "setup_type": "INVENTORY_MIGRATION",
            "ifs_score": 22.0,
        })

        self.assertFalse(classify_long_candidate(index_row))
        self.assertFalse(classify_long_candidate(bearish_row))
        self.assertTrue(classify_long_candidate(bullish_row))

    def test_compute_alpha_score_is_bounded(self):
        row = pd.Series({
            "ifs_score": 300.0,
            "conviction_score": 100.0,
            "smart_money_persistence": 100.0,
            "macro_regime_prob": 100.0,
            "futures_oi_chg": 1000.0,
            "net_inv_shift": 10_000_000.0,
            "spot_change_pct": 20.0,
            "ml_breakout_prob": 100.0,
        })
        score = compute_alpha_score(row)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_simulate_and_summarize_trades(self):
        df = pd.DataFrame([
            {
                "symbol": "RELIANCE",
                "sector": "ENERGY",
                "date": pd.Timestamp("2026-01-01"),
                "setup_type": "FLOOR_BOUNCE",
                "bias": "Bullish Mean Reversion",
                "expected_behavior": "Key Support Bounce",
                "suggested_strategy": "Bull Put Spread",
                "entry_date": pd.Timestamp("2026-01-02"),
                "entry_close": 100.0,
                "exit_date_3d": pd.Timestamp("2026-01-05"),
                "exit_close_3d": 105.0,
                "invalidation_strike": 95.0,
                "ifs_score": 25.0,
                "conviction_score": 50.0,
                "smart_money_persistence": 40.0,
                "priority_score": 10.0,
                "macro_regime_prob": 60.0,
                "futures_oi_chg": 1000.0,
                "net_inv_shift": 500000.0,
                "spot_change_pct": 1.5,
                "ml_breakout_prob": 55.0,
                "gamma_regime": "LONG_GAMMA",
                "structural_bias": "Support Building",
            }
        ])
        config = BacktestConfig(holding_periods=(3,), cost_bps=20.0, min_trades=1, use_cash_ohlc=False)
        trades = simulate_trades(df, config)
        self.assertEqual(len(trades), 1)
        self.assertAlmostEqual(trades.iloc[0]["net_return_pct"], 4.8)

        summary = summarize_trades(trades, ["setup_type", "holding_days"], min_trades=1)
        self.assertEqual(summary.iloc[0]["trades"], 1)
        self.assertEqual(summary.iloc[0]["win_rate_pct"], 100.0)

    def test_cash_ohlc_mode_uses_next_open_and_intraperiod_stop(self):
        signal_df = pd.DataFrame([
            {
                "symbol": "RELIANCE",
                "sector": "ENERGY",
                "date": pd.Timestamp("2026-01-01"),
                "setup_type": "FLOOR_BOUNCE",
                "bias": "Bullish Mean Reversion",
                "expected_behavior": "Key Support Bounce",
                "suggested_strategy": "Bull Put Spread",
                "invalidation_strike": 95.0,
                "ifs_score": 25.0,
                "conviction_score": 50.0,
                "smart_money_persistence": 40.0,
                "priority_score": 10.0,
                "macro_regime_prob": 60.0,
                "futures_oi_chg": 1000.0,
                "net_inv_shift": 500000.0,
                "spot_change_pct": 1.5,
                "ml_breakout_prob": 55.0,
                "gamma_regime": "LONG_GAMMA",
                "structural_bias": "Support Building",
            }
        ])
        prices = pd.DataFrame([
            {"symbol": "RELIANCE", "date": pd.Timestamp("2026-01-02"), "open": 100.0, "high": 103.0, "low": 99.0, "close": 102.0},
            {"symbol": "RELIANCE", "date": pd.Timestamp("2026-01-05"), "open": 102.0, "high": 104.0, "low": 94.0, "close": 103.0},
            {"symbol": "RELIANCE", "date": pd.Timestamp("2026-01-06"), "open": 103.0, "high": 106.0, "low": 101.0, "close": 105.0},
        ])

        with tempfile.NamedTemporaryFile(suffix=".parquet") as tmp:
            prices.to_parquet(tmp.name, index=False)
            config = BacktestConfig(
                holding_periods=(3,),
                cost_bps=20.0,
                stop_loss_pct=7.0,
                min_trades=1,
                price_data_path=tmp.name,
                use_cash_ohlc=True,
                use_trend_filter=False,
            )
            trades = simulate_trades(signal_df, config)

        self.assertEqual(len(trades), 1)
        trade = trades.iloc[0]
        self.assertTrue(trade["stopped"])
        self.assertEqual(trade["entry_close"], 100.0)
        self.assertEqual(trade["exit_close"], 95.0)
        self.assertAlmostEqual(trade["net_return_pct"], -5.2)
        self.assertEqual(trade["price_source"], "cash_ohlc")


if __name__ == "__main__":
    unittest.main()
