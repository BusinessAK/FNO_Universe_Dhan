import os
import sys
import time
import requests
import zipfile
import io
import subprocess
from datetime import datetime, timedelta, timezone

# Calculate today's date in IST (UTC + 5:30) dynamically
utc_dt = datetime.now(timezone.utc)
ist_dt = utc_dt + timedelta(hours=5, minutes=30)
default_date = ist_dt.strftime("%Y%m%d")

date_str = sys.argv[1] if len(sys.argv) > 1 else default_date
url = f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{date_str}_F_0000.csv.zip"
raw_dir = "data/raw"
headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive"
}

print(f"[*] Starting EOD background poller for {date_str}...")

# Check if already processed
expected_file = f"FO_BhavCopy_NSE_FO_0_0_0_{date_str}_F_0000.csv"
if os.path.exists(os.path.join(raw_dir, expected_file)):
    print(f"[!] File {expected_file} already exists locally. Nothing to do!")
    sys.exit(0)

# Check URL status
try:
    session = requests.Session()
    session.headers.update(headers)
    
    # Visit derivatives page to get cookies
    ref_url = "https://www.nseindia.com/all-reports-derivatives"
    print(f"[*] Initializing session via {ref_url}")
    session.get(ref_url, timeout=10)
    
    res = session.get(url, timeout=15)
    if res.status_code == 200:
        print(f"[SUCCESS] EOD BhavCopy found for {date_str}! Starting download and extraction...")
        
        # Extract zip
        with zipfile.ZipFile(io.BytesIO(res.content)) as z:
            for filename in z.namelist():
                if filename.endswith(".csv"):
                    clean_name = f"FO_{filename}"
                    extract_path = os.path.join(raw_dir, clean_name)
                    with open(extract_path, "wb") as f:
                        f.write(z.read(filename))
                    print(f"[SUCCESS] Saved extracted file to {extract_path}")
        
        # ── CM BhavCopy Download (best-effort, same date) ────────────────────
        # poll_eod.py previously only downloaded FO data. CM data is needed for
        # cash market breadth (McClellan, A/D line, new highs/lows). We download
        # it here for the same date so the two datasets never drift apart.
        cm_expected = f"CM_BhavCopy_NSE_CM_0_0_0_{date_str}_F_0000.csv"
        cm_path = os.path.join(raw_dir, cm_expected)
        if os.path.exists(cm_path):
            print(f"[*] CM file already exists: {cm_expected}")
        else:
            cm_url = f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{date_str}_F_0000.csv.zip"
            print(f"[*] Downloading CM BhavCopy for {date_str}...")
            try:
                cm_res = session.get(cm_url, timeout=15)
                if cm_res.status_code == 200:
                    with zipfile.ZipFile(io.BytesIO(cm_res.content)) as z:
                        for fname in z.namelist():
                            if fname.endswith(".csv"):
                                with open(cm_path, "wb") as f:
                                    f.write(z.read(fname))
                                print(f"[SUCCESS] CM saved: {cm_expected}")
                    # Rebuild cash_market_prices.parquet to include the new date
                    subprocess.run(
                        ["python3", "src/research/cash_market_builder.py", "--raw-dir", raw_dir],
                        check=False  # best-effort — never block the main pipeline
                    )
                else:
                    print(f"[!] CM not available yet for {date_str} (status {cm_res.status_code}) — skipping")
            except Exception as cm_err:
                print(f"[!] CM download failed (non-fatal): {cm_err}")
        # ─────────────────────────────────────────────────────────────────────

        # Run EOD DuckDB compiler pipeline FIRST — establishes authoritative
        # EOD settlement prices in session_history.json before greeks.csv is written.
        # This ensures the UI always reads the correct spot from compiled data.
        print("[*] Running daily_compiler.py...")
        subprocess.run(["python3", "daily_compiler.py"], check=True)

        # Run main signal generation pipeline AFTER compiler — greeks.csv is now
        # written with the same T vs T-1 pairing the compiler used.
        print("[*] Running main.py pipeline...")
        subprocess.run(["python3", "main.py"], check=True)

        # Generate Tomorrow's Watchlist briefing (best-effort — never blocks pipeline)
        print("[*] Generating Tomorrow's Watchlist briefing...")
        subprocess.run(["python3", "briefing.py"], check=False)

        # Build Vanguard HUD (best-effort)
        print("[*] Generating Vanguard HUD...")
        subprocess.run(["python3", "scripts/build_hud.py"], check=False)

        print(f"\n=======================================================")
        print(f"🎉 SUCCESS: EOD Bhavcopy {date_str} successfully processed!")
        print(f"All signals updated, and DuckDB/Streamlit are in sync!")
        print(f"=======================================================")
        sys.exit(0)
    elif res.status_code == 404:
        print(f"[*] Checked at {datetime.now().strftime('%H:%M:%S')} IST: Not available yet (404). Will retry in next poll.")
        sys.exit(1)
    else:
        print(f"[!] Checked at {datetime.now().strftime('%H:%M:%S')} IST: Received status code {res.status_code}.")
        sys.exit(2)
except Exception as e:
    print(f"[!] Error during check: {e}")
    sys.exit(3)
