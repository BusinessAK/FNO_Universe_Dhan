import sys
import os
import time
import re
import requests
from datetime import datetime, timedelta, timezone
from src.data_fetcher import NSEDataFetcher
from src.signal_generator import SignalGenerator
from tabulate import tabulate

def main():
    print("=== Institutional F&O Intelligence System (UDiFF Core) ===")
    
    # 1. Initialize data fetcher
    fetcher = NSEDataFetcher()
    fetcher._init_session()
    
    # Calculate today's date in IST (UTC + 5:30) dynamically
    utc_dt = datetime.now(timezone.utc)
    ist_dt = utc_dt + timedelta(hours=5, minutes=30)
    
    print(f"[*] Starting EOD download check from IST Date: {ist_dt.strftime('%Y-%m-%d')}...")
    
    # Fetch/verify FO data for the latest 2 active trading days
    downloaded = 0
    for i in range(10): # Check up to 10 days to find 2 active trading days
        target_date = ist_dt - timedelta(days=i)
        if target_date.weekday() >= 5: continue # Skip weekends
        
        date_str = target_date.strftime("%Y%m%d")
        expected_file = f"FO_BhavCopy_NSE_FO_0_0_0_{date_str}_F_0000.csv"
        expected_path = os.path.join("data/raw", expected_file)
        
        if os.path.exists(expected_path):
            print(f"[*] Already exists locally: {expected_file}")
            downloaded += 1
        else:
            url = fetcher.BASE_URL.format(date_str=date_str)
            print(f"[*] Fetching: {url}")
            try:
                # Add delay to be gentle on NSE servers and avoid CDN blocks
                time.sleep(1.5)
                response = fetcher.session.get(url, timeout=12)
                if response.status_code == 200:
                    path = fetcher._process_zip(response.content, date_str)
                    if path:
                        print(f"[SUCCESS] Downloaded and processed {date_str}")
                        downloaded += 1
                elif response.status_code == 404:
                    print(f"[*] Checked: {date_str} is not available (404).")
                else:
                    print(f"[!] Failed for {date_str} with status code {response.status_code}")
            except Exception as e:
                print(f"[!] Error fetching {date_str}: {e}")
                
        if downloaded >= 2:
            break
            
    # 2. Get historical files for comparison (Shift Analysis)
    pattern = re.compile(r"^FO_BhavCopy_NSE_FO_0_0_0_\d{8}_F_\d{4}\.csv$")
    raw_files = sorted([f for f in os.listdir("data/raw") if pattern.match(f)], reverse=True)
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
