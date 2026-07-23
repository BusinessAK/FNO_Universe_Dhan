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

sys.path.insert(0, os.path.dirname(__file__))

from vanguard.intelligence import InstitutionalIntelligence
from vanguard.core.longitudinal import LongitudinalEngine
from vanguard.core.playbook import build_playbook
from vanguard.core.config import SETUP_PRIORITY
from vanguard.rules.setup_screener import screen, SetupInputs
from vanguard.rules.setup_positions import derive_positions
from vanguard.core.classifier import StructureClassifier
from vanguard.core.breadth import MarketBreadthEngine
from vanguard.core.cash_market_breadth import CashMarketBreadthEngine
from vanguard.config.sector_mapping import get_sector

def extract_date(filename):
    """Extracts YYYY-MM-DD from NSE bhavcopy filename."""
    match = re.search(r'\d{8}', filename)
    if match:
        date_str = match.group(0)
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    return None

def safe_float(val, default=0.0):
    """Safely cast value to float, returning default if None, NaN, or non-numeric."""
    if val is None or val != val:
        return default
    try:
        return float(val)
    except Exception:
        return default

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
    cm_breadth_engine = CashMarketBreadthEngine()
    
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
            
    # Force re-compilation of the latest scanned date to pick up any logic/UI overrides
    if not force_compile and compiled_dates and len(files) > 0:
        latest_scanned_date = extract_date(files[-1])
        if latest_scanned_date in compiled_dates:
            compiled_dates.discard(latest_scanned_date)
            print(f"[*] Forcing re-compilation of the latest session: {latest_scanned_date}")
            
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
        except Exception as e:
            print(f"[!] Failed compiling session for date {date_t}: {e}")
            import traceback
            traceback.print_exc()
            continue

        for _, row in df_intel.iterrows():
            # Per-symbol guard: one bad symbol must not abort the rest of the session
            try:
                symbol = row['SYMBOL']
                
                # Core daily metrics
                spot_t = safe_float(row.get('SPOT_T'))
                spot_tm1 = safe_float(row.get('SPOT_TM1'))
                spot_chg = safe_float(row.get('SPOT_CHG_PCT'))
                pcr_t = safe_float(row.get('PCR_T'))
                
                oi_ce_t = safe_float(row.get('OPEN_INT_CE_T'))
                oi_pe_t = safe_float(row.get('OPEN_INT_PE_T'))
                chg_ce_t = safe_float(row.get('CHG_IN_OI_CE_T'))
                chg_pe_t = safe_float(row.get('CHG_IN_OI_PE_T'))
                
                call_wall_t = safe_float(row.get('CALL_WALL_T'))
                put_wall_t = safe_float(row.get('PUT_WALL_T'))
                gamma_flip_t = safe_float(row.get('GAMMA_FLIP_T'))
                
                # Fetch previous session parameters from compiled history to support longitudinal setups
                prev_session = session_history.get(symbol, {}).get(date_tm1, {})
                call_wall_tm1 = safe_float(prev_session.get("call_wall"))
                put_wall_tm1 = safe_float(prev_session.get("put_wall"))
                gamma_flip_tm1 = safe_float(prev_session.get("gamma_flip"))
                
                gex_t = safe_float(row.get('GEX_T'))
                gex_intensity = safe_float(row.get('GEX_INTENSITY'))
                gex_shift = safe_float(row.get('GEX_SHIFT'))
                
                iv_t = safe_float(row.get('IV_T'))
                iv_shift = safe_float(row.get('IV_SHIFT'))
                
                net_bull_inv_shift = safe_float(row.get('NET_BULL_INV_SHIFT'))

                # Expiry rollover metadata — populated by intelligence.py when a weekly
                # index series was stripped from T-1 before delta computation.
                # Same value for all symbols on a given day (it's a session-level event).
                expiry_filtered      = bool(row.get('EXPIRY_FILTERED', False))
                dropped_expiry_dates = str(row.get('DROPPED_EXPIRY_DATES', ''))

                
                # IFS Score Computation
                lot_size = safe_float(row.get('LOT_SIZE', 1.0))
                
                vol_ce_t = safe_float(row.get('VOLUME_CE_T')) * lot_size
                vol_pe_t = safe_float(row.get('VOLUME_PE_T')) * lot_size
                vol_ce_tm1 = safe_float(row.get('VOLUME_CE_TM1')) * lot_size
                vol_pe_tm1 = safe_float(row.get('VOLUME_PE_TM1')) * lot_size
                
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
                else:
                    # Neutral flow day breaks the streak — persistence counts
                    # strictly consecutive sessions. (A/B vs freeze-on-neutral
                    # showed higher rank IC and cleaner bucket monotonicity.)
                    persistence_tracker[symbol]["bullish_days"] = 0
                    persistence_tracker[symbol]["bearish_days"] = 0

                bull_persist = persistence_tracker[symbol]["bullish_days"]
                bear_persist = persistence_tracker[symbol]["bearish_days"]

                # Scale-free gamma regime: spot vs gamma flip, shared with
                # market_structure_engine + the live structure engine so all
                # three can never silently diverge (see InstitutionalIntelligence
                # .gamma_regime in vanguard/intelligence.py).
                gamma_regime = InstitutionalIntelligence.gamma_regime(spot_t, gamma_flip_t, gex_t)
                
                # Fetch history compiled so far to run true longitudinal models
                sym_history_list = []
                if symbol in session_history:
                    # Exclude date_t itself: on incremental runs the latest session is
                    # force-recompiled while its previous compile is still in history —
                    # including it would make migrations/flips compare today vs old-today.
                    sorted_pd_dates = sorted(d for d in session_history[symbol].keys() if d < date_t)
                    for pd_date in sorted_pd_dates:
                        sym_history_list.append(session_history[symbol][pd_date])

                # ── IV Rank Calculation ──
                # Skip zero placeholders (days where IV failed to compute) so they
                # don't become iv_min and inflate every subsequent rank.
                iv_history = [s.get("iv", 0.0) for s in sym_history_list if s.get("iv", 0.0) > 0]
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

                # Setup screener — the 10 rules live in vanguard/rules/setup_screener.py
                # (wave 2 / R1 extraction; parity-gated against the old inline block).
                setups = screen(SetupInputs(
                    spot_t=spot_t, spot_tm1=spot_tm1, spot_chg=spot_chg,
                    call_wall_t=call_wall_t, call_wall_tm1=call_wall_tm1,
                    put_wall_t=put_wall_t, put_wall_tm1=put_wall_tm1,
                    gamma_flip_t=gamma_flip_t, gamma_flip_tm1=gamma_flip_tm1,
                    gamma_regime=gamma_regime, gex_intensity=gex_intensity,
                    net_bull_inv_shift=net_bull_inv_shift,
                    iv_shift=iv_shift, iv_rank=iv_rank, skew_slope=skew_slope,
                    pe_interp=row.get('PE_INTERP', ''),
                ))
                
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
                    "futures_oi": safe_float(row.get('FUT_OI_T')),
                    "futures_oi_chg": safe_float(row.get('FUT_CHG_OI_T')),
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
                    "skew_slope": skew_slope,
                    "iv_rank": iv_rank,
                    "expiry_filtered": expiry_filtered,
                    "dropped_expiry_dates": dropped_expiry_dates,
                }
                
                # ── True Longitudinal Engine Mappings ──
                sym_history_list_temp = sym_history_list + [day_data]
                
                smart_money_persistence = long_engine.compute_smart_money_persistence(symbol, sym_history_list_temp)
                migrations = long_engine.detect_wall_migrations(sym_history_list_temp)
                structural_bias = struct_classifier.classify_structure(day_data, setups)
                # Assign before detect_structure_flip — it reads structural_bias off the
                # current day (last element of sym_history_list_temp is day_data itself).
                day_data["structural_bias"] = structural_bias
                structure_flip_data = long_engine.detect_structure_flip(sym_history_list_temp)
                
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
                
                # Compile playbook + setup-aware strategy override (vanguard/core/playbook.py)
                # Primary setup by shared precedence; the playbook is built for
                # THAT setup only, so setup_type and playbook always agree.
                primary_setup = next((p for p in SETUP_PRIORITY if p in setups),
                                     setups[0] if setups else None)
                day_data["primary_setup"] = primary_setup or "NONE"
                playbook, s_strat = build_playbook(
                    setups=[primary_setup] if primary_setup else [],
                    spot_t=spot_t,
                    call_wall_t=call_wall_t,
                    put_wall_t=put_wall_t,
                    gamma_flip_t=gamma_flip_t,
                    call_wall_tm1=call_wall_tm1,
                    put_wall_tm1=put_wall_tm1,
                    ifs_final=ifs_final,
                    gamma_regime=gamma_regime,
                    spot_chg=spot_chg,
                    skew_slope=skew_slope,
                    base_strategy=row.get('SUGGESTED_STRATEGY', 'Wait for Setup'),
                    pe_interp=row.get('PE_INTERP', ''),
                )
                day_data["suggested_strategy"] = s_strat

                setup_biases = {}
                for _s in setups:
                    if _s == primary_setup:
                        setup_biases[_s] = playbook.get("bias", "Neutral")
                    else:
                        _pb, _ = build_playbook(
                            setups=[_s], spot_t=spot_t, call_wall_t=call_wall_t,
                            put_wall_t=put_wall_t, gamma_flip_t=gamma_flip_t,
                            call_wall_tm1=call_wall_tm1, put_wall_tm1=put_wall_tm1,
                            ifs_final=ifs_final, gamma_regime=gamma_regime,
                            spot_chg=spot_chg, skew_slope=skew_slope,
                            base_strategy=row.get('SUGGESTED_STRATEGY', 'Wait for Setup'),
                            pe_interp=row.get('PE_INTERP', ''),
                        )
                        setup_biases[_s] = _pb.get("bias", "Neutral")
                day_data["setup_biases"] = setup_biases

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
                # ── Structure Flip Metadata ─────────────────────────────────────────────────
                day_data["structure_flip"]        = structure_flip_data["flip_type"]
                day_data["prev_structural_bias"]  = structure_flip_data["prev_bias"]
                day_data["flip_confidence"]        = structure_flip_data["flip_confidence"]
                day_data["flip_strength"]          = structure_flip_data["flip_strength"]
                
                if symbol not in session_history:
                    session_history[symbol] = {}
                session_history[symbol][date_t] = day_data

            except Exception as e:
                print(f"[!] {row.get('SYMBOL', '?')} failed on {date_t}: {e} — symbol skipped")
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

    # macro_regime_prob is held at 0.0 (ML macro gate decommissioned)
    for d_t, mb in market_breadth_history.items():
        mb["macro_regime_prob"] = 0.0

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
                "sector": get_sector(sym),
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
                # ── Structure Flip Columns ──
                "structure_flip":       day_data.get("structure_flip", "NONE"),
                "prev_structural_bias": day_data.get("prev_structural_bias", ""),
                "flip_confidence":      float(day_data.get("flip_confidence", 0.0)),
                "flip_strength":        day_data.get("flip_strength", "WEAK"),
                "call_wall": day_data["call_wall"],
                "put_wall": day_data["put_wall"],
                "gamma_flip": day_data["gamma_flip"],
                "gex": day_data["gex"],
                "gex_intensity": day_data["gex_intensity"],
                "gex_shift": day_data["gex_shift"],
                "gamma_regime": day_data["gamma_regime"],
                "iv": day_data["iv"],
                "iv_shift": day_data["iv_shift"],
                "iv_rank": day_data.get("iv_rank", 50.0),
                "skew_slope": day_data.get("skew_slope", 1.0),
                "ce_interp": day_data.get("ce_interp", "Neutral"),
                "pe_interp": day_data.get("pe_interp", "Neutral"),
                "suggested_strategy": day_data.get("suggested_strategy", "Wait for Setup"),
            })
            
            # B. Playbook & Setups
            # One row per (symbol, date). When multiple setup types fire simultaneously,
            # collapse to the highest-priority type (setup_type) and store all triggered
            # types pipe-delimited in setup_types for research queries.
            setups_list = day_data.get("setups", [])
            playbook = day_data.get("playbook", {})
            # No-setup days are not persisted — every consumer filters setup_type != 'NONE'
            if setups_list:
                # Prefer the primary recorded at compute time (playbook was built
                # for it); fall back to recomputing for history entries compiled
                # before primary_setup existed.
                primary_type = day_data.get("primary_setup")
                if not primary_type or primary_type == "NONE":
                    primary_type = next((p for p in SETUP_PRIORITY if p in setups_list),
                                        setups_list[0])
                setups_rows.append({
                    "symbol": sym,
                    "sector": get_sector(sym),
                    "date": d_t,
                    "setup_type": primary_type,
                    "setup_types": "|".join(setups_list),
                    "setup_biases": "|".join(
                        f"{k}:{v}" for k, v in day_data.get("setup_biases", {}).items()),
                    "bias": playbook.get("bias", "Neutral"),
                    "trigger_strike": playbook.get("trigger_strike", 0.0),
                    "invalidation_strike": playbook.get("invalidation_strike", 0.0),
                    "expected_behavior": playbook.get("expected_behavior", "Mean Reversion"),
                    "dealer_behavior": playbook.get("dealer_behavior", "Long Gamma")
                })
                
            # C. Inventory Shifts
            inventory_rows.append({
                "symbol": sym,
                "sector": get_sector(sym),
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
            "total_symbols": b["total_symbols"],
            "macro_regime_prob": b.get("macro_regime_prob", 0.0)
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

    # Position lifecycle (trigger -> SL/target resolution) — a pure re-
    # derivation from session_history on every run, same as daily_setups
    # itself; see vanguard/rules/setup_positions.py for why this can't be a
    # stateful incremental job in this pipeline.
    position_rows = derive_positions(session_history)
    for row in position_rows:
        row["sector"] = get_sector(row["symbol"])
    df_positions = pd.DataFrame(position_rows) if position_rows else pd.DataFrame(columns=[
        "symbol", "sector", "setup_type", "bias", "direction", "trigger_date",
        "trigger_price", "sl_price", "target_price", "status",
        "resolved_date", "resolved_price"])

    df_inventory = pd.DataFrame(inventory_rows)
    df_breadth = pd.DataFrame(breadth_rows)
    df_changes = pd.DataFrame(changes_rows) if changes_rows else pd.DataFrame(columns=["date", "symbol", "icon", "type", "msg", "rank"])

    # ─────────────────────────────────────────────────────────────────────────────
    # CASH MARKET BREADTH (full NSE EQ universe ~2,400 symbols)
    # Additive: does not modify existing daily_market_breadth F&O table.
    # ─────────────────────────────────────────────────────────────────────────────
    cm_parquet_path = os.path.join("data", "compiled", "cash_market_prices.parquet")
    cm_breadth_output = os.path.join(output_dir, "daily_cm_breadth.parquet")
    df_cm_breadth = pd.DataFrame()  # fallback if CM parquet not present
    if os.path.exists(cm_parquet_path):
        try:
            df_cm_breadth = cm_breadth_engine.build_cm_breadth(cm_parquet_path, cm_breadth_output)
        except Exception as e:
            print(f"[!] CM breadth computation failed (non-fatal): {e}")
    else:
        print("[!] cash_market_prices.parquet not found — skipping CM breadth. Run cash_market_builder.py first.")

    # ─────────────────────────────────────────────────────────────────────────────
    # EXPORTING TO COLUMNAR PARQUET & DUCKDB INDEX
    # ─────────────────────────────────────────────────────────────────────────────
    output_dir = "data/compiled"
    os.makedirs(output_dir, exist_ok=True)
    
    print("\n[*] Exporting compressed Parquet files to disk...")
    df_structure.to_parquet(os.path.join(output_dir, "daily_market_structure.parquet"), index=False)
    df_setups.to_parquet(os.path.join(output_dir, "daily_setups.parquet"), index=False)
    df_positions.to_parquet(os.path.join(output_dir, "daily_setup_positions.parquet"), index=False)
    df_inventory.to_parquet(os.path.join(output_dir, "daily_inventory.parquet"), index=False)
    df_breadth.to_parquet(os.path.join(output_dir, "daily_market_breadth.parquet"), index=False)
    df_changes.to_parquet(os.path.join(output_dir, "daily_changes.parquet"), index=False)

    print("[*] Creating institutional DuckDB database (vanguard.duckdb)...")
    db_path = os.path.join(output_dir, "vanguard.duckdb")
    # Additive connect, never delete the file: this DB is shared with
    # vanguard/pipeline/context/ (delivery, participant OI, VIX, ban,
    # FII/DII, corporate events) and equity_compiler.py's daily_equity_*
    # tables, none of which this script knows about or should touch.
    # CREATE OR REPLACE TABLE fully replaces each of daily_compiler.py's OWN
    # named tables (same effect as the old drop-and-recreate for them)
    # while leaving every other table in the file untouched — matches the
    # additive pattern equity_compiler.py already uses on this same file.
    import duckdb
    conn = duckdb.connect(db_path)
    conn.execute("CREATE OR REPLACE TABLE daily_market_structure AS SELECT * FROM df_structure")
    conn.execute("CREATE OR REPLACE TABLE daily_setups AS SELECT * FROM df_setups")
    conn.execute("CREATE OR REPLACE TABLE daily_setup_positions AS SELECT * FROM df_positions")
    conn.execute("CREATE OR REPLACE TABLE daily_inventory AS SELECT * FROM df_inventory")
    conn.execute("CREATE OR REPLACE TABLE daily_market_breadth AS SELECT * FROM df_breadth")
    conn.execute("CREATE OR REPLACE TABLE daily_changes AS SELECT * FROM df_changes")
    if not df_cm_breadth.empty:
        conn.execute("CREATE OR REPLACE TABLE daily_cm_breadth AS SELECT * FROM df_cm_breadth")
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
