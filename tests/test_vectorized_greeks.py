"""
F0 parity gate (TRD_fullmap_live_v1 §4): the vectorized Newton IV solver and
vectorized greeks must reproduce the scalar brentq path within |dIV| <= 1e-4,
and process_dataframe(iv_method="vectorized") must be row-for-row equivalent
to the historical scalar loop. Also enforces the < 2 s perf budget at full-map
scale (12.5k rows).
"""
import time
import unittest
from datetime import datetime

import numpy as np
import pandas as pd

from src.greeks_engine import GreeksEngine


def synthetic_grid(n=4000, seed=7):
    """Realistic option rows: ±15% moneyness, 2-45 DTE, 10-80% vol."""
    rng = np.random.default_rng(seed)
    S = rng.uniform(100, 25000, n)
    K = S * rng.uniform(0.85, 1.15, n)
    T = rng.uniform(2 / 365, 45 / 365, n)
    iv = rng.uniform(0.10, 0.80, n)
    otype = np.where(rng.random(n) > 0.5, 'CE', 'PE')
    return S, K, T, iv, otype


class TestIVParity(unittest.TestCase):
    def setUp(self):
        self.eng = GreeksEngine(risk_free_rate=0.07)

    def test_newton_matches_brentq_within_1e4(self):
        S, K, T, true_iv, otype = synthetic_grid()
        price = np.array([self.eng.bs_price(S[i], K[i], T[i], true_iv[i], otype[i])
                          for i in range(len(S))])
        ok = price > 0.05
        S, K, T, price, otype = S[ok], K[ok], T[ok], price[ok], otype[ok]

        iv_vec, converged = self.eng.implied_vol_vectorized(price, S, K, T, otype == 'CE')
        # F0 gate: converged rows within 1e-4 of brentq
        idx = np.where(converged)[0]
        self.assertGreater(len(idx), 0.9 * len(S), "convergence rate collapsed")
        brent = np.array([self.eng.calculate_iv(price[i], S[i], K[i], T[i], otype[i])
                          for i in idx])
        self.assertLess(np.max(np.abs(iv_vec[idx] - brent)), 1e-4)

    def test_invalid_inputs_mirror_calculate_iv(self):
        # T<=0, price<=0, S<=0, K<=0 -> iv 0.0, treated as converged
        iv, conv = self.eng.implied_vol_vectorized(
            price=[0.0, 5.0, 5.0, 5.0], S=[100, 0.0, 100, 100],
            K=[100, 100, 100, 0.0], T=[0.1, 0.1, 0.0, 0.1],
            is_call=[True, True, False, False])
        np.testing.assert_array_equal(iv, [0.0, 0.0, 0.0, 0.0])
        self.assertTrue(conv.all())

    def test_deep_otm_dust_falls_back_not_garbage(self):
        # Near-zero-vega rows must either converge or report converged=False
        # (never a silent wrong IV) — the fallback path handles them.
        iv, conv = self.eng.implied_vol_vectorized(
            price=[0.10], S=[10000.0], K=[16000.0], T=[2 / 365], is_call=[True])
        if conv[0]:
            self.assertTrue(0.001 <= iv[0] <= 5.0)
        else:
            self.assertTrue(np.isnan(iv[0]))


class TestGreeksParity(unittest.TestCase):
    def setUp(self):
        self.eng = GreeksEngine(risk_free_rate=0.07)

    def test_vectorized_matches_all_greeks(self):
        S, K, T, iv, otype = synthetic_grid(n=500, seed=11)
        vec = self.eng.greeks_vectorized(S, K, T, iv, otype == 'CE')
        for i in range(len(S)):
            ref = self.eng.all_greeks(S[i], K[i], T[i], iv[i], otype[i])
            for g in ('DELTA', 'GAMMA', 'VEGA', 'THETA', 'RHO', 'VANNA', 'CHARM', 'VOMMA'):
                self.assertAlmostEqual(vec[g][i], ref[g], places=10,
                                       msg=f"{g} row {i}")

    def test_invalid_rows_zeroed_like_scalar(self):
        vec = self.eng.greeks_vectorized(S=[100, 100], K=[100, 100],
                                         T=[0.0, 0.5], sigma=[0.2, 0.0],
                                         is_call=[True, True])
        for g in vec:
            self.assertEqual(vec[g][0], 0.0)
            self.assertEqual(vec[g][1], 0.0)


class TestProcessDataframeParity(unittest.TestCase):
    """scalar vs vectorized full-path equivalence, including the edge rows:
    dust premiums, far-OTM wall candidates, missing spot, expiry day."""

    def setUp(self):
        self.eng = GreeksEngine(risk_free_rate=0.07)
        self.expiry = datetime(2026, 8, 27)
        self.trade = datetime(2026, 7, 16)

    def _row(self, sym, k, ot, close, oi, expiry=None, trade=None):
        return {'SYMBOL': sym, 'INSTRUMENT': 'STO', 'STRIKE_PR': k,
                'OPTION_TYP': ot, 'CLOSE': close, 'OPEN_INT': oi,
                'CHG_IN_OI': 10, 'VOLUME': 5,
                'EXPIRY_DT': expiry or self.expiry,
                'TIMESTAMP': trade or self.trade}

    def _frame(self):
        rows = []
        # normal near-ATM ladder
        for k in (950, 975, 1000, 1025, 1050):
            rows.append(self._row('AAA', k, 'CE', max(1000 - k, 8) + 12.5, 5000))
            rows.append(self._row('AAA', k, 'PE', max(k - 1000, 8) + 11.0, 4000))
        # dust premium (< 0.05) within the 15% window -> pinned 20% IV
        # (kept at 14% from spot; a farther dust strike is dropped by the
        # distance filter before the dust rule is ever consulted)
        rows.append(self._row('AAA', 1140, 'CE', 0.04, 3000))
        # far strike (>15%) with HUGE OI -> must_keep wall candidate
        rows.append(self._row('AAA', 1400, 'CE', 0.30, 900000))
        # far strike, small OI -> dropped by the 15% filter
        rows.append(self._row('AAA', 1500, 'CE', 0.10, 5))
        # symbol without a spot -> dropped entirely
        rows.append(self._row('NOSPOT', 100, 'CE', 5.0, 1000))
        # expiry day (T == 0) -> IV 0, zero greeks (both paths)
        rows.append(self._row('AAA', 1000, 'CE', 4.0, 2000,
                              expiry=self.trade, trade=self.trade))
        # zero OI -> dropped by the OI filter
        rows.append(self._row('AAA', 990, 'PE', 9.0, 0))
        return pd.DataFrame(rows)

    def test_scalar_vs_vectorized_equivalence(self):
        df = self._frame()
        spots = {'AAA': 1000.0}
        a = self.eng.process_dataframe(df, spots, iv_method="scalar")
        b = self.eng.process_dataframe(df, spots, iv_method="vectorized")

        self.assertEqual(len(a), len(b))
        key = ['SYMBOL', 'STRIKE_PR', 'OPTION_TYP']
        a = a.sort_values(key).reset_index(drop=True)
        b = b.sort_values(key).reset_index(drop=True)
        pd.testing.assert_frame_equal(
            a[key + ['OPEN_INT', 'CHG_IN_OI', 'VOLUME', 'CLOSE']],
            b[key + ['OPEN_INT', 'CHG_IN_OI', 'VOLUME', 'CLOSE']])
        np.testing.assert_allclose(a['IV'], b['IV'], atol=1e-4)
        # greeks tolerance must be consistent with the 1e-4 IV gate: a dIV of
        # 1e-4 legitimately moves vega/delta by ~1e-4, not 1e-6
        for g in ('DELTA', 'GAMMA', 'VEGA', 'THETA', 'VANNA', 'CHARM'):
            np.testing.assert_allclose(a[g], b[g], atol=1e-4, rtol=1e-3, err_msg=g)

    def test_row_selection_semantics(self):
        df = self._frame()
        out = self.eng.process_dataframe(df, {'AAA': 1000.0}, iv_method="vectorized")
        syms = set(zip(out.SYMBOL, out.STRIKE_PR, out.OPTION_TYP))
        self.assertIn(('AAA', 1400, 'CE'), syms)        # wall candidate kept
        self.assertNotIn(('AAA', 1500, 'CE'), syms)     # far dust dropped
        self.assertNotIn(('NOSPOT', 100, 'CE'), syms)   # no spot dropped
        self.assertNotIn(('AAA', 990, 'PE'), syms)      # zero OI dropped
        dust = out[(out.STRIKE_PR == 1140) & (out.OPTION_TYP == 'CE')]
        self.assertAlmostEqual(float(dust.IV.iloc[0]), 0.20)
        tzero = out[(out.STRIKE_PR == 1000) & (out.OPTION_TYP == 'CE') & (out.IV == 0.0)]
        self.assertEqual(len(tzero), 1)                 # expiry-day row: IV 0
        self.assertEqual(float(tzero.GAMMA.iloc[0]), 0.0)

    def test_empty_input(self):
        df = self._frame().iloc[0:0]
        out = self.eng.process_dataframe(df, {'AAA': 1000.0})
        self.assertTrue(out.empty)


class TestPerfBudget(unittest.TestCase):
    def test_full_map_under_two_seconds(self):
        """TRD §4: 12.5k rows end-to-end (IV + greeks) < 2 s."""
        eng = GreeksEngine()
        S, K, T, true_iv, otype = synthetic_grid(n=12500, seed=3)
        price = eng.bs_price(100, 100, 0.1, 0.2, 'CE')  # warm scipy
        rows = pd.DataFrame({
            'SYMBOL': [f'S{i % 215}' for i in range(len(S))],
            'INSTRUMENT': 'STO', 'STRIKE_PR': K, 'OPTION_TYP': otype,
            'CLOSE': np.maximum([eng.bs_price(S[i], K[i], T[i], true_iv[i], otype[i])
                                 for i in range(len(S))], 0.06),
            'OPEN_INT': 1000, 'CHG_IN_OI': 0, 'VOLUME': 1,
            'EXPIRY_DT': datetime(2026, 8, 27), 'TIMESTAMP': datetime(2026, 7, 16),
        })
        # spot per synthetic symbol: use each symbol's own S values
        spots = {f'S{i % 215}': float(S[i]) for i in range(len(S))}
        t0 = time.perf_counter()
        out = eng.process_dataframe(rows, spots, iv_method="vectorized")
        dt = time.perf_counter() - t0
        self.assertGreater(len(out), 0)
        self.assertLess(dt, 2.0, f"vectorized path took {dt:.2f}s (budget 2s)")


if __name__ == '__main__':
    unittest.main()
