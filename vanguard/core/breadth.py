"""
Vanguard Institutional Terminal - Market-Wide Breadth & Change Detection Engine
"""

def _safe_float(metrics: dict, key: str, default: float = 0.0) -> float:
    """Float coercion tolerant of None / NaN / non-numeric metric values."""
    try:
        return float(metrics.get(key) or default)
    except (ValueError, TypeError):
        return default


class MarketBreadthEngine:
    """
    Analyzes top-down institutional breadth and structural shifts across the entire F&O universe.
    Compile statistics on market regimes and extracts daily change events.
    """
    def __init__(self):
        pass

    def compute_market_breadth(self, latest_date: str, session_history: dict) -> dict:
        """
        Aggregates structures for all symbols on the latest date to determine macro breadth.
        """
        total_symbols = 0
        bullish_flow_count = 0
        bearish_flow_count = 0
        compression_count = 0
        expansion_count = 0
        transition_count = 0
        mean_rev_count = 0

        for sym, history in session_history.items():
            metrics = history.get(latest_date)
            if not metrics:
                continue

            total_symbols += 1
            ifs = metrics.get("ifs_score", 0.0)
            bias = metrics.get("structural_bias", "Dealer Controlled")

            # Bullish vs Bearish Flow counts
            if ifs > 15:
                bullish_flow_count += 1
            elif ifs < -15:
                bearish_flow_count += 1

            # Category matching
            if "Compression" in bias:
                compression_count += 1
            elif "Expansion" in bias:
                expansion_count += 1
            elif "Transition" in bias or "Flip Zone" in bias or "Resistance Weakening" in bias or "Support Weakening" in bias:
                transition_count += 1
            elif "Mean Reversion" in bias or "Controlled" in bias or "Support Building" in bias or "Resistance Building" in bias:
                mean_rev_count += 1

        if total_symbols == 0:
            return {
                "bullish_pct": 50.0,
                "bearish_pct": 50.0,
                "compression_pct": 0.0,
                "expansion_pct": 0.0,
                "transition_pct": 0.0,
                "mean_rev_pct": 100.0,
                "total_symbols": 0
            }

        return {
            "bullish_pct": round(bullish_flow_count / total_symbols * 100, 1),
            "bearish_pct": round(bearish_flow_count / total_symbols * 100, 1),
            "compression_pct": round(compression_count / total_symbols * 100, 1),
            "expansion_pct": round(expansion_count / total_symbols * 100, 1),
            "transition_pct": round(transition_count / total_symbols * 100, 1),
            "mean_rev_pct": round(mean_rev_count / total_symbols * 100, 1),
            "total_symbols": total_symbols
        }

    def detect_daily_changes(self, latest_date: str, prev_date: str, session_history: dict) -> list:
        """
        Scans all symbols to identify critical market structure changes from previous session to latest session.
        Returns a list of ranked structured event dictionaries with rank and shift magnitude.
        """
        events = []
        if not prev_date or not latest_date:
            return events

        for sym, history in session_history.items():
            prev_m = history.get(prev_date)
            lat_m = history.get(latest_date)
            if not prev_m or not lat_m:
                continue

            p_pw = _safe_float(prev_m, "put_wall")
            l_pw = _safe_float(lat_m, "put_wall")
            p_cw = _safe_float(prev_m, "call_wall")
            l_cw = _safe_float(lat_m, "call_wall")
            p_gf = _safe_float(prev_m, "gamma_flip")
            l_gf = _safe_float(lat_m, "gamma_flip")

            p_reg, l_reg = prev_m.get("gamma_regime"), lat_m.get("gamma_regime")

            pty_score = _safe_float(lat_m, "priority_score")
            p_gex_int = _safe_float(prev_m, "gex_intensity")
            l_gex_int = _safe_float(lat_m, "gex_intensity")

            # --- 1. DUAL WALL SHIFTS VS INDIVIDUAL WALL SHIFTS ---
            dual_shifted = False
            
            # Detect Synchronized shifts
            if l_pw > p_pw > 0 and l_cw > p_cw > 0:
                # Dual Wall Rise (Strong Bullish Migration)
                mag_pw = abs(l_pw - p_pw) / p_pw
                mag_cw = abs(l_cw - p_cw) / p_cw
                magnitude = max(mag_pw, mag_cw)
                events.append({
                    "symbol": sym,
                    "icon": "🚀",
                    "type": "dual_wall_rise",
                    "magnitude": magnitude,
                    "priority_score": pty_score,
                    "msg": f"<b>{sym}</b>: <b>Dual Option Walls migrated higher</b> (Support: ₹{p_pw:,.0f} → ₹{l_pw:,.0f} | Resistance: ₹{p_cw:,.0f} → ₹{l_cw:,.0f})"
                })
                dual_shifted = True
            elif 0 < l_pw < p_pw and 0 < l_cw < p_cw:
                # Dual Wall Fall (Strong Bearish Migration)
                mag_pw = abs(l_pw - p_pw) / p_pw
                mag_cw = abs(l_cw - p_cw) / p_cw
                magnitude = max(mag_pw, mag_cw)
                events.append({
                    "symbol": sym,
                    "icon": "🩸",
                    "type": "dual_wall_fall",
                    "magnitude": magnitude,
                    "priority_score": pty_score,
                    "msg": f"<b>{sym}</b>: <b>Dual Option Walls migrated lower</b> (Support: ₹{p_pw:,.0f} → ₹{l_pw:,.0f} | Resistance: ₹{p_cw:,.0f} → ₹{l_cw:,.0f})"
                })
                dual_shifted = True
                
            # If not dual-shifted, check for individual wall shifts
            if not dual_shifted:
                # Put Wall Migrations (Support Changes)
                if l_pw > p_pw > 0:
                    magnitude = abs(l_pw - p_pw) / p_pw
                    events.append({
                        "symbol": sym,
                        "icon": "🟢",
                        "type": "support_rise",
                        "magnitude": magnitude,
                        "priority_score": pty_score,
                        "msg": f"<b>{sym}</b>: Support shifted higher (₹{p_pw:,.0f} → ₹{l_pw:,.0f})"
                    })
                elif 0 < l_pw < p_pw:
                    magnitude = abs(l_pw - p_pw) / p_pw
                    events.append({
                        "symbol": sym,
                        "icon": "🔴",
                        "type": "support_drop",
                        "magnitude": magnitude,
                        "priority_score": pty_score,
                        "msg": f"<b>{sym}</b>: Support weakened lower (₹{p_pw:,.0f} → ₹{l_pw:,.0f})"
                    })

                # Call Wall Migrations (Resistance Changes)
                if l_cw > p_cw > 0:
                    magnitude = abs(l_cw - p_cw) / p_cw
                    events.append({
                        "symbol": sym,
                        "icon": "⚡",
                        "type": "resistance_rise",
                        "magnitude": magnitude,
                        "priority_score": pty_score,
                        "msg": f"<b>{sym}</b>: Resistance expanded higher (₹{p_cw:,.0f} → ₹{l_cw:,.0f})"
                    })
                elif 0 < l_cw < p_cw:
                    magnitude = abs(l_cw - p_cw) / p_cw
                    events.append({
                        "symbol": sym,
                        "icon": "🔴",
                        "type": "resistance_fall",
                        "magnitude": magnitude,
                        "priority_score": pty_score,
                        "msg": f"<b>{sym}</b>: Resistance weakened lower (₹{p_cw:,.0f} → ₹{l_cw:,.0f})"
                    })

            # --- 2. OPTION WALL RANGE PINCH / EXPANSION (Volatility Coiling) ---
            p_range = abs(p_cw - p_pw)
            l_range = abs(l_cw - l_pw)
            if p_range > 0.05 * p_pw: # Check if yesterday was non-coiling
                ratio = l_range / p_range
                if ratio <= 0.40: # Compressed by 60% or more
                    magnitude = 1.0 - ratio
                    events.append({
                        "symbol": sym,
                        "icon": "🌀",
                        "type": "option_wall_pinch",
                        "magnitude": magnitude,
                        "priority_score": pty_score,
                        "msg": f"<b>{sym}</b>: Option walls <b>pinched/converged by {magnitude*100:.1f}%</b> (Pinch Strike: ₹{l_cw:,.0f}) — extreme volatility coiling"
                    })
                elif ratio >= 2.0: # Expanded by 100% or more
                    magnitude = ratio - 1.0
                    events.append({
                        "symbol": sym,
                        "icon": "💥",
                        "type": "option_wall_expansion",
                        "magnitude": magnitude,
                        "priority_score": pty_score,
                        "msg": f"<b>{sym}</b>: Option walls <b>expanded by {(ratio-1)*100:.1f}%</b> (New range: ₹{l_pw:,.0f} – ₹{l_cw:,.0f}) — volatility expansion"
                    })

            # --- 3. GEX INTENSITY EXPLOSION (Institutional Block Additions) ---
            if p_gex_int > 1.0 and l_gex_int > 1.0:
                ratio = l_gex_int / p_gex_int
                if ratio >= 3.0: # Surge by 300% or more
                    magnitude = min(1.0, (ratio - 1.0) / 10.0)
                    events.append({
                        "symbol": sym,
                        "icon": "⚡",
                        "type": "gex_intensity_explosion",
                        "magnitude": magnitude,
                        "priority_score": pty_score,
                        "msg": f"<b>{sym}</b>: <b>GEX Concentration Spike of +{int((ratio - 1.0) * 100):d}%</b> (Intensity: {l_gex_int:.3f}), signaling heavy institutional block additions"
                    })

            # --- 4. GAMMA FLIP CROSSOVER ---
            if p_reg == "SHORT_GAMMA" and l_reg == "LONG_GAMMA":
                events.append({
                    "symbol": sym,
                    "icon": "🔋",
                    "type": "regime_flip_bullish",
                    "magnitude": 0.05,
                    "priority_score": pty_score,
                    "msg": f"<b>{sym}</b>: Breached Gamma Flip Trigger (₹{l_gf:,.0f}) — entered Long Gamma"
                })
            elif p_reg == "LONG_GAMMA" and l_reg == "SHORT_GAMMA":
                events.append({
                    "symbol": sym,
                    "icon": "⚠",
                    "type": "regime_flip_bearish",
                    "magnitude": 0.05,
                    "priority_score": pty_score,
                    "msg": f"<b>{sym}</b>: Broke below Gamma Flip Pivot (₹{l_gf:,.0f}) — entered Short Gamma"
                })

        # Priority categorization weights
        type_priority = {
            "dual_wall_rise": 1,
            "dual_wall_fall": 1,
            "support_rise": 2,
            "support_drop": 2,
            "regime_flip_bearish": 3,
            "regime_flip_bullish": 3,
            "option_wall_pinch": 4,
            "option_wall_expansion": 4,
            "gex_intensity_explosion": 4,
            "resistance_rise": 5,
            "resistance_fall": 5
        }

        # Sort: magnitude (descending), priority type (ascending), priority score (descending)
        sorted_events = sorted(
            events,
            key=lambda x: (-x["magnitude"], type_priority.get(x["type"], 9), -x["priority_score"])
        )

        # Inject sequential Rank
        for rank, event in enumerate(sorted_events, 1):
            event["rank"] = rank

        return sorted_events

