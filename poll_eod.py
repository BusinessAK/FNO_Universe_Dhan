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
                        ["python3", "vanguard/research/cash_market_builder.py", "--raw-dir", raw_dir],
                        check=False  # best-effort — never block the main pipeline
                    )
                else:
                    print(f"[!] CM not available yet for {date_str} (status {cm_res.status_code}) — skipping")
            except Exception as cm_err:
                print(f"[!] CM download failed (non-fatal): {cm_err}")
        # ─────────────────────────────────────────────────────────────────────

        # Run EOD DuckDB compiler pipeline — establishes authoritative EOD
        # settlement prices in session_history.json and, via InstitutionalIntelligence
        # .analyze_market_structure(), writes greeks.csv/signals.csv with the same
        # T vs T-1 pairing used everywhere else. (The old standalone main.py pipeline
        # this used to hand off to was deleted in 23b60a1 as orphaned pre-DuckDB code.)
        print("[*] Running vanguard/pipeline/orchestrator.py...")
        subprocess.run(["python3", "vanguard/pipeline/orchestrator.py"], check=True)

        # Run NSE context layer (C1): participant OI, VIX, delivery %, ban list,
        # FII/DII flows, corporate events. Failure-isolated per dataset inside
        # poll_context.py itself and best-effort here (check=False) — per
        # docs/PRD_TRD_nse_context_layer_v1.md, a missing context dataset must
        # never delay the bhav compile. Runs AFTER the compiler (context tables
        # are additive, not required for compile) and BEFORE build_hud/briefing
        # (both join context data into their output).
        context_date = f"{date_str[0:4]}-{date_str[4:6]}-{date_str[6:8]}"
        print(f"[*] Running NSE context-layer poller for {context_date}...")
        subprocess.run(["python3", "scripts/poll_context.py", "--date", context_date], check=False)

        # Generate Tomorrow's Watchlist briefing (best-effort — never blocks pipeline)
        print("[*] Generating Tomorrow's Watchlist briefing...")
        subprocess.run(["python3", "briefing.py"], check=False)

        # AI-interpreted EOD summary (Desk Read) removed from the pipeline —
        # NVIDIA's free-tier Nemotron endpoint proved unreliable (repeated
        # 503s/timeouts on 2026-08-10/11) with no usable fallback (Anthropic
        # path requires a key/subscription this deployment doesn't have).
        # scripts/generate_ai_summary.py still exists if a reliable provider
        # is wired up later.

        # Build Vanguard HUD (best-effort)
        print("[*] Generating Vanguard HUD...")
        subprocess.run(["python3", "scripts/build_hud.py"], check=False)

        # Rolling 60-session retention (best-effort, never blocks the pipeline).
        # Keeps session_history.json (and everything flattened from it) bounded
        # to a fixed session count instead of growing forever — daily_compiler.py
        # loads that file wholesale on every run, so an unbounded history is an
        # unbounded and ever-growing memory footprint (see the 2026-08-10 OOM:
        # ~243 sessions had grown session_history.json past what the VPS could
        # hold in RAM alongside pandas/numpy/duckdb).
        print("[*] Pruning data outside the 60-session retention window...")
        subprocess.run(["python3", "scripts/prune_retention.py", "--retention-sessions", "60"], check=False)

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
