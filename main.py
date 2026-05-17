import sys
import os
from datetime import datetime, timedelta
from src.data_fetcher import NSEDataFetcher
from src.signal_generator import SignalGenerator
from tabulate import tabulate

def main():
    print("=== Institutional F&O Intelligence System (UDiFF Core) ===")
    
    # 1. Fetch Latest Data (T and T-1)
    fetcher = NSEDataFetcher()
    
    # Fetch FO data for the last 2 trading days
    for i in range(5): # Look back up to 5 days to find 2 trading days
        target_date = datetime.now() - timedelta(days=i)
        if target_date.weekday() >= 5: continue
        fetcher.fetch_bhavcopy(target_date)
    
    # 2. Get historical files for comparison (Shift Analysis)
    raw_files = sorted([f for f in os.listdir("data/raw") if "FO" in f and f.endswith(".csv")], reverse=True)
    raw_files = [os.path.join("data/raw", f) for f in raw_files]

    if len(raw_files) >= 2:
        gen = SignalGenerator()
        # Process and Generate Ranked Signals
        signals_df = gen.generate_signals(raw_files[0], raw_files[1])
        
        print("\n" + "!"*80)
        print("VANGUARD INSTITUTIONAL INTELLIGENCE TERMINAL")
        print("Selection: GEX Exposure | OI Shift | Structure Change | Breakout Sustainability")
        print("!"*80)
        
        # Display ALL Ranked High-Conviction Stocks
        print(tabulate(signals_df, headers='keys', tablefmt='psql', showindex=False))
        
        os.makedirs("data/processed", exist_ok=True)
        signals_df.to_csv("data/processed/signals.csv", index=False)
        print(f"\n[SUCCESS] Signals generated and saved to data/processed/signals.csv")
    else:
        print("[!] Need at least 2 days of FO data for full institutional analysis.")

if __name__ == "__main__":
    main()
