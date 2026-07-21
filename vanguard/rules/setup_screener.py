"""
Setup screener (wave 2 / R1) — the 10 setup-detection rules, extracted verbatim
from daily_compiler.py's main() so they are unit-testable and single-sourced.

Contract: `screen(SetupInputs) -> list[str]` reproduces the compiler's original
inline block exactly (ordering included — PINCH_ZONE's dependence on
INVENTORY_MIGRATION is preserved). The wave-2 parity gate recompiled the full
history against the pre-extraction output to prove it.

`skew_state()` is the ONE home of the skew predicate that previously lived in
two drifting copies (compiler + playbook). Both callers now import it.
"""
from __future__ import annotations

from dataclasses import dataclass

from vanguard.config.eod import MIN_WALL_MIGRATION_PCT, GEX_INTENSITY_PIN_THRESHOLD

# Rule thresholds, named. Values unchanged from the inline block.
SQUEEZE_WALL_PROX = 0.025      # spot within 2.5% below call wall
SQUEEZE_MOMENTUM_CHG = 2.0     # or +2% day in short gamma
COIL_MAX_ABS_CHG = 0.4
COIL_MAX_GEX_I = 15.0
FLOOR_WALL_PROX = 0.025
FLOOR_MIN_INV_SHIFT = 20000.0
PIN_FLIP_PROX = 0.015
REGIME_FLIP_PROX = 0.008
PINCH_WALL_EPS = 1.0           # walls "converged" = same strike (abs diff < 1)
PINCH_SPOT_PROX = 0.04
IV_SPIKE_SHIFT = 0.045         # decimal vol units (4.5 IV pts)
IV_SPIKE_RANK = 70.0
IV_CRUSH_SHIFT = -0.045
IV_CRUSH_RANK = 35.0
SKEW_WALL_PROX = 0.03
SKEW_BULL_SLOPE = 1.15
SKEW_BEAR_SLOPE = 0.85


@dataclass
class SetupInputs:
    """Everything the rules read — persisted fields only (the R1 policy:
    anything a rule reads must be stored so history is auditable)."""
    spot_t: float
    spot_tm1: float
    spot_chg: float
    call_wall_t: float
    call_wall_tm1: float
    put_wall_t: float
    put_wall_tm1: float
    gamma_flip_t: float
    gamma_flip_tm1: float
    gamma_regime: str
    gex_intensity: float
    net_bull_inv_shift: float
    iv_shift: float
    iv_rank: float
    skew_slope: float
    pe_interp: str = ""


def skew_state(spot_t: float, call_wall_t: float, put_wall_t: float,
               skew_slope: float) -> str | None:
    """'BULLISH' | 'BEARISH' | None — the single skew predicate.
    Bullish: spot 0–3% below the call wall with CE/PE slope > 1.15.
    Bearish: spot 0–3% above the put wall with slope < 0.85."""
    if spot_t > 0 and call_wall_t > 0 \
            and 0 < (call_wall_t - spot_t) / spot_t <= SKEW_WALL_PROX \
            and skew_slope > SKEW_BULL_SLOPE:
        return "BULLISH"
    if spot_t > 0 and put_wall_t > 0 \
            and 0 < (spot_t - put_wall_t) / spot_t <= SKEW_WALL_PROX \
            and skew_slope < SKEW_BEAR_SLOPE:
        return "BEARISH"
    return None


# ── individual rules (pure; one boolean each) ────────────────────────────────

def gamma_squeeze(i: SetupInputs) -> bool:
    near_wall = (i.gamma_regime == "SHORT_GAMMA" and i.spot_t > 0 and i.call_wall_t > 0
                 and 0 < (i.call_wall_t - i.spot_t) / i.spot_t <= SQUEEZE_WALL_PROX
                 and i.net_bull_inv_shift > 0)
    momentum = i.spot_chg > SQUEEZE_MOMENTUM_CHG and i.gamma_regime == "SHORT_GAMMA"
    return near_wall or momentum


def volatility_coil(i: SetupInputs) -> bool:
    return abs(i.spot_chg) <= COIL_MAX_ABS_CHG and abs(i.gex_intensity) < COIL_MAX_GEX_I


def floor_bounce(i: SetupInputs) -> bool:
    """A put wall only acts as a dealer-defended floor if the OI sitting there
    was written, not bought (see intelligence.classify_oi_flow / playbook.py's
    same "Buying" check on the strategy side) — a wall built from bought puts
    means dealers are short those puts and hedge into a decline rather than
    cushioning it, so there is no floor to sell. pe_interp="" (unknown) leaves
    this unblocked, matching playbook.py's flow-blind default."""
    return (i.gamma_regime == "LONG_GAMMA" and i.spot_t > 0 and i.put_wall_t > 0
            and abs(i.spot_t - i.put_wall_t) / i.spot_t <= FLOOR_WALL_PROX
            and i.net_bull_inv_shift > FLOOR_MIN_INV_SHIFT
            and "Buying" not in i.pe_interp)


def dealer_defense(i: SetupInputs) -> bool:
    return (i.gamma_regime == "LONG_GAMMA"
            and abs(i.gex_intensity) > GEX_INTENSITY_PIN_THRESHOLD
            and i.gamma_flip_t > 0
            and abs(i.spot_t - i.gamma_flip_t) / i.spot_t <= PIN_FLIP_PROX)


def regime_shift(i: SetupInputs) -> bool:
    crossed_up = (i.spot_t > i.gamma_flip_t > 0 and 0 < i.spot_tm1 <= i.gamma_flip_tm1
                  and i.net_bull_inv_shift > 0)
    # Mirror of crossed_up: SHORT_GAMMA transition (spot fell through the
    # flip from at-or-above it) confirmed by bearish OI shift. Without this,
    # a real bearish regime change could only ever be caught by `hovering`
    # (bare proximity, no crossing or flow confirmation) — an asymmetry the
    # downstream strategy override doesn't expect, since it branches on both
    # ifs_final signs for REGIME_SHIFT as if both were equally confirmed.
    crossed_down = (0 < i.spot_t < i.gamma_flip_t and i.spot_tm1 >= i.gamma_flip_tm1 > 0
                     and i.net_bull_inv_shift < 0)
    hovering = (i.gamma_flip_t > 0
                and abs(i.spot_t - i.gamma_flip_t) / i.spot_t <= REGIME_FLIP_PROX)
    return crossed_up or crossed_down or hovering


def inventory_migration(i: SetupInputs) -> bool:
    pw = (abs(i.put_wall_t - i.put_wall_tm1) / i.put_wall_tm1 * 100.0
          if (i.put_wall_t > 0 and i.put_wall_tm1 > 0) else 0.0)
    cw = (abs(i.call_wall_t - i.call_wall_tm1) / i.call_wall_tm1 * 100.0
          if (i.call_wall_t > 0 and i.call_wall_tm1 > 0) else 0.0)
    return max(pw, cw) >= MIN_WALL_MIGRATION_PCT


def pinch_zone(i: SetupInputs, migration_fired: bool) -> bool:
    """Fires only when INVENTORY_MIGRATION did NOT (walls static but pinched)."""
    return (not migration_fired
            and i.call_wall_t > 0 and i.put_wall_t > 0 and i.gamma_flip_t > 0
            and abs(i.call_wall_t - i.put_wall_t) < PINCH_WALL_EPS
            and abs(i.call_wall_t - i.gamma_flip_t) < PINCH_WALL_EPS
            and i.spot_t > 0
            and abs(i.spot_t - i.gamma_flip_t) / i.spot_t <= PINCH_SPOT_PROX)


def iv_spike(i: SetupInputs) -> bool:
    return i.iv_shift > IV_SPIKE_SHIFT and i.iv_rank > IV_SPIKE_RANK


def iv_crush(i: SetupInputs) -> bool:
    return i.iv_shift < IV_CRUSH_SHIFT and i.iv_rank < IV_CRUSH_RANK


def iv_skew_accumulation(i: SetupInputs) -> bool:
    return skew_state(i.spot_t, i.call_wall_t, i.put_wall_t, i.skew_slope) is not None


def screen(i: SetupInputs) -> list[str]:
    """All fired setups, in the compiler's historical emission order."""
    setups: list[str] = []
    if gamma_squeeze(i):
        setups.append("GAMMA_SQUEEZE")
    if volatility_coil(i):
        setups.append("VOLATILITY_COIL")
    if floor_bounce(i):
        setups.append("FLOOR_BOUNCE")
    if dealer_defense(i):
        setups.append("DEALER_DEFENSE")
    if regime_shift(i):
        setups.append("REGIME_SHIFT")
    migration = inventory_migration(i)
    if migration:
        setups.append("INVENTORY_MIGRATION")
    if pinch_zone(i, migration_fired=migration):
        setups.append("PINCH_ZONE")
    if iv_spike(i):
        setups.append("IV_SPIKE")
    if iv_crush(i):
        setups.append("IV_CRUSH")
    if iv_skew_accumulation(i):
        setups.append("IV_SKEW_ACCUMULATION")
    return setups
