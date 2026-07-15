"""
In-memory live state — the single source of truth the compute/trigger engines
read from. Keyed by (exchange_segment, security_id): latest price/OI, session
OHLC, and rolling 1-minute bars. Single async writer (the feed handler), many
readers.

The key MUST include the segment: Dhan's security_id is unique only *within* a
segment, and the F&O universe really does collide — sid 13 is both NIFTY (IDX)
and ABB (NSE_EQ), sid 25 is both BANKNIFTY and ADANIENT. Keying by sid alone
merges those pairs into one state and silently corrupts both.

Normalized tick shape (produced by feed_handler):
    {"seg": int, "sid": int, "ts": float(epoch), "ltp": float,
     "oi": int|None, "vol": int|None, "atp": float|None}
"""
from __future__ import annotations

import math
from collections import deque

Key = tuple[int, int]          # (exchange_segment, security_id)


class SecurityState:
    __slots__ = ("seg", "sid", "ltp", "oi", "vol", "atp", "ts",
                 "o", "h", "l", "prev_close", "bars", "_bar")

    def __init__(self, seg: int, sid: int):
        self.seg = seg
        self.sid = sid
        self.ltp = self.oi = self.vol = self.atp = None
        self.ts = 0.0
        self.o = self.h = self.l = None          # session OHLC
        self.prev_close = None
        self.bars = deque(maxlen=400)            # closed 1-min bars
        self._bar = None                         # in-progress bar

    @property
    def key(self) -> Key:
        return (self.seg, self.sid)

    @property
    def chg_pct(self) -> float:
        if self.ltp and self.prev_close:
            return (self.ltp - self.prev_close) / self.prev_close * 100.0
        return 0.0


class StateStore:
    def __init__(self):
        self._s: dict[Key, SecurityState] = {}

    def get(self, seg: int, sid: int) -> SecurityState | None:
        return self._s.get((seg, sid))

    def _state(self, seg: int, sid: int) -> SecurityState:
        st = self._s.get((seg, sid))
        if st is None:
            st = self._s[(seg, sid)] = SecurityState(seg, sid)
        return st

    def seed_prev_close(self, seg: int, sid: int, prev_close: float):
        self._state(seg, sid).prev_close = prev_close

    def ingest(self, tick: dict) -> str | None:
        """Update state from a tick. Returns the epoch-minute if a bar just closed."""
        st = self._state(tick["seg"], tick["sid"])
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

    def snapshot(self, keys: list[Key] | None = None) -> dict[Key, dict]:
        """Compact (seg, sid)-keyed dict of current state."""
        items = self._s.values() if keys is None else (self._s[k] for k in keys if k in self._s)
        return {st.key: {"ltp": st.ltp, "chg": round(st.chg_pct, 2),
                         "oi": st.oi, "ts": st.ts} for st in items}
