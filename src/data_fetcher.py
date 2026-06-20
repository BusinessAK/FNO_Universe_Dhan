import os
import requests
import zipfile
import io
from datetime import datetime, timedelta
import time
from typing import Optional

class NSEDataFetcher:
    # New UDiFF URL Pattern
    BASE_URL = "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{date_str}_F_0000.csv.zip"
    CM_URL = "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{date_str}_F_0000.csv.zip"
    MAIN_URL = "https://www.nseindia.com/"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive"
    }

    def __init__(self, raw_data_dir: str = "data/raw"):
        self.raw_data_dir = raw_data_dir
        os.makedirs(self.raw_data_dir, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)

    def _init_session(self):
        try:
            url = "https://www.nseindia.com/all-reports-derivatives"
            print(f"[*] Initializing session via {url}")
            self.session.get(url, timeout=10)
        except Exception as e:
            print(f"[!] Warning: Session init failed: {e}")

    def fetch_bhavcopy(self, target_date: Optional[datetime] = None) -> Optional[str]:
        self._init_session()
        
        if target_date is None:
            target_date = datetime.now()

        for _ in range(10):
            date_str = target_date.strftime("%Y%m%d")
            url = self.BASE_URL.format(date_str=date_str)
            print(f"[*] Attempting: {url}")

            try:
                response = self.session.get(url, timeout=15)
                if response.status_code == 200:
                    return self._process_zip(response.content, date_str)
                elif response.status_code == 404:
                    print(f"[!] 404 for {date_str}.")
            except Exception as e:
                print(f"[!] Error: {e}")

            target_date -= timedelta(days=1)
            time.sleep(1)

        return None

    def fetch_cm_bhavcopy(self, target_date: Optional[datetime] = None) -> Optional[str]:
        """Fetches Cash Market Bhavcopy for Delivery % data"""
        self._init_session()
        if target_date is None: target_date = datetime.now()
        
        for _ in range(5):
            date_str = target_date.strftime("%Y%m%d")
            url = self.CM_URL.format(date_str=date_str)
            print(f"[*] Attempting CM: {url}")
            try:
                response = self.session.get(url, timeout=10)
                if response.status_code == 200:
                    return self._process_zip(response.content, date_str, "cm")
            except: pass
            target_date -= timedelta(days=1)
        return None

    def _process_zip(self, content: bytes, date_str: str, market: str = "fo") -> str:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            for filename in z.namelist():
                if filename.endswith(".csv"):
                    # Prefix filename to avoid collision
                    clean_name = f"{market.upper()}_{filename}"
                    extract_path = os.path.join(self.raw_data_dir, clean_name)
                    with open(extract_path, "wb") as f:
                        f.write(z.read(filename))
                    print(f"[SUCCESS] Saved {clean_name}")
                    return extract_path
        return ""

    def fetch_range(self, days=10):
        target_date = datetime.now()
        downloaded = 0
        paths = []
        
        print(f"[*] Starting batch download for {days} days of historical data...")
        
        # Ensure session is initialized once
        self._init_session()
        
        for i in range(days * 3): # Account for weekends/holidays
            date_to_try = target_date - timedelta(days=i)
            if date_to_try.weekday() >= 5: continue # Skip weekends
            
            date_str = date_to_try.strftime("%Y%m%d")
            url = self.BASE_URL.format(date_str=date_str)
            
            # Check if file already exists locally
            expected_file = f"FO_BhavCopy_NSE_FO_0_0_0_{date_str}_F_0000.csv"
            expected_path = os.path.join(self.raw_data_dir, expected_file)
            if os.path.exists(expected_path):
                print(f"[*] Found local: {expected_file}")
                paths.append(expected_path)
                downloaded += 1
            else:
                try:
                    response = self.session.get(url, timeout=10)
                    if response.status_code == 200:
                        path = self._process_zip(response.content, date_str)
                        if path:
                            paths.append(path)
                            downloaded += 1
                except Exception:
                    continue
            
            if downloaded >= days:
                break
        
        return sorted(paths)
