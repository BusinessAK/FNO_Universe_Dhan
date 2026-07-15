#!/usr/bin/env python3
"""
Vanguard live daemon (M0/M1 — the live tape).

Owns the single Dhan MarketFeed connection, streams spot + front futures for the
F&O universe + indices, and drives state_store + tick_journal. Runs only inside
the market-hours daemon window; sleeps off-hours.

    python3 scripts/run_live.py --dry-run    # build manifest + auth check, no socket
    python3 scripts/run_live.py              # live (market hours only)
"""
import argparse
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.live import config as C          # noqa: E402
from src.live import calendar as cal      # noqa: E402
from src.live.state_store import StateStore        # noqa: E402
from src.live.tick_journal import TickJournal      # noqa: E402
from src.live.subscription_mgr import SubscriptionManager  # noqa: E402


def compiled_universe() -> list[str] | None:
    """The 215 symbols we actually analyze (pins the live set to the EOD universe)."""
    try:
        import duckdb
        db = ROOT / "data" / "compiled" / "vanguard.duckdb"
        if not db.exists():
            return None
        con = duckdb.connect(str(db), read_only=True)
        latest = con.execute("SELECT MAX(date) FROM daily_market_structure").fetchone()[0]
        syms = [r[0] for r in con.execute(
            "SELECT DISTINCT symbol FROM daily_market_structure WHERE date=?", [latest]).fetchall()]
        con.close()
        return syms
    except Exception:
        return None


def build_tape():
    """Assemble the M1 tape manifest (spot + front futures).

    Returns (tape, stats, spot_symbols) — spot_symbols is the deduped symbol set
    the tape covers, so the snapshot map is built from exactly what we stream.
    """
    sm = SubscriptionManager()
    universe = compiled_universe()
    fno = sm.fno_underlyings(whitelist=universe)
    # The compiled universe already contains the indices (they have futures), so
    # `fno + INDEX_SYMBOLS` would subscribe each index twice. Dedupe.
    spot_symbols = sorted(set(fno) | set(C.INDEX_SYMBOLS))
    spot = sm.spot_manifest(spot_symbols)
    fut = sm.futures_manifest(fno)
    tape = spot + fut
    stats = {"fno": len(fno), "spot": len(spot), "fut": len(fut),
             "total": len(tape), "conns": len(sm.pack_connections(tape)),
             "msgs": len(sm.chunks(tape))}
    return tape, stats, spot_symbols


def seed_prev_close(store, im, symbols):
    """Seed prev_close from the latest EOD spot_close so chg% is correct from
    the first live tick (rather than waiting for a Previous Close packet)."""
    try:
        import duckdb
        db = ROOT / "data" / "compiled" / "vanguard.duckdb"
        con = duckdb.connect(str(db), read_only=True)
        latest = con.execute("SELECT MAX(date) FROM daily_market_structure").fetchone()[0]
        closes = {r[0]: r[1] for r in con.execute(
            "SELECT symbol, spot_close FROM daily_market_structure WHERE date=?", [latest]).fetchall()}
        con.close()
        n = 0
        for s in symbols:
            row = im.spot(s)
            if row and closes.get(s):
                store.seed_prev_close(int(row["feed_segment"]), int(row["security_id"]),
                                      float(closes[s]))
                n += 1
        print(f"[seed] prev_close seeded for {n} symbols from EOD {latest}")
    except Exception as e:
        print(f"[seed] prev_close seeding skipped: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="build manifest + auth check, no socket")
    args = ap.parse_args()

    print("=" * 70)
    print("  VANGUARD LIVE DAEMON — M1 tape")
    print("=" * 70)

    tape, stats, spot_symbols = build_tape()
    print(f"[manifest] F&O {stats['fno']} · spot {stats['spot']} · futures {stats['fut']} "
          f"→ {stats['total']} instruments / {stats['conns']} conn / {stats['msgs']} msgs")

    # auth probe
    auth_ok = False
    try:
        from src.data.dhan_client import DhanClient
        client = DhanClient()
        auth_ok, msg = client.check_auth()
        print(f"[auth] {'OK' if auth_ok else 'FAIL'} — {msg}")
    except Exception as e:
        print(f"[auth] client init failed: {e}")
        client = None

    if args.dry_run:
        print("[dry-run] manifest assembled + auth probed; not connecting. Exiting.")
        return

    if not auth_ok:
        print("[!] Auth not OK — refusing to start the feed. Check .env token validity.")
        sys.exit(1)

    # ── live loop ─────────────────────────────────────────────────────────
    from src.live.feed_handler import FeedHandler
    from src.live.snapshot import build_key_symbol_map, write_snapshot
    from src.live.bridge import Bridge
    from src.data.instrument_master import InstrumentMaster

    im = InstrumentMaster()
    key_symbol = build_key_symbol_map(im, spot_symbols)

    store = StateStore()
    seed_prev_close(store, im, spot_symbols)
    journal = TickJournal()
    fh = FeedHandler(client, store, journal)

    bridge = Bridge()
    bridge.start()

    import traceback
    logfile = C.LIVE_DIR / f"daemon_{cal.now_ist().strftime('%Y%m%d')}.log"

    def log(msg):
        line = f"{cal.now_ist().strftime('%H:%M:%S')} {msg}"
        print(line, flush=True)
        try:
            with open(logfile, "a") as f:
                f.write(line + "\n")
        except Exception:
            pass

    log(f"[live] open the terminal at http://{C.BRIDGE_HOST}:{C.BRIDGE_PORT}/")
    feed_started = False

    while True:
        if not cal.is_daemon_window():
            wait = cal.seconds_until_daemon_start()
            log(f"[sched] off-hours; sleeping {wait/60:.0f} min")
            time.sleep(min(max(wait, 30), 1800))
            continue

        if not feed_started:
            log(f"[live] entering session; streaming {stats['total']} instruments")
            threading.Thread(target=fh.run, args=(tape,), daemon=True).start()
            feed_started = True

        # Resilient tick: one bad iteration must never kill the daemon.
        try:
            journal.flush()
            write_snapshot(store, key_symbol)
            age = time.time() - fh.last_tick_ts if fh.last_tick_ts else 0
            if cal.is_market_open() and fh.last_tick_ts and age > C.STALE_TICK_ALERT:
                log(f"[watchdog] no tick for {age:.0f}s; feed reconnecting")
        except Exception as e:
            log(f"[loop] error (continuing): {e}")
            traceback.print_exc()
        time.sleep(C.SNAPSHOT_CADENCE)


if __name__ == "__main__":
    main()
