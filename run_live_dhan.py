#!/usr/bin/env python3
import os
import sys
import time
import certifi

# Globally resolve macOS Python SSL Certificate verification failures natively using certifi
os.environ['SSL_CERT_FILE'] = certifi.where()
os.environ['WEBSOCKETS_SSL_CA_FILE'] = certifi.where()

from src.dhan_live import DhanLiveEngine

def main():
    print("=" * 80)
    print("          VANGUARD QUANTITATIVE TERMINAL - LIVE DHAN BRIDGE")
    print("=" * 80)
    
    # Load .env file natively if it exists
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.strip().split("=", 1)
                    os.environ[k.strip()] = v.strip().replace('"', '').replace("'", "")

    # 1. Load or prompt for credentials
    client_id = os.environ.get("DHAN_CLIENT_ID")
    access_token = os.environ.get("DHAN_ACCESS_TOKEN")
    
    if not client_id or not access_token:
        print("[*] No API credentials found in environment variables.")
        client_id = input("Enter your Dhan Client ID: ").strip()
        access_token = input("Enter your Dhan Access Token: ").strip()
        
        if not client_id or not access_token:
            print("[!] Client ID and Access Token are required. Exiting.")
            sys.exit(1)
            
    # 2. Configure target symbols and expiry
    # Target expiry format: YYYY-MM-DD
    target_expiry = "2026-05-26"  # Near-Month May 2026 Expiry
    
    # Track major liquid F&O stocks and index
    target_symbols = ["TMPV", "RELIANCE", "NIFTY", "BHEL", "TATASTEEL", "SBIN"]
    
    print("\n" + "-" * 80)
    print(f"Target Expiry:  {target_expiry}")
    print(f"Target Symbols: {', '.join(target_symbols)}")
    print("-" * 80 + "\n")
    
    # 3. Initialize Live Engine
    engine = DhanLiveEngine(client_id=client_id, access_token=access_token)
    
    try:
        # Load metadata and prepare WebSocket subscription tokens
        engine.load_metadata(target_symbols=target_symbols, target_expiry=target_expiry)
        
        # Start Dhan Live Feed WebSocket and Background Calculator
        engine.start()
        
        print("\n" + "=" * 80)
        print("[SUCCESS] Real-time Dhan options market feed is successfully running!")
        print("[*] GEX and Greeks recalculation thread: Running every 5 seconds.")
        print("[*] Dashboard update pipeline: Active.")
        print("[*] Toggle 'AUTO REFRESH (60s)' on your Streamlit Dashboard to see live updates!")
        print("Press Ctrl+C to terminate the bridge.")
        print("=" * 80 + "\n")
        
        # Keep main thread alive
        while True:
            # Print a diagnostic snapshot of live updates
            time.sleep(10)
            spot_log = ", ".join([f"{sym}: ₹{engine.spot_prices.get(sym, 0):,.2f}" for sym in target_symbols])
            active_options = len(engine.live_quotes)
            print(f"[LIVE SNAPSHOT] Active Options Streaming: {active_options} | Spots: {spot_log}")
            
    except KeyboardInterrupt:
        print("\n[*] Terminating Dhan Live Bridge...")
        engine.stop()
        print("[SUCCESS] Clean exit. Goodbye.")
        sys.exit(0)
    except Exception as e:
        print(f"\n[!] Critical Error: {e}")
        engine.stop()
        sys.exit(1)

if __name__ == "__main__":
    main()
