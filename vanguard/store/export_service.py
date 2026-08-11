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

from vanguard.config.paths import DB, PROCESSED, COMPILED
from vanguard.config.sectors import get_sector
from vanguard.config.eod import TREND_WINDOW_SESSIONS
from vanguard.research.position_stats import summarize_by_group
from vanguard.engines.rrg import build_rrg, build_stock_rrg

MS_COLS = [
    "date", "symbol", "sector", "spot_close", "spot_change_pct", "pcr", "iv", "iv_shift",
    "gex_intensity", "gex_shift", "gamma_regime", "structural_bias",
    "conviction_score", "priority_score", "ifs_score", "smart_money_persistence",
    "futures_oi", "futures_oi_chg", "net_inv_shift", "delta_volume", "delta_ce_oi", "delta_pe_oi",
    "call_wall", "put_wall", "gamma_flip", "ce_interp", "pe_interp", "suggested_strategy",
    "structure_flip", "prev_structural_bias", "flip_confidence", "flip_strength",
]
# Joined from daily_equity_technicals (index symbols like NIFTY/BANKNIFTY have
# no equity technicals, so these come back NULL for them — the Scanner shows
# "—" in that case rather than treating it as an error).
MS_52W_COLS = ["pct_from_52w_high", "pct_from_52w_low"]
# Cash-market traded volume + its 20d relative ratio, also from
# daily_equity_technicals (same LEFT JOIN as the 52W cols). Pairs with the
# Scanner's DLV% column — both are cash-market reads, so the volume shown is
# cash traded qty (matches daily_delivery.traded_qty), NOT F&O total_volume.
MS_VOL_COLS = ["volume", "volume_ratio_20d"]

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

    # 52w/volume enrichment rides on daily_equity_technicals via a LEFT JOIN.
    # On a pre-C1 DB that table is absent (PRD degradation contract) — keep the
    # columns as NULL so the payload shape stays stable, just drop the join.
    et_cols = MS_52W_COLS + MS_VOL_COLS
    have_et = "daily_equity_technicals" in {
        r[0] for r in con.execute("SHOW TABLES").fetchall()}
    if have_et:
        et_select = ", ".join(f"et.{c}" for c in et_cols)
        et_join = ("LEFT JOIN daily_equity_technicals et "
                   "  ON et.symbol = ms.symbol AND CAST(et.date AS DATE) = CAST(ms.date AS DATE) ")
    else:
        et_select = ", ".join(f"NULL AS {c}" for c in et_cols)
        et_join = ""

    data = {
        "meta": {"session": sessions[-1], "sessions": sessions},
        "market_structure": table(
            con,
            f"SELECT {', '.join(f'ms.{c}' for c in MS_COLS)}, {et_select} "
            f"FROM daily_market_structure ms {et_join}"
            f"WHERE ms.date IN ({ph}) ORDER BY ms.date, ms.priority_score DESC NULLS LAST, ms.symbol",
            MS_COLS + et_cols, sessions),
        "setups": table(
            con,
            f"SELECT c.date, c.symbol, COALESCE(m.sector, 'Equity') as sector, "
            f"COALESCE(c.fno_setup, c.equity_setup) as setup_type, '' as setup_types, "
            f"c.bias, c.trigger_strike, c.invalidation_strike, c.expected_behavior, '' as dealer_behavior "
            f"FROM daily_confluence_setups c "
            f"LEFT JOIN daily_market_structure m ON c.symbol = m.symbol AND c.date = m.date "
            f"WHERE c.date IN ({ph}) AND (c.fno_setup != 'NONE' OR c.equity_setup != 'NONE')",
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

    # Symbols actually included in this export — used below to filter the
    # option chain snapshot down to just what the payload ships.
    yi = MS_COLS.index("symbol")
    exported_syms = {r[yi] for r in data["market_structure"]["rows"]}

    # Per-symbol option chain (strike/OI/IV/GEX) for the Dossier's Deep Dive
    # Charts (GEX Profile / OI Concentration / IV Skew). Previously an
    # unconditional fetch('http://127.0.0.1:8787/api/chain/<symbol>') with no
    # offline fallback, so these charts only rendered when scripts/
    # run_bridge.py or run_live.py happened to be running -- even though the
    # data isn't inherently live (unlike /snapshot's LTP overlay, which
    # genuinely needs a running feed). Baked here from the latest EOD
    # compile's snapshot (data/processed/greeks.csv, written by
    # analyze_market_structure) instead, same as everything else in this
    # payload. Always reflects the LATEST compiled session regardless of
    # which SDATE the HUD has time-traveled to -- matches the old
    # live-fetch's behavior exactly, since that never varied by selected
    # date either (a chain snapshot isn't kept per historical session).
    chain_path = PROCESSED / "greeks.csv"
    chain_cols = ["symbol", "strike_pr", "option_typ", "open_int", "iv", "gex"]
    if chain_path.exists():
        gdf = pd.read_csv(chain_path, usecols=["SYMBOL", "STRIKE_PR", "OPTION_TYP", "OPEN_INT", "IV", "GAMMA"])
        gdf = gdf[gdf["SYMBOL"].isin(exported_syms)].copy()
        spot_by_symbol = dict(con.execute(
            "SELECT symbol, spot_close FROM daily_market_structure WHERE date = ?",
            (sessions[-1],)).fetchall())
        spot = gdf["SYMBOL"].map(spot_by_symbol).fillna(0.0)
        mult = gdf["OPTION_TYP"].map({"CE": 1.0, "PE": -1.0}).fillna(1.0)
        gdf["GEX"] = gdf["GAMMA"] * gdf["OPEN_INT"] * spot * 0.01 * mult
        rows = gdf[["SYMBOL", "STRIKE_PR", "OPTION_TYP", "OPEN_INT", "IV", "GEX"]].values.tolist()
        data["chains"] = {"cols": chain_cols, "rows": [[clean(c) for c in r] for r in rows]}
    else:
        data["chains"] = {"cols": chain_cols, "rows": []}

    # Scanner universe (Nifty50 constituents + indices) — the HUD's Symbol
    # Scanner narrows to this list. Regime Core/Breadth/Internals/Positioning/
    # Sectors stay full-215-universe market-wide context — deliberately NOT
    # filtered by this list. Optional like fyers_map above: a fetch failure
    # degrades to the HUD falling back to the full universe rather than
    # blocking the whole EOD/HUD build.
    try:
        from vanguard.pipeline.context.nifty50_universe import (
            get_nifty50_constituents, INDEX_SYMBOLS)
        data["scanner_universe"] = sorted(set(get_nifty50_constituents()) | set(INDEX_SYMBOLS))
    except Exception:
        data["scanner_universe"] = []

    add_flip_repeat(con, data["market_structure"], sessions)
    remap_sector(data["market_structure"])
    remap_sector(data["setups"])

    # alerts msg field carries <b> markup from the compiler; the HUD renders
    # plain text, so strip tags here rather than trusting innerHTML downstream
    mi = CHANGE_COLS.index("msg")
    for r in data["changes"]["rows"]:
        r[mi] = TAG_RE.sub("", r[mi] or "")

    _context_blocks(con, data, sessions, ph)

    # AI-interpreted EOD summary (Desk Read) was removed 2026-08-11 — NVIDIA's
    # free-tier Nemotron endpoint proved unreliable with no usable fallback.
    # data["ai_summary"] is intentionally never set; hud/template.html's
    # drawAiSummary() already no-ops and keeps #p-ai-summary hidden when the
    # key is absent.

    # News catalysts (vanguard/services/catalyst_service.py), read from the
    # per-date DuckDB archive rather than the single overwritten JSON so
    # older sessions keep the catalysts that were actually scanned for them.
    try:
        from vanguard.services.catalyst_service import load_catalysts_for_date
        cat = load_catalysts_for_date(con, data["meta"]["session"])
        if cat.get("catalysts"):
            data["catalysts"] = cat
    except Exception:
        pass

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
        # RRG (sector rotation) uses full daily_index_close history, not the
        # sessions/TREND_WINDOW_SESSIONS caps above — RS-Ratio needs long
        # context, so build_rrg() queries the table itself rather than being
        # handed a pre-filtered slice.
        rrg = build_rrg(con)
        if rrg is not None:
            data["rrg"] = rrg
            # Stock-level drill-down (F&O stocks per sector, vs NIFTY + vs
            # their sector index). Attached under the sector RRG so the HUD
            # can drill from a sector into its constituents; omitted if the
            # equity/index tables are absent (HUD hides the drill-down).
            stocks = build_stock_rrg(con)
            if stocks is not None:
                data["rrg"]["stocks"] = stocks
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
