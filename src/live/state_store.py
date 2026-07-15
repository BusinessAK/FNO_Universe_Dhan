"""
In-memory live state — the single source of truth the compute/trigger engines
read from. Keyed by security_id: latest price/OI, session OHLC, and rolling
1-minute bars. Single async writer (the feed handler), many readers.

Normalized tick shape (produced by feed_handler):
    {"sid": int, "ts": float(epoch), "ltp": float,
     "oi": int|None, "vol": int|None, "atp": float|None}
"""
from __future__ import annotations

import math
from collections import deque


class SecurityState:
    __slots__ = ("sid", "ltp", "oi", "vol", "atp", "ts",
                 "o", "h", "l", "prev_close", "bars", "_bar")

    def __init__(self, sid: int):
        self.sid = sid
        self.ltp = self.oi = self.vol = self.atp = None
        self.ts = 0.0
        self.o = self.h = self.l = None          # session OHLC
        self.prev_close = None
        self.bars = deque(maxlen=400)            # closed 1-min bars
        self._bar = None                         # in-progress bar

    @property
    def chg_pct(self) -> float:
        if self.ltp and self.prev_close:
            return (self.ltp - self.prev_close) / self.prev_close * 100.0
        return 0.0


class StateStore:
    def __init__(self):
        self._s: dict[int, SecurityState] = {}

    def get(self, sid: int) -> SecurityState | None:
        return self._s.get(sid)

    def seed_prev_close(self, sid: int, prev_close: float):
        self._s.setdefault(sid, SecurityState(sid)).prev_close = prev_close

    def ingest(self, tick: dict) -> str | None:
        """Update state from a tick. Returns the epoch-minute if a bar just closed."""
        sid = tick["sid"]
        st = self._s.get(sid) or self._s.setdefault(sid, SecurityState(sid))
        ltp = tick.get("ltp")
        if ltp is None or (isinstance(ltp, float) and math.isnan(ltp)):
            return None
        st.ltp, st.ts = ltp, tick.get("ts", st.ts)
        if tick.get("oi") is not None:
            st.oi = tick["oi"]
        if tick.get("vol") is not None:
            st.vol = tick["vol"]
        if tick.get("atp") is not None:
            st.atp = tick["atp"]
        # session OHLC
        st.o = st.o if st.o is not None else ltp
        st.h = ltp if st.h is None else max(st.h, ltp)
        st.l = ltp if st.l is None else min(st.l, ltp)
        # 1-min bar aggregation
        return self._roll_bar(st, ltp, tick.get("ts", st.ts))

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

    def snapshot(self, sids: list[int] | None = None) -> dict:
        """Compact dict for the bridge/HUD."""
        items = self._s.values() if sids is None else (self._s[i] for i in sids if i in self._s)
        return {st.sid: {"ltp": st.ltp, "chg": round(st.chg_pct, 2),
                         "oi": st.oi, "ts": st.ts} for st in items}
