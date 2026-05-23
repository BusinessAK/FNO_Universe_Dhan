import sys
import os
from pnsea import NSE

try:
    print("[*] Initializing PNSEA Client...")
    nse = NSE()
    print("[*] Fetching NIFTY Option Chain...")
    df, expiries, spot = nse.options.option_chain("NIFTY")
    print(f"[SUCCESS] Spot: {spot}, Expiries count: {len(expiries)}")
    print("[*] DataFrame Columns:")
    print(list(df.columns))
    print("[*] First 2 rows:")
    print(df.head(2).to_dict(orient='records'))
except Exception as e:
    print(f"[ERROR] Failed: {e}")
