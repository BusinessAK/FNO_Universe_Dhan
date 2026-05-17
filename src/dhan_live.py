import os
import time
import urllib.request
import pandas as pd
import numpy as np
import threading
from datetime import datetime
from typing import Dict, List, Tuple
from dhanhq import DhanContext, MarketFeed
from src.greeks_engine import GreeksEngine

class DhanLiveEngine:
    MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"
    CACHE_PATH = "data/raw/dhan_scrip_master.csv"

    def __init__(self, client_id: str, access_token: str, risk_free_rate: float = 0.07):
        self.client_id = client_id
        self.access_token = access_token
        self.r = risk_free_rate
        self.greeks_engine = GreeksEngine(risk_free_rate=self.r)
        
        # Live State Buffers
        self.live_quotes: Dict[str, Dict] = {}  # token -> {'ltp': float, 'oi': int, 'oi_chg': int}
        self.spot_prices: Dict[str, float] = {}  # symbol -> float
        self.token_metadata: Dict[str, Dict] = {}  # token -> metadata dict
        self.symbol_to_spot_token: Dict[str, str] = {}  # symbol -> spot token
        self.spot_token_to_symbol: Dict[str, str] = {}  # spot token -> symbol
        
        self.feed_running = False
        self.feed_instance = None
        self.master_df = None

        os.makedirs("data/raw", exist_ok=True)
        os.makedirs("data/processed", exist_ok=True)

    def download_scrip_master(self, force: bool = False):
        """Downloads the detailed scrip master list from Dhan and caches it."""
        if not force and os.path.exists(self.CACHE_PATH):
            # Check if file was modified today
            mtime = datetime.fromtimestamp(os.path.getmtime(self.CACHE_PATH))
            if mtime.date() == datetime.today().date():
                print("[*] Using cached Dhan Scrip Master list.")
                return

        print(f"[*] Downloading detailed Dhan Scrip Master from {self.MASTER_URL} (this may take a moment)...")
        try:
            import requests
            response = requests.get(self.MASTER_URL, stream=True, timeout=60)
            if response.status_code == 200:
                with open(self.CACHE_PATH, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=1024*1024):
                        if chunk:
                            f.write(chunk)
                print("[SUCCESS] Scrip Master successfully downloaded and cached.")
            else:
                print(f"[!] Server returned status code {response.status_code}")
        except Exception as e:
            print(f"[!] Error downloading Dhan master list: {e}")

    def load_metadata(self, target_symbols: List[str], target_expiry: str):
        """
        Loads option tokens and spot token IDs for target symbols.
        target_expiry format: 'YYYY-MM-DD' (e.g. '2026-05-28')
        """
        self.download_scrip_master()
        
        print("[*] Loading instrument metadata...")
        # Load CSV using pandas
        df = pd.read_csv(self.CACHE_PATH, low_memory=False)
        self.master_df = df
        
        # Clean symbols
        df['SYMBOL_NAME'] = df['SYMBOL_NAME'].astype(str).str.strip().str.upper()
        df['UNDERLYING_SYMBOL'] = df['UNDERLYING_SYMBOL'].astype(str).str.strip().str.upper()
        
        symbols_upper = [s.upper() for s in target_symbols]
        
        # Try to load EOD close prices from signals.csv as fallback seeds
        eod_signals_path = "data/processed/signals.csv"
        eod_spots = {}
        if os.path.exists(eod_signals_path):
            try:
                sig_df = pd.read_csv(eod_signals_path)
                for _, row in sig_df.iterrows():
                    sym = str(row['SYMBOL']).upper().strip()
                    cmp = float(row.get('CMP', 0))
                    if cmp > 0:
                        eod_spots[sym] = cmp
                print(f"[SUCCESS] Seeded spot prices for {len(eod_spots)} symbols from EOD signals.csv.")
            except Exception as e:
                print(f"[!] Warning seeding spot prices: {e}")

        # 1. Map Spot tokens (Cash Market Equities + Indices)
        # Standard stocks: segment 'E', series 'EQ', short symbol is in UNDERLYING_SYMBOL
        spot_df = df[
            (df['EXCH_ID'] == 'NSE') & 
            (df['SEGMENT'] == 'E') &
            (df['SERIES'] == 'EQ') &
            (df['UNDERLYING_SYMBOL'].isin(symbols_upper))
        ]
        
        # Indices: segment 'I', short symbol is in SYMBOL_NAME
        index_df = df[
            (df['EXCH_ID'] == 'NSE') &
            (df['SEGMENT'] == 'I') &
            (df['SYMBOL_NAME'].isin(symbols_upper))
        ]
        
        combined_spot_df = pd.concat([spot_df, index_df])
        
        # Hardcoded realistic fallback closing prices as of May 15, 2026 if file cache is empty
        hardcoded_fallbacks = {
            'NIFTY': 23643.50,
            'BANKNIFTY': 47650.00,
            'FINNIFTY': 21180.00,
            'MIDCPNIFTY': 12240.00,
            'RELIANCE': 1336.40,
            'SBIN': 963.20,
            'TMPV': 356.55,
            'TATASTEEL': 216.84,
            'BHEL': 398.30
        }
        
        for _, row in combined_spot_df.iterrows():
            sym = row['UNDERLYING_SYMBOL'] if row['SEGMENT'] == 'E' else row['SYMBOL_NAME']
            sym = str(sym).upper().strip()
            token = str(row['SECURITY_ID'])
            self.symbol_to_spot_token[sym] = token
            self.spot_token_to_symbol[token] = sym
            # Seed with EOD close price if available, else hardcoded fallback, else standard fallback
            self.spot_prices[sym] = eod_spots.get(sym, hardcoded_fallbacks.get(sym, float(row.get('PREV_CLOSE', 0))))
            print(f"[*] Mapped Spot Token for {sym}: {token} (Seed Price: ₹{self.spot_prices[sym]:.2f})")

        # 2. Map Option tokens (Near-Month active expiry)
        options_df = df[
            (df['EXCH_ID'] == 'NSE') & 
            (df['SEGMENT'] == 'D') &
            (df['UNDERLYING_SYMBOL'].isin(symbols_upper)) &
            (df['SM_EXPIRY_DATE'] == target_expiry) &
            (df['INSTRUMENT_TYPE'] == 'OP')
        ]
        
        mapped_count = 0
        for _, row in options_df.iterrows():
            token = str(row['SECURITY_ID'])
            sym = row['UNDERLYING_SYMBOL']
            strike = float(row['STRIKE_PRICE'])
            opt_type = row['OPTION_TYPE'].upper() # 'CE' or 'PE'
            lot_size = int(row.get('LOT_SIZE', 1))
            
            self.token_metadata[token] = {
                'symbol': sym,
                'strike': strike,
                'option_type': opt_type,
                'lot_size': lot_size,
                'expiry': target_expiry
            }
            mapped_count += 1
            
        print(f"[SUCCESS] Loaded {mapped_count} option instruments for active expiry {target_expiry}.")

        # Seed Option quotes from EOD greeks.csv as fallback seeds
        eod_greeks_path = "data/processed/greeks.csv"
        if os.path.exists(eod_greeks_path):
            try:
                g_df = pd.read_csv(eod_greeks_path)
                eod_lookup = {}
                for _, row in g_df.iterrows():
                    k = (str(row['SYMBOL']).upper().strip(), float(row['STRIKE_PR']), str(row['OPTION_TYP']).upper().strip())
                    eod_lookup[k] = {
                        'ltp': float(row.get('CLOSE', 0)),
                        'oi': int(row.get('OPEN_INT', 0)),
                        'oi_chg': int(row.get('CHG_IN_OI', 0))
                    }
                
                seeded_count = 0
                for token, meta in self.token_metadata.items():
                    k = (meta['symbol'].upper(), meta['strike'], meta['option_type'].upper())
                    if k in eod_lookup:
                        self.live_quotes[token] = {
                            'ltp': eod_lookup[k]['ltp'],
                            'oi': eod_lookup[k]['oi'],
                            'oi_chg': eod_lookup[k]['oi_chg'],
                            'timestamp': datetime.now()
                        }
                        seeded_count += 1
                print(f"[SUCCESS] Seeded {seeded_count} active live quotes from EOD greeks.csv.")
            except Exception as e:
                print(f"[!] Warning seeding option quotes: {e}")

    def start(self):
        """Starts the Dhan Live Market Feed WebSocket in a persistent background thread."""
        if self.feed_running:
            print("[!] Feed already running.")
            return

        # Prepare subscription list
        instruments = []
        # Add spot tokens (Cash Market Equities)
        for sym, token in self.symbol_to_spot_token.items():
            instruments.append((MarketFeed.NSE, token, MarketFeed.Quote))
        
        # Add option tokens (Derivatives)
        for token in self.token_metadata.keys():
            instruments.append((MarketFeed.NSE_FNO, token, MarketFeed.Quote))

        print(f"[*] Initializing Dhan WebSocket for {len(instruments)} instruments...")

        def on_connect(instance):
            print("[SUCCESS] Connected to Dhan Market Feed.")
            # Dhan recommends subscribing
            instance.subscribe_symbols(instruments)

        def on_message(instance, message):
            try:
                # Handle both upper and lowercase keys for maximum compatibility
                token = str(message.get("security_id") or message.get("SecurityID") or "")
                if not token: return
                
                # Check if it's a Spot Price update
                if token in self.spot_token_to_symbol:
                    sym = self.spot_token_to_symbol[token]
                    new_spot = float(message.get("LTP") or message.get("ltp") or 0)
                    if new_spot > 0:
                        self.spot_prices[sym] = new_spot
                
                # Check if it's an Option update
                elif token in self.token_metadata:
                    ltp = float(message.get("LTP") or message.get("ltp") or 0)
                    oi = int(message.get("OI") or message.get("oi") or 0)
                    oi_chg = int(message.get("OI_Chg") or message.get("oi_chg") or 0)
                    
                    self.live_quotes[token] = {
                        'ltp': ltp,
                        'oi': oi,
                        'oi_chg': oi_chg,
                        'timestamp': datetime.now()
                    }
            except Exception as e:
                pass

        def on_error(instance, error):
            print(f"[!] Dhan Market Feed Error: {error}")

        def on_close(instance):
            print("[*] Dhan Market Feed Connection Closed.")

        # Initialize DhanContext and MarketFeed
        dhan_context = DhanContext(self.client_id, self.access_token)
        
        self.feed_instance = MarketFeed(
            dhan_context=dhan_context,
            instruments=instruments,
            on_connect=on_connect,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )

        self.feed_running = True
        
        # Run WebSocket loop in background thread
        ws_thread = threading.Thread(target=self.feed_instance.run_forever, daemon=True)
        ws_thread.start()
        
        # Start background recalculation thread (Every 5 seconds)
        calc_thread = threading.Thread(target=self._gex_recalc_loop, daemon=True)
        calc_thread.start()
        print("[SUCCESS] Background calculations worker started.")

    def _gex_recalc_loop(self):
        """Runs the Black-Scholes calculation and generates live signals/greeks CSVs."""
        while self.feed_running:
            time.sleep(5)  # Re-evaluate live GEX every 5 seconds
            
            try:
                greeks_list = []
                # 1. Recalculate Greeks for all active options using live Spot and live LTP
                for token, meta in self.token_metadata.items():
                    sym = meta['symbol']
                    spot = self.spot_prices.get(sym, 0)
                    if spot <= 0: continue
                    
                    quote = self.live_quotes.get(token)
                    if not quote: continue
                    
                    price = quote['ltp']
                    oi = quote['oi']
                    oi_chg = quote['oi_chg']
                    
                    if price <= 0 or oi <= 0: continue
                    
                    # Compute Time to Expiry (T) in years
                    expiry_dt = datetime.strptime(meta['expiry'], '%Y-%m-%d')
                    T = (expiry_dt - datetime.now()).days / 365.0
                    if T <= 0: T = 0.001
                    
                    K = meta['strike']
                    opt_type = meta['option_type']
                    
                    # Back-out implied volatility and compute Greeks
                    iv = self.greeks_engine.calculate_iv(price, spot, K, T, opt_type)
                    delta, gamma = self.greeks_engine.black_scholes_greeks(spot, K, T, iv, opt_type)
                    
                    # Gamma Exposure (GEX) = Gamma * OI * Spot * 0.01 * Lot Size * Multiplier
                    # In India, GEX is calculated on standard share counts:
                    multiplier = 1 if opt_type == 'CE' else -1
                    gex = gamma * oi * spot * 0.01 * multiplier
                    
                    greeks_list.append({
                        'SYMBOL': sym,
                        'STRIKE_PR': K,
                        'OPTION_TYP': opt_type,
                        'EXPIRY_DT': meta['expiry'],
                        'IV': iv,
                        'DELTA': delta,
                        'GAMMA': gamma,
                        'GEX': gex,
                        'OPEN_INT': oi,
                        'CHG_IN_OI': oi_chg,
                        'CLOSE': price,
                        'CMP': spot,
                        'LOT_SIZE': meta['lot_size']
                    })
                
                if len(greeks_list) == 0:
                    continue
                
                greeks_df = pd.DataFrame(greeks_list)
                greeks_df.to_csv("data/processed/greeks.csv", index=False)
                
                # 2. Recalculate Signals/Walls for the live dashboard
                signals = []
                for sym in self.spot_prices.keys():
                    spot = self.spot_prices[sym]
                    sym_greeks = greeks_df[greeks_df['SYMBOL'] == sym]
                    if sym_greeks.empty:
                        signals.append({
                            'RANK': len(signals) + 1,
                            'SYMBOL': sym,
                            'CMP': spot,
                            'CALL_WALL': 0.0,
                            'PUT_WALL': 0.0,
                            'GAMMA_FLIP': 0.0,
                            'Δ GEX (Lakhs)': 0.0,
                            'Δ CALL OI': "0.0L",
                            'Δ PUT OI': "0.0L",
                            'SCORE': 50
                        })
                        continue
                    
                    # Locate Walls (Strikes with largest absolute GEX)
                    ce_greeks = sym_greeks[sym_greeks['OPTION_TYP'] == 'CE']
                    pe_greeks = sym_greeks[sym_greeks['OPTION_TYP'] == 'PE']
                    
                    call_wall = ce_greeks.loc[ce_greeks['GEX'].idxmax()]['STRIKE_PR'] if not ce_greeks.empty else 0
                    put_wall = pe_greeks.loc[pe_greeks['GEX'].idxmin()]['STRIKE_PR'] if not pe_greeks.empty else 0
                    
                    # Locate Gamma Flip (Strike where net GEX transitions closest to 0)
                    strike_net = sym_greeks.groupby('STRIKE_PR')['GEX'].sum()
                    gamma_flip = strike_net.abs().idxmin() if not strike_net.empty else 0
                    
                    # Compute GEX Shift (Total GEX above spot vs below)
                    gex_above = sym_greeks[sym_greeks['STRIKE_PR'] > spot]['GEX'].sum()
                    gex_below = sym_greeks[sym_greeks['STRIKE_PR'] <= spot]['GEX'].sum()
                    net_gex = sym_greeks['GEX'].sum()
                    
                    # Calculate Score
                    score = int(np.clip(50 + (net_gex / 1e6), 0, 100)) # Normalized Score
                    
                    # Calculate Total OI shifts for both sides
                    total_call_oi_chg = ce_greeks['CHG_IN_OI'].sum() if not ce_greeks.empty else 0
                    total_put_oi_chg = pe_greeks['CHG_IN_OI'].sum() if not pe_greeks.empty else 0
                    
                    signals.append({
                        'RANK': len(signals) + 1,
                        'SYMBOL': sym,
                        'CMP': spot,
                        'CALL_WALL': call_wall,
                        'PUT_WALL': put_wall,
                        'GAMMA_FLIP': gamma_flip,
                        'Δ GEX (Lakhs)': round(net_gex / 1e5, 2),
                        'Δ CALL OI': f"{total_call_oi_chg/1e5:+.1f}L" if total_call_oi_chg else "0.0L",
                        'Δ PUT OI': f"{total_put_oi_chg/1e5:+.1f}L" if total_put_oi_chg else "0.0L",
                        'SCORE': score
                    })
                
                signals_df = pd.DataFrame(signals)
                signals_df.to_csv("data/processed/signals.csv", index=False)
                
            except Exception as e:
                print(f"[!] Error in GEX recalc thread: {e}")

    def stop(self):
        """Stops the live feed and closes all WebSocket connections."""
        self.feed_running = False
        if self.feed_instance:
            self.feed_instance.close_connection()
            print("[*] Live Feed successfully disconnected.")
