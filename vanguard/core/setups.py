from typing import Dict, List, Any
import pandas as pd

def categorize_and_sort(setups_df: pd.DataFrame, session_history: Dict[str, Any], latest_date: str) -> Dict[str, List[Any]]:
    """
    Categorizes setups from the database into the dictionary structure needed for the UI,
    and sorts them by their appropriate metrics (Priority Score or IFS).
    """
    categorized_setups = {
        # F&O Setups
        "GAMMA_SQUEEZE": [], "VOLATILITY_COIL": [], "PINCH_ZONE": [], "FLOOR_BOUNCE": [],
        "DEALER_DEFENSE": [], "REGIME_SHIFT": [], "INVENTORY_MIGRATION": [],
        "IV_SPIKE": [], "IV_CRUSH": [], "IV_SKEW_ACCUMULATION": [],
        # Equity Setups
        "FIFTYTWO_WEEK_BREAKOUT": [], "RSI_EXTREME_REBOUND": [], 
        "BREADTH_DIVERGENCE_REVERSAL": [], "IMBALANCE_CONSOLIDATION": [], 
        "MOMENTUM_BUILDUP": []
    }
    
    for _, r in setups_df.iterrows():
        s_sym = r["symbol"]
        s_type = r["setup_type"]
        s_m = session_history.get(s_sym, {}).get(latest_date, {})
        
        if s_type in categorized_setups:
             # Even if s_m is empty (pure equity), we must display it
             if not s_m:
                 s_m = {"symbol": s_sym, "date": latest_date, "ifs_score": 0.0, "priority_score": 0.0}
             categorized_setups[s_type].append((s_sym, s_m))
             
    # Sort setups: Volatility Coils and Pinch Zones sorted by Priority Score (Pty) descending; all others sorted by absolute IFS score descending
    for s_type in categorized_setups:
        if s_type in ["VOLATILITY_COIL", "PINCH_ZONE", "IV_SKEW_ACCUMULATION"]:
            categorized_setups[s_type] = sorted(
                categorized_setups[s_type],
                key=lambda x: float(x[1].get("priority_score") or 0.0),
                reverse=True
            )
        else:
            categorized_setups[s_type] = sorted(
                categorized_setups[s_type],
                key=lambda x: abs(float(x[1].get("ifs_score") or 0.0)),
                reverse=True
            )
            
    return categorized_setups
