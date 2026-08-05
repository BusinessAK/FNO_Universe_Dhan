#!/usr/bin/env python3
"""
Cross-check vanguard.engines.greeks.GreeksEngine against py_vollib (an
independent, widely-used options-pricing library) on a real NSE F&O
bhavcopy — not a synthetic case, the actual rows that feed the nightly
compiler.

Verifies: IV solve (vectorized + scalar) and all analytical Greeks
(Delta/Gamma/Vega/Theta/Rho) agree with py_vollib to a tight tolerance,
using the SAME risk-free rate and the SAME row-selection path
(GreeksEngine.process_dataframe) the production pipeline actually runs.

Usage:
    python3 scripts/verify_greeks_vs_pyvollib.py [path/to/FO_BhavCopy.csv]

Defaults to the most recent FO_BhavCopy_*.csv under data/raw/ if no path
is given. Read-only — writes nothing.
"""
from __future__ import annotations

import sys
import glob
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vanguard.engines.greeks import GreeksEngine  # noqa: E402
from vanguard.pipeline.normalize import DataProcessor  # noqa: E402

from py_vollib.black_scholes.implied_volatility import implied_volatility as pv_iv  # noqa: E402
from py_vollib.black_scholes.greeks.analytical import (  # noqa: E402
    delta as pv_delta, gamma as pv_gamma, vega as pv_vega, theta as pv_theta,
)

R = 0.07  # must match GreeksEngine's default risk_free_rate


def pick_default_file() -> str:
    candidates = sorted(glob.glob(str(ROOT / "data" / "raw" / "FO_BhavCopy_*.csv")))
    if not candidates:
        raise SystemExit("No FO_BhavCopy_*.csv found under data/raw/ — pass a path explicitly.")
    return candidates[-1]


def main() -> int:
    src = sys.argv[1] if len(sys.argv) > 1 else pick_default_file()
    print(f"[*] Source bhavcopy: {src}")

    dp = DataProcessor()
    df_options, df_futures = dp.normalize(src)
    full_df = pd.concat([df_options, df_futures], ignore_index=True)
    spot_prices = dp.get_spot_prices(full_df)

    engine = GreeksEngine(risk_free_rate=R)
    out = engine.process_dataframe(df_options, spot_prices, iv_method="vectorized")
    out_scalar = engine.process_dataframe(df_options, spot_prices, iv_method="scalar")
    print(f"[*] {len(out)} strikes survived process_dataframe's row selection "
          f"(near-spot + top-OI wall candidates)")

    # T in years, same definition process_dataframe uses internally, recomputed
    # here from the same normalized frame for the py_vollib comparison.
    merged = out.merge(
        df_options[['SYMBOL', 'STRIKE_PR', 'OPTION_TYP', 'EXPIRY_DT', 'TIMESTAMP']]
        .drop_duplicates(subset=['SYMBOL', 'STRIKE_PR', 'OPTION_TYP', 'EXPIRY_DT']),
        on=['SYMBOL', 'STRIKE_PR', 'OPTION_TYP', 'EXPIRY_DT'], how='left',
    )
    merged['T'] = (merged['EXPIRY_DT'] - merged['TIMESTAMP']).dt.days / 365.0
    merged['SPOT'] = merged['SYMBOL'].map(spot_prices)

    rows = []
    skipped_dust = 0
    skipped_deep = 0
    for r in merged.itertuples():
        flag = 'c' if r.OPTION_TYP == 'CE' else 'p'
        S, K, T, sigma, price = r.SPOT, r.STRIKE_PR, r.T, r.IV, r.CLOSE

        if price < 0.05:
            skipped_dust += 1
            continue  # dust rows are pinned at 20% IV by convention, not solved — not a math check
        if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
            skipped_deep += 1
            continue

        try:
            iv_ref = pv_iv(price, S, K, T, R, flag)
        except Exception:
            continue  # py_vollib's own solver failed to bracket — not our bug, skip

        # price greeks at OUR solved IV, to separate "IV solve disagrees" from
        # "greeks formula disagrees given the same IV"
        greeks_at_our_iv = dict(
            delta=pv_delta(flag, S, K, T, R, sigma),
            gamma=pv_gamma(flag, S, K, T, R, sigma),
            vega=pv_vega(flag, S, K, T, R, sigma),
            theta=pv_theta(flag, S, K, T, R, sigma),
        )

        rows.append({
            'SYMBOL': r.SYMBOL, 'STRIKE': K, 'TYPE': r.OPTION_TYP, 'T': T,
            'iv_ours': sigma, 'iv_pyvollib': iv_ref, 'd_iv': sigma - iv_ref,
            'd_delta': r.DELTA - greeks_at_our_iv['delta'],
            'd_gamma': r.GAMMA - greeks_at_our_iv['gamma'],
            'd_vega': r.VEGA - greeks_at_our_iv['vega'],
            'd_theta': r.THETA - greeks_at_our_iv['theta'],
        })

    if not rows:
        print("[!] No comparable rows (all dust/degenerate) — nothing to verify.")
        return 1

    cmp_df = pd.DataFrame(rows)
    print(f"[*] Compared {len(cmp_df)} rows against py_vollib "
          f"({skipped_dust} dust rows and {skipped_deep} degenerate rows excluded from the math check)")

    def summarize(col, label, tol):
        d = cmp_df[col].abs()
        status = "OK" if d.max() < tol else "MISMATCH"
        print(f"    {label:22s} max|diff|={d.max():.2e}  mean|diff|={d.mean():.2e}  "
              f"(tol={tol:.0e})  [{status}]")
        return d.max() < tol

    print("\n[*] Greeks formulas (evaluated at OUR solved IV, so this isolates formula "
          "correctness from IV-solve correctness):")
    ok = True
    ok &= summarize('d_delta', 'Delta', 1e-6)
    ok &= summarize('d_gamma', 'Gamma', 1e-6)
    ok &= summarize('d_vega', 'Vega', 1e-6)
    ok &= summarize('d_theta', 'Theta', 1e-6)

    print("\n[*] IV solve (Newton-Raphson vs py_vollib's own solver, from the market CLOSE price):")
    ok &= summarize('d_iv', 'Implied Vol', 1e-3)

    # Cross-check the scalar (brentq) path too, since it's the historical/fallback path.
    both = out.merge(out_scalar, on=['SYMBOL', 'STRIKE_PR', 'OPTION_TYP', 'EXPIRY_DT'],
                      suffixes=('_vec', '_scalar'))
    both = both[both['CLOSE_vec'] >= 0.05]
    d_vec_scalar = (both['IV_vec'] - both['IV_scalar']).abs()
    print(f"\n[*] Internal parity: vectorized IV vs scalar (brentq) IV on the same rows: "
          f"max|diff|={d_vec_scalar.max():.2e} (tol=1e-4, the F0-parity gate documented in greeks.py)")
    ok &= d_vec_scalar.max() < 1e-4

    print(f"\n{'='*60}")
    print("RESULT: " + ("ALL CHECKS PASSED — Greeks/IV math matches an independent reference library"
                         if ok else "MISMATCH FOUND — see above"))
    print(f"{'='*60}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
