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


def is_structure_validated() -> bool:
    """True once at least one scripts/live_parity_check.py run has passed —
    the HUD's live structure watermark ("INDICATIVE") clears on this. Checks
    every parity_*.json ever written, not just today's: the gate is "has this
    method ever been proven correct," not "was it re-proven today." A later
    regression would need its own re-arm logic — not built, out of scope here."""
    for f in sorted(C.LIVE_DIR.glob("parity_*.json")):
        try:
            if json.loads(f.read_text()).get("passed"):
                return True
        except Exception:
            continue
    return False


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


def write_snapshot(store, key_symbol: dict[tuple[int, int], str], path=None,
                    events: list[dict] | None = None,
                    structure: dict[str, dict] | None = None) -> dict:
    """Serialize current live state to live_snapshot.json (symbol-keyed).

    Emits two distinct clocks, and consumers must not confuse them:
      ts      — when this file was written (i.e. the daemon loop is alive)
      feed_ts — the most recent tick across the tape (i.e. the *feed* is alive)
    Only feed_ts proves the data is live. The loop keeps writing even if the
    feed thread stalls, so a fresh `ts` over a stale `feed_ts` is exactly the
    "frozen prices behind a LIVE badge" failure — judge liveness on feed_ts.

    `events` (optional) is the trigger engine's + live structure engine's
    combined recent-events log, most-recent-first — passed through as-is so
    the HUD's Live Triggers panel renders the server-side transition truth
    rather than recomputing it client-side.

    `structure` (optional, M2) is {symbol: {call_wall, put_wall, gamma_flip,
    gex, gex_intensity, iv_avg, gamma_regime, computed_at}} for covered
    (top-N-by-OI + indices) symbols only — absent means "not covered," and the
    dossier falls back to EOD-only for that symbol, same as today.
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
            "n": len(quotes), "quotes": quotes, "events": events or [],
            "structure": structure or {}, "structure_validated": is_structure_validated()}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(snap))
    tmp.replace(path)                     # atomic write (HUD never reads a partial file)
    return snap
