import pandas as pd
import numpy as np
import os
from datetime import datetime
from src.data_fetcher import NSEDataFetcher
from src.signal_generator import SignalGenerator

class MomentumBacktester:
    def __init__(self):
        self.fetcher = NSEDataFetcher()
        self.gen = SignalGenerator()

    def run_backtest(self, days=15):
        print(f"\n{'='*60}")
        print(f"VANGUARD MOMENTUM BACKTESTER (STRATEGY: NAKED BUYING)")
        print(f"{'='*60}")
        
        # 1. Fetch Data
        files = self.fetcher.fetch_range(days=days)
        if len(files) < 3:
            print("[!] Not enough data to backtest.")
            return

        trades = []
        
        # 2. Iterate through files
        # We need T-1 and T to generate signals for entry at T+1 Open
        for i in range(1, len(files) - 1):
            file_tm1 = files[i-1]
            file_t = files[i]
            file_tp1 = files[i+1] # The "Future" day for result checking
            
            print(f"[*] Processing Signal for: {os.path.basename(file_tp1)}")
            
            # Generate Signals
            signals = self.gen.generate_signals(file_t, file_tm1)
            
            # Filter for Naked Buying ONLY (Not Spreads)
            # Naked buying signals start with "BUY" and don't contain "SELL"
            buying_signals = signals[signals['TRADE'].str.startswith("BUY") & ~signals['TRADE'].str.contains("SELL")]
            
            if buying_signals.empty:
                continue
            
            # Load T+1 data for result checking
            processor = self.gen.intel.processor
            df_tp1, _ = processor.normalize(file_tp1)
            
            for _, sig in buying_signals.iterrows():
                symbol = sig['SYMBOL']
                
                # 1. Identify the Specific Option Instrument
                try:
                    parts = sig['TRADE'].split(' ')
                    strike = float(parts[1])
                    opt_type = 'CE' if 'CALL' in parts[2] else 'PE'
                except:
                    continue

                # 2. Find performance of this SPECIFIC OPTION in T+1
                option_data = df_tp1[
                    (df_tp1['SYMBOL'] == symbol) & 
                    (df_tp1['STRIKE_PR'] == strike) & 
                    (df_tp1['OPTION_TYP'] == opt_type)
                ]
                
                if option_data.empty: continue
                
                # Assume Entry at T+1 OPEN PREMIUM
                entry_premium = option_data['OPEN'].iloc[0]
                if entry_premium <= 0.5: continue # Skip illiquid / cheap options
                
                high_premium = option_data['HIGH'].iloc[0]
                low_premium = option_data['LOW'].iloc[0]
                close_premium = option_data['CLOSE'].iloc[0]
                
                # Define Premium-based Targets
                # Buying: Target +50% Premium, SL -25% Premium
                target_premium = entry_premium * 1.50
                sl_premium = entry_premium * 0.75
                
                result = "OPEN"
                pnl_pct = 0
                
                if high_premium >= target_premium:
                    result = "WIN"
                    pnl_pct = 50.0
                elif low_premium <= sl_premium:
                    result = "LOSS"
                    pnl_pct = -25.0
                else:
                    # If neither hit, calculate PnL based on close
                    pnl_pct = ((close_premium - entry_premium) / entry_premium) * 100

                trades.append({
                    'Date': os.path.basename(file_tp1).split('_')[-2],
                    'Symbol': symbol,
                    'Trade': sig['TRADE'],
                    'Entry_Px': round(entry_premium, 2),
                    'Result': result,
                    'PnL%': round(pnl_pct, 2)
                })

        # 3. Aggregated Results
        if not trades:
            print("[!] No trades generated during backtest period.")
            return

        results_df = pd.DataFrame(trades)
        
        # 3. Calculate Advanced Metrics
        results_df['Equity'] = results_df['PnL%'].cumsum()
        
        # Max Drawdown
        running_max = results_df['Equity'].cummax()
        drawdown = running_max - results_df['Equity']
        max_drawdown = drawdown.max()
        
        # Sharpe Ratio (Assuming daily risk-free rate is ~0)
        pnl_std = results_df['PnL%'].std()
        sharpe_ratio = (results_df['PnL%'].mean() / pnl_std) * np.sqrt(252) if pnl_std != 0 else 0
        
        win_rate = (len(results_df[results_df['Result'] == "WIN"]) / len(results_df)) * 100
        avg_pnl = results_df['PnL%'].mean()
        
        print("\n" + "!"*60)
        print("BACKTEST PERFORMANCE SUMMARY")
        print("!"*60)
        print(f"Total Trades: {len(results_df)}")
        print(f"Win Rate:     {win_rate:.2f}%")
        print(f"Avg PnL%:     {avg_pnl:.2f}%")
        print(f"Max Drawdown: {max_drawdown:.2f}%")
        print(f"Sharpe Ratio: {sharpe_ratio:.2f}")
        print(f"Max Winner:   {results_df['PnL%'].max()}%")
        print(f"Max Loser:    {results_df['PnL%'].min()}%")
        print("!"*60)
        
        from tabulate import tabulate
        print("\nRECENT TRADES LOG:")
        print(tabulate(results_df.tail(20), headers='keys', tablefmt='psql', showindex=False))
        
        results_df.to_csv("data/processed/backtest_momentum.csv", index=False)

if __name__ == "__main__":
    tester = MomentumBacktester()
    tester.run_backtest(days=10)
