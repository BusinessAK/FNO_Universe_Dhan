"""
Vanguard Institutional Terminal - Structural Trend Classification Engine
"""

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
        - Resistance Weakening (Breakout candidate)
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

        # 1. Volatility Squeeze Expansion
        if "GAMMA_SQUEEZE" in setups or "INVENTORY_MIGRATION" in setups or abs(spot_chg) > 2.5:
            return "Expansion"

        # 2. Volatility Compression Squeeze
        if "VOLATILITY_COIL" in setups or (abs(spot_chg) <= 0.4 and abs(gex_intensity) < 15):
            return "Compression"

        # 3. Flip Zone transition
        if "REGIME_SHIFT" in setups or (gf > 0 and abs(spot - gf) / spot <= 0.008):
            return "Flip Zone"

        # 4. Support Building
        if "FLOOR_BOUNCE" in setups or (pw > 0 and abs(spot - pw) / spot <= 0.02 and net_inv > 20000):
            return "Support Building"

        # 5. Resistance Weakening
        if cw > 0 and abs(spot - cw) / spot <= 0.02 and net_inv > 50000:
            return "Resistance Weakening"

        # 6. Dealer Controlled Pinned zones
        if "DEALER_DEFENSE" in setups or abs(gex_intensity) > 75:
            return "Dealer Controlled"

        # Default classification based on IFS
        if ifs > 15:
            return "Support Building"
        elif ifs < -15:
            return "Resistance Weakening"
        else:
            return "Dealer Controlled"
