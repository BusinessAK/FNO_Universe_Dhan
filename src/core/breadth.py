"""
Vanguard Institutional Terminal - Market-Wide Breadth & Change Detection Engine
"""

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
            elif "Transition" in bias or "Flip Zone" in bias or "Resistance Weakening" in bias:
                transition_count += 1
            elif "Mean Reversion" in bias or "Controlled" in bias or "Support Building" in bias:
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
        Returns a list of structured event dictionaries:
        e.g., {"symbol": "SBIN", "icon": "🟢", "msg": "Support shifted higher (₹720 → ₹740)"}
        """
        events = []
        if not prev_date or not latest_date:
            return events

        for sym, history in session_history.items():
            prev_m = history.get(prev_date)
            lat_m = history.get(latest_date)
            if not prev_m or not lat_m:
                continue

            p_pw, l_pw = prev_m.get("put_wall", 0.0), lat_m.get("put_wall", 0.0)
            p_cw, l_cw = prev_m.get("call_wall", 0.0), lat_m.get("call_wall", 0.0)
            p_gf, l_gf = prev_m.get("gamma_flip", 0.0), lat_m.get("gamma_flip", 0.0)
            p_reg, l_reg = prev_m.get("gamma_regime"), lat_m.get("gamma_regime")

            # 1. Put Wall Migrations (Support Changes)
            if l_pw > p_pw > 0:
                events.append({
                    "symbol": sym,
                    "icon": "🟢",
                    "type": "support_rise",
                    "msg": f"<b>{sym}</b>: Support shifted higher (₹{p_pw:,.0f} → ₹{l_pw:,.0f})"
                })
            elif l_pw < p_pw > 0:
                events.append({
                    "symbol": sym,
                    "icon": "🔴",
                    "type": "support_drop",
                    "msg": f"<b>{sym}</b>: Support weakened lower (₹{p_pw:,.0f} → ₹{l_pw:,.0f})"
                })

            # 2. Call Wall Migrations (Resistance Changes)
            if l_cw > p_cw > 0:
                events.append({
                    "symbol": sym,
                    "icon": "⚡",
                    "type": "resistance_rise",
                    "msg": f"<b>{sym}</b>: Resistance expanded higher (₹{p_cw:,.0f} → ₹{l_cw:,.0f})"
                })
            elif l_cw < p_cw > 0:
                events.append({
                    "symbol": sym,
                    "icon": "🟢",
                    "type": "resistance_fall",
                    "msg": f"<b>{sym}</b>: Resistance weakened lower (₹{p_cw:,.0f} → ₹{l_cw:,.0f})"
                })

            # 3. Gamma Flip Crossover
            if p_reg == "SHORT_GAMMA" and l_reg == "LONG_GAMMA":
                events.append({
                    "symbol": sym,
                    "icon": "🔋",
                    "type": "regime_flip_bullish",
                    "msg": f"<b>{sym}</b>: Breached Gamma Flip Trigger (₹{l_gf:,.0f}) — entered Long Gamma"
                })
            elif p_reg == "LONG_GAMMA" and l_reg == "SHORT_GAMMA":
                events.append({
                    "symbol": sym,
                    "icon": "⚠",
                    "type": "regime_flip_bearish",
                    "msg": f"<b>{sym}</b>: Broke below Gamma Flip Pivot (₹{l_gf:,.0f}) — entered Short Gamma"
                })

        # Sort events: prioritize support shifts, then resistance, then flips
        # Limit to top 15 most active/important structural changes for EOD digest
        type_priority = {"support_rise": 1, "regime_flip_bullish": 2, "regime_flip_bearish": 3, "support_drop": 4, "resistance_rise": 5}
        sorted_events = sorted(events, key=lambda x: type_priority.get(x["type"], 9))
        return sorted_events[:15]
