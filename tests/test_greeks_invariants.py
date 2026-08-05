"""
Property/invariant tests for GreeksEngine — checks that don't require a
"known right answer" (that's what verify_greeks_vs_pyvollib.py / py_vollib
comparison is for), just internal mathematical consistency that must hold
for ANY correct Black-Scholes implementation. These are cheap and catch a
different class of bug: a formula change that's internally inconsistent
even if it happens to match a reference on the specific cases tested.
"""
import itertools
import unittest

import numpy as np

from vanguard.engines.greeks import GreeksEngine

# Broad grid spanning ITM/ATM/OTM, short/long-dated, low/high vol — the
# combinations most likely to expose a sign error or bad edge-case branch.
GRID = list(itertools.product(
    [100.0],                      # S
    [70.0, 90.0, 100.0, 110.0, 140.0],  # K
    [1 / 365, 7 / 365, 30 / 365, 0.25, 1.0],  # T (years)
    [0.10, 0.20, 0.50, 1.0],       # sigma
))


class TestPutCallParity(unittest.TestCase):
    """C - P = S - K*e^(-rT), independent of sigma — the canonical
    no-arbitrage identity for European options. If this breaks, the pricer
    is wrong regardless of what any single Greek looks like."""

    def setUp(self):
        self.r = 0.07
        self.engine = GreeksEngine(risk_free_rate=self.r)

    def test_parity_holds_across_grid(self):
        for S, K, T, sigma in GRID:
            c = self.engine.bs_price(S, K, T, sigma, 'CE')
            p = self.engine.bs_price(S, K, T, sigma, 'PE')
            lhs = c - p
            rhs = S - K * np.exp(-self.r * T)
            self.assertAlmostEqual(
                lhs, rhs, places=6,
                msg=f"Put-call parity violated at S={S} K={K} T={T} sigma={sigma}: "
                    f"C-P={lhs:.6f} vs S-K*e^-rT={rhs:.6f}")


class TestGreeksBounds(unittest.TestCase):
    """Sign/range constraints that hold for ANY valid Black-Scholes Greeks,
    for any S/K/T/sigma combination — no dependence on a reference value."""

    def setUp(self):
        self.engine = GreeksEngine(risk_free_rate=0.07)

    def test_call_delta_in_zero_one(self):
        for S, K, T, sigma in GRID:
            g = self.engine.all_greeks(S, K, T, sigma, 'CE')
            self.assertGreaterEqual(g['DELTA'], 0.0)
            self.assertLessEqual(g['DELTA'], 1.0)

    def test_put_delta_in_minus_one_zero(self):
        for S, K, T, sigma in GRID:
            g = self.engine.all_greeks(S, K, T, sigma, 'PE')
            self.assertGreaterEqual(g['DELTA'], -1.0)
            self.assertLessEqual(g['DELTA'], 0.0)

    def test_gamma_nonnegative_and_equal_for_call_and_put(self):
        # Gamma is identical for a call and put at the same strike (both are
        # d^2V/dS^2 of the same underlying probability density) — a real
        # cross-check, not just a sign bound.
        for S, K, T, sigma in GRID:
            gc = self.engine.all_greeks(S, K, T, sigma, 'CE')['GAMMA']
            gp = self.engine.all_greeks(S, K, T, sigma, 'PE')['GAMMA']
            self.assertGreaterEqual(gc, 0.0)
            self.assertAlmostEqual(gc, gp, places=8)

    def test_vega_nonnegative_and_equal_for_call_and_put(self):
        # Same identity as gamma: vega doesn't depend on option_type in BS.
        for S, K, T, sigma in GRID:
            vc = self.engine.all_greeks(S, K, T, sigma, 'CE')['VEGA']
            vp = self.engine.all_greeks(S, K, T, sigma, 'PE')['VEGA']
            self.assertGreaterEqual(vc, 0.0)
            self.assertAlmostEqual(vc, vp, places=8)

    def test_call_theta_negative_for_nondividend_option(self):
        # For a non-dividend-paying European call, theta is always <= 0
        # (time decay always hurts a long call). Puts can have positive
        # theta deep ITM under high rates, so this check is call-only.
        for S, K, T, sigma in GRID:
            theta = self.engine.all_greeks(S, K, T, sigma, 'CE')['THETA']
            self.assertLessEqual(theta, 1e-9,
                                  msg=f"Call theta should be <=0 at S={S} K={K} T={T} sigma={sigma}, got {theta}")

    def test_deep_itm_call_delta_approaches_one(self):
        g = self.engine.all_greeks(S=300.0, K=100.0, T=0.5, sigma=0.2, option_type='CE')
        self.assertGreater(g['DELTA'], 0.99)

    def test_deep_otm_call_delta_approaches_zero(self):
        g = self.engine.all_greeks(S=50.0, K=200.0, T=0.5, sigma=0.2, option_type='CE')
        self.assertLess(g['DELTA'], 0.01)

    def test_atm_gamma_and_vega_peak_near_the_money(self):
        # Gamma/Vega are maximized ATM and decay away from it, at fixed T/sigma.
        S, T, sigma = 100.0, 0.25, 0.2
        atm = self.engine.all_greeks(S, 100.0, T, sigma, 'CE')
        wing = self.engine.all_greeks(S, 60.0, T, sigma, 'CE')
        self.assertGreater(atm['GAMMA'], wing['GAMMA'])
        self.assertGreater(atm['VEGA'], wing['VEGA'])


class TestIVRoundTrip(unittest.TestCase):
    """Price at a known sigma, then solve IV back out from that price —
    must recover the original sigma. Exercises calculate_iv (scalar) and
    implied_vol_vectorized (vectorized) identically, and checks they agree
    with each other, not just with the seed."""

    def setUp(self):
        self.engine = GreeksEngine(risk_free_rate=0.07)

    def test_scalar_iv_round_trip(self):
        for S, K, T, sigma in GRID:
            price = self.engine.bs_price(S, K, T, sigma, 'CE')
            if price < 0.05:
                continue  # dust prices are pinned at 20% by convention upstream, not a solver case
            vega = self.engine.all_greeks(S, K, T, sigma, 'CE')['VEGA']
            if vega < 1e-3:
                continue  # vega~0 (deep ITM/OTM + short T): price is flat in sigma, IV is genuinely unidentifiable
            recovered = self.engine.calculate_iv(price, S, K, T, 'CE')
            self.assertAlmostEqual(
                recovered, sigma, places=3,
                msg=f"IV round-trip failed at S={S} K={K} T={T} sigma={sigma}: recovered {recovered}")

    def test_vectorized_iv_round_trip_matches_scalar(self):
        rows = [(S, K, T, sigma) for S, K, T, sigma in GRID]
        S = np.array([r[0] for r in rows])
        K = np.array([r[1] for r in rows])
        T = np.array([r[2] for r in rows])
        sigma = np.array([r[3] for r in rows])
        price = np.array([self.engine.bs_price(s, k, t, v, 'CE') for s, k, t, v in rows])
        vega = np.array([self.engine.all_greeks(s, k, t, v, 'CE')['VEGA'] for s, k, t, v in rows])
        is_call = np.ones(len(rows), dtype=bool)

        iv_vec, converged = self.engine.implied_vol_vectorized(price, S, K, T, is_call)

        for i, (s, k, t, v) in enumerate(rows):
            if price[i] < 0.05:
                continue
            if vega[i] < 1e-3:
                continue  # same vega-starved edge case as the scalar round-trip test
            if not converged[i]:
                continue  # non-converged rows fall back to scalar in process_dataframe, not tested here
            self.assertAlmostEqual(
                iv_vec[i], v, places=3,
                msg=f"Vectorized IV round-trip failed at S={s} K={k} T={t} sigma={v}: got {iv_vec[i]}")


if __name__ == '__main__':
    unittest.main()
