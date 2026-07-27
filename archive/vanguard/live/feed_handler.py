"""
Feed handler — owns the Fyers MarketFeed connection, normalizes packets, and
drives state_store + tick_journal + the bar-close callback (trigger engine wake).
"""
from __future__ import annotations

import time
import traceback
import threading

from vanguard.live.state_store import StateStore
from vanguard.live.tick_journal import TickJournal


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _key(raw: dict) -> tuple[int, str] | None:
    """(exchange_segment, security_id). We use seg=0 for all Fyers symbols, 
    and symbol as sid."""
    sid = raw.get("symbol")
    if not sid:
        return None
    return (0, str(sid))


def normalize(raw: dict) -> dict | None:
    """SDK tick dict → our normalized tick. Returns None for non-price packets."""
    if not isinstance(raw, dict):
        return None
    
    key = _key(raw)
    if key is None:
        return None
    seg, sid = key

    # Fyers v3 websocket payload example (litemode=False):
    # {'symbol': 'NSE:...', 'ltp': 100.5, 'vol_traded_today': 1500, 'open_interest': 5000, ...}
    
    # If ltp is missing, it's not a standard price update.
    ltp = raw.get("ltp")
    if ltp is None:
        # Check if it's an OI-only update (not typical in Fyers, they send full packets)
        if raw.get("open_interest") is not None:
            return {"seg": seg, "sid": sid, "ts": time.time(), "ltp": None, "oi": _int(raw.get("open_interest"))}
        return None
        
    try:
        ltp = float(ltp)
    except (TypeError, ValueError):
        return None

    tick = {"seg": seg, "sid": sid, "ts": time.time(), "ltp": ltp}
    
    # Map volume
    vol = raw.get("vol_traded_today") or raw.get("volume")
    if vol is not None:
        tick["vol"] = _int(vol)
        
    # Map open interest
    oi = raw.get("open_interest") or raw.get("OI")
    if oi is not None:
        tick["oi"] = _int(oi)
        
    # Average traded price
    atp = raw.get("avg_trade_price") or raw.get("avg_price")
    if atp is not None:
        tick["atp"] = _float(atp)
        
    return tick


class FeedHandler:
    def __init__(self, fyers_client, store: StateStore, journal: TickJournal,
                 on_bar_close=None):
        self.client = fyers_client
        self.store = store
        self.journal = journal
        self.on_bar_close = on_bar_close
        self._feed = None
        self._running = False
        self._stopped_evt = threading.Event()
        self.last_tick_ts = 0.0
        self.tick_count = 0

    def _handle(self, raw: dict):
        """Route one SDK packet. Prev-close seeds baseline; price packets update state."""
        if not isinstance(raw, dict):
            return
        
        # Fyers often sends a list of dictionaries if multiple symbols updated.
        if "symbolData" in raw:
            for item in raw["symbolData"]:
                self._process_single_tick(item)
        elif "symbol" in raw:
            self._process_single_tick(raw)

    def _process_single_tick(self, raw: dict):
        # Extract prev close if available
        pc = _float(raw.get("prev_close_price") or raw.get("prev_close"))
        if pc:
            key = _key(raw)
            if key is not None:
                self.store.seed_prev_close(*key, pc)

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
        """Run in a daemon thread. Connects once and then blocks until stop()
        is called.

        FyersDataSocket.connect() is NOT blocking (SDK-verified): it spawns
        ws_thread/message_thread/ping_thread and returns in ~2s. The SDK also
        owns reconnect-on-drop itself (market_feed() passes reconnect=True —
        FyersDataSocket.__on_close() calls self.connect() again internally,
        with its own backoff and a max-attempts cap). A wrapping while-loop
        that calls connect() again here would race that internal reconnect:
        FyersDataSocket is a __new__-level singleton, so a second connect()
        call reinitializes the *same* instance's state out from under any
        still-running threads from the previous one, instead of layering a
        clean new connection on top.
        """
        self._running = True
        self._stopped_evt.clear()

        def on_connect():
            print("[feed] connected, subscribing...")
            if self._feed:
                # FyersDataSocket subscribe takes a list of symbol strings
                syms = [i[1] for i in instruments]
                self._feed.subscribe(symbols=syms, data_type="SymbolUpdate")

        def on_close(message):
            print(f"[feed] disconnected: {message}")

        def on_error(message):
            print(f"[feed] error: {message}")

        def on_message(message):
            # Fyers sends a single dict or a dict with 'symbolData'
            # if message is a list, process each item
            if isinstance(message, list):
                for m in message:
                    self._handle(m)
            else:
                self._handle(message)

        print(f"[feed] connecting ({len(instruments)} instruments)...")
        try:
            self._feed = self.client.market_feed(
                instruments=instruments,
                on_connect=on_connect,
                on_close=on_close,
                on_error=on_error,
                on_ticks=on_message
            )
            self._feed.connect()
        except Exception as e:
            print(f"[feed] connect() crashed: {e}")
            traceback.print_exc()

        # connect() has already returned; the SDK's background threads carry
        # the connection (and its own reconnect-on-drop) from here. This
        # thread just waits for stop() to request shutdown.
        self._stopped_evt.wait()

    def stop(self):
        """Soft shutdown — disable the SDK's own reconnect loop first, then
        close the connection so ws_thread/message_thread/ping_thread are
        actually joined (close_connection(), not unsubscribe(), does that)."""
        self._running = False
        if self._feed:
            self._feed.restart_flag = False
            try:
                self._feed.close_connection()
            except Exception as e:
                print(f"[feed] close_connection() error: {e}")
            self._feed = None
        self._stopped_evt.set()
