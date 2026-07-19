"""
Feed handler — owns the Dhan MarketFeed connection, normalizes packets, and
drives state_store + tick_journal + the bar-close callback (trigger engine wake).

The connection loop uses the dhanhq v2 run_forever()/get_data() model. The
normalize() step is pure and unit-tested offline; the socket loop needs a live
market session to verify (only you can run that).
"""
from __future__ import annotations

import time
import traceback

from vanguard.live.state_store import StateStore
from vanguard.live.tick_journal import TickJournal


def _key(raw: dict) -> tuple[int, int] | None:
    """(exchange_segment, security_id) — the instrument identity. security_id
    alone is ambiguous across segments (sid 13 = NIFTY *and* ABB), so a packet
    without a segment is unkeyable and must be dropped rather than guessed at."""
    seg, sid = _int(raw.get("exchange_segment")), _int(raw.get("security_id"))
    return None if seg is None or sid is None else (seg, sid)


def normalize(raw: dict) -> dict | None:
    """SDK tick dict → our normalized tick. Returns None for non-price packets
    (those are handled separately, e.g. Previous Close seeds prev_close)."""
    if not isinstance(raw, dict):
        return None
    t = raw.get("type", "")
    key = _key(raw)
    if key is None:
        return None
    seg, sid = key

    if t in ("Ticker Data", "Quote Data", "Full Data", "Market Depth"):
        ltp = raw.get("LTP")
        if ltp is None:
            return None
        try:
            ltp = float(ltp)
        except (TypeError, ValueError):
            return None
        tick = {"seg": seg, "sid": sid, "ts": time.time(), "ltp": ltp}
        if raw.get("volume") is not None:
            tick["vol"] = _int(raw["volume"])
        if raw.get("OI") is not None:
            tick["oi"] = _int(raw["OI"])
        if raw.get("avg_price") is not None:
            tick["atp"] = _float(raw["avg_price"])
        return tick

    if t == "OI Data":
        oi = _int(raw.get("OI"))
        if oi is None:
            return None
        return {"seg": seg, "sid": sid, "ts": time.time(), "ltp": None, "oi": oi}

    return None


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class FeedHandler:
    def __init__(self, dhan_client, store: StateStore, journal: TickJournal,
                 on_bar_close=None):
        self.client = dhan_client
        self.store = store
        self.journal = journal
        self.on_bar_close = on_bar_close
        self._feed = None
        self._running = False
        self.last_tick_ts = 0.0
        self.tick_count = 0

    def _handle(self, raw: dict):
        """Route one SDK packet. Prev-close seeds baseline; OI-only updates OI;
        price packets update state + journal + maybe fire a bar close."""
        if not isinstance(raw, dict):
            return
        if raw.get("type") == "Previous Close":
            key = _key(raw)
            pc = _float(raw.get("prev_close") or raw.get("Previous Close"))
            if key is not None and pc:
                self.store.seed_prev_close(*key, pc)
            return
        tick = normalize(raw)
        if tick is None:
            return
        self.last_tick_ts = time.time()
        self.tick_count += 1
        if tick.get("ltp") is not None:
            self.journal.append(tick)
        closed = self.store.ingest(tick)
        if closed and self.on_bar_close:
            self.on_bar_close((tick["seg"], tick["sid"]), closed)

    def run(self, instruments: list):
        """Blocking connection loop — run in a daemon thread. Reconnects on drop."""
        self._running = True
        backoff = 1.0
        while self._running:
            try:
                self._feed = self.client.market_feed(instruments)
                self._feed.run_forever()
                backoff = 1.0
                while self._running:
                    data = self._feed.get_data()
                    if data:
                        self._handle(data)
            except Exception as e:
                print(f"[feed_handler] connection error: {e}; reconnecting in {backoff:.0f}s")
                traceback.print_exc()
                time.sleep(backoff)
                backoff = min(60.0, backoff * 2)

    def stop(self):
        self._running = False
        try:
            if self._feed:
                self._feed.disconnect()
        except Exception:
            pass
