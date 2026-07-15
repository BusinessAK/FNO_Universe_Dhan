"""
Live snapshot — the symbol-keyed JSON the HUD polls. Translates the
security-id-keyed state store into {symbol: {ltp, chg, oi}} that the HUD (which
knows symbols, not security ids) can overlay onto its EOD view.
"""
from __future__ import annotations

import json
import time

from src.live import config as C
from src.live import calendar as cal


def build_key_symbol_map(im, symbols: list[str]) -> dict[tuple[int, int], str]:
    """(exchange_segment, security_id) -> symbol for spot instruments.

    Keyed by segment+id, never id alone: NIFTY and ABB share security_id 13
    (as do BANKNIFTY and ADANIENT on 25), so an id-keyed map silently drops
    whichever symbol is built first.
    """
    out = {}
    for s in symbols:
        row = im.spot(s)
        if row:
            out[(int(row["feed_segment"]), int(row["security_id"]))] = s
    return out


def write_snapshot(store, key_symbol: dict[tuple[int, int], str], path=None) -> dict:
    """Serialize current live state to live_snapshot.json (symbol-keyed).

    Emits two distinct clocks, and consumers must not confuse them:
      ts      — when this file was written (i.e. the daemon loop is alive)
      feed_ts — the most recent tick across the tape (i.e. the *feed* is alive)
    Only feed_ts proves the data is live. The loop keeps writing even if the
    feed thread stalls, so a fresh `ts` over a stale `feed_ts` is exactly the
    "frozen prices behind a LIVE badge" failure — judge liveness on feed_ts.
    """
    path = path or C.SNAPSHOT_JSON
    quotes = {}
    feed_ts = 0.0
    for (seg, sid), sym in key_symbol.items():
        st = store.get(seg, sid)
        if st and st.ltp is not None:
            quotes[sym] = {"ltp": round(st.ltp, 2), "chg": round(st.chg_pct, 2),
                           "oi": st.oi, "ts": st.ts}
            feed_ts = max(feed_ts, st.ts or 0.0)
    snap = {"ts": time.time(), "feed_ts": feed_ts, "market_open": cal.is_market_open(),
            "n": len(quotes), "quotes": quotes}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(snap))
    tmp.replace(path)                     # atomic write (HUD never reads a partial file)
    return snap
