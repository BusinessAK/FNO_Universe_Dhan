"""
WS manifest builder core (TRD_fullmap_live_v1 §2) — turns yesterday's bhav into
tomorrow's WebSocket subscription set:

    99.5%-of-OI strikes  +  ±5 zero-OI ATM buffer  +  full front chain of
    armed-setup names  +  spot + front futures for the whole universe.

The manifest is also the OI baseline: every option row carries the bhav's
OPEN_INT/close, which is what the live diff engine measures ΔOI against
(replaces the old greeks.csv seed).

Pure functions over dataframes — the script wrapper (scripts/build_ws_manifest.py)
owns file discovery, DuckDB access, and the reuse-previous-manifest fallback.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from vanguard.live import config as C

# Bhav columns the builder depends on — validated up front so an NSE format
# change fails loudly with a diff instead of producing an empty manifest (N10).
REQUIRED_BHAV_COLS = ["TckrSymb", "XpryDt", "StrkPric", "OptnTp",
                      "OpnIntrst", "ClsPric", "FinInstrmTp"]

MANIFEST_COLS = ["seg", "sid", "mode", "kind", "symbol", "expiry", "strike",
                 "otype", "oi_baseline", "close_baseline", "reason"]


class ManifestError(RuntimeError):
    """Loud failure — the caller reuses the previous manifest (never an empty one)."""


def validate_bhav_schema(bhav: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_BHAV_COLS if c not in bhav.columns]
    if missing:
        raise ManifestError(
            f"bhav schema changed — missing columns {missing}; "
            f"present: {sorted(bhav.columns.tolist())[:20]}...")


def _norm_expiry(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce").dt.strftime("%Y-%m-%d")


def _option_master_key_map(im) -> dict:
    """(underlying, expiry_str, strike_2dp, otype) -> (seg, sid) for options."""
    m = im.df[im.df.kind == "OPT"]
    return {
        (u, str(e), round(float(k), 2), o): (int(seg), int(sid))
        for u, e, k, o, seg, sid in zip(
            m.underlying, m.expiry, m.strike, m.option_type,
            m.feed_segment, m.security_id)
    }


def select_oi_strikes(bhav: pd.DataFrame, universe: set[str],
                      coverage: float) -> pd.DataFrame:
    """The OI-ranked prefix reaching `coverage` of total OI (universe-pinned)."""
    opt = bhav[bhav.FinInstrmTp.isin(["STO", "IDO"])].copy()
    opt = opt[opt.TckrSymb.isin(universe)]
    opt["OpnIntrst"] = pd.to_numeric(opt.OpnIntrst, errors="coerce").fillna(0)
    opt = opt[opt.OpnIntrst > 0]
    if opt.empty:
        raise ManifestError("no option rows with OI in bhav after universe pinning")
    opt = opt.sort_values("OpnIntrst", ascending=False)
    total = opt.OpnIntrst.sum()
    return opt[opt.OpnIntrst.cumsum() <= total * coverage]


def build_manifest(bhav: pd.DataFrame, im, universe: set[str],
                   spot_closes: dict[str, float], armed_symbols: set[str],
                   today: date, coverage: float | None = None,
                   atm_buffer: int | None = None) -> tuple[pd.DataFrame, dict]:
    """Returns (manifest_df, report). Raises ManifestError on any condition
    where a stale manifest beats a fresh-but-wrong one."""
    coverage = coverage or C.OI_COVERAGE
    atm_buffer = atm_buffer or C.ATM_BUFFER
    validate_bhav_schema(bhav)

    key_map = _option_master_key_map(im)
    rows: dict[tuple[int, int], dict] = {}          # (seg,sid) -> row, first reason wins

    def add_option(seg, sid, sym, expiry, strike, otype, oi, close, reason):
        key = (seg, sid)
        if key not in rows:
            rows[key] = dict(seg=seg, sid=sid, mode=C.MODE_FULL, kind="OPT",
                             symbol=sym, expiry=str(expiry), strike=float(strike),
                             otype=otype, oi_baseline=float(oi),
                             close_baseline=float(close), reason=reason)

    # ── 1. OI-coverage set (with the >1% unmapped abort) ─────────────────────
    def map_oi_set(cov: float) -> tuple[int, int, float]:
        sel = select_oi_strikes(bhav, universe, cov)
        sel = sel.assign(EXP_N=_norm_expiry(sel.XpryDt),
                         K_N=sel.StrkPric.astype(float).round(2))
        unmapped = 0
        unmapped_oi = 0.0
        for r in sel.itertuples():
            hit = key_map.get((r.TckrSymb, r.EXP_N, r.K_N, r.OptnTp))
            if hit is None:
                unmapped += 1
                unmapped_oi += r.OpnIntrst
                continue
            add_option(hit[0], hit[1], r.TckrSymb, r.EXP_N, r.K_N, r.OptnTp,
                       r.OpnIntrst, r.ClsPric, "oi_set")
        return len(sel), unmapped, unmapped_oi

    n_sel, n_unmapped, oi_unmapped = map_oi_set(coverage)
    if n_sel and n_unmapped / n_sel > 0.01:
        raise ManifestError(
            f"{n_unmapped}/{n_sel} OI-set strikes unmapped (> 1%) — instrument "
            f"master drift (corporate action / stale scrip master?)")

    # ── 2. ATM buffer (zero-OI strikes near spot; rollover-aware, N6) ────────
    def add_chain(sym, chain, oi_lookup, reason):
        for r in chain.itertuples():
            oi, close = oi_lookup.get(
                (str(r.expiry), round(float(r.strike), 2), r.option_type), (0.0, 0.0))
            add_option(int(r.feed_segment), int(r.security_id), sym, r.expiry,
                       r.strike, r.option_type, oi, close, reason)

    opt_bhav = bhav[bhav.FinInstrmTp.isin(["STO", "IDO"])]
    opt_bhav = opt_bhav.assign(EXP_N=_norm_expiry(opt_bhav.XpryDt),
                               K_N=pd.to_numeric(opt_bhav.StrkPric, errors="coerce").round(2))
    for sym in universe:
        spot = spot_closes.get(sym)
        if not spot or spot <= 0:
            continue
        base = opt_bhav[opt_bhav.TckrSymb == sym]
        oi_lookup = {(r.EXP_N, r.K_N, r.OptnTp):
                     (float(r.OpnIntrst or 0), float(r.ClsPric or 0))
                     for r in base.itertuples()}
        exps = im.expiries(sym)
        if not exps:
            continue
        add_chain(sym, im.near_atm(sym, spot, n_strikes=atm_buffer,
                                   expiry=exps[0]), oi_lookup, "atm_buffer")
        # rollover eve: dying front series — also window the next expiry
        if len(exps) > 1 and pd.to_datetime(str(exps[0])).date() <= today + timedelta(days=1):
            add_chain(sym, im.near_atm(sym, spot, n_strikes=atm_buffer,
                                       expiry=exps[1]), oi_lookup, "rollover")

    # ── 3. Armed setups: a WIDER ATM window, not the full chain ─────────────
    # daily_setups arms most of the universe (186/215 observed 2026-07-16), so
    # "armed" is not a small hot list — a full-chain rule would blow the size
    # bounds. Trigger/invalidation levels are near ATM by construction, so a
    # wider window carries the same information at bounded cost.
    for sym in armed_symbols & universe:
        spot = spot_closes.get(sym)
        exps = im.expiries(sym)
        if not exps or not spot or spot <= 0:
            continue
        base = opt_bhav[opt_bhav.TckrSymb == sym]
        oi_lookup = {(r.EXP_N, r.K_N, r.OptnTp):
                     (float(r.OpnIntrst or 0), float(r.ClsPric or 0))
                     for r in base.itertuples()}
        add_chain(sym, im.near_atm(sym, spot, n_strikes=C.ARMED_WINDOW,
                                   expiry=exps[0]), oi_lookup, "armed")

    # ── 4. Spot + front futures for the whole universe ───────────────────────
    for sym in sorted(universe):
        srow = im.spot(sym)
        if srow:
            key = (int(srow["feed_segment"]), int(srow["security_id"]))
            rows.setdefault(key, dict(
                seg=key[0], sid=key[1], mode=C.MODE_QUOTE, kind="SPOT",
                symbol=sym, expiry="", strike=0.0, otype="",
                oi_baseline=0.0, close_baseline=float(spot_closes.get(sym) or 0),
                reason="spot"))
        fut = im.futures(sym)
        if not fut.empty:
            r = fut.sort_values("expiry").iloc[0]
            key = (C.SEG_NSE_FNO, int(r.security_id))
            rows.setdefault(key, dict(
                seg=key[0], sid=key[1], mode=C.MODE_FULL, kind="FUT",
                symbol=sym, expiry=str(r.expiry), strike=0.0, otype="",
                oi_baseline=0.0, close_baseline=0.0, reason="fut"))

    out = pd.DataFrame(list(rows.values()), columns=MANIFEST_COLS)

    # ── 5. Bounds (N11) — one retry at the fallback coverage before aborting ─
    if len(out) > C.MANIFEST_MAX and coverage > C.OI_COVERAGE_FALLBACK:
        return build_manifest(bhav, im, universe, spot_closes, armed_symbols,
                              today, coverage=C.OI_COVERAGE_FALLBACK,
                              atm_buffer=atm_buffer)
    if not (C.MANIFEST_MIN <= len(out) <= C.MANIFEST_MAX):
        raise ManifestError(
            f"manifest size {len(out)} outside [{C.MANIFEST_MIN}, {C.MANIFEST_MAX}] "
            f"— refusing a suspicious map (N11)")

    n_opt = int((out.kind == "OPT").sum())
    report = {
        "total": len(out),
        "by_reason": out.reason.value_counts().to_dict(),
        "by_kind": out.kind.value_counts().to_dict(),
        "coverage_used": coverage,
        "oi_set_selected": n_sel,
        "oi_set_unmapped": n_unmapped,
        "unmapped_oi_share": float(oi_unmapped) if n_sel else 0.0,
        "options": n_opt,
        "connections_needed": -(-len(out) // C.WS_MAX_PER_CONN),
    }
    return out, report
