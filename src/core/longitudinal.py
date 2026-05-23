"""
Vanguard Institutional Terminal - Longitudinal Quantitative Analytics Engine
"""
import numpy as np

class LongitudinalEngine:
    """
    Analyzes historical structural positioning over time.
    Tracks wall migration speed, resistance weakening, gamma regime stability,
    and computes the weighted Smart Money Persistence™ Score.
    """
    def __init__(self):
        pass

    def compute_smart_money_persistence(self, symbol: str, history_list: list) -> float:
        """
        Computes the Smart Money Persistence™ Score (0-100%) for a symbol based on its recent session history.
        Formula:
            Persistence = (bullish_days_factor * 40) + (wall_shift_factor * 30) + (gex_stability_factor * 20) + (price_acceptance_factor * 10)
        """
        if not history_list:
            return 0.0

        # We look at the last 5 sessions for longitudinal trends
        recent = history_list[-5:]
        n_sessions = len(recent)

        # 1. Bullish Flow Days Factor (0.0 to 1.0)
        # Ratio of positive net inventory flow shifts
        bullish_days = sum(1 for s in recent if s.get("net_inv_shift", 0.0) > 50000)
        bullish_factor = bullish_days / n_sessions if n_sessions > 0 else 0.0

        # 2. Wall Shift Strength Factor (0.0 to 1.0)
        # Meaures if the support Put Wall is rising (institutional accumulation floor)
        # or resistance Call Wall is rising (expansion breakout)
        wall_shift_score = 0.0
        if len(recent) >= 2:
            prev = recent[0]
            latest = recent[-1]
            
            p_pw = prev.get("put_wall", 0.0)
            l_pw = latest.get("put_wall", 0.0)
            p_cw = prev.get("call_wall", 0.0)
            l_cw = latest.get("call_wall", 0.0)

            # Put wall rising is extremely bullish (+1.0)
            if l_pw > p_pw > 0:
                wall_shift_score += 0.6
            elif l_pw == p_pw > 0:
                wall_shift_score += 0.3 # Stable support is positive
                
            # Call wall rising with rising spot shows expansion (+0.4)
            if l_cw > p_cw > 0:
                wall_shift_score += 0.4
            elif l_cw == p_cw > 0:
                wall_shift_score += 0.2
        else:
            wall_shift_score = 0.5 # Default middle score
            
        wall_shift_factor = min(1.0, max(0.0, wall_shift_score))

        # 3. GEX Stability Factor (0.0 to 1.0)
        # Meaures how consistently positive the dealer GEX positioning is (suppresses volatility)
        long_gamma_days = sum(1 for s in recent if s.get("gamma_regime") == "LONG_GAMMA")
        gex_stability_factor = long_gamma_days / n_sessions if n_sessions > 0 else 0.0

        # 4. Price Acceptance Factor (0.0 to 1.0)
        # Spot accepting above Gamma Flip triggers mean reversion/squeeze momentum
        spot_above_flip = sum(1 for s in recent if s.get("spot_close", 0.0) >= s.get("gamma_flip", 0.0))
        price_acceptance_factor = spot_above_flip / n_sessions if n_sessions > 0 else 0.0

        # 5. Compile Weighted Score
        persistence_score = (
            (bullish_factor * 40.0) +
            (wall_shift_factor * 30.0) +
            (gex_stability_factor * 20.0) +
            (price_acceptance_factor * 10.0)
        )
        
        return round(max(0.0, min(100.0, persistence_score)), 1)

    def detect_wall_migrations(self, history_list: list) -> dict:
        """
        Analyzes multi-session walls shifts to determine EOD support/resistance migration states.
        """
        if len(history_list) < 2:
            return {
                "put_shift": "Stable",
                "call_shift": "Stable",
                "regime_change": False,
                "put_wall_pct_change": 0.0,
                "call_wall_pct_change": 0.0
            }

        prev = history_list[-2]
        latest = history_list[-1]

        prev_pw, latest_pw = prev.get("put_wall", 0.0), latest.get("put_wall", 0.0)
        prev_cw, latest_cw = prev.get("call_wall", 0.0), latest.get("call_wall", 0.0)
        prev_gf, latest_gf = prev.get("gamma_flip", 0.0), latest.get("gamma_flip", 0.0)

        # 1. Put Wall Migration
        if latest_pw > prev_pw > 0:
            put_shift = "Higher (Support Rising)"
        elif latest_pw < prev_pw > 0:
            put_shift = "Lower (Support Dropping)"
        else:
            put_shift = "Stable"

        # 2. Call Wall Migration
        if latest_cw > prev_cw > 0:
            call_shift = "Higher (Resistance Rising)"
        elif latest_cw < prev_cw > 0:
            call_shift = "Lower (Resistance Weakening)"
        else:
            call_shift = "Stable"

        # 3. Gamma Regime Crossover Shift
        regime_change = prev.get("gamma_regime") != latest.get("gamma_regime")

        return {
            "put_shift": put_shift,
            "call_shift": call_shift,
            "regime_change": regime_change,
            "put_wall_pct_change": round((latest_pw - prev_pw) / prev_pw * 100, 2) if prev_pw > 0 else 0.0,
            "call_wall_pct_change": round((latest_cw - prev_cw) / prev_cw * 100, 2) if prev_cw > 0 else 0.0
        }
