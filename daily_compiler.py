#!/usr/bin/env python3
"""
Vanguard Institutional EOD Terminal - Columnar compiler pipeline
Pre-calculates longitudinal structures, Smart Money Persistence, Playbooks, and Breadth,
and saves the compiled datasets as Parquet tables indexed inside local DuckDB.
"""
import os
import sys
import json
import re
import pandas as pd
import numpy as np
from datetime import datetime

# Setup workspace paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
sys.path.insert(0, os.path.dirname(__file__))

from src.intelligence import InstitutionalIntelligence
from src.core.longitudinal import LongitudinalEngine
from src.core.classifier import StructureClassifier
from src.core.breadth import MarketBreadthEngine

def extract_date(filename):
    """Extracts YYYY-MM-DD from NSE bhavcopy filename."""
    match = re.search(r'\d{8}', filename)
    if match:
        date_str = match.group(0)
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    return None

def main():
    print("=" * 80)
    print("  VANGUARD INSTITUTIONAL TERMINAL — HIGH-PERFORMANCE EOD COMPILER (DuckDB)")
    print("=" * 80)
    
    raw_dir = "data/raw"
    if not os.path.exists(raw_dir):
        print(f"[!] Error: Raw data directory {raw_dir} does not exist.")
        sys.exit(1)
        
    files = sorted([f for f in os.listdir(raw_dir) if "FO" in f and f.endswith(".csv")])
    if len(files) < 2:
        print("[!] Error: At least 2 days of FO Bhavcopies are required to compile historical shifts.")
        sys.exit(1)
        
    print(f"[*] Chronological Bhavcopies scanned: {len(files)} files.")
    
    # Initialize Core Engines
    print("[*] Instantiating quant models and intelligence frameworks...")
    intel = InstitutionalIntelligence()
    long_engine = LongitudinalEngine()
    struct_classifier = StructureClassifier()
    breadth_engine = MarketBreadthEngine()
    
    # Chronological history index for persistence and trend mappings
    session_history = {}
    persistence_tracker = {}
    
    # Incremental Compile Layer: Load pre-existing session history to skip completed days
    output_dir = "data/compiled"
    session_history_path = os.path.join(output_dir, "session_history.json")
    force_compile = "--force" in sys.argv
    
    compiled_dates = set()
    if not force_compile and os.path.exists(session_history_path):
        try:
            with open(session_history_path) as f:
                session_history = json.load(f)
            print(f"[*] Loaded existing session history with {len(session_history)} symbols (Incremental Mode).")
            if session_history:
                # Union compiled dates from benchmark indices first, then fall back to all symbols.
                # Using a single symbol is risky — if it has a data gap, valid dates get skipped.
                compiled_dates = set()
                for bench in ["NIFTY", "BANKNIFTY"]:
                    if bench in session_history:
                        compiled_dates.update(session_history[bench].keys())
                # Final fallback: if neither index present, union all symbols
                if not compiled_dates:
                    for sym in session_history:
                        compiled_dates.update(session_history[sym].keys())
        except Exception as e:
            print(f"[!] Warning: Failed to load session history: {e}. Re-building database from scratch.")
            session_history = {}
            
    # Loop adjacent pairs chronologically
    for i in range(1, len(files)):
        file_tm1_name = files[i-1]
        file_t_name = files[i]
        
        date_tm1 = extract_date(file_tm1_name)
        date_t = extract_date(file_t_name)
        
        # Check if this trading day is already processed and compiled
        if not force_compile and date_t in compiled_dates:
            # Restore persistence counters to preserve consecutive trend states
            for symbol in session_history:
                if date_t in session_history[symbol]:
                    day_data = session_history[symbol][date_t]
                    persistence_tracker[symbol] = {
                        "bullish_days": int(day_data.get("bullish_persistence", 0)),
                        "bearish_days": int(day_data.get("bearish_persistence", 0))
                    }
            print(f"[*] Session {date_t} already compiled. Bypassing raw Greeks processing.")
            continue
            
        print(f"[+] Compiling Session: {date_t} (T) vs {date_tm1} (T-1)...")
        
        file_tm1_path = os.path.join(raw_dir, file_tm1_name)
        file_t_path = os.path.join(raw_dir, file_t_name)
        
        try:
            df_intel = intel.analyze_market_structure(file_t_path, file_tm1_path)
            
            for _, row in df_intel.iterrows():
                symbol = row['SYMBOL']
                
                # Core daily metrics
                spot_t = float(row.get('SPOT_T', 0.0))
                spot_tm1 = float(row.get('SPOT_TM1', 0.0))
                spot_chg = float(row.get('SPOT_CHG_PCT', 0.0))
                pcr_t = float(row.get('PCR_T', 0.0))
                
                oi_ce_t = float(row.get('OPEN_INT_CE_T', 0.0))
                oi_pe_t = float(row.get('OPEN_INT_PE_T', 0.0))
                chg_ce_t = float(row.get('CHG_IN_OI_CE_T', 0.0))
                chg_pe_t = float(row.get('CHG_IN_OI_PE_T', 0.0))
                
                call_wall_t = float(row.get('CALL_WALL_T', 0.0))
                put_wall_t = float(row.get('PUT_WALL_T', 0.0))
                gamma_flip_t = float(row.get('GAMMA_FLIP_T', 0.0))
                
                # Fetch previous session parameters from compiled history to support longitudinal setups
                prev_session = session_history.get(symbol, {}).get(date_tm1, {})
                call_wall_tm1 = prev_session.get("call_wall", 0.0)
                put_wall_tm1 = prev_session.get("put_wall", 0.0)
                gamma_flip_tm1 = prev_session.get("gamma_flip", 0.0)
                
                gex_t = float(row.get('GEX_T', 0.0))
                gex_intensity = float(row.get('GEX_INTENSITY', 0.0))
                gex_shift = float(row.get('GEX_SHIFT', 0.0))
                
                iv_t = float(row.get('IV_T', 0.0))
                iv_shift = float(row.get('IV_SHIFT', 0.0))
                
                net_bull_inv_shift = float(row.get('NET_BULL_INV_SHIFT', 0.0))

                # Expiry rollover metadata — populated by intelligence.py when a weekly
                # index series was stripped from T-1 before delta computation.
                # Same value for all symbols on a given day (it's a session-level event).
                expiry_filtered      = bool(row.get('EXPIRY_FILTERED', False))
                dropped_expiry_dates = str(row.get('DROPPED_EXPIRY_DATES', ''))

                
                # IFS Score Computation
                vol_ce_t = float(row.get('VOLUME_CE_T', 0.0))
                vol_pe_t = float(row.get('VOLUME_PE_T', 0.0))
                vol_ce_tm1 = float(row.get('VOLUME_CE_TM1', 0.0))
                vol_pe_tm1 = float(row.get('VOLUME_PE_TM1', 0.0))
                
                vol_t = vol_ce_t + vol_pe_t
                vol_tm1 = vol_ce_tm1 + vol_pe_tm1
                vol_delta = vol_t - vol_tm1
                
                pe_oi_scaled = chg_pe_t / 1e5
                ce_oi_scaled = chg_ce_t / 1e5
                vol_delta_scaled = vol_delta / 1e5
                gex_shift_scaled = gex_shift / 2e5
                price_acc = spot_chg
                
                ifs = (0.35 * pe_oi_scaled) - (0.35 * ce_oi_scaled) + (0.10 * vol_delta_scaled) + (0.10 * gex_shift_scaled) + (0.10 * price_acc)
                ifs_final = round(max(-100.0, min(100.0, ifs * 15.0)), 1)
                
                # Basic Persistence Count Seeding
                if symbol not in persistence_tracker:
                    persistence_tracker[symbol] = {"bullish_days": 0, "bearish_days": 0}
                    
                if net_bull_inv_shift > 50000:
                    persistence_tracker[symbol]["bullish_days"] += 1
                    persistence_tracker[symbol]["bearish_days"] = 0
                elif net_bull_inv_shift < -50000:
                    persistence_tracker[symbol]["bearish_days"] += 1
                    persistence_tracker[symbol]["bullish_days"] = 0
                
                bull_persist = persistence_tracker[symbol]["bullish_days"]
                bear_persist = persistence_tracker[symbol]["bearish_days"]
                
                gamma_regime = "TRANSITION_REGIME"
                if gex_t > 200000:
                    gamma_regime = "LONG_GAMMA"
                elif gex_t < -10000:
                    gamma_regime = "SHORT_GAMMA"
                
                # Fetch history compiled so far to run true longitudinal models
                sym_history_list = []
                if symbol in session_history:
                    sorted_pd_dates = sorted(list(session_history[symbol].keys()))
                    for pd_date in sorted_pd_dates:
                        sym_history_list.append(session_history[symbol][pd_date])

                # ── IV Rank Calculation ──
                iv_history = [s.get("iv", 0.0) for s in sym_history_list]
                if iv_history:
                    iv_min = min(iv_history)
                    iv_max = max(iv_history)
                    iv_rank = ((iv_t - iv_min) / (iv_max - iv_min) * 100.0) if iv_max > iv_min else 50.0
                else:
                    iv_rank = 50.0

                # ── Skew Slope Check (OTM Call vs ATM Call Ratio) ──
                skew_slope = 1.0
                # Using average option prices close CE vs PE to approximate skew slope
                if row.get('CLOSE_CE_T', 0.0) > 0 and row.get('CLOSE_PE_T', 0.0) > 0:
                    skew_slope = float(row.get('CLOSE_CE_T') / row.get('CLOSE_PE_T'))

                # Setup screener scan rules
                setups = []
                # 1. GAMMA_SQUEEZE (Tier 1: Volatility Expansion)
                if (gamma_regime == "SHORT_GAMMA" and spot_t > 0 and call_wall_t > 0 and 0 < (call_wall_t - spot_t) / spot_t <= 0.025 and net_bull_inv_shift > 0) or (spot_chg > 2.0 and gamma_regime == "SHORT_GAMMA"):
                    setups.append("GAMMA_SQUEEZE")
                
                # 2. VOLATILITY_COIL (Tier 1: Volatility Compression)
                if abs(spot_chg) <= 0.4 and abs(gex_intensity) < 15:
                    setups.append("VOLATILITY_COIL")
                
                # 3. FLOOR_BOUNCE (Tier 2: Support Floor Bounce)
                if gamma_regime == "LONG_GAMMA" and spot_t > 0 and put_wall_t > 0 and abs(spot_t - put_wall_t) / spot_t <= 0.025 and net_bull_inv_shift > 20000:
                    setups.append("FLOOR_BOUNCE")
                
                # 4. DEALER_DEFENSE (Tier 2: Dealer Pin Zones)
                if gamma_regime == "LONG_GAMMA" and abs(gex_intensity) > 75 and gamma_flip_t > 0 and abs(spot_t - gamma_flip_t) / spot_t <= 0.015:
                    setups.append("DEALER_DEFENSE")
                
                # 5. REGIME_SHIFT (Tier 3: Regime Flip Transition)
                if (spot_t > gamma_flip_t > 0 and 0 < spot_tm1 <= gamma_flip_tm1 and net_bull_inv_shift > 0) or (gamma_flip_t > 0 and abs(spot_t - gamma_flip_t) / spot_t <= 0.008):
                    setups.append("REGIME_SHIFT")
                
                # 6. INVENTORY_MIGRATION (Tier 3: Wall Migration Breakout / Collapse)
                if (put_wall_t != put_wall_tm1 and put_wall_t > 0 and put_wall_tm1 > 0) or (call_wall_t != call_wall_tm1 and call_wall_t > 0 and call_wall_tm1 > 0):
                    setups.append("INVENTORY_MIGRATION")
                
                # 7. PINCH_ZONE (Tier 2: All walls converged — Compression Breakout Setup)
                # Fires only when INVENTORY_MIGRATION did NOT trigger (walls static but all pinched)
                if (
                    "INVENTORY_MIGRATION" not in setups
                    and call_wall_t > 0 and put_wall_t > 0 and gamma_flip_t > 0
                    and abs(call_wall_t - put_wall_t) < 1.0
                    and abs(call_wall_t - gamma_flip_t) < 1.0
                    and spot_t > 0
                    and abs(spot_t - gamma_flip_t) / spot_t <= 0.04
                ):
                    setups.append("PINCH_ZONE")

                # 8. IV_SPIKE Setup (Vol Spike - Premium Rich)
                if iv_shift > 4.5 and iv_rank > 70:
                    setups.append("IV_SPIKE")

                # 9. IV_CRUSH Setup (Vol Crush - Post Event)
                if iv_shift < -4.5 and iv_rank < 35:
                    setups.append("IV_CRUSH")

                # 10. IV_SKEW_ACCUMULATION Setup (Speculative Skew Chase)
                if spot_t > 0 and call_wall_t > 0 and 0 < (call_wall_t - spot_t) / spot_t <= 0.03 and skew_slope > 1.15:
                    setups.append("IV_SKEW_ACCUMULATION")
                
                # Ratios for conviction circle
                instab_factor = min(10.0, abs(gex_intensity) / 15.0) / 10.0
                asym_factor = min(10.0, abs(pcr_t - 1.0) / 0.5) / 10.0
                price_factor = min(10.0, abs(spot_chg) / (iv_t * 100 + 0.1)) / 10.0
                vol_factor = min(10.0, vol_t / 5e5) / 10.0

                # Dynamic Setup Details
                setups_details = {}
                for setup in setups:
                    if setup == "GAMMA_SQUEEZE":
                        setups_details["GAMMA_SQUEEZE"] = {"expected_range": f"₹{spot_t * 0.995:,.1f} to ₹{spot_t * (1 + iv_t * 0.6):,.1f}", "trigger_strike": float(call_wall_t), "risk_zone": f"Below ₹{gamma_flip_t:,.0f}"}
                    elif setup == "VOLATILITY_COIL":
                        setups_details["VOLATILITY_COIL"] = {"expected_range": f"₹{spot_t * (1 - iv_t * 0.4):,.1f} to ₹{spot_t * (1 + iv_t * 0.4):,.1f}", "trigger_strike": float(gamma_flip_t), "risk_zone": "Symmetric break"}
                    elif setup == "FLOOR_BOUNCE":
                        setups_details["FLOOR_BOUNCE"] = {"expected_range": f"₹{put_wall_t:,.1f} to ₹{spot_t * (1 + iv_t * 0.4):,.1f}", "trigger_strike": float(put_wall_t), "risk_zone": f"Below ₹{put_wall_t:,.0f}"}
                    elif setup == "DEALER_DEFENSE":
                        setups_details["DEALER_DEFENSE"] = {"expected_range": f"₹{gamma_flip_t * 0.985:,.1f} to ₹{gamma_flip_t * 1.015:,.1f}", "trigger_strike": float(gamma_flip_t), "risk_zone": "Pin break range"}
                    elif setup == "REGIME_SHIFT":
                        setups_details["REGIME_SHIFT"] = {"expected_range": f"₹{spot_t * 0.99:,.1f} to ₹{spot_t * (1 + iv_t * 0.7):,.1f}", "trigger_strike": float(gamma_flip_t), "risk_zone": f"Below ₹{gamma_flip_t:,.0f}"}
                    elif setup == "INVENTORY_MIGRATION":
                        setups_details["INVENTORY_MIGRATION"] = {"expected_range": f"₹{spot_t * 0.99:,.1f} to ₹{spot_t * (1 + iv_t * 0.6):,.1f}", "trigger_strike": float(put_wall_t), "risk_zone": f"Below ₹{put_wall_t:,.0f}"}
                    elif setup == "PINCH_ZONE":
                        setups_details["PINCH_ZONE"] = {"expected_range": f"₹{gamma_flip_t * 0.97:,.1f} to ₹{gamma_flip_t * 1.03:,.1f}", "trigger_strike": float(gamma_flip_t), "risk_zone": f"Break ₹{gamma_flip_t:,.0f} — above=bull, below=bear"}
                
                # Base snapshot data
                day_data = {
                    "date": date_t,
                    "spot_close": spot_t,
                    "spot_change_pct": spot_chg,
                    "futures_oi": float(row.get('FUT_OI_T', 0.0)),
                    "futures_oi_chg": float(row.get('FUT_CHG_OI_T', 0.0)),
                    "pcr": pcr_t,
                    "total_ce_oi": oi_ce_t,
                    "total_pe_oi": oi_pe_t,
                    "delta_ce_oi": chg_ce_t,
                    "delta_pe_oi": chg_pe_t,
                    "total_volume": vol_t,
                    "delta_volume": vol_delta,
                    "net_inv_shift": net_bull_inv_shift,
                    "ifs_score": ifs_final,
                    "call_wall": call_wall_t,
                    "put_wall": put_wall_t,
                    "gamma_flip": gamma_flip_t,
                    "gex": gex_t,
                    "gex_intensity": gex_intensity,
                    "gex_shift": gex_shift,
                    "gamma_regime": gamma_regime,
                    "iv": iv_t,
                    "iv_shift": iv_shift,
                    "bullish_persistence": bull_persist,
                    "bearish_persistence": bear_persist,
                    "setups": setups,
                    "setups_details": setups_details,
                    "ce_interp": row.get('CE_INTERP', 'Neutral'),
                    "pe_interp": row.get('PE_INTERP', 'Neutral'),
                    "suggested_strategy": row.get('SUGGESTED_STRATEGY', 'Wait for Setup'),
                    # Expiry rollover flag — True on days when an index weekly series
                    # expired overnight and was stripped from T-1 before delta computation.
                    "expiry_filtered": expiry_filtered,
                    "dropped_expiry_dates": dropped_expiry_dates,
                }
                
                # ── True Longitudinal Engine Mappings ──
                sym_history_list_temp = sym_history_list + [day_data]
                
                smart_money_persistence = long_engine.compute_smart_money_persistence(symbol, sym_history_list_temp)
                migrations = long_engine.detect_wall_migrations(sym_history_list_temp)
                structural_bias = struct_classifier.classify_structure(day_data, setups)
                
                # Compute conviction
                conviction_score = (
                    30.0 * (smart_money_persistence / 100.0) +
                    20.0 * instab_factor +
                    20.0 * asym_factor +
                    15.0 * price_factor +
                    15.0 * vol_factor
                )
                conviction_score = round(max(0.0, min(100.0, conviction_score * 1.5)), 1)
                
                # Priority Score
                inv_persist = max(bull_persist, bear_persist) + 1.0
                gamma_instab = (abs(gex_intensity) / 10.0) + 1.0
                price_comp = 5.0 / (abs(spot_chg) + 0.1)
                priority_score = round(inv_persist * gamma_instab * price_comp, 2)
                
                # Rapid crossover regime shift
                regime_transition = migrations["regime_change"]
                
                # Compile playbook
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
                        playbook = {
                            "bias": "Strong Bullish Momentum",
                            "trigger_strike": float(call_wall_t),
                            "invalidation_strike": float(put_wall_t),
                            "expected_behavior": "Bullish Trend Extension",
                            "dealer_behavior": "Dual Wall Upward Migration"
                        }
                    elif put_down and call_down:
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
                        if spot_t > put_wall_t and spot_chg > 0:
                            playbook = {
                                "bias": "Support Normalization",
                                "trigger_strike": float(put_wall_t),
                                "invalidation_strike": float(put_wall_t * 0.985),
                                "expected_behavior": "Bullish Rebalancing",
                                "dealer_behavior": "Support Floor Normalization"
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
                    playbook = {
                        "bias": "Bullish Breakout",
                        "trigger_strike": float(call_wall_t),
                        "invalidation_strike": float(spot_t * 0.97),
                        "expected_behavior": "Upside Skew Chase Breakout",
                        "dealer_behavior": "Speculative Call Buying Squeeze"
                    }
                elif ifs_final > 15:
                    playbook = {"bias": "Bullish Bias", "trigger_strike": float(call_wall_t), "invalidation_strike": float(put_wall_t), "expected_behavior": "Support Floor Building", "dealer_behavior": "Put Writing Support"}
                elif ifs_final < -15:
                    playbook = {"bias": "Bearish Bias", "trigger_strike": float(put_wall_t), "invalidation_strike": float(call_wall_t), "expected_behavior": "Ceiling Reinforcement", "dealer_behavior": "Call Writing Reinforcement"}

                # ── Setup-Aware High-Fidelity Suggested Strategy Override ──
                s_strat = row.get('SUGGESTED_STRATEGY', 'Wait for Setup')
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
                        # Spot below gamma flip + put skew building → sell the rally cap
                        s_strat = "Bear Call Spread (Credit)"
                    else:
                        # Neutral / Regime Transition — defer to gamma_regime
                        s_strat = "Bull Call Spread (Debit)" if gamma_regime == "LONG_GAMMA" else "Bear Call Spread (Credit)"
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
                
                day_data["suggested_strategy"] = s_strat

                # Save updated longitudinal stats
                day_data["conviction_score"] = conviction_score
                day_data["priority_score"] = priority_score
                day_data["smart_money_persistence"] = smart_money_persistence
                day_data["put_wall_shift"] = migrations["put_shift"]
                day_data["call_wall_shift"] = migrations["call_shift"]
                day_data["regime_change"] = migrations["regime_change"]
                day_data["put_wall_pct_change"] = migrations["put_wall_pct_change"]
                day_data["call_wall_pct_change"] = migrations["call_wall_pct_change"]
                day_data["structural_bias"] = structural_bias
                day_data["regime_transition"] = regime_transition
                day_data["playbook"] = playbook
                
                if symbol not in session_history:
                    session_history[symbol] = {}
                session_history[symbol][date_t] = day_data
                
        except Exception as e:
            print(f"[!] Failed compiling session for date {date_t}: {e}")
            import traceback
            traceback.print_exc()

    # ─────────────────────────────────────────────────────────────────────────────
    # COMPILING BREADTH AND CHANGE ALERTS LEDGER
    # ─────────────────────────────────────────────────────────────────────────────
    print("\n[*] Processing global market breadth and change events...")
    all_symbols = sorted(list(session_history.keys()))
    all_dates = []
    if all_symbols:
        for sym in all_symbols:
            all_dates.extend(list(session_history[sym].keys()))
    unique_dates = sorted(list(set(all_dates)))
    
    market_breadth_history = {}
    market_changes_history = {}
    
    for idx, d_t in enumerate(unique_dates):
        breadth = breadth_engine.compute_market_breadth(d_t, session_history)
        market_breadth_history[d_t] = breadth
        
        prev_d = unique_dates[idx-1] if idx > 0 else None
        changes = breadth_engine.detect_daily_changes(d_t, prev_d, session_history)
        market_changes_history[d_t] = changes

    # ─────────────────────────────────────────────────────────────────────────────
    # DATA FLATTENING FOR COLUMNAR PARQUET EXPORTS
    # ─────────────────────────────────────────────────────────────────────────────
    print("[*] Flattening compiled datasets into Pandas structures...")
    
    structure_rows = []
    setups_rows = []
    inventory_rows = []
    
    for sym, history in session_history.items():
        for d_t, day_data in history.items():
            # A. Structure records
            structure_rows.append({
                "symbol": sym,
                "date": d_t,
                "spot_close": day_data["spot_close"],
                "spot_change_pct": day_data["spot_change_pct"],
                "futures_oi": day_data.get("futures_oi", 0.0),
                "futures_oi_chg": day_data.get("futures_oi_chg", 0.0),
                "pcr": day_data["pcr"],
                "total_ce_oi": day_data["total_ce_oi"],
                "total_pe_oi": day_data["total_pe_oi"],
                "delta_ce_oi": day_data["delta_ce_oi"],
                "delta_pe_oi": day_data["delta_pe_oi"],
                "total_volume": day_data["total_volume"],
                "delta_volume": day_data["delta_volume"],
                "net_inv_shift": day_data["net_inv_shift"],
                "ifs_score": day_data["ifs_score"],
                "smart_money_persistence": day_data["smart_money_persistence"],
                "conviction_score": day_data["conviction_score"],
                "priority_score": day_data["priority_score"],
                "structural_bias": day_data["structural_bias"],
                "regime_transition": bool(day_data["regime_transition"]),
                "call_wall": day_data["call_wall"],
                "put_wall": day_data["put_wall"],
                "gamma_flip": day_data["gamma_flip"],
                "gex": day_data["gex"],
                "gex_intensity": day_data["gex_intensity"],
                "gex_shift": day_data["gex_shift"],
                "gamma_regime": day_data["gamma_regime"],
                "iv": day_data["iv"],
                "iv_shift": day_data["iv_shift"],
                "ce_interp": day_data.get("ce_interp", "Neutral"),
                "pe_interp": day_data.get("pe_interp", "Neutral"),
                "suggested_strategy": day_data.get("suggested_strategy", "Wait for Setup")
            })
            
            # B. Playbook & Setups
            setups_list = day_data.get("setups", [])
            playbook = day_data.get("playbook", {})
            if setups_list:
                for s_type in setups_list:
                    setups_rows.append({
                        "symbol": sym,
                        "date": d_t,
                        "setup_type": s_type,
                        "bias": playbook.get("bias", "Neutral"),
                        "trigger_strike": playbook.get("trigger_strike", 0.0),
                        "invalidation_strike": playbook.get("invalidation_strike", 0.0),
                        "expected_behavior": playbook.get("expected_behavior", "Mean Reversion"),
                        "dealer_behavior": playbook.get("dealer_behavior", "Long Gamma")
                    })
            else:
                setups_rows.append({
                    "symbol": sym,
                    "date": d_t,
                    "setup_type": "NONE",
                    "bias": playbook.get("bias", "Neutral"),
                    "trigger_strike": playbook.get("trigger_strike", 0.0),
                    "invalidation_strike": playbook.get("invalidation_strike", 0.0),
                    "expected_behavior": playbook.get("expected_behavior", "Mean Reversion"),
                    "dealer_behavior": playbook.get("dealer_behavior", "Long Gamma")
                })
                
            # C. Inventory Shifts
            inventory_rows.append({
                "symbol": sym,
                "date": d_t,
                "put_wall_shift": day_data.get("put_wall_shift", "Stable"),
                "call_wall_shift": day_data.get("call_wall_shift", "Stable"),
                "regime_change": bool(day_data.get("regime_change", False)),
                "put_wall_pct_change": float(day_data.get("put_wall_pct_change", 0.0)),
                "call_wall_pct_change": float(day_data.get("call_wall_pct_change", 0.0)),
                "bullish_persistence": int(day_data.get("bullish_persistence", 0)),
                "bearish_persistence": int(day_data.get("bearish_persistence", 0))
            })

    # D. Breadth Rows
    breadth_rows = []
    for d_t, b in market_breadth_history.items():
        breadth_rows.append({
            "date": d_t,
            "bullish_pct": b["bullish_pct"],
            "bearish_pct": b["bearish_pct"],
            "compression_pct": b["compression_pct"],
            "expansion_pct": b["expansion_pct"],
            "transition_pct": b["transition_pct"],
            "mean_rev_pct": b["mean_rev_pct"],
            "total_symbols": b["total_symbols"]
        })
        
    # E. Changes Rows
    changes_rows = []
    for d_t, alerts_list in market_changes_history.items():
        for a in alerts_list:
            changes_rows.append({
                "date": d_t,
                "symbol": a["symbol"],
                "icon": a["icon"],
                "type": a["type"],
                "msg": a["msg"],
                "rank": a.get("rank", 999)
            })

    # Convert to DataFrames
    df_structure = pd.DataFrame(structure_rows)
    df_setups = pd.DataFrame(setups_rows)
    df_inventory = pd.DataFrame(inventory_rows)
    df_breadth = pd.DataFrame(breadth_rows)
    df_changes = pd.DataFrame(changes_rows) if changes_rows else pd.DataFrame(columns=["date", "symbol", "icon", "type", "msg", "rank"])

    # ─────────────────────────────────────────────────────────────────────────────
    # EXPORTING TO COLUMNAR PARQUET & DUCKDB INDEX
    # ─────────────────────────────────────────────────────────────────────────────
    output_dir = "data/compiled"
    os.makedirs(output_dir, exist_ok=True)
    
    print("\n[*] Exporting compressed Parquet files to disk...")
    df_structure.to_parquet(os.path.join(output_dir, "daily_market_structure.parquet"), index=False)
    df_setups.to_parquet(os.path.join(output_dir, "daily_setups.parquet"), index=False)
    df_inventory.to_parquet(os.path.join(output_dir, "daily_inventory.parquet"), index=False)
    df_breadth.to_parquet(os.path.join(output_dir, "daily_market_breadth.parquet"), index=False)
    df_changes.to_parquet(os.path.join(output_dir, "daily_changes.parquet"), index=False)

    print("[*] Creating institutional DuckDB database (vanguard.duckdb)...")
    db_path = os.path.join(output_dir, "vanguard.duckdb")
    if os.path.exists(db_path):
        os.remove(db_path)
        
    import duckdb
    conn = duckdb.connect(db_path)
    conn.execute("CREATE TABLE daily_market_structure AS SELECT * FROM df_structure")
    conn.execute("CREATE TABLE daily_setups AS SELECT * FROM df_setups")
    conn.execute("CREATE TABLE daily_inventory AS SELECT * FROM df_inventory")
    conn.execute("CREATE TABLE daily_market_breadth AS SELECT * FROM df_breadth")
    conn.execute("CREATE TABLE daily_changes AS SELECT * FROM df_changes")
    conn.close()

    # Backwards compatibility JSON dump
    output_json = os.path.join(output_dir, "session_history.json")
    with open(output_json, "w") as f:
        json.dump(session_history, f, indent=4)

    print("\n" + "=" * 80)
    print("[SUCCESS] Columnar database compiles chronologically!")
    print(f"Parquet files location: {output_dir}")
    print(f"DuckDB DB Location: {db_path}")
    print(f"Total Symbols Indexed: {len(session_history)}")
    print("=" * 80)

if __name__ == "__main__":
    main()
