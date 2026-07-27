import time
import threading
import random
from pathlib import Path
import sys

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from vanguard.live.state_store import StateStore
from vanguard.live.live_compute import LiveStructureEngine
from scripts.run_live import build_options_tape, eod_spot_closes, seed_oi_baseline
from vanguard.data.instrument_master import InstrumentMaster
from vanguard.live import config as C
from vanguard.live.bridge import Bridge
from vanguard.live.snapshot import build_key_symbol_map, write_snapshot

def run_stress_test():
    print("[sim] Booting Vanguard Local Simulator...")
    im = InstrumentMaster()
    
    # 1. Grab all Spot Symbols (Top N defaults to None = Full Universe)
    import duckdb
    db_path = Path("data/compiled/vanguard.duckdb")
    con = duckdb.connect(str(db_path), read_only=True)
    latest = con.execute("SELECT MAX(date) FROM daily_market_structure").fetchone()[0]
    rows = con.execute("SELECT symbol FROM daily_market_structure WHERE date = ?", [latest]).fetchall()
    spot_symbols = sorted({r[0] for r in rows} | set(C.INDEX_SYMBOLS))
    
    key_symbol = {}
    for s in spot_symbols:
        row = im.spot(s)
        if row:
            key_symbol[(0, str(row["security_id"]))] = s
            
    print(f"[sim] Loaded {len(key_symbol)} spot symbols.")
    
    from vanguard.live.subscription_mgr import SubscriptionManager
    sm = SubscriptionManager()
    spot_closes = eod_spot_closes()
    
    print("[sim] Building full universe options tape (this takes a moment)...")
    options_tape, covered_names, name_spots, key_to_meta = build_options_tape(im, sm, spot_closes)
    
    # 3. Boot StateStore & Engine
    store = StateStore()
    
    # Seed Prev Closes
    for s in spot_symbols:
        row = im.spot(s)
        if row and spot_closes.get(s):
            store.seed_prev_close(0, str(row["security_id"]), float(spot_closes[s]))
            
    oi_baseline = seed_oi_baseline()
    symbol_spot_key = {sym: key for key, sym in key_symbol.items()}
    
    engine = LiveStructureEngine(key_to_meta, oi_baseline, symbol_spot_key)
    
    print(f"[sim] Engine booted. {len(options_tape)} instruments in catalog.")
    
    # 4. Define Tick Injector Thread
    running = True
    
    def injector():
        """Simulates massive volatility by updating random options multiple times per second."""
        keys = list(key_to_meta.keys())
        ticks_injected = 0
        start = time.time()
        
        while running:
            # Pick a batch of 500 random instruments to update
            batch = random.sample(keys, min(500, len(keys)))
            for key in batch:
                # Randomly fluctuate LTP and OI
                fake_tick = {
                    "seg": key[0],
                    "sid": key[1],
                    "ts": time.time(),
                    "ltp": float(random.randint(5, 500)),
                    "vol": random.randint(1000, 50000),
                    "oi": random.randint(10000, 100000)
                }
                store.ingest(fake_tick)
                ticks_injected += 1
                
            time.sleep(0.1) # 10 loops per second -> 5,000 ticks/sec
            
            if ticks_injected % 50000 == 0:
                elapsed = time.time() - start
                print(f"[injector] Pushed {ticks_injected} ticks at {ticks_injected/elapsed:.0f} ticks/sec")

    # 5. Define Compute Thread
    def compute_loop():
        """Simulates the 30-second compute loop (sped up to 5 seconds for testing)."""
        cycle = 1
        while running:
            time.sleep(5)
            
            spot_prices = {}
            for sym in spot_symbols:
                key = symbol_spot_key.get(sym)
                st = store.get(*key) if key else None
                spot_prices[sym] = float(st.ltp) if (st and st.ltp is not None) else spot_closes.get(sym, 0.0)
            
            print(f"\n[cycle {cycle}] Executing compute...")
            
            t0 = time.time()
            res, events = engine.run_cycle(store, spot_prices)
            t1 = time.time()
            
            # Compute live setups for the UI
            from vanguard.live.live_compute import compute_live_setups
            live_setups = compute_live_setups(res, spot_prices)
            
            # Write to disk so the Bridge can serve it
            write_snapshot(store, key_symbol, events=events, structure=res, setups=live_setups)
            
            print(f"[cycle {cycle}] Solved Greeks & Walls in {t1-t0:.3f} seconds. Snapshot written.")
            cycle += 1

    
    print("[sim] Starting UI Bridge server...")
    bridge = Bridge()
    bridge.start()
    
    print("[sim] Launching threads (Run indefinitely, press Ctrl+C to stop)...")
    t_inj = threading.Thread(target=injector, daemon=True)
    t_comp = threading.Thread(target=compute_loop, daemon=True)
    
    t_inj.start()
    t_comp.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[sim] Shutting down simulator...")
        running = False
        t_inj.join()
        t_comp.join()

if __name__ == "__main__":
    run_stress_test()
