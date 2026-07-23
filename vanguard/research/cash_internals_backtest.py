#!/usr/bin/env python3
"""
Cash Internals Backtester

This script analyzes the relationship between broad cash market internals 
(A/D ratio, McClellan Oscillator, NH-NL, Moving Average Breadth, FII/DII Cash)
and forward Nifty 50 returns to identify statistically significant trading edges.
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
    
    # 1. Fetch CM Breadth
    df_cm = con.execute("""
        SELECT 
            date::DATE as date,
            cm_ad_ratio as ad_ratio,
            cm_mcclellan_osc as mcclellan,
            cm_pct_above_50dma as pct_above_50dma,
            cm_pct_above_200dma as pct_above_200dma,
            (cm_new_highs - cm_new_lows) as nh_nl_net
        FROM daily_cm_breadth
        ORDER BY date
    """).fetchdf()
    
    # 2. Fetch Institutional Cash
    df_inst = con.execute("""
        SELECT 
            date::DATE as date,
            SUM(CASE WHEN category = 'FII' THEN net_cr ELSE 0 END) as fii_cash,
            SUM(CASE WHEN category = 'DII' THEN net_cr ELSE 0 END) as dii_cash
        FROM daily_fii_dii
        GROUP BY date
        ORDER BY date
    """).fetchdf()
    
    # 3. Fetch Nifty 50 Index Close
    df_index = con.execute("""
        SELECT 
            date::DATE as date,
            close
        FROM daily_index_close
        WHERE index_name = 'Nifty 50'
        ORDER BY date
    """).fetchdf()
    
    # Merge Data
    df = pd.merge(df_cm, df_index, on='date', how='inner')
    df = pd.merge(df, df_inst, on='date', how='left').sort_values('date').reset_index(drop=True)
    
    if df.empty:
        print("No overlapping data found.")
        return
        
    # 4. Calculate Forward Returns
    horizons = [1, 3, 5, 10, 20]
    
    for h in horizons:
        df[f'fwd_ret_{h}d'] = (df['close'].shift(-h) / df['close'] - 1.0) * 100.0
        
    print("\n" + "="*50)
    print("CASH INTERNALS BACKTEST & ANALYSIS")
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
        for h in [1, 3, 5, 10, 20]:
            ret = subset[f'fwd_ret_{h}d']
            win_rate = (ret > 0).mean() * 100
            print(f"  {h:2d}D Fwd: Mean {ret.mean():+5.2f}% | Median {ret.median():+5.2f}% | Win {win_rate:5.1f}%")

    # [1] A/D Ratio Analysis
    print("\n[1] A/D Ratio Extremes")
    # A/D ratio < 0.5 means there are >2 decliners for every advancer
    eval_regime("Extreme Oversold (A/D < 0.5)", df_eval['ad_ratio'] < 0.5)
    # A/D ratio > 2.0 means there are >2 advancers for every decliner
    eval_regime("Extreme Overbought (A/D > 2.0)", df_eval['ad_ratio'] > 2.0)
    
    # [2] McClellan Oscillator Analysis
    print("\n[2] McClellan Oscillator Extremes")
    eval_regime("Deeply Oversold (McClellan < -100)", df_eval['mcclellan'] < -100)
    eval_regime("Deeply Overbought (McClellan > 100)", df_eval['mcclellan'] > 100)
    
    # [3] Trend Health (200 DMA)
    print("\n[3] Structural Trend Health (>200 DMA)")
    eval_regime("Structurally Weak (< 30% above 200DMA)", df_eval['pct_above_200dma'] < 30)
    eval_regime("Structurally Strong (> 60% above 200DMA)", df_eval['pct_above_200dma'] > 60)
    
    # [4] Institutional Cash Flows (FII)
    print("\n[4] FII Cash Flow Extremes")
    if not df_eval['fii_cash'].isna().all():
        p10 = df_eval['fii_cash'].quantile(0.10)
        p90 = df_eval['fii_cash'].quantile(0.90)
        eval_regime(f"Massive FII Selling (Bottom 10% < {p10:.0f} Cr)", df_eval['fii_cash'] <= p10)
        eval_regime(f"Massive FII Buying (Top 10% > {p90:.0f} Cr)", df_eval['fii_cash'] >= p90)
    else:
        print("\n[4] FII Cash Flow Extremes (No Data Available)")
        
    print("\n" + "="*50 + "\n")

if __name__ == "__main__":
    main()
