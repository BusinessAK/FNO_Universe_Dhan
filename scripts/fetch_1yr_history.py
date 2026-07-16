#!/usr/bin/env python3
import sys
import os
import time
from datetime import datetime, timedelta, timezone

# Setup package paths
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'src'))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.data_fetcher import NSEDataFetcher

def fetch_history(days_back=365):
    print("=" * 80)
    print(f"  VANGUARD INSTITUTIONAL TERMINAL — BULK HISTORICAL DOWNLOADER ({days_back} DAYS)")
    print("=" * 80)
    
    fetcher = NSEDataFetcher()
    fetcher._init_session()
    
    utc_dt = datetime.now(timezone.utc)
    ist_dt = utc_dt + timedelta(hours=5, minutes=30)
    
    downloaded_count = 0
    skipped_count = 0
    failed_count = 0
    
    for i in range(days_back):
        target_date = ist_dt - timedelta(days=i)
        
        # Skip weekends
        if target_date.weekday() >= 5: 
            continue 
            
        date_str = target_date.strftime("%Y%m%d")
        expected_file = f"FO_BhavCopy_NSE_FO_0_0_0_{date_str}_F_0000.csv"
        expected_path = os.path.join("data/raw", expected_file)
        
        if os.path.exists(expected_path):
            print(f"[*] ALREADY EXISTS: {expected_file}")
            skipped_count += 1
            continue
            
        url = fetcher.BASE_URL.format(date_str=date_str)
        print(f"[*] FETCHING: {url}")
        
        try:
            # Gentle delay to avoid CDN block
            time.sleep(2.5)
            response = fetcher.session.get(url, timeout=15)
            
            if response.status_code == 200:
                path = fetcher._process_zip(response.content, date_str)
                if path:
                    print(f"[SUCCESS] Downloaded {date_str}")
                    downloaded_count += 1
            elif response.status_code == 404:
                print(f"[SKIP] {date_str} returned 404 (Likely NSE Holiday)")
            elif response.status_code == 403:
                print(f"[!] 403 Forbidden on {date_str}. NSE CDN might be blocking us. Pausing 10s...")
                time.sleep(10)
                failed_count += 1
            else:
                print(f"[!] Failed for {date_str} with status code {response.status_code}")
                failed_count += 1
                
        except Exception as e:
            print(f"[!] Error fetching {date_str}: {e}")
            failed_count += 1
            time.sleep(5)
            
    print("\n" + "=" * 80)
    print(f"[DONE] Historical bulk download complete.")
    print(f"       Downloaded: {downloaded_count}")
    print(f"       Skipped (Already local): {skipped_count}")
    print(f"       Failed/Blocked: {failed_count}")
    print("=" * 80)

if __name__ == "__main__":
    # Ensure data/raw exists
    os.makedirs("data/raw", exist_ok=True)
    fetch_history(365)
