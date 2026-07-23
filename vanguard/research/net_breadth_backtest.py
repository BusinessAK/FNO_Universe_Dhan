#!/usr/bin/env python3
"""
Net Breadth Backtester

This script analyzes the relationship between the Net Breadth indicator 
(Bullish % - Bearish % of F&O Universe) and forward Nifty 50 returns,
as well as the relationship between Coil (compression) and forward volatility.
"""

import sys
import duckdb
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "compiled" / "vanguard.duckdb"

def main():
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}")
        sys.exit(1)
        
    con = duckdb.connect(str(DB_PATH), read_only=True)
    
    # 1. Fetch Market Breadth
    df_breadth = con.execute("""
        SELECT 
            date::DATE as date, 
            bullish_pct, 
            bearish_pct, 
            compression_pct as coil
        FROM daily_market_breadth
        ORDER BY date
    """).fetchdf()
    df_breadth['net_breadth'] = df_breadth['bullish_pct'] - df_breadth['bearish_pct']
    
    # 2. Fetch Nifty 50 Index Close
    df_index = con.execute("""
        SELECT 
            date::DATE as date,
            close
        FROM daily_index_close
        WHERE index_name = 'Nifty 50'
        ORDER BY date
    """).fetchdf()
    
    # Merge Data
    df = pd.merge(df_breadth, df_index, on='date', how='inner').sort_values('date').reset_index(drop=True)
    
    if df.empty:
        print("No overlapping data found.")
        return
        
    # 3. Calculate Forward Returns & Volatility
    horizons = [1, 3, 5, 10, 20]
    
    for h in horizons:
        df[f'fwd_ret_{h}d'] = (df['close'].shift(-h) / df['close'] - 1.0) * 100.0
        # Forward absolute return (proxy for realized volatility over window)
        df[f'fwd_abs_ret_{h}d'] = df[f'fwd_ret_{h}d'].abs()
        
    # 4. Correlation Analysis
    print("\n" + "="*50)
    print("NET BREADTH BACKTEST & ANALYSIS")
    print("="*50)
    print(f"Period: {df['date'].min()} to {df['date'].max()} ({len(df)} sessions)")
    
    print("\n[1] Spearman Rank Correlation (Net Breadth vs Forward Returns)")
    print("-----------------------------------------------------------------")
    for h in horizons:
        valid = df.dropna(subset=['net_breadth', f'fwd_ret_{h}d'])
        if len(valid) > 0:
            corr, pval = spearmanr(valid['net_breadth'], valid[f'fwd_ret_{h}d'])
            sig = "***" if pval < 0.01 else "**" if pval < 0.05 else "*" if pval < 0.1 else ""
            print(f"{h:2d}D Forward Return : {corr:6.3f} (p-val: {pval:.4f}) {sig}")
            
    print("\n[2] Spearman Rank Correlation (Coil vs Forward Absolute Returns)")
    print("-----------------------------------------------------------------")
    for h in horizons:
        valid = df.dropna(subset=['coil', f'fwd_abs_ret_{h}d'])
        if len(valid) > 0:
            corr, pval = spearmanr(valid['coil'], valid[f'fwd_abs_ret_{h}d'])
            sig = "***" if pval < 0.01 else "**" if pval < 0.05 else "*" if pval < 0.1 else ""
            print(f"{h:2d}D Forward Abs Ret: {corr:6.3f} (p-val: {pval:.4f}) {sig}")

    # 5. Extreme Regimes (Deciles)
    print("\n[3] Extreme Regimes (Bottom 10% vs Top 10% Net Breadth)")
    print("-----------------------------------------------------------------")
    
    # Drop rows where 5d forward return is na to have a fair comparison set
    df_eval = df.dropna(subset=['fwd_ret_5d', 'fwd_ret_10d']).copy()
    
    if len(df_eval) > 20:
        p10 = df_eval['net_breadth'].quantile(0.10)
        p90 = df_eval['net_breadth'].quantile(0.90)
        
        excess_bear = df_eval[df_eval['net_breadth'] <= p10]
        excess_bull = df_eval[df_eval['net_breadth'] >= p90]
        
        print(f"Excessive Bearish (Net Breadth <= {p10:.1f}%) [N={len(excess_bear)}]:")
        for h in [1, 3, 5, 10]:
            ret = excess_bear[f'fwd_ret_{h}d']
            win_rate = (ret > 0).mean() * 100
            print(f"  {h:2d}D Fwd: Mean {ret.mean():+5.2f}% | Median {ret.median():+5.2f}% | Win {win_rate:5.1f}%")
            
        print(f"\nExcessive Bullish (Net Breadth >= {p90:.1f}%) [N={len(excess_bull)}]:")
        for h in [1, 3, 5, 10]:
            ret = excess_bull[f'fwd_ret_{h}d']
            win_rate = (ret > 0).mean() * 100
            print(f"  {h:2d}D Fwd: Mean {ret.mean():+5.2f}% | Median {ret.median():+5.2f}% | Win {win_rate:5.1f}%")

    # 6. Crossover Regimes
    print("\n[4] Zero-Line Crossover Analysis")
    print("-----------------------------------------------------------------")
    # T-1 < 0 and T >= 0 (Bullish Cross)
    df_eval['prev_net'] = df_eval['net_breadth'].shift(1)
    bull_cross = df_eval[(df_eval['prev_net'] < 0) & (df_eval['net_breadth'] >= 0)]
    bear_cross = df_eval[(df_eval['prev_net'] >= 0) & (df_eval['net_breadth'] < 0)]
    
    print(f"Bullish Zero-Crosses (Bear -> Bull) [N={len(bull_cross)}]:")
    if len(bull_cross) > 0:
        for h in [1, 3, 5, 10]:
            ret = bull_cross[f'fwd_ret_{h}d']
            win_rate = (ret > 0).mean() * 100
            print(f"  {h:2d}D Fwd: Mean {ret.mean():+5.2f}% | Median {ret.median():+5.2f}% | Win {win_rate:5.1f}%")
            
    print(f"\nBearish Zero-Crosses (Bull -> Bear) [N={len(bear_cross)}]:")
    if len(bear_cross) > 0:
        for h in [1, 3, 5, 10]:
            ret = bear_cross[f'fwd_ret_{h}d']
            win_rate = (ret > 0).mean() * 100
            print(f"  {h:2d}D Fwd: Mean {ret.mean():+5.2f}% | Median {ret.median():+5.2f}% | Win {win_rate:5.1f}%")

    print("="*50 + "\n")

if __name__ == "__main__":
    main()
