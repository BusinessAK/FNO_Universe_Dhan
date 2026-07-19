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
import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vanguard.live import config as C          # noqa: E402
from vanguard.live import calendar as cal      # noqa: E402
from vanguard.live.state_store import StateStore        # noqa: E402
from vanguard.live.tick_journal import TickJournal      # noqa: E402
from vanguard.live.subscription_mgr import SubscriptionManager  # noqa: E402
from vanguard.live.trigger_engine import TriggerEngine, load_armed_book  # noqa: E402
from vanguard.live.alert_sink import AlertSink                  # noqa: E402
from vanguard.live import live_compute as lc                    # noqa: E402


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


def build_trigger_engine(key_symbol: dict) -> TriggerEngine:
    """Load today's armed setups (daily_setups) and wire up the trigger engine
    against the same (segment, security_id) -> symbol map the spot tape uses —
    triggers are spot-based, so no separate keying is needed."""
    import duckdb
    db = ROOT / "data" / "compiled" / "vanguard.duckdb"
    con = duckdb.connect(str(db), read_only=True)
    try:
        book = load_armed_book(con)
    finally:
        con.close()
    return TriggerEngine(book, key_symbol)


def eod_spot_closes() -> dict[str, float]:
    """Latest EOD spot_close per symbol — used as the initial near-ATM window
    center at daemon start (before any live tick exists) and as the fallback
    spot for covered names whose spot instrument hasn't ticked yet."""
    import duckdb
    db = ROOT / "data" / "compiled" / "vanguard.duckdb"
    con = duckdb.connect(str(db), read_only=True)
    try:
        latest = con.execute("SELECT MAX(date) FROM daily_market_structure").fetchone()[0]
        return {r[0]: r[1] for r in con.execute(
            "SELECT symbol, spot_close FROM daily_market_structure WHERE date=?", [latest]).fetchall()}
    finally:
        con.close()


def build_options_tape(im, sm: SubscriptionManager, spot_closes: dict[str, float]):
    """M2 near-ATM options manifest: top-N-by-OI stocks + all indices, front
    expiry only (see the M2 plan — this scope is the one benchmarked to fit
    comfortably inside both the WS budget and the 30s compute cadence)."""
    import duckdb
    db = ROOT / "data" / "compiled" / "vanguard.duckdb"
    con = duckdb.connect(str(db), read_only=True)
    try:
        covered = lc.select_covered_names(con)
    finally:
        con.close()
    name_spots = {s: spot_closes[s] for s in covered if spot_closes.get(s)}
    options_tape = sm.options_manifest(name_spots)
    key_to_meta = lc.build_option_catalog(im, covered, name_spots)
    return options_tape, covered, name_spots, key_to_meta


def seed_oi_baseline() -> dict[tuple[str, float, str], float]:
    """Per-strike EOD OPEN_INT from the last compile's greeks.csv — the OI
    baseline live_compute falls back to until a live OI tick arrives for that
    instrument (NSE's OI dissemination is ~3-min floored regardless)."""
    path = ROOT / "data" / "processed" / "greeks.csv"
    if not path.exists():
        return {}
    try:
        import pandas as pd
        df = pd.read_csv(path, usecols=["SYMBOL", "STRIKE_PR", "OPTION_TYP", "OPEN_INT"])
        return {(r.SYMBOL, float(r.STRIKE_PR), r.OPTION_TYP): float(r.OPEN_INT)
                for r in df.itertuples()}
    except Exception as e:
        print(f"[live_compute] OI baseline seed failed (starting from zero): {e}")
        return {}


def structure_loop(store, structure_engine: lc.LiveStructureEngine, symbol_spot_key: dict,
                    covered_names: list[str], spot_closes: dict[str, float],
                    alert_sink: AlertSink, latest_structure: dict, log):
    """Runs forever in its own daemon thread at COMPUTE_CADENCE. Never lets one
    bad cycle kill the thread — same resilience posture as the main loop."""
    while True:
        time.sleep(C.COMPUTE_CADENCE)
        try:
            spot_prices = {}
            for sym in covered_names:
                key = symbol_spot_key.get(sym)
                st = store.get(*key) if key else None
                spot_prices[sym] = float(st.ltp) if (st and st.ltp is not None) else spot_closes.get(sym, 0.0)
            structure, events = structure_engine.run_cycle(store, spot_prices)
            latest_structure.clear()
            latest_structure.update(structure)
            if events:
                alert_sink.fire_all(events)
                append_live_events(events)
        except Exception as e:
            log(f"[live_compute] cycle error (continuing): {e}")


def append_live_events(events: list[dict]):
    if not events:
        return
    path = C.LIVE_DIR / f"live_events_{cal.now_ist().strftime('%Y%m%d')}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


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
        from vanguard.data.dhan_client import DhanClient
        client = DhanClient()
        auth_ok, msg = client.check_auth()
        print(f"[auth] {'OK' if auth_ok else 'FAIL'} — {msg}")
    except Exception as e:
        print(f"[auth] client init failed: {e}")
        client = None

    if args.dry_run:
        try:
            import duckdb
            db = ROOT / "data" / "compiled" / "vanguard.duckdb"
            con = duckdb.connect(str(db), read_only=True)
            book = load_armed_book(con)
            con.close()
            n_setups = sum(len(v) for v in book.values())
            print(f"[triggers] armed {n_setups} setups across {len(book)} symbols")
        except Exception as e:
            print(f"[triggers] dry-run armed-book check failed: {e}")
        try:
            from vanguard.data.instrument_master import InstrumentMaster
            sm = SubscriptionManager()
            im = InstrumentMaster()
            spot_closes = eod_spot_closes()
            options_tape, covered, name_spots, key_to_meta = build_options_tape(im, sm, spot_closes)
            combined = tape + options_tape
            print(f"[live_compute] covered {len(covered)} names ({len(name_spots)} with a spot to window on): "
                  f"{', '.join(covered[:10])}{'...' if len(covered) > 10 else ''}")
            print(f"[live_compute] options manifest: {len(options_tape)} instruments "
                  f"({len(key_to_meta)} catalog entries) — "
                  f"combined with spot/fut tape: {len(combined)} instruments / "
                  f"{len(sm.pack_connections(combined))} conn")
        except Exception as e:
            print(f"[live_compute] dry-run manifest check failed: {e}")
        print("[dry-run] manifest assembled + auth probed; not connecting. Exiting.")
        return

    if not auth_ok:
        print("[!] Auth not OK — refusing to start the feed. Check .env token validity.")
        sys.exit(1)

    # ── live loop ─────────────────────────────────────────────────────────
    from vanguard.live.feed_handler import FeedHandler
    from vanguard.live.snapshot import build_key_symbol_map, write_snapshot
    from vanguard.live.bridge import Bridge
    from vanguard.data.instrument_master import InstrumentMaster

    im = InstrumentMaster()
    key_symbol = build_key_symbol_map(im, spot_symbols)

    store = StateStore()
    seed_prev_close(store, im, spot_symbols)
    journal = TickJournal()

    trigger_engine = build_trigger_engine(key_symbol)
    alert_sink = AlertSink()
    print(f"[triggers] armed {trigger_engine.armed_count()} setups across "
          f"{len(trigger_engine.armed_book)} symbols")

    # ── M2: live structure (walls/GEX/gamma-flip/regime) ────────────────────
    sm = SubscriptionManager()
    spot_closes = eod_spot_closes()
    options_tape, covered_names, name_spots, key_to_meta = build_options_tape(im, sm, spot_closes)
    tape = tape + options_tape   # same connection/thread — fits comfortably (see the M2 plan)
    stats["total"] += len(options_tape)
    oi_baseline = seed_oi_baseline()
    structure_engine = lc.LiveStructureEngine(key_to_meta, oi_baseline)
    symbol_spot_key = {sym: key for key, sym in key_symbol.items()}
    latest_structure: dict = {}
    print(f"[live_compute] covered {len(covered_names)} names, {len(options_tape)} option "
          f"instruments ({len(oi_baseline)} EOD OI baseline rows seeded)")

    def on_bar_close(key, bar):
        fired = trigger_engine.on_bar_close(key, bar)
        if fired:
            alert_sink.fire_all(fired)
            append_live_events(fired)

    fh = FeedHandler(client, store, journal, on_bar_close=on_bar_close)

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
            threading.Thread(target=structure_loop,
                              args=(store, structure_engine, symbol_spot_key, covered_names,
                                    spot_closes, alert_sink, latest_structure, log),
                              daemon=True).start()
            feed_started = True

        # Resilient tick: one bad iteration must never kill the daemon.
        try:
            journal.flush()
            write_snapshot(store, key_symbol, events=list(alert_sink.recent), structure=latest_structure)
            age = time.time() - fh.last_tick_ts if fh.last_tick_ts else 0
            if cal.is_market_open() and fh.last_tick_ts and age > C.STALE_TICK_ALERT:
                log(f"[watchdog] no tick for {age:.0f}s; feed reconnecting")
        except Exception as e:
            log(f"[loop] error (continuing): {e}")
            traceback.print_exc()
        time.sleep(C.SNAPSHOT_CADENCE)


if __name__ == "__main__":
    main()
