#!/usr/bin/env python3
"""Bounded live-tape capture — proves the real socket + normalize + ingest path.
Self-terminates via a hard watchdog so it can never hang the session.

    python3 scripts/live_capture_test.py <seconds> <light|full>
"""
import os
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vanguard.data.dhan_client import DhanClient          # noqa: E402
from vanguard.data.instrument_master import InstrumentMaster  # noqa: E402
from vanguard.live.feed_handler import normalize            # noqa: E402
from vanguard.live import config as C                       # noqa: E402

DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 15
MODE = sys.argv[2] if len(sys.argv) > 2 else "light"

# Hard watchdog: force-exit no matter what the socket does.
def _watchdog():
    time.sleep(DURATION + 8)
    print("[watchdog] force exit", flush=True)
    os._exit(0)
threading.Thread(target=_watchdog, daemon=True).start()

im = InstrumentMaster()
name = {}          # security_id -> readable label
instruments = []

def add(seg, sid, label):
    instruments.append((int(seg), str(int(sid)), C.MODE_QUOTE))
    name[int(sid)] = label

if MODE == "light":
    for sym in ("NIFTY", "RELIANCE"):
        sp = im.spot(sym); add(sp["feed_segment"], sp["security_id"], f"{sym} spot")
    fut = im.futures("RELIANCE").sort_values("expiry")
    if not fut.empty:
        add(C.SEG_NSE_FNO, fut.iloc[0].security_id, "RELIANCE fut")
else:
    from vanguard.live.subscription_mgr import SubscriptionManager
    import duckdb
    con = duckdb.connect(str(ROOT / "data/compiled/vanguard.duckdb"), read_only=True)
    latest = con.execute("SELECT MAX(date) FROM daily_market_structure").fetchone()[0]
    uni = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM daily_market_structure WHERE date=?", [latest]).fetchall()]
    con.close()
    sm = SubscriptionManager()
    fno = sm.fno_underlyings(whitelist=uni)
    for seg, sid, mode in sm.spot_manifest(fno + C.INDEX_SYMBOLS):
        instruments.append((seg, sid, mode))
    for seg, sid, mode in sm.futures_manifest(fno):
        instruments.append((seg, sid, mode))

print(f"[capture] mode={MODE}  instruments={len(instruments)}  duration={DURATION}s", flush=True)

client = DhanClient()
feed = client.market_feed(instruments)

seen = {}          # sid -> latest normalized tick
counts = defaultdict(int)
start = time.time()
try:
    feed.run_forever()                     # connect + subscribe
    while time.time() - start < DURATION:
        data = feed.get_data()
        if isinstance(data, dict):
            t = data.get("type", "")
            counts[t] += 1
            n = normalize(data)
            if n and n.get("ltp") is not None:
                seen[n["sid"]] = n
except Exception as e:
    print(f"[capture] loop error: {e}", flush=True)

print(f"\n[capture] packets by type: {dict(counts)}", flush=True)
print(f"[capture] instruments with live LTP: {len(seen)}", flush=True)
if MODE == "light":
    for sid, t in seen.items():
        print(f"  {name.get(sid, sid):18s} LTP ₹{t['ltp']:,.2f}"
              f"{'  OI '+str(t['oi']) if t.get('oi') else ''}", flush=True)
else:
    shown = 0
    for sid, t in seen.items():
        if shown < 12:
            print(f"  sid {sid:>8}  LTP ₹{t['ltp']:,.2f}", flush=True); shown += 1
    print(f"  ... {len(seen)} total names live", flush=True)

try:
    feed.disconnect()
except Exception:
    pass
print("[capture] done", flush=True)
os._exit(0)
