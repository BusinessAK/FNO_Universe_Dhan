"""
Regression: intelligence.py's get_detailed_metrics must OI-weight IV rather
than averaging it unweighted across every included strike.

get_detailed_metrics is a closure nested inside analyze_market_structure, so
this exercises it through the real entry point with tiny synthetic bhavcopy
CSVs (NIFTY-dust-dilution shape: a couple of liquid, high-OI strikes at a
real solved IV, plus a pile of low-OI near-worthless strikes that fall back
to the hardcoded 0.20 IV) rather than depending on today's live market data.
"""
import os
import sys
from datetime import datetime

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.intelligence import InstitutionalIntelligence

SYMBOL = "TESTCO"
SPOT = 100.0
EXPIRY = "2026-09-24"


def _row(strike, opt_type, close, open_int, chg_in_oi=0, volume=10, trade_date="2026-07-15"):
    return {
        "TradDt": trade_date, "BizDt": trade_date, "Sgmt": "FO", "Src": "NSE",
        "FinInstrmTp": "STO", "FinInstrmId": 1, "ISIN": None,
        "TckrSymb": SYMBOL, "SctySrs": None, "XpryDt": EXPIRY,
        "FininstrmActlXpryDt": EXPIRY, "StrkPric": strike, "OptnTp": opt_type,
        "FinInstrmNm": f"{SYMBOL}{opt_type}{strike}", "OpnPric": close, "HghPric": close,
        "LwPric": close, "ClsPric": close, "LastPric": close, "PrvsClsgPric": close,
        "UndrlygPric": SPOT, "SttlmPric": close, "OpnIntrst": open_int,
        "ChngInOpnIntrst": chg_in_oi, "TtlTradgVol": volume, "TtlTrfVal": 0,
        "TtlNbOfTxsExctd": 1, "SsnId": "F1", "NewBrdLotQty": 1000,
        "Rmks": None, "Rsvd1": None, "Rsvd2": None, "Rsvd3": None, "Rsvd4": None,
    }


def _chain(strikes_and_oi, opt_type, dust_strikes, dust_oi=50):
    """A couple of liquid ATM/near-ATM strikes at a solvable price, plus a pile
    of near-worthless dust strikes (price < 0.05) that trip the 0.20 IV
    fallback in GreeksEngine — the exact shape that dilutes an unweighted mean."""
    rows = [_row(k, opt_type, close, oi) for k, close, oi in strikes_and_oi]
    rows += [_row(k, opt_type, 0.02, dust_oi) for k in dust_strikes]
    return rows


def _build_bhavcopy(path):
    # Liquid strike prices below are Black-Scholes prices at sigma=0.12 (spot
    # 100, r=0.07, T~71 days) — verified via GreeksEngine.bs_price so the
    # "real" IV in this fixture is known and clearly distinct from the 0.20
    # dust fallback, rather than an arbitrary guessed price.
    rows = (
        _chain([(100.0, 2.8421, 100_000), (102.0, 1.8219, 60_000)], "CE",
               dust_strikes=[104, 105, 106, 107, 108, 109, 110, 111])
        + _chain([(100.0, 1.4897, 90_000), (98.0, 0.8232, 50_000)], "PE",
                 dust_strikes=[96, 95, 94, 93, 92, 91, 90, 89])
    )
    pd.DataFrame(rows).to_csv(path, index=False)


class TestIvWeighting:
    def test_iv_is_oi_weighted_not_diluted_by_dust(self, tmp_path):
        f_t = tmp_path / "bhav_t.csv"
        f_tm1 = tmp_path / "bhav_tm1.csv"
        _build_bhavcopy(f_t)
        _build_bhavcopy(f_tm1)

        result = InstitutionalIntelligence().analyze_market_structure(str(f_t), str(f_tm1))
        row = result[result.SYMBOL == SYMBOL].iloc[0]

        # The dust strikes (8 per side, price < 0.05) all fall back to IV=0.20,
        # heavily outnumbering the 2 liquid strikes per side. An unweighted mean
        # would land close to 0.20; the OI-weighted mean must stay close to the
        # liquid strikes' real, much-lower solved IV instead.
        assert row["IV_CE_T"] < 0.15, (
            f"IV_CE_T={row['IV_CE_T']:.3f} looks pulled toward the 0.20 dust "
            f"fallback — IV aggregation may not be OI-weighted"
        )
        assert row["IV_PE_T"] < 0.15, f"IV_PE_T={row['IV_PE_T']:.3f} looks dust-diluted"
