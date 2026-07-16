"""Unit tests for src/intelligence.InstitutionalIntelligence.classify_oi_flow."""
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.intelligence import InstitutionalIntelligence

classify = InstitutionalIntelligence.classify_oi_flow
verified_flow = InstitutionalIntelligence.verified_oi_flow


def _leg(strike, opt_typ, close, prev_close, oi, chg_in_oi, volume=100, symbol="TEST"):
    return {
        "SYMBOL": symbol,
        "OPTION_TYP": opt_typ,
        "STRIKE_PR": strike,
        "CLOSE": close,
        "PREV_CLOSE": prev_close,
        "OPEN_INT": oi,
        "CHG_IN_OI": chg_in_oi,
        "VOLUME": volume,
    }


def _chain(legs, filler_oi=100_000):
    """Legs plus an inert strike, so chain OI is realistic and quiet-band tests are explicit."""
    base = [_leg(500, "CE", 10.0, 10.0, filler_oi, 0, volume=0),
            _leg(500, "PE", 10.0, 10.0, filler_oi, 0, volume=0)]
    return pd.DataFrame(base + legs)


class TestFourStateMatrix:
    def test_oi_up_premium_up_is_long_buildup(self):
        df = _chain([_leg(600, "PE", 12.0, 9.0, 50_000, 40_000)])
        assert classify(df).loc["TEST", "PE_INTERP"] == "Put Buying (Long Build-up)"

    def test_oi_up_premium_down_is_short_buildup(self):
        df = _chain([_leg(600, "PE", 9.0, 12.0, 50_000, 40_000)])
        assert classify(df).loc["TEST", "PE_INTERP"] == "Put Writing (Short Build-up)"

    def test_oi_down_premium_down_is_long_unwinding(self):
        df = _chain([_leg(600, "CE", 9.0, 12.0, 50_000, -40_000)])
        assert classify(df).loc["TEST", "CE_INTERP"] == "Long Unwinding"

    def test_oi_down_premium_up_is_short_covering(self):
        df = _chain([_leg(600, "CE", 12.0, 9.0, 50_000, -40_000)])
        assert classify(df).loc["TEST", "CE_INTERP"] == "Short Covering"


class TestSpotIndependence:
    """The classifier must read the option's premium, never the underlying's move."""

    def test_falling_premium_on_oi_build_is_writing_regardless_of_spot(self):
        # The case the old spot-proxy got wrong: puts gaining OI while their premium
        # falls (IV collapsing faster than spot drops) is writing, not buying.
        df = _chain([_leg(600, "PE", 8.0, 14.0, 50_000, 40_000)])
        assert classify(df).loc["TEST", "PE_INTERP"] == "Put Writing (Short Build-up)"

    def test_no_underlying_column_required(self):
        df = _chain([_leg(600, "PE", 12.0, 9.0, 50_000, 40_000)])
        assert "SPOT_PRICE" not in df.columns
        classify(df)  # must not raise


class TestNeutralAndChurn:
    def test_heavy_two_way_flow_netting_flat_is_churn_not_direction(self):
        # Gross 80k on a 200k chain, but nets to zero: no direction to report.
        df = _chain([
            _leg(600, "CE", 12.0, 9.0, 50_000, 40_000),
            _leg(700, "CE", 9.0, 12.0, 50_000, -40_000),
        ])
        assert classify(df).loc["TEST", "CE_INTERP"] == "Two-Sided Churn"

    def test_barely_traded_chain_is_neutral(self):
        # Gross 100 against a 200k chain is far below the quiet band.
        df = _chain([_leg(600, "CE", 12.0, 9.0, 50_000, 100)])
        assert classify(df).loc["TEST", "CE_INTERP"] == "Neutral"

    def test_split_premium_vote_is_mixed(self):
        # Equal OI added at rising and falling premium: no majority either way.
        df = _chain([
            _leg(600, "CE", 12.0, 9.0, 50_000, 40_000),
            _leg(700, "CE", 9.0, 12.0, 50_000, 40_000),
        ])
        assert classify(df).loc["TEST", "CE_INTERP"] == "Mixed Build-up"


class TestRobustness:
    def test_untraded_strike_does_not_vote(self):
        # A stale far-month strike with a garbage previous close must not outvote
        # the liquid body of the chain just because its "premium change" is huge.
        df = _chain([
            _leg(600, "PE", 12.0, 9.0, 50_000, 40_000, volume=500),
            _leg(900, "PE", 34.0, 81.0, 1_000, 30_000, volume=0),
        ])
        assert classify(df).loc["TEST", "PE_INTERP"] == "Put Buying (Long Build-up)"

    def test_one_illiquid_leg_cannot_outvote_by_magnitude(self):
        # Votes are weighted by OI, not by the size of the premium move.
        df = _chain([
            _leg(600, "PE", 12.0, 9.0, 50_000, 40_000, volume=500),
            _leg(900, "PE", 34.0, 81.0, 5_000, 2_000, volume=5),
        ])
        assert classify(df).loc["TEST", "PE_INTERP"] == "Put Buying (Long Build-up)"

    def test_symbol_with_only_calls_still_reports_both_columns(self):
        df = pd.DataFrame([_leg(600, "CE", 12.0, 9.0, 50_000, 40_000)])
        out = classify(df)
        assert out.loc["TEST", "CE_INTERP"] == "Call Buying (Long Build-up)"
        assert out.loc["TEST", "PE_INTERP"] == "Neutral"

    def test_missing_premium_column_raises(self):
        df = _chain([_leg(600, "CE", 12.0, 9.0, 50_000, 40_000)]).drop(columns=["PREV_CLOSE"])
        with pytest.raises(KeyError, match="PREV_CLOSE"):
            classify(df)

    def test_symbols_are_classified_independently(self):
        df = pd.DataFrame([
            _leg(600, "PE", 12.0, 9.0, 50_000, 40_000, symbol="BULLS"),
            _leg(600, "PE", 9.0, 12.0, 50_000, 40_000, symbol="BEARS"),
        ])
        out = classify(df)
        assert out.loc["BULLS", "PE_INTERP"] == "Put Buying (Long Build-up)"
        assert out.loc["BEARS", "PE_INTERP"] == "Put Writing (Short Build-up)"


class TestVerifiedOiFlowEightStates:
    """verified_oi_flow collapses to sign(premium_chg), flipped for puts,
    independent of OI direction — verified against all 8 CE/PE x
    OI-direction x premium-direction combinations before being shipped.
    """

    def test_ce_buying_oi_up_premium_up_is_bullish(self):
        df = _chain([_leg(600, "CE", 12.0, 9.0, 50_000, 40_000)])
        assert verified_flow(df).loc["TEST", "VERIFIED_CE_FLOW"] == 40_000

    def test_ce_writing_oi_up_premium_down_is_bearish(self):
        df = _chain([_leg(600, "CE", 9.0, 12.0, 50_000, 40_000)])
        assert verified_flow(df).loc["TEST", "VERIFIED_CE_FLOW"] == -40_000

    def test_ce_long_unwind_oi_down_premium_down_is_bearish(self):
        # Call buyers abandoning a bullish bet as it decays — bearish, not bullish.
        df = _chain([_leg(600, "CE", 9.0, 12.0, 50_000, -40_000)])
        assert verified_flow(df).loc["TEST", "VERIFIED_CE_FLOW"] == -40_000

    def test_ce_short_covering_oi_down_premium_up_is_bullish(self):
        # Call writers forced to cover as spot rallies past them — bullish.
        df = _chain([_leg(600, "CE", 12.0, 9.0, 50_000, -40_000)])
        assert verified_flow(df).loc["TEST", "VERIFIED_CE_FLOW"] == 40_000

    def test_pe_buying_oi_up_premium_up_is_bearish(self):
        df = _chain([_leg(600, "PE", 12.0, 9.0, 50_000, 40_000)])
        assert verified_flow(df).loc["TEST", "VERIFIED_PE_FLOW"] == -40_000

    def test_pe_writing_oi_up_premium_down_is_bullish(self):
        df = _chain([_leg(600, "PE", 9.0, 12.0, 50_000, 40_000)])
        assert verified_flow(df).loc["TEST", "VERIFIED_PE_FLOW"] == 40_000

    def test_pe_long_unwind_oi_down_premium_down_is_bullish(self):
        # Put buyers abandoning a bearish bet as it decays — bullish, not bearish.
        df = _chain([_leg(600, "PE", 9.0, 12.0, 50_000, -40_000)])
        assert verified_flow(df).loc["TEST", "VERIFIED_PE_FLOW"] == 40_000

    def test_pe_short_covering_oi_down_premium_up_is_bearish(self):
        # Put writers forced to cover as spot falls through their floor — bearish.
        df = _chain([_leg(600, "PE", 12.0, 9.0, 50_000, -40_000)])
        assert verified_flow(df).loc["TEST", "VERIFIED_PE_FLOW"] == -40_000


class TestVerifiedOiFlowProperties:
    def test_flat_premium_contributes_zero(self):
        df = _chain([_leg(600, "CE", 10.0, 10.0, 50_000, 40_000)])
        assert verified_flow(df).loc["TEST", "VERIFIED_CE_FLOW"] == 0.0

    def test_untraded_strike_excluded_like_classify_oi_flow(self):
        df = _chain([_leg(600, "CE", 12.0, 9.0, 50_000, 40_000, volume=0)])
        assert verified_flow(df).loc["TEST", "VERIFIED_CE_FLOW"] == 0.0

    def test_two_way_churn_cancels_via_per_strike_sign_not_a_special_case(self):
        # Equal-and-opposite bullish/bearish legs: should net near zero on their
        # own, with no churn-detection branch needed (unlike classify_oi_flow).
        df = _chain([
            _leg(600, "CE", 12.0, 9.0, 50_000, 40_000),   # bullish +40k
            _leg(700, "CE", 9.0, 12.0, 50_000, 40_000),   # bearish -40k
        ])
        assert verified_flow(df).loc["TEST", "VERIFIED_CE_FLOW"] == 0.0

    def test_partial_conviction_nets_proportionally_not_binary(self):
        # 60k bullish vs 40k bearish should net +20k, not collapse to a label.
        df = _chain([
            _leg(600, "CE", 12.0, 9.0, 60_000, 60_000),
            _leg(700, "CE", 9.0, 12.0, 40_000, 40_000),
        ])
        assert verified_flow(df).loc["TEST", "VERIFIED_CE_FLOW"] == 20_000

    def test_missing_column_raises(self):
        df = _chain([_leg(600, "CE", 12.0, 9.0, 50_000, 40_000)]).drop(columns=["PREV_CLOSE"])
        with pytest.raises(KeyError, match="PREV_CLOSE"):
            verified_flow(df)

    def test_symbol_with_only_calls_still_reports_both_columns(self):
        df = pd.DataFrame([_leg(600, "CE", 12.0, 9.0, 50_000, 40_000)])
        out = verified_flow(df)
        assert out.loc["TEST", "VERIFIED_CE_FLOW"] == 40_000
        assert out.loc["TEST", "VERIFIED_PE_FLOW"] == 0.0


class TestRealBhavcopyRow:
    """Regression: the SONACOMS 2026-07-14 row that exposed the spot-proxy bug."""

    BHAV = "data/raw/FO_BhavCopy_NSE_FO_0_0_0_20260714_F_0000.csv"

    @pytest.mark.skipif(not os.path.exists(BHAV), reason="bhavcopy not present")
    def test_sonacoms_put_buying_confirmed_from_premium(self):
        from src.processor import DataProcessor

        df_t, _ = DataProcessor().normalize(self.BHAV)
        out = classify(df_t)
        # 403,025 of the added put OI went on at strikes where the premium rose,
        # against 2,450 where it fell — a genuine long build-up.
        assert out.loc["SONACOMS", "PE_INTERP"] == "Put Buying (Long Build-up)"
        # Calls churned 401,800 gross but netted only -31,850 (7.9%): no direction.
        assert out.loc["SONACOMS", "CE_INTERP"] == "Two-Sided Churn"

    @pytest.mark.skipif(not os.path.exists(BHAV), reason="bhavcopy not present")
    def test_sonacoms_verified_flow_is_net_bearish_not_bullish(self):
        # The raw OI delta (CHG_IN_OI_PE_T=+305,025) looks bullish under the old
        # "rising PE OI = written puts" assumption. Verified flow correctly reads
        # it as net bearish, since the added PE OI was bought, not written.
        from src.processor import DataProcessor

        df_t, _ = DataProcessor().normalize(self.BHAV)
        out = verified_flow(df_t)
        row = out.loc["SONACOMS"]
        assert row["VERIFIED_PE_FLOW"] < 0
        assert (row["VERIFIED_PE_FLOW"] + row["VERIFIED_CE_FLOW"]) < 0
