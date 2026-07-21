"""
Export service (wave 3 / P1) — the ONE payload builder for the HUD.

Both consumers use this module, so baked and served output cannot drift:
  - scripts/build_hud.py bakes build_payload() into hud/vanguard_hud.html
  - vanguard/serve/api.py serves it live at /session/latest

Extracted verbatim from scripts/build_hud.py; every new dataset (NSE context
layer etc.) is added HERE exactly once.
"""
from __future__ import annotations

import json
import math
import re

import duckdb
import pandas as pd

from vanguard.config.paths import DB, COMPILED
from vanguard.config.sectors import get_sector
from vanguard.config.eod import TREND_WINDOW_SESSIONS
from vanguard.research.position_stats import summarize_by_group

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
POSITION_COLS = ["symbol", "sector", "setup_type", "bias", "direction",
                  "trigger_date", "trigger_price", "sl_price", "target_price",
                  "status", "resolved_date", "resolved_price"]
TRACK_RECORD_COLS = ["track", "setup_type", "n", "win_rate", "avg_r", "total_r"]
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
    # cols is COPIED: add_flip_repeat appends to tbl["cols"], and aliasing the
    # module-level *_COLS list corrupts every later build_payload() call in the
    # same process (the served/cache path — caught by test_served_equals_built).
    rows = con.execute(sql, params).fetchall()
    return {"cols": list(cols), "rows": [[clean(c) for c in r] for r in rows]}


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


def _track_record_block(con, tables) -> dict | None:
    """Win rate / avg R / total R per setup type, both tracks tagged and
    concatenated into one block (not two separate ones) so the client can
    group/toggle without a second fetch. Reuses vanguard.research.
    position_stats.summarize_by_group() — the same function equity_setups_
    backtest.py's E4 gate already uses — rather than recomputing this math a
    third time (PRD §6.4: "one function, two callers, no drift").

    Resolved positions only (summarize_by_group drops OPEN rows itself,
    R is undefined until a position resolves). Returns None if neither
    track's position table exists/has resolved rows yet, matching this
    module's "absent table = absent key" degradation contract."""
    frames = []
    for track, tbl_name in (("fno", "daily_setup_positions"),
                            ("equity", "daily_equity_setup_positions")):
        if tbl_name not in tables:
            continue
        df = con.execute(f"SELECT * FROM {tbl_name}").fetchdf()
        if df.empty:
            continue
        g = summarize_by_group(df)
        if g.empty:
            continue
        g = g.reset_index()
        g.insert(0, "track", track)
        frames.append(g)
    if not frames:
        return None
    combined = pd.concat(frames, ignore_index=True)
    return {
        "cols": list(TRACK_RECORD_COLS),
        "rows": [[clean(row[c]) for c in TRACK_RECORD_COLS]
                for _, row in combined.iterrows()],
    }


def remap_sector(tbl):
    """Apply current sector mapping at export time so mapping fixes show
    without waiting for a full recompile (DB bakes sector at compile time)."""
    si, yi = tbl["cols"].index("sector"), tbl["cols"].index("symbol")
    for r in tbl["rows"]:
        mapped = get_sector(r[yi])
        if mapped != "Other":
            r[si] = mapped


def build_payload(db_path=None, sessions: int = 30) -> dict:
    """The complete HUD data payload for the last `sessions` compiled sessions."""
    con = duckdb.connect(str(db_path or DB), read_only=True)
    try:
        return _build(con, sessions)
    finally:
        con.close()


def _build(con, n_sessions: int) -> dict:
    sessions = [r[0] for r in con.execute(
        "SELECT DISTINCT date FROM daily_market_structure ORDER BY date DESC LIMIT ?",
        (n_sessions,)).fetchall()]
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
    dhan_map_path = COMPILED / "dhan_symbol_map.json"
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

    _context_blocks(con, data, sessions, ph)
    return data


# ── NSE context layer (C2) — every block optional: absent table = absent key,
#    and the HUD hides the panel (PRD degradation contract) ──────────────────

def _ban_signal_rows(data, sessions):
    """Synthesize ban_enter/ban_exit Signal Feed rows by diffing consecutive
    sessions inside the export window (PRD 2.2) — no compiler change needed."""
    by_date = {}
    for d, sym in data["ban"]["rows"]:
        by_date.setdefault(d, set()).add(sym)
    ch = data["changes"]
    ci = {c: i for i, c in enumerate(ch["cols"])}
    for prev, cur in zip(sessions[:-1], sessions[1:]):
        p, c = by_date.get(clean(prev), set()), by_date.get(clean(cur), set())
        for sym in sorted(c - p):
            row = [None] * len(ch["cols"])
            row[ci["date"]], row[ci["symbol"]] = clean(cur), sym
            row[ci["icon"]], row[ci["type"]] = "⛔", "ban_enter"
            row[ci["msg"]] = f"{sym}: entered F&O ban (MWPL >= 95%) — no new positions"
            row[ci["rank"]] = 0
            ch["rows"].append(row)
        for sym in sorted(p - c):
            row = [None] * len(ch["cols"])
            row[ci["date"]], row[ci["symbol"]] = clean(cur), sym
            row[ci["icon"]], row[ci["type"]] = "✅", "ban_exit"
            row[ci["msg"]] = f"{sym}: exited F&O ban — new positions allowed"
            row[ci["rank"]] = 0
            ch["rows"].append(row)


POS_COLS = ["date", "participant", "fut_idx_long", "fut_idx_short",
            "fut_stk_long", "fut_stk_short",
            "opt_idx_call_long", "opt_idx_call_short",
            "opt_idx_put_long", "opt_idx_put_short"]
VIX_COLS = ["date", "close", "chg_pct"]
DLV_COLS = ["date", "symbol", "delivery_pct", "ratio_20d"]


def _context_blocks(con, data, sessions, ph):
    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    if "daily_participant_oi" in tables:
        data["positioning"] = table(
            con,
            f"SELECT {', '.join(POS_COLS)} FROM daily_participant_oi "
            "WHERE date IN (SELECT DISTINCT date FROM daily_participant_oi "
            "               ORDER BY date DESC LIMIT ?) "
            "ORDER BY date, participant",
            POS_COLS, (TREND_WINDOW_SESSIONS,))
    if "daily_index_close" in tables:
        # 252 sessions so the HUD can place today's VIX on a 1-year percentile
        vix = table(
            con,
            f"SELECT {', '.join(VIX_COLS)} FROM daily_index_close "
            "WHERE upper(index_name) = 'INDIA VIX' ORDER BY date DESC LIMIT 252",
            VIX_COLS)
        vix["rows"].reverse()
        data["vix"] = vix
    if "daily_ban" in tables:
        data["ban"] = table(
            con,
            f"SELECT date, symbol FROM daily_ban WHERE date IN ({ph}) "
            "ORDER BY date, symbol", ["date", "symbol"], sessions)
        _ban_signal_rows(data, sessions)
    if "daily_setup_positions" in tables:
        # Currently-open positions regardless of how old trigger_date is
        # (a position can stay open indefinitely), plus resolved positions
        # whose resolved_date falls inside the exported session window — so
        # HUD time-travel to an earlier date in that window still shows them
        # as open, matching the point-in-time semantics drawSetups() applies
        # client-side. Positions that both triggered and resolved entirely
        # before the window are irrelevant to any date the HUD can display.
        data["setup_positions"] = table(
            con,
            "SELECT symbol, sector, setup_type, bias, direction, trigger_date, "
            "trigger_price, sl_price, target_price, status, resolved_date, "
            "resolved_price FROM daily_setup_positions "
            "WHERE status = 'OPEN' OR resolved_date >= ? ORDER BY trigger_date",
            POSITION_COLS, (sessions[0],))
    if "daily_equity_setup_positions" in tables:
        # Track B (equity) — identical point-in-time semantics and column
        # shape to setup_positions above (daily_equity_setup_positions was
        # built to match daily_setup_positions's shape exactly, PRD §5), a
        # separate block rather than a shared one with an asset_class flag
        # so Track A and Track B stats can never accidentally blend on the
        # client either (same reasoning as keeping their DB tables separate).
        data["equity_setup_positions"] = table(
            con,
            "SELECT symbol, sector, setup_type, bias, direction, trigger_date, "
            "trigger_price, sl_price, target_price, status, resolved_date, "
            "resolved_price FROM daily_equity_setup_positions "
            "WHERE status = 'OPEN' OR resolved_date >= ? ORDER BY trigger_date",
            POSITION_COLS, (sessions[0],))
    track_record = _track_record_block(con, tables)
    if track_record is not None:
        data["track_record"] = track_record
    if "daily_fii_dii" in tables:
        fd = table(con, "SELECT date, category, buy_cr, sell_cr, net_cr "
                        "FROM daily_fii_dii ORDER BY date DESC LIMIT ?",
                   ["date", "category", "buy_cr", "sell_cr", "net_cr"],
                   (2 * TREND_WINDOW_SESSIONS,))
        fd["rows"].reverse()
        data["fii_dii"] = fd
    if "corporate_events" in tables:
        # forward-looking events for universe symbols, within +14 calendar days
        data["events"] = table(con, f"""
            SELECT symbol, event_type, event_date, details FROM corporate_events
            WHERE symbol IN (SELECT DISTINCT symbol FROM daily_market_structure)
              AND event_date >= ? AND event_date <= CAST(? AS TIMESTAMP) + INTERVAL 14 DAY
            ORDER BY event_date""",
            ["symbol", "event_type", "event_date", "details"],
            (sessions[-1], sessions[-1]))
    if "daily_delivery" in tables:
        # ratio vs the symbol's OWN trailing 20 sessions (level is structural;
        # the ratio is the signal) — window excludes the current day
        data["delivery"] = table(
            con,
            f"""SELECT date, symbol, delivery_pct,
                delivery_pct / NULLIF(AVG(delivery_pct) OVER (
                    PARTITION BY symbol ORDER BY date
                    ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING), 0) AS ratio_20d
                FROM daily_delivery
                WHERE symbol IN (SELECT DISTINCT symbol FROM daily_market_structure)
                QUALIFY date IN ({ph}) ORDER BY date, symbol""",
            DLV_COLS, sessions)


def payload_json(db_path=None, sessions: int = 30) -> str:
    """Compact JSON — the exact string both baked and served paths emit."""
    return json.dumps(build_payload(db_path, sessions),
                      separators=(",", ":"), ensure_ascii=False)
