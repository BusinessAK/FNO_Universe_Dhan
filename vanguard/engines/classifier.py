"""
Vanguard Institutional Terminal - Structural Trend Classification Engine
"""
from vanguard.core.config import GEX_INTENSITY_PIN_THRESHOLD


class StructureClassifier:
    """
    Evaluates spot price relative to dealer walls and volume momentum to
    classify the underlying stock structure into professional institutional categories.
    """
    def __init__(self):
        pass

    def classify_structure(self, metrics: dict, setups: list) -> str:
        """
        Classifies stock structure into one of the key institutional states:
        - Support Building (Bullish accumulation)
        - Support Weakening (Bearish distribution at the floor)
        - Resistance Weakening (Breakout candidate)
        - Resistance Building (Ceiling reinforcement, bearish)
        - Compression (Volatility loading)
        - Expansion (Active trending)
        - Dealer Controlled (Mean reversion)
        - Flip Zone (Regime transition)
        """
        spot = metrics.get("spot_close", 0.0)
        cw = metrics.get("call_wall", 0.0)
        pw = metrics.get("put_wall", 0.0)
        gf = metrics.get("gamma_flip", 0.0)
        gex_intensity = metrics.get("gex_intensity", 0.0)
        spot_chg = metrics.get("spot_change_pct", 0.0)
        net_inv = metrics.get("net_inv_shift", 0.0)
        ifs = metrics.get("ifs_score", 0.0)

        # 1. Volatility Squeeze Expansion (True breakouts beyond walls or huge daily move)
        is_breakout = (cw > 0 and spot > cw * 1.01)
        is_breakdown = (pw > 0 and spot < pw * 0.99)
        if "GAMMA_SQUEEZE" in setups or is_breakout or is_breakdown or abs(spot_chg) > 2.5:
            return "Expansion"

        # 2. Volatility Compression Squeeze
        if "VOLATILITY_COIL" in setups or (abs(spot_chg) <= 0.4 and abs(gex_intensity) < 15):
            return "Compression"

        # 3. Support Building / Weakening (bullish vs bearish flow at the floor)
        if spot > 0 and pw > 0 and abs(spot - pw) / spot <= 0.02:
            if "FLOOR_BOUNCE" in setups or ifs > 10:
                return "Support Building"
            if ifs < -10:
                return "Support Weakening"
        elif "FLOOR_BOUNCE" in setups:
            return "Support Building"

        # 4. Resistance Weakening / Building (bullish vs bearish flow at the ceiling)
        if spot > 0 and cw > 0 and abs(spot - cw) / spot <= 0.02:
            if ifs > 15:
                return "Resistance Weakening"
            if ifs < -15:
                return "Resistance Building"

        # 5. Flip Zone transition
        if "REGIME_SHIFT" in setups or (spot > 0 and gf > 0 and abs(spot - gf) / spot <= 0.008):
            return "Flip Zone"

        # 6. Dealer Controlled Pinned zones
        if "DEALER_DEFENSE" in setups or abs(gex_intensity) > GEX_INTENSITY_PIN_THRESHOLD:
            return "Dealer Controlled"

        # Default classification based on IFS
        if ifs > 15:
            return "Support Building"
        elif ifs < -15:
            return "Support Weakening"
        else:
            return "Dealer Controlled"
