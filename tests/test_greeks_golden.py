"""
Golden-snapshot regression test for GreeksEngine.process_dataframe.

Freezes the actual output (IV + all Greeks) computed from a REAL NSE F&O
bhavcopy (2026-07-31, NIFTY + TCS) as a checked-in fixture. If a future
change to greeks.py — or anything upstream it depends on (normalize.py's
column mapping, T calculation, row-selection filters) — silently shifts
these numbers, this test catches it immediately, even though the shift
might still pass the invariant tests (test_greeks_invariants.py) and even
the py_vollib cross-check (scripts/verify_greeks_vs_pyvollib.py) if the
new formula happens to also be internally consistent and correct in
isolation but different from what production has been shipping.

To intentionally update the golden file after a deliberate, reviewed
formula change, regenerate it:
    python3 -c "
    import json, pandas as pd
    from vanguard.engines.greeks import GreeksEngine
    from vanguard.pipeline.normalize import DataProcessor
    dp = DataProcessor()
    df_options, df_futures = dp.normalize('tests/fixtures/golden_bhavcopy_20260731_sample.csv')
    spots = dp.get_spot_prices(pd.concat([df_options, df_futures], ignore_index=True))
    out = GreeksEngine(risk_free_rate=0.07).process_dataframe(df_options, spots, iv_method='vectorized')
    out = out.sort_values(['SYMBOL','STRIKE_PR','OPTION_TYP','EXPIRY_DT']).reset_index(drop=True)
    out['EXPIRY_DT'] = out['EXPIRY_DT'].astype(str)
    cols = ['SYMBOL','STRIKE_PR','OPTION_TYP','EXPIRY_DT','IV','DELTA','GAMMA','VEGA','THETA','VANNA','CHARM']
    json.dump({'spot_prices': spots, 'rows': out[cols].to_dict('records')},
               open('tests/fixtures/golden_greeks_20260731.json', 'w'), indent=1)
    "
"""
import json
import unittest
from pathlib import Path

import pandas as pd

from vanguard.engines.greeks import GreeksEngine
from vanguard.pipeline.normalize import DataProcessor

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BHAVCOPY = FIXTURES / "golden_bhavcopy_20260731_sample.csv"
GOLDEN = FIXTURES / "golden_greeks_20260731.json"

NUMERIC_COLS = ['IV', 'DELTA', 'GAMMA', 'VEGA', 'THETA', 'VANNA', 'CHARM']
TOL = 1e-8  # deterministic computation on frozen input — should match near-exactly


class TestGreeksGoldenSnapshot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(GOLDEN) as f:
            golden = json.load(f)
        cls.golden_rows = pd.DataFrame(golden['rows'])
        cls.golden_spots = golden['spot_prices']

        dp = DataProcessor()
        df_options, df_futures = dp.normalize(str(BHAVCOPY))
        full_df = pd.concat([df_options, df_futures], ignore_index=True)
        cls.spots = dp.get_spot_prices(full_df)

        engine = GreeksEngine(risk_free_rate=0.07)
        out = engine.process_dataframe(df_options, cls.spots, iv_method="vectorized")
        out = out.sort_values(['SYMBOL', 'STRIKE_PR', 'OPTION_TYP', 'EXPIRY_DT']).reset_index(drop=True)
        out['EXPIRY_DT'] = out['EXPIRY_DT'].astype(str)
        cls.actual_rows = out[['SYMBOL', 'STRIKE_PR', 'OPTION_TYP', 'EXPIRY_DT'] + NUMERIC_COLS]

    def test_spot_prices_unchanged(self):
        self.assertEqual(self.spots, self.golden_spots)

    def test_row_count_unchanged(self):
        self.assertEqual(len(self.actual_rows), len(self.golden_rows),
                          "Row-selection (near-spot filter / top-OI wall candidates) changed — "
                          "verify this is an intentional change before regenerating the golden file.")

    def test_row_identity_unchanged(self):
        key_cols = ['SYMBOL', 'STRIKE_PR', 'OPTION_TYP', 'EXPIRY_DT']
        actual_keys = set(map(tuple, self.actual_rows[key_cols].values))
        golden_keys = set(map(tuple, self.golden_rows[key_cols].values))
        self.assertEqual(actual_keys, golden_keys,
                          "The set of (symbol, strike, type, expiry) rows shipped by process_dataframe "
                          "changed — check the 15%-distance filter / wall-candidate logic.")

    def test_iv_and_greeks_match_golden(self):
        merged = self.actual_rows.merge(
            self.golden_rows, on=['SYMBOL', 'STRIKE_PR', 'OPTION_TYP', 'EXPIRY_DT'],
            suffixes=('_actual', '_golden'),
        )
        self.assertEqual(len(merged), len(self.actual_rows), "Merge dropped rows — key mismatch, see other tests.")
        for col in NUMERIC_COLS:
            diff = (merged[f'{col}_actual'] - merged[f'{col}_golden']).abs()
            self.assertLess(
                diff.max(), TOL,
                msg=f"{col} drifted from the golden snapshot: max|diff|={diff.max():.2e} "
                    f"at row {merged.loc[diff.idxmax(), ['SYMBOL', 'STRIKE_PR', 'OPTION_TYP', 'EXPIRY_DT']].to_dict()}")


if __name__ == '__main__':
    unittest.main()
