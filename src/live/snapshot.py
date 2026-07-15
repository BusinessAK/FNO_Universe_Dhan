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


def build_sid_symbol_map(im, symbols: list[str]) -> dict[int, str]:
    """security_id -> symbol for spot instruments (what the HUD displays)."""
    out = {}
    for s in symbols:
        row = im.spot(s)
        if row:
            out[int(row["security_id"])] = s
    return out


def write_snapshot(store, sid_symbol: dict[int, str], path=None) -> dict:
    """Serialize current live state to live_snapshot.json (symbol-keyed)."""
    path = path or C.SNAPSHOT_JSON
    quotes = {}
    for sid, sym in sid_symbol.items():
        st = store.get(sid)
        if st and st.ltp is not None:
            quotes[sym] = {"ltp": round(st.ltp, 2), "chg": round(st.chg_pct, 2),
                           "oi": st.oi, "ts": st.ts}
    snap = {"ts": time.time(), "market_open": cal.is_market_open(),
            "n": len(quotes), "quotes": quotes}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(snap))
    tmp.replace(path)                     # atomic write (HUD never reads a partial file)
    return snap
