#!/usr/bin/env python3
"""
briefing.py — Vanguard Quant Desk: Tomorrow's Watchlist Service

Usage:
    python3 briefing.py              # most recent compiled session
    python3 briefing.py 2026-06-25  # specific date
    python3 briefing.py --quiet     # suppress stdout, write file only

Output:
    • Formatted report printed to stdout
    • data/reports/YYYYMMDD_watchlist.md  (always written)
"""
from __future__ import annotations

import os
import re
import sys
import textwrap
from datetime import datetime, timezone, timedelta
from pathlib import Path


def _strip_html(text: str) -> str:
    """Remove HTML tags from alert messages stored in the database."""
    return re.sub(r"<[^>]+>", "", str(text))

import duckdb

# ── Path setup ───────────────────────────────────────────────────────────────
ROOT     = Path(__file__).parent
DB_PATH  = ROOT / "data" / "compiled" / "vanguard.duckdb"
RPT_DIR  = ROOT / "data" / "reports"

sys.path.insert(0, str(ROOT))
from vanguard.services.briefing_service import (
    get_regime_context,
    get_top_setups,
    get_sector_pulse,
    get_key_levels,
    get_ifs_leaders,
    get_structural_alerts,
)
from vanguard.services.catalyst_service import run_catalyst_scan, load_catalysts

CATALYST_PATH = ROOT / "data" / "compiled" / "daily_catalysts.json"

# ─────────────────────────────────────────────────────────────────────────────
# Formatting helpers
# ─────────────────────────────────────────────────────────────────────────────

WIDTH = 72

def _hr(char="─"):
    return char * WIDTH

def _header(title: str) -> str:
    pad = WIDTH - 2
    top    = "╔" + "═" * pad + "╗"
    middle = "║" + title.center(pad) + "║"
    bottom = "╚" + "═" * pad + "╝"
    return "\n".join([top, middle, bottom])

def _section(title: str) -> str:
    return f"\n{_hr()}\n  {title}\n{_hr('─')}"

def _fmt_num(v, decimals=2, prefix="", suffix=""):
    if v is None or (isinstance(v, float) and v != v):
        return "N/A"
    try:
        return f"{prefix}{v:,.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return str(v)

def _pct(v):
    return _fmt_num(v, 1, suffix="%")

def _crore(v):
    if v is None:
        return "N/A"
    try:
        return f"₹{v/1e7:,.1f}Cr"
    except Exception:
        return "N/A"

def _bias_arrow(bias: str) -> str:
    return {"LONG": "▲ LONG", "SHORT": "▼ SHORT", "BULLISH": "▲ BULL",
            "BEARISH": "▼ BEAR"}.get(str(bias).upper(), "◆ " + str(bias))

def _gamma_tag(regime: str) -> str:
    r = str(regime).upper()
    if "LONG" in r:
        return "[LONG γ]"
    if "SHORT" in r:
        return "[SHORT γ]"
    return "[NEUTRAL γ]"

def _col(val, width, align="<"):
    s = str(val) if val is not None else "—"
    if align == ">":
        return s[:width].rjust(width)
    return s[:width].ljust(width)


# ─────────────────────────────────────────────────────────────────────────────
# Report builder
# ─────────────────────────────────────────────────────────────────────────────

def build_report(date: str) -> str:
    """
    Queries DuckDB and assembles the full briefing report as a string.
    """
    if not DB_PATH.exists():
        return f"[ERROR] Database not found at {DB_PATH}"

    conn = duckdb.connect(str(DB_PATH), read_only=True)
    lines: list[str] = []

    try:
        # ── Header ────────────────────────────────────────────────────────────
        ts_ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
        run_at = ts_ist.strftime("%d-%b-%Y %H:%M IST")
        lines.append(_header(
            f"VANGUARD QUANT DESK  ·  TOMORROW'S WATCHLIST  ·  {date}"
        ))
        lines.append(f"  Generated : {run_at}")

        # ─────────────────────────────────────────────────────────────────────
        # STEP 1 — Market Regime
        # ─────────────────────────────────────────────────────────────────────
        lines.append(_section("STEP 1 — MARKET REGIME CONTEXT"))
        ctx = get_regime_context(conn, date)
        bias   = ctx.get("bias", "NEUTRAL")
        sizing = ctx.get("sizing", "REDUCED")

        lines.append(f"\n  Regime   : {ctx.get('regime_label','N/A')}")
        lines.append(f"  Direction: {_bias_arrow(bias)}  │  Position Sizing: {sizing}")

        # Cash breadth table
        lines.append("\n  ── Cash Market Breadth (NSE EQ Universe) ──")
        total = ctx.get("cm_total_symbols", 0)
        adv   = ctx.get("cm_advances", 0)
        dec   = ctx.get("cm_declines", 0)
        unch  = ctx.get("cm_unchanged", 0)
        lines.append(f"  Universe    : {total:,} symbols")
        lines.append(
            f"  Adv/Dec/Unch: {adv:,} / {dec:,} / {unch:,}  "
            f"({_pct(ctx.get('cm_advance_pct'))} adv)"
        )
        lines.append(
            f"  A/D Ratio   : {_fmt_num(ctx.get('cm_ad_ratio'))}  │  "
            f"Vol A/D: {_fmt_num(ctx.get('cm_volume_ad_ratio'))}"
        )
        lines.append(
            f"  DMA %       : 20d={_pct(ctx.get('cm_pct_above_20dma'))}  "
            f"50d={_pct(ctx.get('cm_pct_above_50dma'))}  "
            f"200d={_pct(ctx.get('cm_pct_above_200dma'))}"
        )
        lines.append(
            f"  RSI Breadth : OB(>70)={_pct(ctx.get('cm_pct_overbought_70'))}  "
            f"OS(<30)={_pct(ctx.get('cm_pct_oversold_30'))}"
        )
        nh = ctx.get("cm_new_highs", 0)
        nl = ctx.get("cm_new_lows", 0)
        nh_nl = ctx.get("cm_nh_nl_ratio", 0.0)
        lines.append(
            f"  NH/NL       : {int(nh) if nh else 0} highs / "
            f"{int(nl) if nl else 0} lows  (ratio {_fmt_num(nh_nl)})"
        )
        lines.append(
            f"  McClellan   : {_fmt_num(ctx.get('cm_mcclellan_osc'))}  │  "
            f"Cum A/D Line: {_fmt_num(ctx.get('cm_ad_line'))}"
        )
        lines.append(
            f"  Turnover    : Top-20 stocks = "
            f"{_pct(ctx.get('cm_turnover_top20_pct'))} of total volume"
        )

        # F&O breadth
        fo = ctx.get("fo_breadth", {})
        if fo:
            lines.append("\n  ── F&O Universe Regime Distribution ──")
            lines.append(
                f"  Bullish={_pct(fo.get('bullish_pct'))}  "
                f"Bearish={_pct(fo.get('bearish_pct'))}  "
                f"Compress={_pct(fo.get('compression_pct'))}  "
                f"Expand={_pct(fo.get('expansion_pct'))}"
            )

        # Index gamma levels
        idx = ctx.get("index_levels", {})
        for sym in ["NIFTY", "BANKNIFTY"]:
            if sym in idx:
                r = idx[sym]
                lines.append(f"\n  ── {sym} ──")
                lines.append(
                    f"  Spot={_fmt_num(r.get('spot_close'),0,'₹')}  "
                    f"Call Wall={_fmt_num(r.get('call_wall'),0,'₹')}  "
                    f"Put Wall={_fmt_num(r.get('put_wall'),0,'₹')}  "
                    f"γ-Flip={_fmt_num(r.get('gamma_flip'),0,'₹')}"
                )
                lines.append(
                    f"  Gamma Regime: {_gamma_tag(r.get('gamma_regime',''))}  │  "
                    f"Fut OI Chg: {_fmt_num(r.get('futures_oi_chg'),0)}"
                )

        # ─────────────────────────────────────────────────────────────────────
        # STEP 2 — Top Setups
        # ─────────────────────────────────────────────────────────────────────
        lines.append(_section("STEP 2 — TOP SETUPS  (F&O Universe)"))
        setups = get_top_setups(conn, date, n=15, bias=bias)
        if setups:
            hdr = (
                f"  {'SYMBOL':<12} {'SETUP':<22} {'BIAS':<8} "
                f"{'IFS':>5}  {'SPOT':>9}  {'TRIGGER':>9}  "
                f"{'INVAL':>9}  {'γ REGIME':<14}"
            )
            lines.append(hdr)
            lines.append("  " + "─" * (WIDTH - 4))
            for s in setups:
                lines.append(
                    f"  {_col(s.get('symbol'),12)}"
                    f"{_col(s.get('setup_type'),22)}"
                    f"{_col(s.get('bias'),8)}"
                    f"{_col(_fmt_num(s.get('ifs_score'),1),5,'>')}  "
                    f"{_col(_fmt_num(s.get('spot_close'),0),9,'>')}  "
                    f"{_col(_fmt_num(s.get('trigger_strike'),0),9,'>')}  "
                    f"{_col(_fmt_num(s.get('invalidation_strike'),0),9,'>')}  "
                    f"{_col(_gamma_tag(s.get('gamma_regime','')),14)}"
                )
            lines.append("")
            lines.append(
                f"  * Confirm with live price action at tomorrow's open before acting."
            )
        else:
            lines.append("  No setups registered for this date.")

        # ─────────────────────────────────────────────────────────────────────
        # STEP 3 — Sector Pulse
        # ─────────────────────────────────────────────────────────────────────
        lines.append(_section("STEP 3 — SECTOR PULSE"))
        sectors = get_sector_pulse(conn, date)
        if sectors:
            hdr = (
                f"  {'SECTOR':<22} {'#':>4}  {'AVG IFS':>8}  "
                f"{'NET INV SHIFT':>14}  {'AVG CHG%':>9}"
            )
            lines.append(hdr)
            lines.append("  " + "─" * (WIDTH - 4))
            for s in sectors:
                tag = "▲" if (s.get("avg_ifs") or 0) > 5 else ("▼" if (s.get("avg_ifs") or 0) < -5 else "◆")
                lines.append(
                    f"  {tag} {_col(s.get('sector'),20)}"
                    f"{_col(s.get('symbols'),4,'>')}  "
                    f"{_col(_fmt_num(s.get('avg_ifs')),8,'>')}  "
                    f"{_col(_fmt_num(s.get('total_net_inv'),0),14,'>')}  "
                    f"{_col(_pct(s.get('avg_chg_pct')),9,'>')}"
                )
        else:
            lines.append("  No sector data for this date.")

        # ─────────────────────────────────────────────────────────────────────
        # STEP 4 — Key Levels
        # ─────────────────────────────────────────────────────────────────────
        lines.append(_section("STEP 4 — KEY LEVELS  (NIFTY / BANKNIFTY)"))
        levels = get_key_levels(conn, date)
        for sym in ["NIFTY", "BANKNIFTY"]:
            if sym in levels:
                r = levels[sym]
                lines.append(f"\n  {sym}")
                lines.append(
                    f"    Spot Close  : {_fmt_num(r.get('spot_close'),2,'₹')}"
                )
                lines.append(
                    f"    Call Wall   : {_fmt_num(r.get('call_wall'),0,'₹')}  "
                    f"(supply / resistance)"
                )
                lines.append(
                    f"    Put Wall    : {_fmt_num(r.get('put_wall'),0,'₹')}  "
                    f"(support / dealer-defended)"
                )
                lines.append(
                    f"    Gamma Flip  : {_fmt_num(r.get('gamma_flip'),0,'₹')}  "
                    f"(volatility regime pivot)"
                )
                lines.append(
                    f"    Gamma Regime: {_gamma_tag(r.get('gamma_regime',''))}  "
                    f"({r.get('gamma_regime','')})"
                )
                lines.append(
                    f"    Strategy    : {r.get('suggested_strategy','—')}"
                )
                lines.append(
                    f"    Struct Bias : {r.get('structural_bias','—')}"
                )
                lines.append(
                    f"    Fut OI Δ    : {_fmt_num(r.get('futures_oi_chg'),0)}  │  "
                    f"GEX: {_fmt_num(r.get('gex'),0)}"
                )

        if not levels:
            lines.append("  Index level data not available for this date.")

        # ─────────────────────────────────────────────────────────────────────
        # STEP 5 — IFS Leaders / Laggards
        # ─────────────────────────────────────────────────────────────────────
        lines.append(_section("STEP 5 — IFS LEADERS & LAGGARDS"))
        ifs = get_ifs_leaders(conn, date, n=5)
        if ifs["leaders"] or ifs["laggards"]:
            hdr = (
                f"  {'SYMBOL':<12} {'SECTOR':<18} {'IFS':>6}  "
                f"{'SPOT':>9}  {'CHG%':>7}  BIAS"
            )
            lines.append("\n  ─── LEADERS (Bullish IFS) ───")
            lines.append(hdr)
            for r in ifs["leaders"]:
                lines.append(
                    f"  ▲ {_col(r.get('symbol'),10)}"
                    f"{_col(r.get('sector'),18)}"
                    f"{_col(_fmt_num(r.get('ifs_score'),1),6,'>')}  "
                    f"{_col(_fmt_num(r.get('spot_close'),0),9,'>')}  "
                    f"{_col(_pct(r.get('spot_change_pct')),7,'>')}  "
                    f"{r.get('structural_bias','—')}"
                )
            lines.append("\n  ─── LAGGARDS (Bearish IFS) ───")
            lines.append(hdr)
            for r in ifs["laggards"]:
                lines.append(
                    f"  ▼ {_col(r.get('symbol'),10)}"
                    f"{_col(r.get('sector'),18)}"
                    f"{_col(_fmt_num(r.get('ifs_score'),1),6,'>')}  "
                    f"{_col(_fmt_num(r.get('spot_close'),0),9,'>')}  "
                    f"{_col(_pct(r.get('spot_change_pct')),7,'>')}  "
                    f"{r.get('structural_bias','—')}"
                )
        else:
            lines.append("  IFS data not available for this date.")

        # ─────────────────────────────────────────────────────────────────────
        # STEP 6 — Structural Alerts
        # ─────────────────────────────────────────────────────────────────────
        alerts = get_structural_alerts(conn, date, top_n=20)
        if alerts:
            lines.append(_section("STEP 6 — STRUCTURAL ALERTS"))
            for a in alerts:
                icon = a.get("icon", "◆")
                lines.append(f"  {icon}  [{a.get('type','—')}]  {a.get('symbol','—')}  —  {_strip_html(a.get('msg',''))}")

        # ─────────────────────────────────────────────────────────────────────
        # STEP 7 — CATALYST SCAN  (news → F&O impact)
        # ─────────────────────────────────────────────────────────────────────
        # Load pre-computed catalysts if JSON exists (written in main)
        _catalyst_data = load_catalysts(str(CATALYST_PATH))
        _catalysts = _catalyst_data.get("catalysts", [])

        if _catalysts:
            _mode_tag = _catalyst_data.get("mode", "RULES")
            lines.append(_section(f"STEP 7 — CATALYST SCAN  [{_mode_tag} MODE]"))
            lines.append(f"  Generated: {_catalyst_data.get('generated','—')}  |  "
                         f"{len(_catalysts)} catalyst(s) found")
            for ci, cat in enumerate(_catalysts, 1):
                impact = cat.get("impact", "NEUTRAL")
                conf   = cat.get("confidence", 0.0)
                syms   = ", ".join(cat.get("affected_symbols", [])[:6]) or "—"
                secs   = ", ".join(cat.get("affected_sectors", [])[:3]) or "—"
                impact_arrow = {"BULLISH": "▲", "BEARISH": "▼",
                                "MIXED": "◆", "NEUTRAL": "○"}.get(impact, "◆")
                lines.append(f"")
                lines.append(f"  CATALYST #{ci}  {impact_arrow} {impact}  (confidence: {conf:.0%})")
                lines.append(f"  Headline  : {cat.get('headline','')}")
                lines.append(f"  Source    : {cat.get('source','—')}  |  {cat.get('published','—')}")
                lines.append(f"  Affected  : {syms}")
                if secs != "—":
                    lines.append(f"  Sector(s) : {secs}")
                lines.append(f"  Reason    : {cat.get('reason','')}")
                lines.append(f"  Suggestion: {cat.get('suggestion','')}")
        else:
            lines.append(_section("STEP 7 — CATALYST SCAN"))
            lines.append("  No catalysts loaded. Run briefing.py after EOD compile to populate.")
            lines.append("  To enable AI mode: set GEMINI_API_KEY and CATALYST_AI_MODE=true in .env")

        # ─────────────────────────────────────────────────────────────────────
        # Risk Controls Footer
        # ─────────────────────────────────────────────────────────────────────
        lines.append(_section("RISK CONTROLS"))
        sizing_map = {
            "FULL":    "Standard lot sizing. Full allocation allowed.",
            "HALF":    "Half-lot sizing only. Wait for open confirmation.",
            "REDUCED": "Minimal sizing. No new initiations; manage existing book.",
        }
        lines.append(f"\n  Position Sizing  : {sizing}  —  {sizing_map.get(sizing,'')}")
        lines.append(  "  Stop Loss Rule   : Hard stop at invalidation_strike for ALL setups.")
        lines.append(  "  Confirmation Rule: Do NOT act on any name without live open confirmation.")
        lines.append(  "  Index Hedge      : If gamma regime is SHORT γ, maintain index put hedge.")
        lines.append(f"\n{_hr('═')}")
        lines.append(
            "  DISCLAIMER: This briefing is generated from compiled EOD data.\n"
            "  All setups are directional hypotheses, not trade recommendations.\n"
            "  Always confirm with live price action at the open."
        )
        lines.append(_hr("═"))

    finally:
        conn.close()

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Resolve latest compiled date
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_date(arg: str | None) -> str:
    """
    If arg is provided and matches YYYY-MM-DD, return it.
    Otherwise query DuckDB for the most recent date in daily_market_structure —
    the F&O calendar drives every setups/levels/alerts section; the cash-market
    table can run ahead of it when an FO bhav download fails, which would
    resolve to a date with zero setups.
    Falls back to today IST if DB is not available.
    """
    if arg and len(arg) == 10 and arg[4] == "-":
        return arg

    if DB_PATH.exists():
        try:
            conn = duckdb.connect(str(DB_PATH), read_only=True)
            tables = conn.execute("SHOW TABLES").df()["name"].tolist()
            for src_table in ("daily_market_structure", "daily_cm_breadth"):
                if src_table in tables:
                    row = conn.execute(
                        f"SELECT MAX(CAST(date AS VARCHAR)) AS d FROM {src_table}"
                    ).df()
                    val = row.iloc[0]["d"]
                    if val:
                        conn.close()
                        return str(val)[:10]
            conn.close()
        except Exception:
            pass

    # Fallback: today IST
    ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    return ist.strftime("%Y-%m-%d")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    args   = [a for a in sys.argv[1:] if not a.startswith("--")]
    quiet  = "--quiet" in sys.argv
    skip_catalyst = "--no-catalyst" in sys.argv

    date_arg = args[0] if args else None
    date     = _resolve_date(date_arg)

    # ── Step A: Run catalyst scan (before building report so STEP 7 has data) ─
    if not skip_catalyst and DB_PATH.exists():
        try:
            # Pull F&O symbol universe from DB
            _conn = duckdb.connect(str(DB_PATH), read_only=True)
            _sym_df = _conn.execute(
                "SELECT DISTINCT symbol FROM daily_market_structure WHERE date = ?",
                [date]
            ).df()
            _conn.close()
            fno_symbols = set(_sym_df["symbol"].tolist())
            run_catalyst_scan(
                fno_symbols=fno_symbols,
                date=date,
                output_path=str(CATALYST_PATH),
                quiet=quiet,
            )
        except Exception as e:
            if not quiet:
                print(f"[CATALYST] Scan error (non-fatal): {e}")

    # ── Step B: Build report (STEP 7 reads the JSON just written above) ────────
    report = build_report(date)

    # Print to stdout unless --quiet
    if not quiet:
        print(report)

    # Always write file
    RPT_DIR.mkdir(parents=True, exist_ok=True)
    fname  = date.replace("-", "") + "_watchlist.md"
    fpath  = RPT_DIR / fname
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(f"# Tomorrow's Watchlist — {date}\n\n")
        f.write("```\n")
        f.write(report)
        f.write("\n```\n")

    if not quiet:
        print(f"\n  ✅ Report saved → {fpath}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
