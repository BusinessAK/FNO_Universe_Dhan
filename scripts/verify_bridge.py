#!/usr/bin/env python3
"""Bounded verification of the M1.5 chain: live feed -> state_store -> snapshot
-> bridge HTTP. Self-terminates via watchdog."""
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 10

def _wd():
    time.sleep(DURATION + 12)
    print("[watchdog] force exit", flush=True); os._exit(0)
threading.Thread(target=_wd, daemon=True).start()

from src.data.dhan_client import DhanClient
from src.data.instrument_master import InstrumentMaster
from src.live import config as C
from src.live.state_store import StateStore
from src.live.tick_journal import TickJournal
from src.live.feed_handler import FeedHandler
from src.live.snapshot import build_key_symbol_map, write_snapshot
from src.live.bridge import Bridge

# ABB/ADANIENT share a security_id with NIFTY/BANKNIFTY — keep both pairs here so
# a live run proves the (segment, security_id) keying holds against the real feed.
symbols = ["NIFTY", "ABB", "BANKNIFTY", "ADANIENT", "RELIANCE", "TCS", "HDFCBANK", "INFY", "SBIN"]
im = InstrumentMaster()
instruments = []
for s in symbols:
    sp = im.spot(s)
    if sp:
        instruments.append((int(sp["feed_segment"]), str(int(sp["security_id"])), C.MODE_QUOTE))
key_symbol = build_key_symbol_map(im, symbols)

client = DhanClient()
store = StateStore()
# seed prev_close from EOD so chg% is correct from the first tick
import duckdb
con = duckdb.connect(str(ROOT / "data/compiled/vanguard.duckdb"), read_only=True)
_latest = con.execute("SELECT MAX(date) FROM daily_market_structure").fetchone()[0]
_closes = {r[0]: r[1] for r in con.execute("SELECT symbol, spot_close FROM daily_market_structure WHERE date=?", [_latest]).fetchall()}
con.close()
for s in symbols:
    sp = im.spot(s)
    if sp and _closes.get(s):
        store.seed_prev_close(int(sp["feed_segment"]), int(sp["security_id"]), float(_closes[s]))
journal = TickJournal("BRIDGEVERIFY")
fh = FeedHandler(client, store, journal)

print(f"[verify] streaming {len(instruments)} spot names for {DURATION}s", flush=True)
threading.Thread(target=fh.run, args=(instruments,), daemon=True).start()
time.sleep(DURATION)

snap = write_snapshot(store, key_symbol)
print(f"[verify] snapshot: {snap['n']} live quotes, market_open={snap['market_open']}", flush=True)

bridge = Bridge()
bridge.start()
time.sleep(0.5)
with urllib.request.urlopen(f"http://{C.BRIDGE_HOST}:{C.BRIDGE_PORT}/snapshot", timeout=3) as r:
    body = r.read().decode()
print(f"[verify] bridge /snapshot HTTP {r.status}:", flush=True)
import json as _j
q = _j.loads(body)["quotes"]
for sym, v in q.items():
    print(f"    {sym:10s} ₹{v['ltp']:,.2f}  ({v['chg']:+.2f}%)", flush=True)

# HUD served?
with urllib.request.urlopen(f"http://{C.BRIDGE_HOST}:{C.BRIDGE_PORT}/", timeout=3) as r:
    hud_ok = r.status == 200 and b"VANGUARD" in r.read()[:5000]
print(f"[verify] bridge serves HUD: {hud_ok}", flush=True)

fh.stop(); journal.close()
try: journal.path.unlink()
except Exception: pass
print("[verify] done", flush=True)
os._exit(0)
