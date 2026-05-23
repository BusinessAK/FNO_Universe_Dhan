import os
from datetime import datetime, timedelta
import time
from src.data_fetcher import NSEDataFetcher
from src.signal_generator import SignalGenerator

def download_and_process_may():
    print("=== Downloading and Processing May 2026 Bhavcopies ===")
    
    # 1. Initialize data fetcher
    fetcher = NSEDataFetcher()
    fetcher._init_session()
    
    # Range of dates: May 1, 2026 to May 22, 2026
    start_date = datetime(2026, 5, 1)
    end_date = datetime(2026, 5, 22)
    
    current_date = start_date
    downloaded_paths = []
    
    while current_date <= end_date:
        # Skip weekends (Saturday=5, Sunday=6)
        if current_date.weekday() >= 5:
            current_date += timedelta(days=1)
            continue
            
        date_str = current_date.strftime("%Y%m%d")
        expected_file = f"FO_BhavCopy_NSE_FO_0_0_0_{date_str}_F_0000.csv"
        expected_path = os.path.join("data/raw", expected_file)
        
        if os.path.exists(expected_path):
            print(f"[*] Already exists locally: {expected_file}")
            downloaded_paths.append(expected_path)
        else:
            url = fetcher.BASE_URL.format(date_str=date_str)
            print(f"[*] Fetching: {url}")
            try:
                # Add delay to be gentle on NSE servers
                time.sleep(1.5)
                response = fetcher.session.get(url, timeout=15)
                if response.status_code == 200:
                    path = fetcher._process_zip(response.content, date_str)
                    if path:
                        print(f"[SUCCESS] Downloaded and extracted {date_str}")
                        downloaded_paths.append(path)
                elif response.status_code == 404:
                    print(f"[!] 404 Not Found for {date_str} (might be a trading holiday)")
                else:
                    print(f"[!] Failed for {date_str} with status code {response.status_code}")
            except Exception as e:
                print(f"[!] Error fetching {date_str}: {e}")
                
        current_date += timedelta(days=1)
        
    print("\n=== Fetching completed. Let's process the latest two days. ===")
    
    # Let's see what raw files we have now
    raw_files = sorted([f for f in os.listdir("data/raw") if "FO" in f and f.endswith(".csv")], reverse=True)
    raw_files = [os.path.join("data/raw", f) for f in raw_files]
    
    print(f"[*] Found {len(raw_files)} total raw FO bhavcopy files in data/raw.")
    for f in raw_files[:5]:
        print(f"  - {os.path.basename(f)}")
        
    if len(raw_files) >= 2:
        print(f"\n[*] Processing comparison: {os.path.basename(raw_files[0])} vs {os.path.basename(raw_files[1])}")
        gen = SignalGenerator()
        signals_df = gen.generate_signals(raw_files[0], raw_files[1])
        
        # Save signals
        os.makedirs("data/processed", exist_ok=True)
        signals_df.to_csv("data/processed/signals.csv", index=False)
        print(f"[SUCCESS] Signals generated and saved to data/processed/signals.csv")
        
        # Also let's print top 10 ranked signals
        print("\nTop 10 Ranked Institutional Signals:")
        from tabulate import tabulate
        print(tabulate(signals_df.head(10), headers='keys', tablefmt='psql', showindex=False))
    else:
        print("[!] Need at least 2 days of FO data for processing.")

if __name__ == "__main__":
    download_and_process_may()
