"""
Live structure engine (M2) — recomputes walls / GEX / gamma-flip / gamma-regime
every COMPUTE_CADENCE (30s) from live near-ATM option ticks, reusing
GreeksEngine.process_dataframe, GammaAnalyzer.calculate_gex, and
InstitutionalIntelligence.compute_walls_and_flip/.gamma_regime completely
unmodified — the same math the EOD pipeline uses, just fed live ticks instead
of a bhav close.

Scope (see the M2 plan): top-N-by-OI stocks + all indices, front-expiry only.
Widening this is a separate, explicitly-deferred follow-on — see
src/greeks_engine.py's per-row Brent-solve cost, benchmarked in the plan as the
actual bottleneck (not the WebSocket budget).
"""
from __future__ import annotations

import time

import pandas as pd

from src.live import config as C
from src.greeks_engine import GreeksEngine
from src.analyzer import GammaAnalyzer
from src.intelligence import InstitutionalIntelligence

_engine = GreeksEngine()
_gamma = GammaAnalyzer()

# consecutive compute cycles a relocated wall must hold before firing WALL_RELOCATED
WALL_CONFIRM_CYCLES = 2
IV_EVENT_THRESHOLD = 0.02   # +-2 vol points vs the session's first computed IV


def select_covered_names(con, top_n: int | None = None) -> list[str]:
    """Top-N stock underlyings by yesterday's EOD total OI, plus every index —
    indices are always covered regardless of OI rank on this platform."""
    top_n = top_n or C.TOP_N_LIVE_OPTIONS
    latest = con.execute("SELECT MAX(date) FROM daily_market_structure").fetchone()[0]
    rows = con.execute(
        "SELECT symbol FROM daily_market_structure WHERE date = ? "
        "ORDER BY total_ce_oi + total_pe_oi DESC LIMIT ?",
        [latest, top_n],
    ).fetchall()
    top = {r[0] for r in rows}
    return sorted(top | set(C.INDEX_SYMBOLS))


def build_option_catalog(im, covered_names: list[str],
                         name_spots: dict[str, float]) -> dict[tuple[int, int], dict]:
    """(segment, security_id) -> {symbol, strike, option_type, expiry} for the
    near-ATM window of every covered name. Window sizing (STRIKE_WINDOW /
    STRIKE_WINDOW_INDEX) mirrors SubscriptionManager.options_manifest() exactly
    — this must stay in sync with what we actually subscribe to, or ticks
    arrive for instruments this catalog can't interpret (or vice versa)."""
    key_to_meta: dict[tuple[int, int], dict] = {}
    for sym in covered_names:
        spot = name_spots.get(sym)
        if not spot or spot <= 0:
            continue
        win = C.STRIKE_WINDOW_INDEX if sym in C.INDEX_SYMBOLS else C.STRIKE_WINDOW
        chain = im.near_atm(sym, spot, n_strikes=win)
        for r in chain.itertuples():
            key = (C.SEG_NSE_FNO, int(r.security_id))
            key_to_meta[key] = {"symbol": sym, "strike": float(r.strike),
                                 "option_type": r.option_type, "expiry": r.expiry}
    return key_to_meta


def build_option_frame(store, key_to_meta: dict[tuple[int, int], dict],
                        oi_baseline: dict[tuple[str, float, str], float]) -> pd.DataFrame:
    """Live ticks -> the bhav-shaped frame GreeksEngine.process_dataframe expects.
    Instruments with no tick yet are skipped entirely — never invent a price.
    OPEN_INT falls back to the EOD baseline until a live OI tick arrives (NSE's
    OI dissemination is ~3-min floored regardless, so this is a short gap)."""
    rows = []
    now_ts = pd.Timestamp.now()
    for (seg, sid), meta in key_to_meta.items():
        st = store.get(seg, sid)
        if st is None or st.ltp is None:
            continue
        sym, strike, opt_type, expiry = meta["symbol"], meta["strike"], meta["option_type"], meta["expiry"]
        base_key = (sym, strike, opt_type)
        base_oi = oi_baseline.get(base_key, 0.0)
        oi = float(st.oi) if st.oi is not None else base_oi
        rows.append({
            "INSTRUMENT": "IDO" if sym in C.INDEX_SYMBOLS else "STO",
            "SYMBOL": sym, "STRIKE_PR": strike, "OPTION_TYP": opt_type,
            "EXPIRY_DT": pd.Timestamp(expiry), "TIMESTAMP": now_ts,
            "CLOSE": float(st.ltp), "OPEN_INT": oi, "CHG_IN_OI": oi - base_oi,
            "VOLUME": float(st.vol) if st.vol is not None else 0.0,
        })
    return pd.DataFrame(rows)


def compute(df: pd.DataFrame, spot_prices: dict[str, float]) -> dict[str, dict]:
    """One live compute cycle: IV/Greeks -> walls/flip -> GEX -> regime, per
    covered symbol. Empty input (no ticks yet) yields no structure — the HUD
    falls back to EOD-only for symbols missing from the result, same as the
    LTP overlay already does for freshness."""
    if df.empty:
        return {}
    greeks_df = _engine.process_dataframe(df, spot_prices)
    if greeks_df.empty:
        return {}
    walls = InstitutionalIntelligence.compute_walls_and_flip(greeks_df, spot_prices)
    gex_summary = _gamma.calculate_gex(greeks_df, spot_prices)
    gex_by_symbol = gex_summary.set_index("SYMBOL") if not gex_summary.empty else gex_summary

    now = time.time()
    out = {}
    for sym, wf in walls.items():
        spot = spot_prices.get(sym, 0.0)
        has_gex_row = (not gex_by_symbol.empty) and (sym in gex_by_symbol.index)
        if has_gex_row:
            row = gex_by_symbol.loc[sym]
            gex_total, gex_intensity, iv_avg = float(row["GEX"]), float(row["GEX_INTENSITY"]), float(row["IV"])
        else:
            gex_total = gex_intensity = iv_avg = 0.0
        regime = InstitutionalIntelligence.gamma_regime(spot, wf["gamma_flip"], gex_total)
        out[sym] = {
            "call_wall": wf["call_wall"], "put_wall": wf["put_wall"],
            "gamma_flip": wf["gamma_flip"], "gex": gex_total,
            "gex_intensity": gex_intensity, "iv_avg": iv_avg,
            "gamma_regime": regime, "computed_at": now,
        }
    return out


class LiveStructureEngine:
    """Owns catalog + OI baseline + per-symbol prior-cycle state; run_cycle()
    is called every COMPUTE_CADENCE and returns (structure, new_events)."""

    def __init__(self, key_to_meta: dict[tuple[int, int], dict],
                 oi_baseline: dict[tuple[str, float, str], float]):
        self.key_to_meta = key_to_meta
        self.oi_baseline = oi_baseline
        self._confirmed_wall: dict[tuple[str, str], float] = {}   # (symbol, side) -> last-fired wall
        self._candidate_wall: dict[tuple[str, str], tuple[float, int]] = {}  # -> (candidate, streak)
        self._prev_regime: dict[str, str] = {}
        self._session_open_iv: dict[str, float] = {}
        self._iv_alerted: set[tuple[str, str]] = set()   # (symbol, "up"/"down"), one-shot per day

    def run_cycle(self, store, spot_prices: dict[str, float]) -> tuple[dict, list[dict]]:
        df = build_option_frame(store, self.key_to_meta, self.oi_baseline)
        result = compute(df, spot_prices)
        events = self._diff_events(result)
        return result, events

    def _diff_events(self, result: dict[str, dict]) -> list[dict]:
        events = []
        now = time.time()
        for sym, cur in result.items():
            events.extend(self._regime_events(sym, cur, now))
            events.extend(self._wall_events(sym, cur, now))
            events.extend(self._iv_events(sym, cur, now))
        return events

    def _regime_events(self, sym, cur, now) -> list[dict]:
        prev = self._prev_regime.get(sym)
        self._prev_regime[sym] = cur["gamma_regime"]
        if prev is None or prev == cur["gamma_regime"]:
            return []
        return [{"ts": now, "symbol": sym, "type": "REGIME_CROSS",
                 "from": prev, "to": cur["gamma_regime"]}]

    def _wall_events(self, sym, cur, now) -> list[dict]:
        fired = []
        for side, field in (("call", "call_wall"), ("put", "put_wall")):
            wall = cur[field]
            key = (sym, side)
            if wall <= 0:
                continue
            confirmed = self._confirmed_wall.get(key)
            if confirmed is None:
                self._confirmed_wall[key] = wall   # first sighting — establish baseline, no event
                continue
            if wall == confirmed:
                self._candidate_wall.pop(key, None)
                continue
            cand, streak = self._candidate_wall.get(key, (wall, 0))
            if cand != wall:
                streak = 0
            streak += 1
            if streak >= WALL_CONFIRM_CYCLES:
                fired.append({"ts": now, "symbol": sym, "type": "WALL_RELOCATED", "side": side,
                              "from": confirmed, "to": wall})
                self._confirmed_wall[key] = wall
                self._candidate_wall.pop(key, None)
            else:
                self._candidate_wall[key] = (wall, streak)
        return fired

    def _iv_events(self, sym, cur, now) -> list[dict]:
        iv = cur["iv_avg"]
        if iv <= 0:
            return []
        open_iv = self._session_open_iv.setdefault(sym, iv)
        if open_iv <= 0:
            return []
        delta = iv - open_iv
        direction = "up" if delta >= IV_EVENT_THRESHOLD else ("down" if delta <= -IV_EVENT_THRESHOLD else None)
        if direction is None or (sym, direction) in self._iv_alerted:
            return []
        self._iv_alerted.add((sym, direction))
        return [{"ts": now, "symbol": sym, "type": "IV_EVENT", "direction": direction,
                 "iv": iv, "open_iv": open_iv, "delta": delta}]
