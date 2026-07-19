"""Unit tests for vanguard/core/playbook.build_playbook (extracted from daily_compiler)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vanguard.core.playbook import build_playbook


def _build(**overrides):
    """Calls build_playbook with neutral defaults, overriding only what a test cares about."""
    kwargs = dict(
        setups=[],
        spot_t=100.0,
        call_wall_t=105.0,
        put_wall_t=95.0,
        gamma_flip_t=100.0,
        call_wall_tm1=105.0,
        put_wall_tm1=95.0,
        ifs_final=0.0,
        gamma_regime="LONG_GAMMA",
        spot_chg=0.0,
        skew_slope=1.0,
        base_strategy="Wait for Setup",
    )
    kwargs.update(overrides)
    return build_playbook(**kwargs)


class TestInventoryMigration:
    def test_dual_wall_up_with_flow_is_strong_bullish(self):
        pb, strat = _build(
            setups=["INVENTORY_MIGRATION"],
            put_wall_t=97.0, put_wall_tm1=95.0,
            call_wall_t=107.0, call_wall_tm1=105.0,
            ifs_final=25.0,
        )
        assert pb["bias"] == "Strong Bullish Momentum"
        assert pb["trigger_strike"] == 107.0
        assert pb["invalidation_strike"] == 97.0
        assert strat == "Bull Call Spread (Debit)"

    def test_dual_wall_up_with_bearish_flow_is_trap(self):
        pb, strat = _build(
            setups=["INVENTORY_MIGRATION"],
            put_wall_t=97.0, put_wall_tm1=95.0,
            call_wall_t=107.0, call_wall_tm1=105.0,
            ifs_final=-20.0,
        )
        assert pb["bias"] == "Bullish Trap (Divergence)"
        assert strat == "Wait for Setup"

    def test_put_wall_drop_above_spot_is_normalization_not_breakdown(self):
        pb, strat = _build(
            setups=["INVENTORY_MIGRATION"],
            spot_t=100.0, spot_chg=1.0,
            put_wall_t=93.0, put_wall_tm1=95.0,
        )
        assert pb["bias"] == "Support Normalization"
        assert strat == "Bull Put Spread (Credit)"

    def test_put_wall_drop_below_spot_is_bearish_breakdown(self):
        pb, strat = _build(
            setups=["INVENTORY_MIGRATION"],
            spot_t=90.0, spot_chg=-2.0,
            put_wall_t=93.0, put_wall_tm1=95.0,
            ifs_final=-5.0,
        )
        assert pb["bias"] == "Bearish Breakdown"
        assert strat == "Bear Put Spread (Debit)"


class TestFloorBounceFlowGate:
    """A put wall is only a floor worth selling if the OI there was written."""

    def test_written_put_wall_still_sells_the_floor(self):
        _, strat = _build(setups=["FLOOR_BOUNCE"], pe_interp="Put Writing (Short Build-up)")
        assert strat == "Bull Put Spread (Credit)"

    def test_bought_put_wall_suppresses_the_credit_spread(self):
        # The SONACOMS 2026-07-14 shape: FLOOR_BOUNCE fires, but the put OI at the
        # wall was bought, so there is no written floor to sell.
        _, strat = _build(setups=["FLOOR_BOUNCE"], pe_interp="Put Buying (Long Build-up)")
        assert strat == "Wait for Setup"

    def test_unknown_flow_preserves_flow_blind_behaviour(self):
        _, strat = _build(setups=["FLOOR_BOUNCE"])
        assert strat == "Bull Put Spread (Credit)"

    def test_churn_does_not_suppress(self):
        # Only an affirmative buying read disqualifies the floor; absence of
        # conviction is not evidence against it.
        _, strat = _build(setups=["FLOOR_BOUNCE"], pe_interp="Two-Sided Churn")
        assert strat == "Bull Put Spread (Credit)"

    def test_gate_does_not_touch_other_setups(self):
        _, strat = _build(setups=["GAMMA_SQUEEZE"], pe_interp="Put Buying (Long Build-up)")
        assert strat == "ATM Option Buying (Call)"

    def test_range_shift_degenerate_walls_widened(self):
        # No individual migration pattern matches (tm1 walls are 0) -> Range Shift.
        # trigger (call wall) == invalidation (put wall) triggers the 2% widen guard.
        pb, _ = _build(
            setups=["INVENTORY_MIGRATION"],
            call_wall_t=100.0, put_wall_t=100.0,
            call_wall_tm1=0.0, put_wall_tm1=0.0,
        )
        assert pb["bias"] == "Range Shift"
        assert pb["trigger_strike"] == 100.0
        assert pb["invalidation_strike"] == 98.0


class TestPinchZone:
    def test_spot_above_flip_is_bullish_watch(self):
        pb, strat = _build(setups=["PINCH_ZONE"], spot_t=101.0, gamma_flip_t=100.0)
        assert "Bullish Breakout Watch" in pb["bias"]
        assert strat == "Bull Call Spread (Debit)"

    def test_spot_below_flip_is_bearish_watch(self):
        pb, strat = _build(setups=["PINCH_ZONE"], spot_t=99.0, gamma_flip_t=100.0)
        assert "Bearish Breakdown Watch" in pb["bias"]
        assert strat == "Bear Put Spread (Debit)"


class TestGammaSqueeze:
    def test_invalidation_clamped_below_call_wall(self):
        # Flip sits above 99% of the call wall -> invalidation forced to cw * 0.98
        pb, strat = _build(setups=["GAMMA_SQUEEZE"], call_wall_t=105.0, gamma_flip_t=104.9)
        assert pb["bias"] == "Bullish Breakout"
        assert pb["invalidation_strike"] == 105.0 * 0.98
        assert strat == "ATM Option Buying (Call)"


class TestIVSetups:
    def test_iv_spike_direction_from_ifs(self):
        _, bear = _build(setups=["IV_SPIKE"], ifs_final=-10.0)
        _, bull = _build(setups=["IV_SPIKE"], ifs_final=10.0)
        assert bear == "Bear Call Spread (Credit)"
        assert bull == "Bull Put Spread (Credit)"

    def test_iv_skew_bullish_chase(self):
        pb, strat = _build(
            setups=["IV_SKEW_ACCUMULATION"],
            spot_t=100.0, call_wall_t=102.0, skew_slope=1.3,
        )
        assert pb["bias"] == "Bullish Breakout"
        assert strat == "Bull Call Spread (Debit)"

    def test_iv_skew_bearish_chase(self):
        pb, strat = _build(
            setups=["IV_SKEW_ACCUMULATION"],
            spot_t=100.0, call_wall_t=120.0, put_wall_t=98.0, skew_slope=0.8,
        )
        assert pb["bias"] == "Bearish Breakdown"
        assert strat == "Bear Put Spread (Debit)"


class TestFallbacks:
    def test_regime_shift_strategy_from_ifs_sign(self):
        _, bull = _build(setups=["REGIME_SHIFT"], ifs_final=5.0)
        _, bear = _build(setups=["REGIME_SHIFT"], ifs_final=-5.0)
        assert bull == "Bull Put Spread (Credit)"
        assert bear == "Bear Call Spread (Credit)"

    def test_no_setup_ifs_bias(self):
        pb_bull, strat_bull = _build(ifs_final=20.0)
        pb_bear, strat_bear = _build(ifs_final=-20.0)
        pb_flat, strat_flat = _build(ifs_final=0.0)
        assert pb_bull["bias"] == "Bullish Bias" and strat_bull == "Bull Put Spread (Credit)"
        assert pb_bear["bias"] == "Bearish Bias" and strat_bear == "Bear Call Spread (Credit)"
        assert pb_flat["bias"] == "Neutral" and strat_flat == "Wait for Setup"

    def test_volatility_coil_strategy(self):
        pb, strat = _build(setups=["VOLATILITY_COIL"])
        assert pb["bias"] == "Volatility Expansion"
        assert strat == "Long Straddle (Breakout Watch)"
