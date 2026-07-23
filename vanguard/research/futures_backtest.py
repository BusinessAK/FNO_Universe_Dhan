#!/usr/bin/env python3
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
    
    df_oi = con.execute("""
        SELECT 
            date::DATE as date,
            participant,
            fut_idx_long,
            fut_idx_short
        FROM daily_participant_oi
        WHERE participant IN ('FII', 'CLIENT')
        ORDER BY date
    """).fetchdf()
    
    df_index = con.execute("""
        SELECT 
            date::DATE as date,
            close
        FROM daily_index_close
        WHERE index_name = 'Nifty 50'
        ORDER BY date
    """).fetchdf()
    
    df_oi['net_stance'] = df_oi['fut_idx_long'] - df_oi['fut_idx_short']
    df_pivot = df_oi.pivot(index='date', columns='participant', values='net_stance').reset_index()
    df = pd.merge(df_pivot, df_index, on='date', how='inner').sort_values('date').reset_index(drop=True)
    
    horizons = [1, 3, 5, 10, 20]
    for h in horizons:
        df[f'fwd_ret_{h}d'] = (df['close'].shift(-h) / df['close'] - 1.0) * 100.0
        
    print("\n" + "="*50)
    print("ROLLING INDEX FUTURES POSITIONING BACKTEST (NO LOOK-AHEAD BIAS)")
    print("="*50)
    
    # Calculate rolling percentiles (60-day window)
    window = 60
    for p in ['FII', 'CLIENT']:
        df[f'{p}_roll_10'] = df[p].rolling(window).quantile(0.10)
        df[f'{p}_roll_90'] = df[p].rolling(window).quantile(0.90)
        
    # Drop rows where we don't have enough history for the rolling window
    df_eval = df.dropna(subset=[f'FII_roll_10']).copy()
    
    print(f"Period: {df_eval['date'].min()} to {df_eval['date'].max()} ({len(df_eval)} sessions out of sample)")

    def eval_regime(name, condition):
        subset = df_eval[condition]
        print(f"\n{name} [N={len(subset)}]")
        print("-" * 40)
        if len(subset) == 0:
            print("  No occurrences.")
            return
        for h in horizons:
            # We must drop NaN forward returns for accuracy
            ret = subset[f'fwd_ret_{h}d'].dropna()
            if len(ret) == 0:
                continue
            win_rate = (ret > 0).mean() * 100
            print(f"  {h:2d}D Fwd: Mean {ret.mean():+5.2f}% | Median {ret.median():+5.2f}% | Win {win_rate:5.1f}%")

    for p in ['CLIENT', 'FII']:
        print(f"\n[{p}] Index Futures Positioning")
        # Extreme Bearish: Current value is below the 60-day rolling 10th percentile
        eval_regime(f"Extreme Bearish (Below 60D 10th Percentile)", df_eval[p] <= df_eval[f'{p}_roll_10'])
        eval_regime(f"Extreme Bullish (Above 60D 90th Percentile)", df_eval[p] >= df_eval[f'{p}_roll_90'])

    print("\n" + "="*50 + "\n")

if __name__ == "__main__":
    main()
