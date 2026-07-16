#!/usr/bin/env python3
"""Build the Vanguard Orbital Deck HUD.

Exports the last N compiled sessions from vanguard.duckdb, embeds them as JSON
into hud/template.html, and writes the self-contained hud/vanguard_hud.html.
The deck supports session time-travel across the exported window.

Usage:
    python3 scripts/build_hud.py [--db PATH] [--out PATH] [--sessions 30]
"""
import argparse
import json
import math
import re
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.config.sector_mapping import get_sector  # noqa: E402
from src.core.config import TREND_WINDOW_SESSIONS  # noqa: E402

MS_COLS = [
    "date", "symbol", "sector", "spot_close", "spot_change_pct", "pcr", "iv", "iv_shift",
    "gex_intensity", "gex_shift", "gamma_regime", "structural_bias",
    "conviction_score", "priority_score", "ifs_score", "smart_money_persistence",
    "futures_oi", "futures_oi_chg", "net_inv_shift", "delta_ce_oi", "delta_pe_oi",
    "call_wall", "put_wall", "gamma_flip", "ce_interp", "pe_interp", "suggested_strategy",
    "structure_flip", "prev_structural_bias", "flip_confidence", "flip_strength",
]

# Sessions of lookback the flip radar's whipsaw guard needs behind each exported
# session. Derived here rather than in the HUD: the guard has to see sessions the
# export window itself does not contain, or the oldest exported sessions would
# report every flip as fresh.
FLIP_REPEAT_LOOKBACK = 3
SETUP_COLS = ["date", "symbol", "sector", "setup_type", "setup_types", "bias",
              "trigger_strike", "invalidation_strike", "expected_behavior", "dealer_behavior"]
CHANGE_COLS = ["date", "symbol", "icon", "type", "msg", "rank"]
BREADTH_COLS = ["date", "bullish_pct", "bearish_pct", "compression_pct",
                "expansion_pct", "transition_pct", "mean_rev_pct"]
CM_COLS = ["date", "cm_ad_ratio", "cm_net_advances", "cm_ad_line", "cm_mcclellan_osc",
           "cm_pct_above_20dma", "cm_pct_above_50dma", "cm_pct_above_200dma",
           "cm_new_highs", "cm_new_lows"]

TAG_RE = re.compile(r"<[^>]+>")


def clean(v):
    """JSON-safe cell: NaN/Inf -> None, floats rounded, timestamps -> ISO date."""
    if v is None:
        return None
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return round(v, 6)
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d")
    return v


def table(con, sql, cols, params=()):
    rows = con.execute(sql, params).fetchall()
    return {"cols": cols, "rows": [[clean(c) for c in r] for r in rows]}


def add_flip_repeat(con, tbl, sessions):
    """Tag each flip whose symbol also flipped in the FLIP_REPEAT_LOOKBACK sessions
    before it — mostly IFS churn rather than a fresh structural turn.

    Reads back past the export window so the oldest exported sessions are judged
    against real history instead of an empty lookback.
    """
    # Keys are compared against already-cleaned row values, so normalise both sides.
    window = sorted(clean(r[0]) for r in con.execute(
        "SELECT DISTINCT date FROM daily_market_structure WHERE date <= ? "
        "ORDER BY date DESC LIMIT ?",
        (sessions[-1], len(sessions) + FLIP_REPEAT_LOOKBACK)).fetchall())
    order = {d: i for i, d in enumerate(window)}

    flipped = set()
    for sym, d in con.execute(
        "SELECT symbol, date FROM daily_market_structure "
        "WHERE structure_flip IS NOT NULL AND structure_flip != 'NONE' AND date <= ?",
        (sessions[-1],)
    ).fetchall():
        i = order.get(clean(d))
        if i is not None:
            flipped.add((sym, i))

    di, yi, fi = tbl["cols"].index("date"), tbl["cols"].index("symbol"), tbl["cols"].index("structure_flip")
    tbl["cols"].append("flip_repeat")
    for r in tbl["rows"]:
        i = order.get(r[di])
        repeat = (
            r[fi] not in (None, "NONE")
            and i is not None
            and any((r[yi], i - k) in flipped for k in range(1, FLIP_REPEAT_LOOKBACK + 1))
        )
        r.append(repeat)


def remap_sector(tbl):
    """Apply current sector mapping at export time so mapping fixes show
    without waiting for a full recompile (DB bakes sector at compile time)."""
    si, yi = tbl["cols"].index("sector"), tbl["cols"].index("symbol")
    for r in tbl["rows"]:
        mapped = get_sector(r[yi])
        if mapped != "Other":
            r[si] = mapped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "compiled" / "vanguard.duckdb"))
    ap.add_argument("--out", default=str(ROOT / "hud" / "vanguard_hud.html"))
    ap.add_argument("--sessions", type=int, default=30)
    args = ap.parse_args()

    con = duckdb.connect(args.db, read_only=True)
    sessions = [r[0] for r in con.execute(
        "SELECT DISTINCT date FROM daily_market_structure ORDER BY date DESC LIMIT ?",
        (args.sessions,)).fetchall()]
    sessions.sort()
    ph = ", ".join("?" * len(sessions))

    data = {
        "meta": {"session": sessions[-1], "sessions": sessions},
        "market_structure": table(
            con,
            f"SELECT {', '.join(MS_COLS)} FROM daily_market_structure "
            f"WHERE date IN ({ph}) ORDER BY date, priority_score DESC NULLS LAST",
            MS_COLS, sessions),
        "setups": table(
            con,
            f"SELECT {', '.join(SETUP_COLS)} FROM daily_setups "
            f"WHERE date IN ({ph}) AND setup_type != 'NONE'",
            SETUP_COLS, sessions),
        "changes": table(
            con,
            f"SELECT {', '.join(CHANGE_COLS)} FROM daily_changes "
            f"WHERE date IN ({ph}) ORDER BY date, rank",
            CHANGE_COLS, sessions),
        # Trend charts (waveform, McClellan, A/D line) all draw the same
        # TREND_WINDOW_SESSIONS lookback — export exactly that window.
        "breadth": table(
            con,
            f"SELECT {', '.join(BREADTH_COLS)} FROM daily_market_breadth "
            "ORDER BY date DESC LIMIT ?",
            BREADTH_COLS, (TREND_WINDOW_SESSIONS,)),
        "cm_breadth": table(
            con,
            f"SELECT {', '.join(CM_COLS)} FROM daily_cm_breadth "
            "ORDER BY date DESC LIMIT ?",
            CM_COLS, (TREND_WINDOW_SESSIONS,)),
        # NIFTY close over the trend window — overlaid (indexed) on the A/D line
        # so breadth/price divergence is visible.
        "nifty": table(
            con,
            "SELECT date, spot_close FROM daily_market_structure "
            "WHERE symbol = 'NIFTY' ORDER BY date DESC LIMIT ?",
            ["date", "spot_close"], (TREND_WINDOW_SESSIONS,)),
    }
    # trend rows come back newest-first; charts want chronological order
    data["breadth"]["rows"].reverse()
    data["cm_breadth"]["rows"].reverse()
    data["nifty"]["rows"].reverse()

    # Ticker → Dhan display-symbol map for chart deep links (tv.dhan.co resolves
    # its own symbology, not NSE tickers). Regenerate via scripts/build_dhan_map.py.
    dhan_map_path = ROOT / "data" / "compiled" / "dhan_symbol_map.json"
    dhan_map = {}
    if dhan_map_path.exists():
        full_map = json.loads(dhan_map_path.read_text())
        yi = MS_COLS.index("symbol")
        exported_syms = {r[yi] for r in data["market_structure"]["rows"]}
        dhan_map = {s: full_map[s] for s in exported_syms if s in full_map}
    data["dhan_map"] = dhan_map

    add_flip_repeat(con, data["market_structure"], sessions)
    remap_sector(data["market_structure"])
    remap_sector(data["setups"])

    # alerts msg field carries <b> markup from the compiler; the HUD renders
    # plain text, so strip tags here rather than trusting innerHTML downstream
    mi = CHANGE_COLS.index("msg")
    for r in data["changes"]["rows"]:
        r[mi] = TAG_RE.sub("", r[mi] or "")

    template = (ROOT / "hud" / "template.html").read_text()
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    html = template.replace("__VANGUARD_DATA__", payload)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    print(f"sessions {sessions[0]} → {sessions[-1]} ({len(sessions)}) | "
          f"ms {len(data['market_structure']['rows'])} rows | "
          f"setups {len(data['setups']['rows'])} | signals {len(data['changes']['rows'])}")
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
