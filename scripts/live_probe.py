#!/usr/bin/env python3
"""
F1 live probe (TRD_fullmap_live_v1 §0, "remaining live-session checks").
Run ONCE during market hours (~10 min) before F2 work begins. Verifies, with
evidence written to data/live/probe_report_<date>.json:

  P1  Full-mode subscriptions actually deliver OI (and at what cadence)
  P2  Dhan accepts the full manifest scale (3 x ~4.7k) on one token
  P3  Option-Chain REST response shape (one paced call — sweeper contract)
  P4  Whether OI arrives via Full packets, OI Data packets, or both (dedupe)

    python3 scripts/live_probe.py --minutes 10
    python3 scripts/live_probe.py --minutes 3 --conns 1     # smaller smoke
"""
import argparse
import json
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd                                   # noqa: E402

from vanguard.live import config as C                      # noqa: E402
from vanguard.live import calendar as cal                  # noqa: E402
from vanguard.live.subscription_mgr import SubscriptionManager  # noqa: E402


class Stats:
    """Shared collector — one lock, coarse-grained (probe-only, not hot path)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.by_type = defaultdict(int)
        self.full_with_oi = 0
        self.oi_data_pkts = 0
        self.oi_last_seen: dict[tuple, list] = defaultdict(list)   # key -> [ts,...]
        self.keys_with_oi = set()
        self.keys_seen = set()
        self.conn_status: dict[int, str] = {}
        self.first_ts = None
        self.last_ts = None

    def tick(self, conn_id: int, raw: dict):
        if not isinstance(raw, dict):
            return
        t = raw.get("type", "?")
        key = (raw.get("exchange_segment"), raw.get("security_id"))
        now = time.time()
        with self.lock:
            self.by_type[t] += 1
            self.keys_seen.add(key)
            self.first_ts = self.first_ts or now
            self.last_ts = now
            oi = raw.get("OI")
            if oi not in (None, 0, "0"):
                self.keys_with_oi.add(key)
                self.oi_last_seen[key].append(now)
                if t == "OI Data":
                    self.oi_data_pkts += 1
                else:
                    self.full_with_oi += 1


def conn_worker(client, conn_id: int, instruments: list, stats: Stats, stop: threading.Event):
    try:
        feed = client.market_feed(instruments)
        feed.run_forever()
        stats.conn_status[conn_id] = "connected"
        while not stop.is_set():
            data = feed.get_data()
            if data:
                stats.tick(conn_id, data)
        feed.disconnect()
    except Exception as e:
        stats.conn_status[conn_id] = f"ERROR: {e}"


def latest_manifest() -> pd.DataFrame:
    files = sorted(C.LIVE_DIR.glob("ws_manifest_*.parquet"))
    if not files:
        print("[probe] no ws_manifest — run scripts/build_ws_manifest.py first")
        sys.exit(1)
    print(f"[probe] manifest: {files[-1].name}")
    return pd.read_parquet(files[-1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=10.0)
    ap.add_argument("--conns", type=int, default=None,
                    help="limit to first N connections (smoke mode)")
    ap.add_argument("--force", action="store_true", help="skip market-hours guard")
    args = ap.parse_args()

    if not args.force and not cal.is_market_open():
        print("[probe] market closed — run during 09:15-15:30 IST (or --force)")
        return 1

    from vanguard.data.dhan_client import DhanClient
    client = DhanClient()
    ok, msg = client.check_auth()
    print(f"[auth] {'OK' if ok else 'FAIL'} — {msg}")
    if not ok:
        return 1

    mf = latest_manifest()
    tape = [(int(r.seg), str(int(r.sid)), int(r.mode)) for r in mf.itertuples()]
    conns = SubscriptionManager.pack_connections(tape)
    if args.conns:
        conns = conns[: args.conns]
    print(f"[probe] subscribing {sum(len(c) for c in conns)} instruments over {len(conns)} conns "
          f"(modes: {mf['mode'].value_counts().to_dict()})")

    stats = Stats()
    stop = threading.Event()
    threads = []
    for i, chunk in enumerate(conns):
        th = threading.Thread(target=conn_worker, args=(client, i, chunk, stats, stop), daemon=True)
        th.start()
        threads.append(th)
        time.sleep(2.0)                       # stagger connects

    t_end = time.time() + args.minutes * 60
    while time.time() < t_end:
        time.sleep(15)
        with stats.lock:
            rate = sum(stats.by_type.values()) / max(1e-9, (stats.last_ts or 0) - (stats.first_ts or 0)) \
                if stats.first_ts else 0.0
            print(f"[probe] pkts={dict(stats.by_type)} | keys={len(stats.keys_seen)} "
                  f"| keys_with_OI={len(stats.keys_with_oi)} | ~{rate:.0f} pkt/s "
                  f"| conns={stats.conn_status}")
    stop.set()

    # P3: one paced Option-Chain REST call (NIFTY front expiry)
    chain_probe = {}
    try:
        opt = mf[(mf.symbol == "NIFTY") & (mf.kind == "OPT")]
        expiry = sorted(opt.expiry.unique())[0]
        from vanguard.data.instrument_master import InstrumentMaster
        im = InstrumentMaster()
        idx = im.df[(im.df.kind == "INDEX") & (im.df.underlying == "NIFTY")].iloc[0]
        time.sleep(3.0)                       # respect the 1/3s bucket
        res = client.option_chain(int(idx.security_id), "IDX_I", expiry)
        data = res.get("data", {}) if isinstance(res, dict) else {}
        oc = (data.get("data") or data).get("oc") if isinstance(data, dict) else None
        chain_probe = {
            "status": res.get("status") if isinstance(res, dict) else str(type(res)),
            "top_keys": sorted(data.keys()) if isinstance(data, dict) else None,
            "n_strikes": len(oc) if isinstance(oc, dict) else None,
        }
        print(f"[probe] option-chain REST: {chain_probe}")
    except Exception as e:
        chain_probe = {"error": str(e)}
        print(f"[probe] option-chain REST failed: {e}")

    # OI cadence: median gap between successive OI updates per instrument
    gaps = []
    for ts_list in stats.oi_last_seen.values():
        gaps += [b - a for a, b in zip(ts_list, ts_list[1:])]
    gaps.sort()
    med_gap = gaps[len(gaps) // 2] if gaps else None

    report = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "minutes": args.minutes,
        "conns": {str(k): v for k, v in stats.conn_status.items()},
        "packets_by_type": dict(stats.by_type),
        "distinct_instruments_seen": len(stats.keys_seen),
        "distinct_instruments_with_oi": len(stats.keys_with_oi),
        "oi_via_full_packets": stats.full_with_oi,
        "oi_via_oi_data_packets": stats.oi_data_pkts,
        "median_oi_update_gap_secs": med_gap,
        "option_chain_probe": chain_probe,
        "verdicts": {
            "P1_full_mode_delivers_oi": len(stats.keys_with_oi) > 0,
            "P2_scale_accepted": all("ERROR" not in str(v) for v in stats.conn_status.values())
                                  and len(stats.conn_status) == len(conns),
            "P3_rest_chain_ok": bool(chain_probe.get("n_strikes")),
            "P4_oi_dual_path": stats.full_with_oi > 0 and stats.oi_data_pkts > 0,
        },
    }
    out = C.LIVE_DIR / f"probe_report_{datetime.now().strftime('%Y%m%d')}.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"[probe] report -> {out}")
    print(json.dumps(report["verdicts"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
