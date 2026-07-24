#!/usr/bin/env python3
"""
Fyers API v3 Login Flow

This script helps you generate a daily access token for Fyers API v3.
Before running this, make sure you have created an app on the Fyers API dashboard
and added the following to your .env file:
FYERS_APP_ID="your_client_id-100" 
FYERS_APP_SECRET="your_secret_key"
FYERS_REDIRECT_URI="https://127.0.0.1:8080/"  (or whichever redirect URI you set)

Usage:
    python3 scripts/fyers_login.py
"""
import os
import sys
import webbrowser
from pathlib import Path
from urllib.parse import urlparse, parse_qs

try:
    from fyers_apiv3 import fyersModel
except ImportError:
    print("Please install fyers-apiv3 first: pip install fyers-apiv3")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent

def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip('"').strip("'")

def append_to_env(key, value):
    env = ROOT / ".env"
    lines = env.read_text().splitlines() if env.exists() else []
    
    # Remove existing key if present
    lines = [line for line in lines if not line.startswith(f"{key}=")]
    lines.append(f'{key}="{value}"')
    
    env.write_text("\n".join(lines) + "\n")
    print(f"\n[+] Successfully saved {key} to .env")

def main():
    load_env()
    
    # FYERS_CLIENT_ID/FYERS_SECRET_KEY are the canonical names (same ones
    # fyers_client.py reads); FYERS_APP_ID/FYERS_APP_SECRET kept as a fallback
    # for anyone who set the older names.
    client_id = os.environ.get("FYERS_CLIENT_ID") or os.environ.get("FYERS_APP_ID")
    secret_key = os.environ.get("FYERS_SECRET_KEY") or os.environ.get("FYERS_APP_SECRET")
    redirect_uri = os.environ.get("FYERS_REDIRECT_URI", "https://127.0.0.1:8080/")

    if not client_id or not secret_key:
        print("ERROR: FYERS_CLIENT_ID and FYERS_SECRET_KEY must be set in .env")
        print("Example:")
        print('FYERS_CLIENT_ID="YOUR_CLIENT_ID-100"')
        print('FYERS_SECRET_KEY="YOUR_SECRET_KEY"')
        sys.exit(1)
        
    print("Initializing Fyers Session...")
    session = fyersModel.SessionModel(
        client_id=client_id,
        secret_key=secret_key,
        redirect_uri=redirect_uri,
        response_type="code",
        grant_type="authorization_code"
    )
    
    auth_url = session.generate_authcode()
    print("\n" + "="*80)
    print("1. Please click the link below (or copy-paste it into your browser) to login.")
    print("2. After successful login, you will be redirected to an error/empty page.")
    print("3. Check the URL of that page and copy the value of the 'auth_code' parameter.")
    print("="*80 + "\n")
    print(f"Login URL:\n{auth_url}\n")
    
    try:
        webbrowser.open(auth_url)
    except:
        pass
        
    pasted = input("Paste the auth_code here: ").strip()

    if not pasted:
        print("Auth code cannot be empty.")
        sys.exit(1)

    # The redirected page's URL (not just the auth_code param) is what's
    # actually visible to copy, so pasting the whole thing is the natural
    # mistake — extract auth_code from it instead of sending the full URL
    # to Fyers as if it were the code.
    if pasted.startswith("http://") or pasted.startswith("https://"):
        query = urlparse(pasted).query
        parsed = parse_qs(query)
        if "auth_code" not in parsed:
            print(f"Couldn't find an 'auth_code' parameter in that URL: {pasted}")
            sys.exit(1)
        auth_code = parsed["auth_code"][0]
        print("(Detected a full URL — extracted the auth_code parameter from it.)")
    else:
        auth_code = pasted
        
    print("\nGenerating access token...")
    session.set_token(auth_code)
    response = session.generate_token()
    
    if response.get("s") == "ok" or "access_token" in response:
        access_token = response["access_token"]
        print("Authentication successful!")
        append_to_env("FYERS_ACCESS_TOKEN", access_token)
    else:
        print(f"Authentication failed. Response from Fyers: {response}")

if __name__ == "__main__":
    main()
