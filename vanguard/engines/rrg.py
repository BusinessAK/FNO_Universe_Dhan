"""
RRG (Relative Rotation Graph) — JdK-style RS-Ratio / RS-Momentum per sector,
benchmarked against Nifty 50. A derived-analytics module (same role as
gamma.py/intelligence.py elsewhere in vanguard/engines/) — reads real NSE
sector index closes from daily_index_close, computes rotation coordinates,
and returns a small display-ready payload block. Called from
vanguard/store/export_service.py; never writes to the DB.

Formula: the well-known open-source two-stage rolling z-score approximation
of JdK's RRG methodology (RS = 100*sector/benchmark; RS-Ratio =
100 + zscore(RS, W); RS-Momentum = 100 + zscore(RS-Ratio.diff(1), W)) — not
a reverse-engineering of StockCharts' proprietary formula.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from vanguard.config.sectors import get_sector

# HUD sector label -> exact daily_index_close.index_name string. Hand-verified
# against the DB (not fuzzy-matched) — a few labels don't match 1:1, e.g.
# "NIFTY MEDIA & COMM" only has a plain "Nifty Media" index, and "NIFTY
# SERVICES" is named "Nifty Services Sector" in the raw feed.
INDEX_NAME_BY_SECTOR = {
    "NIFTY IT": "Nifty IT",
    "NIFTY PVT BANK": "Nifty Private Bank",
    "NIFTY PSU BANK": "Nifty PSU Bank",
    "NIFTY FIN SERVICE": "Nifty Financial Services",
    "NIFTY MEDIA & COMM": "Nifty Media",
    "NIFTY OIL & GAS": "Nifty Oil & Gas",
    "NIFTY ENERGY": "Nifty Energy",
    "NIFTY INFRA": "Nifty Infrastructure",
    "NIFTY AUTO": "Nifty Auto",
    "NIFTY PHARMA": "Nifty Pharma",
    "NIFTY FMCG": "Nifty FMCG",
    "NIFTY CONS DURABLES": "Nifty Consumer Durables",
    "NIFTY METAL": "Nifty Metal",
    "NIFTY COMMODITIES": "Nifty Commodities",
    "NIFTY REALTY": "Nifty Realty",
    "NIFTY SERVICES": "Nifty Services Sector",
}

BENCHMARK_INDEX_NAME = "Nifty 50"

# Nominal trailing tail per timeframe — used both to derive the rolling
# window and as the client's default display length. The HUD slices its own
# tail ending at the selected (time-travelled) session, so this is a guide,
# not a hard shipped length.
TAIL_LENGTH = {"1D": 6, "1W": 8, "1M": 5}
# How many *computed* points to ship per timeframe. The RS-Ratio/Momentum
# series is computed over the FULL history (so every shipped point already
# reflects a settled rolling stat), then only the last SHIP_N are shipped —
# enough that the HUD can slice a tail ending at any session in its ~30-session
# window and still show a full trail. Daily needs ~30 window + tail lookback.
SHIP_N = {"1D": 45, "1W": 20, "1M": 14}
SAFETY_MARGIN = 2   # spare valid points wanted beyond the tail
MIN_W = 3            # rolling std needs >=3 samples to be minimally meaningful
MAX_W = 10           # standard JdK-approximation default once history allows it
EPS = 1e-9
CLIP = 4.0           # cap the z-score itself, on top of the eps floor on std


def _derive_window(n_valid: int, tail: int) -> tuple[int, int, bool]:
    """Rolling window size + (possibly shrunk) tail length + thin flag.

    Tail length drives window size (with an explicit safety margin), not the
    other way around — picking both as independent fixed constants per
    timeframe is how a thin history (e.g. ~13 monthly candles) quietly ends
    up with almost no margin. If even MIN_W can't clear the requested tail,
    shrink the tail instead of padding fabricated points or crashing.
    """
    w = int(np.clip((n_valid - tail - SAFETY_MARGIN + 1) // 2, MIN_W, MAX_W))
    valid_momentum = n_valid - 2 * w + 1
    if valid_momentum >= tail:
        return w, tail, False
    w = MIN_W
    shrunk_tail = max(0, n_valid - 2 * w + 1)
    return w, min(tail, shrunk_tail), True


def _zscore(x: pd.Series, w: int) -> pd.Series:
    mean = x.rolling(w).mean()
    std = x.rolling(w).std()
    z = (x - mean) / std.clip(lower=EPS)
    return z.clip(-CLIP, CLIP)


def _rs_ratio_momentum(sector_close: pd.Series, bench_close: pd.Series, w: int) -> pd.DataFrame:
    rs = 100.0 * sector_close / bench_close
    rs_ratio = 100.0 + _zscore(rs, w)
    roc = rs_ratio.diff(1)
    rs_momentum = 100.0 + _zscore(roc, w)
    return pd.DataFrame({"rs_ratio": rs_ratio, "rs_momentum": rs_momentum})


def _resample(s: pd.Series, timeframe: str) -> pd.Series:
    """Resample to weekly/monthly, but index each bucket by its ACTUAL last
    trading date rather than the calendar period-end. Matters for the current
    forming bucket: July's month-end label (2026-07-31) is a future date, so
    a "date <= selected session" slice would wrongly drop it — and it's more
    truthful anyway (the bucket's data really is "as of" its last trading day)."""
    s = s.dropna()
    if timeframe == "1D":
        return s
    rule = {"1W": "W-FRI", "1M": "ME"}[timeframe]
    val = s.resample(rule).last()
    last_date = s.index.to_series().resample(rule).last()
    mask = val.notna()
    return pd.Series(val[mask].values,
                     index=pd.DatetimeIndex(last_date[mask].values)).sort_index()


def _is_period_partial(last_daily_date: pd.Timestamp, timeframe: str) -> bool:
    """Is the most recent Weekly/Monthly bucket still forming (not yet a
    closed candle)? Approximated from calendar position, not an exchange
    holiday calendar — good enough to flag "still moving", not exact."""
    if timeframe == "1W":
        return last_daily_date.weekday() != 4  # not yet a Friday close
    if timeframe == "1M":
        nxt = last_daily_date + pd.tseries.offsets.BDay(1)
        return nxt.month == last_daily_date.month
    return False


def build_rrg(con, benchmark: str = BENCHMARK_INDEX_NAME) -> dict | None:
    names = [benchmark] + list(INDEX_NAME_BY_SECTOR.values())
    ph = ", ".join("?" * len(names))
    df = con.execute(
        f"SELECT date, index_name, close FROM daily_index_close "
        f"WHERE index_name IN ({ph}) ORDER BY date",
        names,
    ).fetchdf()
    if df.empty or benchmark not in set(df["index_name"]):
        return None

    df["date"] = pd.to_datetime(df["date"])
    wide = df.pivot(index="date", columns="index_name", values="close").sort_index()
    if benchmark not in wide.columns:
        return None
    last_daily_date = wide.index[-1]

    out_timeframes = {}
    for tf, tail in TAIL_LENGTH.items():
        partial_current = _is_period_partial(last_daily_date, tf) and tf != "1D"
        bench_r = _resample(wide[benchmark], tf)

        # Compute each sector's full RS-Ratio/Momentum series (over the full
        # history, so every value reflects a settled rolling window), then
        # collect them into a shared-date-axis frame.
        rr_cols, rm_cols, w_used = {}, {}, None
        for label, index_name in INDEX_NAME_BY_SECTOR.items():
            if index_name not in wide.columns:
                continue
            sec_r = _resample(wide[index_name], tf)
            aligned = pd.concat({"sector": sec_r, "bench": bench_r}, axis=1).dropna()
            n_valid = len(aligned)
            if n_valid < 2 * MIN_W:
                continue  # can't derive even a minimal window — skip this sector
            w, _this_tail, _thin = _derive_window(n_valid, tail)
            w_used = w_used or w
            rrgm = _rs_ratio_momentum(aligned["sector"], aligned["bench"], w)
            rr_cols[label] = rrgm["rs_ratio"]
            rm_cols[label] = rrgm["rs_momentum"]

        if not rr_cols:
            continue
        rr_df = pd.DataFrame(rr_cols)
        rm_df = pd.DataFrame(rm_cols)
        # shared date axis: drop leading warm-up rows where every sector is NaN,
        # then ship only the last SHIP_N computed periods.
        idx = rr_df.dropna(how="all").index
        idx = idx[-SHIP_N[tf]:]
        if len(idx) == 0:
            continue
        dates = [d.strftime("%Y-%m-%d") for d in idx]
        partial_last = bool(partial_current and idx[-1] == rr_df.index[-1])

        sectors_out = {}
        for label in rr_cols:
            rr = rr_df[label].reindex(idx)
            rm = rm_df[label].reindex(idx)
            arr = [
                None if (pd.isna(a) or pd.isna(b))
                else [round(float(a), 4), round(float(b), 4)]
                for a, b in zip(rr, rm)
            ]
            sectors_out[label] = arr

        out_timeframes[tf] = {
            "lookback": w_used,
            "candles": len(rr_df),
            "dates": dates,          # shared, ascending, one entry per shipped period
            "partial_last": partial_last,  # is the final shipped period still forming
            "sectors": sectors_out,  # label -> [[rs_ratio, rs_momentum] | null, ...] aligned to dates
        }
        if len(rr_df) < TAIL_LENGTH[tf] + MIN_W:
            out_timeframes[tf]["thin"] = True

    if not out_timeframes:
        return None
    return {"benchmark": benchmark, "timeframes": out_timeframes}


# ── Stock-level RRG (drill-down from a sector) ───────────────────────────────
STOCK_DEFAULT_N = 15   # most-liquid names shown by default per sector; rest ship hidden
STOCK_RS_DP = 2        # ship 2dp (a ~98-104 scatter shows no visible difference at 4dp)


def _stock_series(adj_close: pd.Series, bench_close: pd.Series, tf: str, tail: int):
    """Windowed RS-Ratio/RS-Momentum for one stock vs one benchmark, on the
    shared date axis. Returns (idx, rr_series, rm_series, partial_ok, candles)
    or None if too little history. Same math as the sector builder."""
    sec_r = _resample(adj_close, tf)
    ben_r = _resample(bench_close, tf)
    aligned = pd.concat({"s": sec_r, "b": ben_r}, axis=1).dropna()
    if len(aligned) < 2 * MIN_W:
        return None
    w, _t, _thin = _derive_window(len(aligned), tail)
    rrgm = _rs_ratio_momentum(aligned["s"], aligned["b"], w)
    return rrgm["rs_ratio"], rrgm["rs_momentum"], w


def build_stock_rrg(con, benchmark: str = BENCHMARK_INDEX_NAME) -> dict | None:
    """RRG for individual F&O stocks within each sector, measured vs BOTH the
    NIFTY 50 benchmark ("n") and the stock's own sector index ("s"). Mirrors
    the sector RRG's shape/helpers; uses corporate-action-adjusted adj_close
    from daily_equity_technicals. Read-only. Returns None if the tables are
    absent so the HUD simply omits the drill-down."""
    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    if "daily_equity_technicals" not in tables or "daily_index_close" not in tables:
        return None

    # benchmark + all 16 sector index closes (one query)
    idx_names = [benchmark] + list(INDEX_NAME_BY_SECTOR.values())
    ph = ", ".join("?" * len(idx_names))
    idf = con.execute(
        f"SELECT date, index_name, close FROM daily_index_close "
        f"WHERE index_name IN ({ph}) ORDER BY date", idx_names).fetchdf()
    if idf.empty or benchmark not in set(idf["index_name"]):
        return None
    idf["date"] = pd.to_datetime(idf["date"])
    iwide = idf.pivot(index="date", columns="index_name", values="close").sort_index()
    bench_close = iwide[benchmark]

    # F&O universe + latest-session futures_oi for the liquidity ranking
    latest = con.execute("SELECT MAX(date) FROM daily_market_structure").fetchone()[0]
    oi = {s: (o or 0.0) for s, o in con.execute(
        "SELECT symbol, futures_oi FROM daily_market_structure WHERE date = ?",
        (latest,)).fetchall()}
    # group F&O symbols by sector (only sectors we have an index for)
    by_sector: dict[str, list[str]] = {}
    for sym in oi:
        sec = get_sector(sym)
        if sec in INDEX_NAME_BY_SECTOR:
            by_sector.setdefault(sec, []).append(sym)

    all_syms = sorted({s for lst in by_sector.values() for s in lst})
    ph2 = ", ".join("?" * len(all_syms))
    sdf = con.execute(
        f"SELECT date, symbol, adj_close FROM daily_equity_technicals "
        f"WHERE symbol IN ({ph2}) AND adj_close IS NOT NULL ORDER BY date", all_syms).fetchdf()
    if sdf.empty:
        return None
    sdf["date"] = pd.to_datetime(sdf["date"])
    swide = sdf.pivot(index="date", columns="symbol", values="adj_close").sort_index()
    last_daily_date = swide.index[-1]

    def rnd(a, b):
        return None if (pd.isna(a) or pd.isna(b)) else [round(float(a), STOCK_RS_DP), round(float(b), STOCK_RS_DP)]

    out_tf: dict[str, dict] = {}
    for tf, tail in TAIL_LENGTH.items():
        partial_current = _is_period_partial(last_daily_date, tf) and tf != "1D"

        # First pass: compute every stock's full RS-Ratio/Momentum series vs
        # both benchmarks. Collect into per-sector dicts of Series, and gather a
        # SINGLE shared date axis across ALL stocks — a shorter-history name
        # must still align to the same shipped `dates` array (else its last
        # value lands on the wrong index in the HUD).
        per_sector: dict[str, dict] = {}   # sec -> {sym: (rr_n,rm_n,rr_s,rm_s)}
        all_rr_n = {}                       # sym -> rr_n (for the shared axis)
        w_used = None
        for sec, syms in by_sector.items():
            sec_close = iwide.get(INDEX_NAME_BY_SECTOR[sec])
            if sec_close is None:
                continue
            got = {}
            for sym in syms:
                if sym not in swide.columns:
                    continue
                vs_n = _stock_series(swide[sym], bench_close, tf, tail)
                vs_s = _stock_series(swide[sym], sec_close, tf, tail)
                if vs_n is None or vs_s is None:
                    continue
                rr_n, rm_n, w = vs_n
                rr_s, rm_s, _ = vs_s
                got[sym] = (rr_n, rm_n, rr_s, rm_s)
                all_rr_n[sym] = rr_n
                w_used = w_used or w
            if got:
                per_sector[sec] = got

        if not all_rr_n:
            continue
        rr_frame = pd.DataFrame(all_rr_n)
        idx = rr_frame.dropna(how="all").index[-SHIP_N[tf]:]
        if len(idx) == 0:
            continue
        tf_dates = [d.strftime("%Y-%m-%d") for d in idx]
        tf_partial = bool(partial_current and idx[-1] == rr_frame.index[-1])
        candles = len(rr_frame)

        sectors_block: dict[str, dict] = {}
        for sec, got in per_sector.items():
            symbols_out = {}
            for sym, (rr_n, rm_n, rr_s, rm_s) in got.items():
                n_arr = [rnd(a, b) for a, b in zip(rr_n.reindex(idx), rm_n.reindex(idx))]
                s_arr = [rnd(a, b) for a, b in zip(rr_s.reindex(idx), rm_s.reindex(idx))]
                symbols_out[sym] = {"n": n_arr, "s": s_arr}
            default = sorted(symbols_out, key=lambda s: oi.get(s, 0.0), reverse=True)[:STOCK_DEFAULT_N]
            sectors_block[sec] = {"default": default, "symbols": symbols_out}

        if not sectors_block or tf_dates is None:
            continue
        out_tf[tf] = {
            "lookback": w_used,
            "candles": candles,
            "dates": tf_dates,
            "partial_last": tf_partial,
            "sectors": sectors_block,
        }
        if candles < TAIL_LENGTH[tf] + MIN_W:
            out_tf[tf]["thin"] = True

    if not out_tf:
        return None
    return {
        "sector_index": dict(INDEX_NAME_BY_SECTOR),
        "timeframes": out_tf,
    }
