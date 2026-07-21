"""
Wave 2 / R1: table-driven tests for the 10 extracted setup rules
(vanguard/rules/setup_screener.py). Each case flips exactly one condition
across its threshold so a future edit to any rule breaks a named case.
The full-history recompile parity gate is run separately; these tests pin
per-rule semantics.
"""
import unittest

from vanguard.rules.setup_screener import SetupInputs, screen, skew_state


def base(**over) -> SetupInputs:
    """A quiet symbol that fires NOTHING (verified by test_base_fires_nothing);
    spot_chg=0.5 keeps VOLATILITY_COIL off, gex_intensity=20 too."""
    d = dict(spot_t=1000.0, spot_tm1=990.0, spot_chg=0.5,
             call_wall_t=1100.0, call_wall_tm1=1100.0,
             put_wall_t=900.0, put_wall_tm1=900.0,
             gamma_flip_t=1050.0, gamma_flip_tm1=1050.0,
             gamma_regime="TRANSITION_REGIME", gex_intensity=20.0,
             net_bull_inv_shift=0.0, iv_shift=0.0, iv_rank=50.0,
             skew_slope=1.0)
    d.update(over)
    return SetupInputs(**d)


class TestScreenerRules(unittest.TestCase):
    def test_base_fires_nothing(self):
        self.assertEqual(screen(base()), [])

    # ── GAMMA_SQUEEZE ────────────────────────────────────────────────────
    def test_squeeze_near_wall_arm(self):
        i = base(gamma_regime="SHORT_GAMMA", call_wall_t=1020.0,  # 2% away
                 net_bull_inv_shift=1.0)
        self.assertIn("GAMMA_SQUEEZE", screen(i))

    def test_squeeze_wall_too_far(self):
        i = base(gamma_regime="SHORT_GAMMA", call_wall_t=1030.0,  # 3% > 2.5%
                 net_bull_inv_shift=1.0)
        self.assertNotIn("GAMMA_SQUEEZE", screen(i))

    def test_squeeze_needs_bull_shift(self):
        i = base(gamma_regime="SHORT_GAMMA", call_wall_t=1020.0,
                 net_bull_inv_shift=0.0)
        self.assertNotIn("GAMMA_SQUEEZE", screen(i))

    def test_squeeze_momentum_arm(self):
        i = base(gamma_regime="SHORT_GAMMA", spot_chg=2.1)
        self.assertIn("GAMMA_SQUEEZE", screen(i))

    def test_squeeze_momentum_wrong_regime(self):
        i = base(gamma_regime="LONG_GAMMA", spot_chg=2.1)
        self.assertNotIn("GAMMA_SQUEEZE", screen(i))

    # ── VOLATILITY_COIL ──────────────────────────────────────────────────
    def test_coil_arm(self):
        i = base(spot_chg=0.4, gex_intensity=14.9)
        self.assertIn("VOLATILITY_COIL", screen(i))

    def test_coil_gex_too_hot(self):
        i = base(spot_chg=0.4, gex_intensity=15.0)
        self.assertNotIn("VOLATILITY_COIL", screen(i))

    def test_coil_move_too_big(self):
        i = base(spot_chg=0.41, gex_intensity=10.0)
        self.assertNotIn("VOLATILITY_COIL", screen(i))

    # ── FLOOR_BOUNCE ─────────────────────────────────────────────────────
    def test_floor_arm(self):
        i = base(gamma_regime="LONG_GAMMA", put_wall_t=980.0,   # 2% away
                 net_bull_inv_shift=20001.0)
        self.assertIn("FLOOR_BOUNCE", screen(i))

    def test_floor_shift_at_threshold_off(self):
        i = base(gamma_regime="LONG_GAMMA", put_wall_t=980.0,
                 net_bull_inv_shift=20000.0)                     # > required
        self.assertNotIn("FLOOR_BOUNCE", screen(i))

    def test_floor_blocked_when_puts_were_bought(self):
        i = base(gamma_regime="LONG_GAMMA", put_wall_t=980.0,
                 net_bull_inv_shift=20001.0,
                 pe_interp="Put Buying (Long Build-up)")
        self.assertNotIn("FLOOR_BOUNCE", screen(i))

    def test_floor_arms_when_puts_were_written(self):
        i = base(gamma_regime="LONG_GAMMA", put_wall_t=980.0,
                 net_bull_inv_shift=20001.0,
                 pe_interp="Put Writing (Short Build-up)")
        self.assertIn("FLOOR_BOUNCE", screen(i))

    def test_floor_arms_when_flow_unknown(self):
        i = base(gamma_regime="LONG_GAMMA", put_wall_t=980.0,
                 net_bull_inv_shift=20001.0, pe_interp="")
        self.assertIn("FLOOR_BOUNCE", screen(i))

    # ── DEALER_DEFENSE (GEX_INTENSITY_PIN_THRESHOLD = 25) ────────────────
    def test_pin_arm(self):
        i = base(gamma_regime="LONG_GAMMA", gex_intensity=25.1,
                 gamma_flip_t=1010.0)                            # 1% away
        self.assertIn("DEALER_DEFENSE", screen(i))

    def test_pin_flip_too_far(self):
        i = base(gamma_regime="LONG_GAMMA", gex_intensity=25.1,
                 gamma_flip_t=1020.0)                            # 2% > 1.5%
        self.assertNotIn("DEALER_DEFENSE", screen(i))

    # ── REGIME_SHIFT ─────────────────────────────────────────────────────
    def test_regime_cross_arm(self):
        i = base(spot_t=1060.0, gamma_flip_t=1050.0, spot_tm1=1040.0,
                 gamma_flip_tm1=1045.0, net_bull_inv_shift=1.0)
        self.assertIn("REGIME_SHIFT", screen(i))

    def test_regime_hover_arm_no_shift_needed(self):
        i = base(spot_t=1000.0, gamma_flip_t=1005.0)             # 0.5% < 0.8%
        self.assertIn("REGIME_SHIFT", screen(i))

    def test_regime_cross_down_arm(self):
        i = base(spot_t=1040.0, gamma_flip_t=1050.0, spot_tm1=1060.0,
                 gamma_flip_tm1=1055.0, net_bull_inv_shift=-1.0)
        self.assertIn("REGIME_SHIFT", screen(i))

    def test_regime_cross_down_needs_bear_shift(self):
        i = base(spot_t=1040.0, gamma_flip_t=1050.0, spot_tm1=1060.0,
                 gamma_flip_tm1=1055.0, net_bull_inv_shift=0.0)
        self.assertNotIn("REGIME_SHIFT", screen(i))

    # ── INVENTORY_MIGRATION (MIN_WALL_MIGRATION_PCT = 2.0) ───────────────
    def test_migration_arm_call_side(self):
        i = base(call_wall_t=1130.0, call_wall_tm1=1100.0)       # 2.7%
        self.assertIn("INVENTORY_MIGRATION", screen(i))

    def test_migration_below_min_shift(self):
        i = base(call_wall_t=1120.0, call_wall_tm1=1100.0)       # 1.8%
        self.assertNotIn("INVENTORY_MIGRATION", screen(i))

    def test_migration_zero_wall_no_div_by_zero(self):
        i = base(call_wall_tm1=0.0, put_wall_tm1=0.0)
        self.assertNotIn("INVENTORY_MIGRATION", screen(i))

    # ── PINCH_ZONE (suppressed by migration) ─────────────────────────────
    def _pinched(self, **over):
        d = dict(call_wall_t=1000.0, put_wall_t=1000.0, gamma_flip_t=1000.0,
                 call_wall_tm1=1000.0, put_wall_tm1=1000.0)
        d.update(over)
        return base(**d)

    def test_pinch_arm(self):
        self.assertIn("PINCH_ZONE", screen(self._pinched()))

    def test_pinch_suppressed_by_migration(self):
        i = self._pinched(call_wall_tm1=970.0)                   # migration fires
        out = screen(i)
        self.assertIn("INVENTORY_MIGRATION", out)
        self.assertNotIn("PINCH_ZONE", out)

    def test_pinch_spot_too_far(self):
        i = self._pinched(spot_t=1050.0)                         # 5% > 4%
        self.assertNotIn("PINCH_ZONE", screen(i))

    # ── IV_SPIKE / IV_CRUSH ──────────────────────────────────────────────
    def test_iv_spike_arm(self):
        i = base(iv_shift=0.046, iv_rank=70.1)
        self.assertIn("IV_SPIKE", screen(i))

    def test_iv_spike_rank_at_threshold_off(self):
        i = base(iv_shift=0.046, iv_rank=70.0)
        self.assertNotIn("IV_SPIKE", screen(i))

    def test_iv_crush_arm(self):
        i = base(iv_shift=-0.046, iv_rank=34.9)
        self.assertIn("IV_CRUSH", screen(i))

    # ── IV_SKEW_ACCUMULATION + skew_state ────────────────────────────────
    def test_skew_bullish(self):
        self.assertEqual(skew_state(1000.0, 1020.0, 900.0, 1.16), "BULLISH")
        self.assertIn("IV_SKEW_ACCUMULATION",
                      screen(base(call_wall_t=1020.0, skew_slope=1.16)))

    def test_skew_bearish(self):
        self.assertEqual(skew_state(1000.0, 1100.0, 980.0, 0.84), "BEARISH")

    def test_skew_none_when_slope_flat(self):
        self.assertIsNone(skew_state(1000.0, 1020.0, 980.0, 1.0))

    def test_skew_spot_above_call_wall_none(self):
        # (call_wall - spot) must be strictly positive
        self.assertIsNone(skew_state(1020.0, 1020.0, 900.0, 1.5))


class TestPlaybookUsesSharedPredicate(unittest.TestCase):
    def test_skew_playbook_matches_skew_state(self):
        """The SBICARD divergence class: playbook's IV_SKEW branch must agree
        with the screener's predicate, both directions."""
        from vanguard.rules.playbook import build_playbook
        common = dict(setups=["IV_SKEW_ACCUMULATION"], put_wall_t=900.0,
                      gamma_flip_t=1000.0, call_wall_tm1=1020.0, put_wall_tm1=900.0,
                      ifs_final=0.0, gamma_regime="SHORT_GAMMA", spot_chg=0.0,
                      base_strategy="Wait for Setup", pe_interp="")
        pb_bull, _ = build_playbook(spot_t=1000.0, call_wall_t=1020.0,
                                    skew_slope=1.16, **common)
        self.assertEqual(pb_bull["bias"], "Bullish Breakout")
        pb_bear, _ = build_playbook(spot_t=1000.0, call_wall_t=1020.0,
                                    skew_slope=1.0, **common)
        self.assertEqual(pb_bear["bias"], "Bearish Breakdown")


if __name__ == "__main__":
    unittest.main()
