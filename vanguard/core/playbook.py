"""
Vanguard Institutional Terminal - Tactical Playbook Builder

Extracted from daily_compiler so the playbook and strategy-selection logic is a
pure, unit-testable function. Logic is unchanged from the inline compiler
version.
"""


def build_playbook(
    setups: list,
    spot_t: float,
    call_wall_t: float,
    put_wall_t: float,
    gamma_flip_t: float,
    call_wall_tm1: float,
    put_wall_tm1: float,
    ifs_final: float,
    gamma_regime: str,
    spot_chg: float,
    skew_slope: float = 1.0,
    base_strategy: str = "Wait for Setup",
    pe_interp: str = "",
) -> tuple:
    """
    Builds the tactical playbook dict and the suggested strategy string for one
    (symbol, date) from its triggered setups and structural levels.

    pe_interp is the put-side flow read (see intelligence.classify_oi_flow). It
    gates FLOOR_BOUNCE: a put wall only acts as a floor if the OI sitting there
    was written, so a wall built from bought puts does not earn a credit spread.
    Defaults to "" (unknown), which leaves the flow-blind behaviour unchanged.

    Returns (playbook: dict, suggested_strategy: str).
    """
    playbook = {
        "bias": "Neutral",
        "trigger_strike": 0.0,
        "invalidation_strike": 0.0,
        "expected_behavior": "Mean Reversion",
        "dealer_behavior": "Long Gamma"
    }
    if "GAMMA_SQUEEZE" in setups:
        invalid_val = float(gamma_flip_t)
        if invalid_val >= float(call_wall_t * 0.99):
            invalid_val = float(call_wall_t * 0.98)
        playbook = {"bias": "Bullish Breakout", "trigger_strike": float(call_wall_t), "invalidation_strike": invalid_val, "expected_behavior": "Short Squeeze Breakout", "dealer_behavior": "Short Gamma Hedging Squeeze"}
    elif "INVENTORY_MIGRATION" in setups:
        # Classify the specific type of wall migration dynamically!
        put_up = put_wall_t > put_wall_tm1 > 0
        put_down = 0 < put_wall_t < put_wall_tm1
        call_up = call_wall_t > call_wall_tm1 > 0
        call_down = 0 < call_wall_t < call_wall_tm1

        if put_up and call_up:
            if ifs_final <= -10:
                playbook = {
                    "bias": "Bullish Trap (Divergence)",
                    "trigger_strike": float(call_wall_t),
                    "invalidation_strike": float(put_wall_t),
                    "expected_behavior": "Low-Conviction Rally",
                    "dealer_behavior": "Dual Wall Upward Migration"
                }
            else:
                playbook = {
                    "bias": "Strong Bullish Momentum",
                    "trigger_strike": float(call_wall_t),
                    "invalidation_strike": float(put_wall_t),
                    "expected_behavior": "Bullish Trend Extension",
                    "dealer_behavior": "Dual Wall Upward Migration"
                }
        elif put_down and call_down:
            if ifs_final >= 10:
                playbook = {
                    "bias": "Bearish Trap (Divergence)",
                    "trigger_strike": float(put_wall_t),
                    "invalidation_strike": float(call_wall_t),
                    "expected_behavior": "Low-Conviction Selloff",
                    "dealer_behavior": "Dual Wall Downward Migration"
                }
            else:
                playbook = {
                    "bias": "Strong Bearish Momentum",
                    "trigger_strike": float(put_wall_t),
                    "invalidation_strike": float(call_wall_t),
                    "expected_behavior": "Bearish Trend Extension",
                    "dealer_behavior": "Dual Wall Downward Migration"
                }
        elif put_up:
            invalid_val = float(put_wall_tm1)
            if invalid_val >= float(put_wall_t * 0.99):
                invalid_val = float(put_wall_t * 0.98)

            if ifs_final <= -10:
                playbook = {
                    "bias": "Support Rise (Divergence)",
                    "trigger_strike": float(put_wall_t),
                    "invalidation_strike": invalid_val,
                    "expected_behavior": "Vulnerable Support Floor",
                    "dealer_behavior": "Support Floor Upward Migration"
                }
            else:
                playbook = {
                    "bias": "Bullish Accumulation",
                    "trigger_strike": float(put_wall_t),
                    "invalidation_strike": invalid_val,
                    "expected_behavior": "Support Floor Rise",
                    "dealer_behavior": "Support Floor Upward Migration"
                }
        elif put_down:
            invalid_val = float(put_wall_tm1)
            if invalid_val <= float(put_wall_t * 1.01):
                invalid_val = float(put_wall_t * 1.02)

            # If spot price is rising and remains above the new Put Wall, this is support normalization, not a breakdown!
            if spot_t > put_wall_t and (spot_chg > 0 or ifs_final > 15):
                playbook = {
                    "bias": "Support Normalization",
                    "trigger_strike": float(put_wall_t),
                    "invalidation_strike": float(put_wall_t * 0.985),
                    "expected_behavior": "Bullish Rebalancing",
                    "dealer_behavior": "Support Floor Normalization"
                }
            else:
                if ifs_final >= 10:
                    playbook = {
                        "bias": "Support Drop (Divergence)",
                        "trigger_strike": float(put_wall_t),
                        "invalidation_strike": invalid_val,
                        "expected_behavior": "False Breakdown Warning",
                        "dealer_behavior": "Support Floor Downward Migration"
                    }
                else:
                    playbook = {
                        "bias": "Bearish Breakdown",
                        "trigger_strike": float(put_wall_t),
                        "invalidation_strike": invalid_val,
                        "expected_behavior": "Support Floor Collapse",
                        "dealer_behavior": "Support Floor Downward Migration"
                    }
        elif call_up:
            invalid_val = float(call_wall_tm1)
            if invalid_val >= float(call_wall_t * 0.99):
                invalid_val = float(call_wall_t * 0.98)

            if ifs_final <= -10:
                playbook = {
                    "bias": "False Breakout Warning",
                    "trigger_strike": float(call_wall_t),
                    "invalidation_strike": invalid_val,
                    "expected_behavior": "Ceiling Rise (Divergence)",
                    "dealer_behavior": "Call Wall Upward Migration"
                }
            else:
                playbook = {
                    "bias": "Bullish Breakout",
                    "trigger_strike": float(call_wall_t),
                    "invalidation_strike": invalid_val,
                    "expected_behavior": "Resistance Ceiling Rise",
                    "dealer_behavior": "Call Wall Upward Migration"
                }
        elif call_down:
            invalid_val = float(call_wall_tm1)
            if invalid_val <= float(call_wall_t * 1.01):
                invalid_val = float(call_wall_t * 1.02)

            if ifs_final >= 10:
                playbook = {
                    "bias": "Ceiling Drop (Divergence)",
                    "trigger_strike": float(call_wall_t),
                    "invalidation_strike": invalid_val,
                    "expected_behavior": "False Breakdown Warning",
                    "dealer_behavior": "Call Wall Downward Migration"
                }
            else:
                playbook = {
                    "bias": "Bearish Consolidation",
                    "trigger_strike": float(call_wall_t),
                    "invalidation_strike": invalid_val,
                    "expected_behavior": "Ceiling Drop (Bearish)",
                    "dealer_behavior": "Call Wall Downward Migration"
                }
        else:
            playbook = {
                "bias": "Range Shift",
                "trigger_strike": float(call_wall_t),
                "invalidation_strike": float(put_wall_t),
                "expected_behavior": "Wall Rebalancing",
                "dealer_behavior": "Inventory Repositioning"
            }
    elif "REGIME_SHIFT" in setups:
        playbook = {"bias": "Regime Transition", "trigger_strike": float(gamma_flip_t), "invalidation_strike": float(gamma_flip_t * 0.99), "expected_behavior": "Volatility Stabilization", "dealer_behavior": "Hedging Crossover Transition"}
    elif "VOLATILITY_COIL" in setups:
        playbook = {"bias": "Volatility Expansion", "trigger_strike": float(gamma_flip_t), "invalidation_strike": float(spot_t * 0.985), "expected_behavior": "Coil Breakout Watch", "dealer_behavior": "Inventory Compression Coil"}
    elif "DEALER_DEFENSE" in setups:
        playbook = {"bias": "Mean Reversion", "trigger_strike": float(gamma_flip_t), "invalidation_strike": float(gamma_flip_t * 0.98), "expected_behavior": "Institutional Pin Target", "dealer_behavior": "Straddle Pin Defense"}
    elif "FLOOR_BOUNCE" in setups:
        playbook = {"bias": "Bullish Mean Reversion", "trigger_strike": float(put_wall_t), "invalidation_strike": float(put_wall_t * 0.985), "expected_behavior": "Key Support Bounce", "dealer_behavior": "Put Wall Support Hedging"}
    elif "PINCH_ZONE" in setups:
        # All walls converged — breakout direction determined by spot price relative to the pinch wall (gamma_flip_t)
        is_bullish = (spot_t >= gamma_flip_t) if spot_t > 0 and gamma_flip_t > 0 else (ifs_final >= 0)
        if is_bullish:
            pz_bias = "Compression — Bullish Breakout Watch"
            pz_behavior = "Bullish Breakout Watch"
            invalid_val = float(spot_t * 0.985)
        else:
            pz_bias = "Compression — Bearish Breakdown Watch"
            pz_behavior = "Bearish Breakdown Watch"
            invalid_val = float(spot_t * 1.015)
        playbook = {
            "bias": pz_bias,
            "trigger_strike": float(gamma_flip_t),
            "invalidation_strike": invalid_val,
            "expected_behavior": pz_behavior,
            "dealer_behavior": "Long Gamma Pin Defense"
        }
    elif "IV_SPIKE" in setups:
        playbook = {
            "bias": "Volatility Mean Reversion",
            "trigger_strike": float(spot_t),
            "invalidation_strike": float(spot_t * 1.05) if ifs_final < 0 else float(spot_t * 0.95),
            "expected_behavior": "IV Contraction Reversion",
            "dealer_behavior": "Premium Rich Straddle Selling"
        }
    elif "IV_CRUSH" in setups:
        playbook = {
            "bias": "Volatility Stable Range",
            "trigger_strike": float(spot_t),
            "invalidation_strike": float(spot_t * 1.03),
            "expected_behavior": "IV Collapse Flatline",
            "dealer_behavior": "Post Event Unwinding"
        }
    elif "IV_SKEW_ACCUMULATION" in setups:
        is_bullish_skew = spot_t > 0 and call_wall_t > 0 and 0 < (call_wall_t - spot_t) / spot_t <= 0.03 and skew_slope > 1.15
        if is_bullish_skew:
            playbook = {
                "bias": "Bullish Breakout",
                "trigger_strike": float(call_wall_t),
                "invalidation_strike": float(spot_t * 0.97),
                "expected_behavior": "Upside Skew Chase Breakout",
                "dealer_behavior": "Speculative Call Buying Squeeze"
            }
        else:
            playbook = {
                "bias": "Bearish Breakdown",
                "trigger_strike": float(put_wall_t),
                "invalidation_strike": float(spot_t * 1.03),
                "expected_behavior": "Downside Skew Chase Breakdown",
                "dealer_behavior": "Speculative Put Buying Squeeze"
            }
    elif ifs_final > 15:
        playbook = {"bias": "Bullish Bias", "trigger_strike": float(call_wall_t), "invalidation_strike": float(put_wall_t), "expected_behavior": "Support Floor Building", "dealer_behavior": "Put Writing Support"}
    elif ifs_final < -15:
        playbook = {"bias": "Bearish Bias", "trigger_strike": float(put_wall_t), "invalidation_strike": float(call_wall_t), "expected_behavior": "Ceiling Reinforcement", "dealer_behavior": "Call Writing Reinforcement"}

    # Degenerate-plan guard: converged walls can leave trigger ==
    # invalidation (a zero-width risk plan). Widen invalidation 2%
    # away on the safe side of the bias.
    if (playbook["trigger_strike"] > 0
            and abs(playbook["trigger_strike"] - playbook["invalidation_strike"]) < 1e-9):
        _pb_bias = playbook["bias"].lower()
        if "bear" in _pb_bias or "breakdown" in _pb_bias:
            playbook["invalidation_strike"] = round(playbook["trigger_strike"] * 1.02, 2)
        else:
            playbook["invalidation_strike"] = round(playbook["trigger_strike"] * 0.98, 2)

    # ── Setup-Aware High-Fidelity Suggested Strategy Override ──
    s_strat = base_strategy
    p_bias = playbook.get("bias", "Neutral")

    if "GAMMA_SQUEEZE" in setups:
        s_strat = "ATM Option Buying (Call)"
    elif "IV_SPIKE" in setups:
        s_strat = "Bear Call Spread (Credit)" if ifs_final < 0 else "Bull Put Spread (Credit)"
    elif "IV_CRUSH" in setups:
        s_strat = "Iron Condor / Short Straddle"
    elif "VOLATILITY_COIL" in setups:
        s_strat = "Long Straddle (Breakout Watch)"
    elif "FLOOR_BOUNCE" in setups:
        # Selling this floor is only justified if someone else wrote it. When the
        # wall's OI was bought instead, dealers are short those puts and hedge
        # into a decline rather than cushioning it, so there is no floor to sell.
        if "Buying" in pe_interp:
            s_strat = "Wait for Setup"
        else:
            s_strat = "Bull Put Spread (Credit)"
    elif "DEALER_DEFENSE" in setups:
        s_strat = "Iron Condor / Short Straddle"
    elif "PINCH_ZONE" in setups:
        is_pz_bullish = (spot_t >= gamma_flip_t) if spot_t > 0 and gamma_flip_t > 0 else (ifs_final >= 0)
        if is_pz_bullish:
            s_strat = "Bull Call Spread (Debit)"
        else:
            s_strat = "Bear Put Spread (Debit)"
    elif "INVENTORY_MIGRATION" in setups:
        if p_bias == "Strong Bullish Momentum" or p_bias == "Bullish Breakout":
            s_strat = "Bull Call Spread (Debit)"
        elif p_bias == "Bullish Accumulation" or p_bias == "Support Normalization":
            s_strat = "Bull Put Spread (Credit)"
        elif p_bias == "Bearish Consolidation":
            s_strat = "Bear Call Spread (Credit)"
        elif p_bias == "Bearish Breakdown" or p_bias == "Strong Bearish Momentum":
            s_strat = "Bear Put Spread (Debit)"
        else:
            s_strat = "Wait for Setup"
    elif "IV_SKEW_ACCUMULATION" in setups:
        # Bias direction takes precedence; gamma_regime is a secondary tie-breaker
        # for neutral/transition cases where direction is unclear.
        if "Bullish" in p_bias:
            # Spot above gamma flip + call skew building → buy the breakout
            s_strat = "Bull Call Spread (Debit)"
        elif "Bearish" in p_bias:
            # Spot below gamma flip + put skew building → buy the breakdown
            s_strat = "Bear Put Spread (Debit)"
        else:
            # Neutral / Regime Transition — defer to gamma_regime
            s_strat = "Bull Call Spread (Debit)" if gamma_regime == "LONG_GAMMA" else "Bear Put Spread (Debit)"
    elif "REGIME_SHIFT" in setups:
        if p_bias == "Regime Transition" and ifs_final >= 0:
            s_strat = "Bull Put Spread (Credit)"
        elif p_bias == "Regime Transition" and ifs_final < 0:
            s_strat = "Bear Call Spread (Credit)"
    elif ifs_final > 15:
        s_strat = "Bull Put Spread (Credit)"
    elif ifs_final < -15:
        s_strat = "Bear Call Spread (Credit)"
    else:
        s_strat = "Wait for Setup"

    return playbook, s_strat
