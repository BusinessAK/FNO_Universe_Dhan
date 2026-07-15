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
    """Assemble the M1 tape manifest (spot + front futures). Returns (tape, stats)."""
    sm = SubscriptionManager()
    universe = compiled_universe()
    fno = sm.fno_underlyings(whitelist=universe)
    spot = sm.spot_manifest(fno + C.INDEX_SYMBOLS)
    fut = sm.futures_manifest(fno)
    tape = spot + fut
    stats = {"fno": len(fno), "spot": len(spot), "fut": len(fut),
             "total": len(tape), "conns": len(sm.pack_connections(tape)),
             "msgs": len(sm.chunks(tape))}
    return tape, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="build manifest + auth check, no socket")
    args = ap.parse_args()

    print("=" * 70)
    print("  VANGUARD LIVE DAEMON — M1 tape")
    print("=" * 70)

    tape, stats = build_tape()
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
    store = StateStore()
    journal = TickJournal()
    fh = FeedHandler(client, store, journal)

    while True:
        wait = cal.seconds_until_daemon_start()
        if wait > 0:
            print(f"[sched] off-hours; sleeping {wait/60:.0f} min until daemon window")
            time.sleep(min(wait, 1800))
            continue

        print(f"[live] entering session; streaming {stats['total']} instruments")
        t = threading.Thread(target=fh.run, args=(tape,), daemon=True)
        t.start()
        while cal.is_daemon_window():
            journal.flush()
            age = time.time() - fh.last_tick_ts if fh.last_tick_ts else 0
            if cal.is_market_open() and fh.last_tick_ts and age > C.STALE_TICK_ALERT:
                print(f"[watchdog] no tick for {age:.0f}s in market hours")
            time.sleep(C.SNAPSHOT_CADENCE)
        print("[live] daemon window closed; stopping feed, flushing journal")
        fh.stop()
        journal.close()


if __name__ == "__main__":
    main()
