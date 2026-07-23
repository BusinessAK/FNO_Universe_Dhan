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
        bullish_days = sum(1 for s in recent if s.get("ifs_score", 0.0) > 10)
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

    # ── Structural Bias Classification Helpers ────────────────────────────────
    # Unambiguously bullish biases — always map to BULLISH regardless of IFS
    _BULLISH_BIASES = frozenset([
        "Support Building", "Resistance Weakening",
        "Bullish Accumulation", "Bullish Breakout", "Bullish Bias",
        "Strong Bullish Momentum", "Bullish Mean Reversion",
    ])
    # Unambiguously bearish biases — always map to BEARISH regardless of IFS
    _BEARISH_BIASES = frozenset([
        "Support Weakening", "Resistance Building",
        "Bearish Breakdown", "Bearish Consolidation", "Bearish Bias",
        "Strong Bearish Momentum",
    ])
    # Ambiguous biases — polarity determined entirely by IFS sign
    # Expansion: directional but sign-dependent
    # Compression, Flip Zone, Dealer Controlled: indeterminate without IFS
    _IFS_DEPENDENT_BIASES = frozenset([
        "Expansion", "Compression", "Flip Zone", "Dealer Controlled",
    ])

    def _bias_polarity(self, bias: str, ifs: float) -> str:
        """Returns 'BULLISH', 'BEARISH', or 'NEUTRAL' for a given structural_bias + ifs_score."""
        if bias in self._BULLISH_BIASES:
            return "BULLISH"
        if bias in self._BEARISH_BIASES:
            return "BEARISH"
        # Ambiguous biases (Expansion, Compression, Flip Zone, Dealer Controlled)
        # and any unknown label — resolve by IFS sign with a small dead-band
        if ifs > 10:
            return "BULLISH"
        if ifs < -10:
            return "BEARISH"
        return "NEUTRAL"

    def detect_structure_flip(self, history_list: list) -> dict:
        """
        Detects day-over-day structural polarity transitions:
          - BEARISH_TO_BULLISH : structure flipped from bearish to bullish
          - BULLISH_TO_BEARISH : structure flipped from bullish to bearish
          - NONE               : no confirmed flip

        Returns a dict:
            {
                "flip_type":        str,   # "BEARISH_TO_BULLISH" | "BULLISH_TO_BEARISH" | "NONE"
                "prev_bias":        str,   # previous day structural_bias label
                "curr_bias":        str,   # current day structural_bias label
                "prev_polarity":    str,   # "BULLISH" | "BEARISH" | "NEUTRAL"
                "curr_polarity":    str,   # "BULLISH" | "BEARISH" | "NEUTRAL"
                "flip_confidence":  float, # 0.0 – 100.0 confidence score
                "flip_strength":    str,   # "STRONG" | "MODERATE" | "WEAK"
            }

        Confidence formula (0–100):
          40pts  IFS sign reversal magnitude  (IFS crossed zero + absolute magnitude)
          25pts  Persistence threshold         (prev bias held for ≥2 days)
          20pts  GEX regime alignment          (gamma regime supports new direction)
          15pts  Price acceptance              (spot moved in direction of new bias)
        """
        no_flip = {
            "flip_type": "NONE",
            "prev_bias": "",
            "curr_bias": "",
            "prev_polarity": "NEUTRAL",
            "curr_polarity": "NEUTRAL",
            "flip_confidence": 0.0,
            "flip_strength": "WEAK",
        }

        if len(history_list) < 2:
            return no_flip

        prev = history_list[-2]
        curr = history_list[-1]

        prev_bias = str(prev.get("structural_bias", ""))
        curr_bias = str(curr.get("structural_bias", ""))
        prev_ifs  = float(prev.get("ifs_score", 0.0))
        curr_ifs  = float(curr.get("ifs_score", 0.0))

        prev_pol = self._bias_polarity(prev_bias, prev_ifs)
        curr_pol = self._bias_polarity(curr_bias, curr_ifs)

        # No flip if same polarity or either side is NEUTRAL
        if prev_pol == curr_pol or "NEUTRAL" in (prev_pol, curr_pol):
            return {**no_flip, "prev_bias": prev_bias, "curr_bias": curr_bias,
                    "prev_polarity": prev_pol, "curr_polarity": curr_pol}

        # Determine flip type
        if prev_pol == "BEARISH" and curr_pol == "BULLISH":
            flip_type = "BEARISH_TO_BULLISH"
        else:
            flip_type = "BULLISH_TO_BEARISH"

        # ── Confidence Scoring ───────────────────────────────────────────────
        # 1. IFS reversal magnitude (40pts)
        ifs_sign_crossed = (prev_ifs * curr_ifs < 0)  # True if literally crossed zero
        ifs_magnitude = min(40.0, abs(curr_ifs) / 100.0 * 40.0 + (10.0 if ifs_sign_crossed else 0.0))

        # 2. Persistence threshold (25pts) — previous bias was sustained ≥ 2 sessions
        prev_bull_persist = int(prev.get("bullish_persistence", 0))
        prev_bear_persist = int(prev.get("bearish_persistence", 0))
        prev_streak = prev_bear_persist if prev_pol == "BEARISH" else prev_bull_persist
        persistence_pts = 25.0 if prev_streak >= 2 else (12.0 if prev_streak == 1 else 0.0)

        # 3. GEX regime alignment (20pts)
        curr_gamma_regime = str(curr.get("gamma_regime", ""))
        regime_aligned = (
            (flip_type == "BEARISH_TO_BULLISH" and curr_gamma_regime == "LONG_GAMMA") or
            (flip_type == "BULLISH_TO_BEARISH" and curr_gamma_regime == "SHORT_GAMMA")
        )
        regime_pts = 20.0 if regime_aligned else 0.0

        # 4. Price acceptance (15pts)
        spot_chg = float(curr.get("spot_change_pct", 0.0))
        price_aligned = (
            (flip_type == "BEARISH_TO_BULLISH" and spot_chg > 0) or
            (flip_type == "BULLISH_TO_BEARISH" and spot_chg < 0)
        )
        price_pts = min(15.0, abs(spot_chg) / 3.0 * 15.0) if price_aligned else 0.0

        confidence = round(ifs_magnitude + persistence_pts + regime_pts + price_pts, 1)
        confidence = max(0.0, min(100.0, confidence))

        if confidence >= 60.0:
            strength = "STRONG"
        elif confidence >= 35.0:
            strength = "MODERATE"
        else:
            strength = "WEAK"

        return {
            "flip_type": flip_type,
            "prev_bias": prev_bias,
            "curr_bias": curr_bias,
            "prev_polarity": prev_pol,
            "curr_polarity": curr_pol,
            "flip_confidence": confidence,
            "flip_strength": strength,
        }

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

        # 1. Put Wall Migration (both walls must exist — a missing wall today is
        # a data gap, not a support drop)
        if latest_pw > prev_pw > 0:
            put_shift = "Higher (Support Rising)"
        elif 0 < latest_pw < prev_pw:
            put_shift = "Lower (Support Dropping)"
        else:
            put_shift = "Stable"

        # 2. Call Wall Migration
        if latest_cw > prev_cw > 0:
            call_shift = "Higher (Resistance Rising)"
        elif 0 < latest_cw < prev_cw:
            call_shift = "Lower (Resistance Weakening)"
        else:
            call_shift = "Stable"

        # 3. Gamma Regime Crossover Shift
        regime_change = prev.get("gamma_regime") != latest.get("gamma_regime")

        return {
            "put_shift": put_shift,
            "call_shift": call_shift,
            "regime_change": regime_change,
            "put_wall_pct_change": round((latest_pw - prev_pw) / prev_pw * 100, 2) if prev_pw > 0 and latest_pw > 0 else 0.0,
            "call_wall_pct_change": round((latest_cw - prev_cw) / prev_cw * 100, 2) if prev_cw > 0 and latest_cw > 0 else 0.0
        }
