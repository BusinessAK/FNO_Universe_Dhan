"""
In-memory live state — the single source of truth the compute/trigger engines
read from. Keyed by (exchange_segment, security_id): latest price/OI, session
OHLC, and rolling 1-minute bars. One writer thread (the feed handler) inserts
new keys and mutates existing ones; the compute-cycle thread reads via
dirty_keys()/get()/snapshot(), all lock-guarded at the dict-shape level (see
StateStore's docstring) — a compute cycle can run concurrently with ticks
arriving without racing the feed thread's key inserts.

The key MUST include the segment: under the old Dhan feed, security_id was
unique only *within* a segment (sid 13 was both NIFTY (IDX) and ABB (NSE_EQ)).
Fyers keys by ticker string instead, which doesn't collide the same way, but
the (seg, sid) shape is kept so this store's contract doesn't depend on which
broker's identifiers happen to be collision-free this month.

Normalized tick shape (produced by feed_handler):
    {"seg": int, "sid": str, "ts": float(epoch), "ltp": float,
     "oi": int|None, "vol": int|None, "atp": float|None}
"""
from __future__ import annotations

import math
import threading
from collections import deque

Key = tuple[int, str]          # (exchange_segment, security_id) — sid is the Fyers ticker string


class SecurityState:
    __slots__ = ("seg", "sid", "ltp", "oi", "vol", "atp", "ts",
                 "o", "h", "l", "prev_close", "bars", "_bar", "is_dirty")

    def __init__(self, seg: int, sid: str):
        self.seg = seg
        self.sid = sid
        self.ltp = self.oi = self.vol = self.atp = None
        self.ts = 0.0
        self.o = self.h = self.l = None          # session OHLC
        self.prev_close = None
        self.bars = deque(maxlen=400)            # closed 1-min bars
        self._bar = None                         # in-progress bar
        self.is_dirty = True                     # force first compute

    @property
    def key(self) -> Key:
        return (self.seg, self.sid)

    @property
    def chg_pct(self) -> float:
        if self.ltp and self.prev_close:
            return (self.ltp - self.prev_close) / self.prev_close * 100.0
        return 0.0


class StateStore:
    """Structural mutation of _s (new-key inserts) and any full iteration over
    it are serialized through _lock. Per-object attribute get/set (the hot
    path in ingest()) is left unlocked: CPython's GIL makes a single
    attribute read/write atomic, and the feed thread is the only writer of
    any given SecurityState's fields — only the dict's own shape is shared
    across threads (the feed thread inserting new keys while the compute
    thread iterates for dirty ones)."""

    def __init__(self):
        self._s: dict[Key, SecurityState] = {}
        self._lock = threading.Lock()

    def get(self, seg: int, sid: str) -> SecurityState | None:
        with self._lock:
            return self._s.get((seg, sid))

    def _state(self, seg: int, sid: str) -> SecurityState:
        with self._lock:
            st = self._s.get((seg, sid))
            if st is None:
                st = self._s[(seg, sid)] = SecurityState(seg, sid)
            return st

    def seed_prev_close(self, seg: int, sid: str, prev_close: float):
        self._state(seg, sid).prev_close = prev_close

    def dirty_keys(self) -> list[Key]:
        """Snapshot of keys whose state changed since the last clear_dirty_flags().
        The one sanctioned way to inspect dirty state from outside this class —
        callers must not iterate self._s directly (see class docstring)."""
        with self._lock:
            return [k for k, st in self._s.items() if st.is_dirty]

    def ingest(self, tick: dict) -> str | None:
        """Update state from a tick. Returns the epoch-minute if a bar just closed.

        OI-only ticks (ltp=None, from standalone "OI Data" packets — the OI
        update path under MODE_FULL) update oi + ts but never touch price,
        OHLC, or bars. Dropping them entirely was the pre-full-map bug that
        would have silently starved every OI-derived metric."""
        st = self._state(tick["seg"], tick["sid"])
        ltp = tick.get("ltp")
        if ltp is None or (isinstance(ltp, float) and math.isnan(ltp)):
            if tick.get("oi") is not None and tick["oi"] != st.oi:
                st.oi = tick["oi"]
                st.ts = tick.get("ts", st.ts)
                st.is_dirty = True
            return None
            
        if ltp != st.ltp:
            st.ltp, st.ts = ltp, tick.get("ts", st.ts)
            st.is_dirty = True
        else:
            st.ts = tick.get("ts", st.ts)
            
        if tick.get("oi") is not None and tick["oi"] != st.oi:
            st.oi = tick["oi"]
            st.is_dirty = True
            
        if tick.get("vol") is not None and tick["vol"] != st.vol:
            st.vol = tick["vol"]
            st.is_dirty = True
            
        if tick.get("atp") is not None:
            st.atp = tick["atp"]
            
        # session OHLC
        st.o = st.o if st.o is not None else ltp
        st.h = ltp if st.h is None else max(st.h, ltp)
        st.l = ltp if st.l is None else min(st.l, ltp)
        # 1-min bar aggregation
        return self._roll_bar(st, ltp, tick.get("ts", st.ts))

    def clear_dirty_flags(self, keys: list[Key]):
        with self._lock:
            states = [self._s[k] for k in keys if k in self._s]
        for st in states:
            st.is_dirty = False

    def _roll_bar(self, st: SecurityState, ltp: float, ts: float) -> str | None:
        minute = int(ts // 60) * 60
        b = st._bar
        if b is None:
            st._bar = {"t": minute, "o": ltp, "h": ltp, "l": ltp, "c": ltp}
            return None
        if minute > b["t"]:
            st.bars.append(b)                    # close the prior bar
            st._bar = {"t": minute, "o": ltp, "h": ltp, "l": ltp, "c": ltp}
            return str(b["t"])                   # a bar closed → trigger engine wakes
        b["h"] = max(b["h"], ltp)
        b["l"] = min(b["l"], ltp)
        b["c"] = ltp
        return None

    def snapshot(self, keys: list[Key] | None = None) -> dict[Key, dict]:
        """Compact (seg, sid)-keyed dict of current state."""
        with self._lock:
            items = list(self._s.values()) if keys is None else [self._s[k] for k in keys if k in self._s]
        return {st.key: {"ltp": st.ltp, "chg": round(st.chg_pct, 2),
                         "oi": st.oi, "ts": st.ts} for st in items}
