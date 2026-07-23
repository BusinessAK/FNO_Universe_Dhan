#!/usr/bin/env python3
"""
Participant Positioning Backtester

This script analyzes the relationship between participant index option positioning
(FII, DII, PRO, CLIENT) and forward Nifty 50 returns.
"""

import sys
import duckdb
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "compiled" / "vanguard.duckdb"

def main():
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}")
        sys.exit(1)
        
    con = duckdb.connect(str(DB_PATH), read_only=True)
    
    # 1. Fetch Participant OI
    df_oi = con.execute("""
        SELECT 
            date::DATE as date,
            participant,
            opt_idx_call_long,
            opt_idx_call_short,
            opt_idx_put_long,
            opt_idx_put_short
        FROM daily_participant_oi
        ORDER BY date
    """).fetchdf()
    
    # 2. Fetch Nifty 50 Index Close
    df_index = con.execute("""
        SELECT 
            date::DATE as date,
            close
        FROM daily_index_close
        WHERE index_name = 'Nifty 50'
        ORDER BY date
    """).fetchdf()
    
    # Calculate Net Stance: (Call Long - Call Short) + (Put Short - Put Long)
    df_oi['net_stance'] = (df_oi['opt_idx_call_long'] - df_oi['opt_idx_call_short']) + \
                          (df_oi['opt_idx_put_short'] - df_oi['opt_idx_put_long'])
                          
    # Pivot to get participants as columns
    df_pivot = df_oi.pivot(index='date', columns='participant', values='net_stance').reset_index()
    
    # Merge Data
    df = pd.merge(df_pivot, df_index, on='date', how='inner').sort_values('date').reset_index(drop=True)
    
    if df.empty:
        print("No overlapping data found.")
        return
        
    # Calculate Forward Returns
    horizons = [1, 3, 5, 10, 20]
    for h in horizons:
        df[f'fwd_ret_{h}d'] = (df['close'].shift(-h) / df['close'] - 1.0) * 100.0
        
    print("\n" + "="*50)
    print("PARTICIPANT POSITIONING BACKTEST & ANALYSIS")
    print("="*50)
    print(f"Period: {df['date'].min()} to {df['date'].max()} ({len(df)} sessions)")
    
    df_eval = df.dropna(subset=[f'fwd_ret_{h}d' for h in horizons]).copy()
    
    def eval_regime(name, condition):
        subset = df_eval[condition]
        print(f"\n{name} [N={len(subset)}]")
        print("-" * 40)
        if len(subset) == 0:
            print("  No occurrences.")
            return
        for h in horizons:
            ret = subset[f'fwd_ret_{h}d']
            win_rate = (ret > 0).mean() * 100
            print(f"  {h:2d}D Fwd: Mean {ret.mean():+5.2f}% | Median {ret.median():+5.2f}% | Win {win_rate:5.1f}%")

    participants = [col for col in df_pivot.columns if col != 'date']
    
    for p in participants:
        print(f"\n[{p}] Index Options Positioning")
        if p not in df_eval.columns or df_eval[p].isna().all():
            print("  No Data Available.")
            continue
            
        p10 = df_eval[p].quantile(0.10)
        p90 = df_eval[p].quantile(0.90)
        
        eval_regime(f"Extreme Bearish (Bottom 10% < {p10:,.0f} contracts)", df_eval[p] <= p10)
        eval_regime(f"Extreme Bullish (Top 10% > {p90:,.0f} contracts)", df_eval[p] >= p90)

    print("\n" + "="*50 + "\n")

if __name__ == "__main__":
    main()
