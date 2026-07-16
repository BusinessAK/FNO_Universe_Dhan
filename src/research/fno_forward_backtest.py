import duckdb
import pandas as pd
import numpy as np
import os

# Create research dir if not exists
os.makedirs("data/research", exist_ok=True)

def fetch_data():
    conn = duckdb.connect("data/compiled/vanguard.duckdb")
    
    # Get Market Structure
    query_ms = """
        SELECT date, symbol, spot_close, ifs_score, structural_bias 
        FROM daily_market_structure
    """
    df_ms = conn.execute(query_ms).fetchdf()
    
    # Get Setups (specifically looking for INVENTORY_MIGRATION)
    query_setups = """
        SELECT date, symbol, setup_type
        FROM daily_setups
        WHERE setup_type = 'INVENTORY_MIGRATION'
    """
    df_setups = conn.execute(query_setups).fetchdf()
    conn.close()
    
    return df_ms, df_setups

def build_forward_returns(df_ms, df_setups):
    # Convert dates to proper datetime for sorting
    df_ms['date'] = pd.to_datetime(df_ms['date'])
    df_setups['date'] = pd.to_datetime(df_setups['date'])
    
    # Merge structure and setups
    # Add a boolean column indicating presence of INVENTORY_MIGRATION
    df_setups['has_inv_mig'] = True
    df_setups = df_setups[['date', 'symbol', 'has_inv_mig']].drop_duplicates()
    
    df = pd.merge(df_ms, df_setups, on=['date', 'symbol'], how='left')
    df['has_inv_mig'] = df['has_inv_mig'].fillna(False)
    
    # Sort rigorously by symbol and time
    df = df.sort_values(['symbol', 'date']).reset_index(drop=True)
    
    # Compute Forward Close and Forward Max Closes per symbol
    def compute_forward_metrics(group):
        group['spot_T1'] = group['spot_close'].shift(-1)
        group['spot_T3'] = group['spot_close'].shift(-3)
        group['spot_T5'] = group['spot_close'].shift(-5)
        
        # Max of the closes between T+1 and T+3
        group['max_T1_T3'] = group['spot_close'].rolling(window=3, min_periods=1).max().shift(-3)
        # Max of the closes between T+1 and T+5
        group['max_T1_T5'] = group['spot_close'].rolling(window=5, min_periods=1).max().shift(-5)
        
        return group
        
    df = df.groupby('symbol', group_keys=False).apply(compute_forward_metrics)
    
    # Drop rows where we don't have a valid T+1 (i.e., end of the dataset)
    df = df.dropna(subset=['spot_T1'])
    return df

def run_backtest(df, slippage=0.002):
    # DEFINE THE FOOTPRINT TRIGGER
    # 1. IFS > 30 (Strong Institutional Flow)
    # 2. Structural Bias = Expansion (Volatility Expansion regime)
    # 3. Inventory Migration Setup = True
    trigger_mask = (
        (df['ifs_score'] > 30) & 
        (df['structural_bias'] == 'Expansion') & 
        (df['has_inv_mig'] == True)
    )
    
    trades = df[trigger_mask].copy()
    num_trades = len(trades)
    
    if num_trades == 0:
        return {"num_trades": 0}
        
    # Calculate returns (Close-to-Close) adjusted for Slippage at entry and exit
    trades['ret_T1'] = (trades['spot_T1'] - trades['spot_close']) / trades['spot_close'] - (slippage * 2)
    trades['ret_T3'] = (trades['spot_T3'] - trades['spot_close']) / trades['spot_close'] - (slippage * 2)
    trades['ret_T5'] = (trades['spot_T5'] - trades['spot_close']) / trades['spot_close'] - (slippage * 2)
    
    # Calculate Max Excursion (Max Close)
    trades['max_ret_T3'] = (trades['max_T1_T3'] - trades['spot_close']) / trades['spot_close'] - (slippage * 2)
    trades['max_ret_T5'] = (trades['max_T1_T5'] - trades['spot_close']) / trades['spot_close'] - (slippage * 2)
    
    def calculate_expectancy(returns):
        returns = returns.dropna()
        if len(returns) == 0:
            return 0, 0, 0, 0
        win_mask = returns > 0
        win_rate = win_mask.mean()
        loss_rate = 1 - win_rate
        avg_win = returns[win_mask].mean() if win_rate > 0 else 0
        avg_loss = returns[~win_mask].mean() if loss_rate > 0 else 0
        expectancy = (win_rate * avg_win) + (loss_rate * avg_loss)
        return win_rate, avg_win, avg_loss, expectancy
        
    results = {"num_trades": num_trades}
    
    for metric, col in [("T+1 Close", "ret_T1"), 
                        ("T+3 Close", "ret_T3"), 
                        ("T+5 Close", "ret_T5"),
                        ("T+3 Max Close", "max_ret_T3"),
                        ("T+5 Max Close", "max_ret_T5")]:
        wr, aw, al, exp = calculate_expectancy(trades[col])
        results[metric] = {
            "win_rate": wr,
            "avg_win": aw,
            "avg_loss": al,
            "expectancy": exp
        }
        
    return results

def generate_markdown_report(results, slippage):
    md = f"# F&O Footprint Forward Backtest Report\n\n"
    md += f"**Trigger Logic:** `IFS > 30` AND `Structural Bias == EXPANSION` AND `Inventory Migration Setup Present`\n"
    md += f"**Execution Slippage Assumed:** {slippage*100:.2f}% per round trip (entry + exit)\n\n"
    
    n = results.get("num_trades", 0)
    md += f"### Total Signals Fired: {n}\n\n"
    
    if n == 0:
        md += "> No setups matched this criteria in the database."
        return md
        
    md += "| Metric | Win Rate | Avg Win | Avg Loss | **Expectancy (Edge)** |\n"
    md += "|---|---|---|---|---|\n"
    
    for metric in ["T+1 Close", "T+3 Close", "T+5 Close", "T+3 Max Close", "T+5 Max Close"]:
        res = results[metric]
        wr = res['win_rate'] * 100
        aw = res['avg_win'] * 100
        al = res['avg_loss'] * 100
        exp = res['expectancy'] * 100
        exp_format = f"**{exp:+.2f}%**" if exp > 0 else f"{exp:+.2f}%"
        md += f"| {metric} | {wr:.1f}% | {aw:+.2f}% | {al:+.2f}% | {exp_format} |\n"
        
    md += "\n> **Analysis Note:** Expectancy is the true mathematical edge per trade (Win Rate × Avg Win) + (Loss Rate × Avg Loss). "
    md += "A positive expectancy means this footprint possesses genuine predictive alpha over random entry.\n"
    
    return md

if __name__ == "__main__":
    print("[*] Fetching DB Data...")
    df_ms, df_setups = fetch_data()
    print("[*] Building Forward Returns...")
    df = build_forward_returns(df_ms, df_setups)
    
    # We will test an aggressive frictionless model, and a realistic slippage model
    print("[*] Running Backtest (0.2% Slippage)...")
    res_realistic = run_backtest(df, slippage=0.002)
    
    report = generate_markdown_report(res_realistic, slippage=0.002)
    
    print("\n" + report)
    with open("data/research/forward_backtest_report.md", "w") as f:
        f.write(report)
        
    print("\n[*] Saved to data/research/forward_backtest_report.md")
