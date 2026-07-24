"""
Live structure engine (M2) — recomputes walls / GEX / gamma-flip / gamma-regime
every COMPUTE_CADENCE (30s) from live near-ATM option ticks, reusing
GreeksEngine.process_dataframe, GammaAnalyzer.calculate_gex, and
InstitutionalIntelligence.compute_walls_and_flip/.gamma_regime completely
unmodified — the same math the EOD pipeline uses, just fed live ticks instead
of a bhav close.

Scope (see the M2 plan): top-N-by-OI stocks + all indices, front-expiry only.
Widening this is a separate, explicitly-deferred follow-on — see
vanguard/greeks_engine.py's per-row Brent-solve cost, benchmarked in the plan as the
actual bottleneck (not the WebSocket budget).
"""
from __future__ import annotations

import time
import concurrent.futures
import numpy as np
import pandas as pd

from vanguard.live import config as C
from vanguard.greeks_engine import GreeksEngine
from vanguard.analyzer import GammaAnalyzer
from vanguard.intelligence import InstitutionalIntelligence

_engine = GreeksEngine()
_gamma = GammaAnalyzer()

# consecutive compute cycles a relocated wall must hold before firing WALL_RELOCATED
WALL_CONFIRM_CYCLES = 2
IV_EVENT_THRESHOLD = 0.02   # +-2 vol points vs the session's first computed IV

# Below this many dirty option-rows, compute() inline rather than pooling —
# a rough heuristic (a few symbols' worth of near-ATM rows), not a profiled
# number. Re-tune against a real session before trusting it at the margins.
MIN_ROWS_FOR_POOL = 400


def select_covered_names(con, constituents: list[str] | None = None) -> list[str]:
    """Nifty50 constituents (vanguard.live.universe, NSE-fetched and cached
    daily) that are also present in the compiled F&O universe, plus every
    index — indices are always covered regardless of index membership.

    Replaces the old OI-ranked top-N selection (TOP_N_LIVE_OPTIONS): Nifty50
    + indices measures at ~2,978 instruments at full strike depth, well
    inside the single-connection WS_MAX_PER_CONN=5000 budget, so there's no
    need for an OI cutoff — every constituent gets covered, not just the
    highest-OI subset of them.

    `constituents` is injectable for tests; production always uses the real
    NSE-fetched list."""
    if constituents is None:
        from vanguard.live.universe import get_nifty50_constituents
        constituents = get_nifty50_constituents()
    latest = con.execute("SELECT MAX(date) FROM daily_market_structure").fetchone()[0]
    known = {r[0] for r in con.execute(
        "SELECT DISTINCT symbol FROM daily_market_structure WHERE date = ?", [latest]).fetchall()}
    covered = (set(constituents) & known) | set(C.INDEX_SYMBOLS)
    return sorted(covered)


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
            key = (0, str(r.security_id))
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


def compute(df: pd.DataFrame, spot_prices: dict[str, float]) -> tuple[dict[str, dict], dict[str, str]]:
    """One live compute cycle: IV/Greeks -> walls/flip -> GEX -> regime, per
    covered symbol. Returns structure dictionary and serialized Live Chain JSONs."""
    if df.empty:
        return {}, {}
    greeks_df = _engine.process_dataframe(df, spot_prices)
    if greeks_df.empty:
        return {}, {}
    # Per-strike GEX on greeks_df itself (same formula/precedent as the EOD
    # export path — vanguard/engines/intelligence.py's analyze_market_
    # structure(), greeks_t['GEX'] = GAMMA*OPEN_INT*SPOT*0.01*MULTIPLIER).
    # Needed so the chain JSON below (served at /api/chain/<symbol>, the
    # dossier's GEX Profile chart) actually carries a GEX field per strike —
    # GammaAnalyzer.calculate_gex() computes its own GEX internally too, but
    # only to aggregate it away into a per-symbol summary; that per-row copy
    # was never returned or merged back, so every chain row's GEX silently
    # read as undefined -> 0 client-side, rendering the chart as empty bars.
    greeks_df["SPOT"] = greeks_df["SYMBOL"].map(spot_prices)
    multiplier = greeks_df["OPTION_TYP"].map({"CE": 1, "PE": -1}).fillna(1)
    greeks_df["GEX"] = greeks_df["GAMMA"] * greeks_df["OPEN_INT"] * greeks_df["SPOT"].fillna(0.0) * 0.01 * multiplier
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
        
    chains_json = {}
    cols = ["STRIKE_PR", "OPTION_TYP", "EXPIRY_DT", "CLOSE", "OPEN_INT", "CHG_IN_OI", "IV", "DELTA", "GAMMA", "VEGA", "THETA", "GEX"]
    for sym, group in greeks_df.groupby("SYMBOL"):
        available_cols = [c for c in cols if c in group.columns]
        chains_json[sym] = group[available_cols].to_json(orient="records")
        
    return out, chains_json


def compute_live_setups(structure: dict, spot_prices: dict) -> list[dict]:
    """Computes high-conviction intraday setups purely from live structure."""
    setups = []
    for sym, st in structure.items():
        spot = spot_prices.get(sym, 0.0)
        if not spot:
            continue
            
        call_wall = st.get("call_wall", 0.0)
        put_wall = st.get("put_wall", 0.0)
        regime = st.get("gamma_regime", "NEUTRAL")
        gex = st.get("gex", 0.0)
        flip = st.get("gamma_flip", 0.0)
        
        setup_type = None
        bias = "NEUTRAL"
        trigger = 0.0
        invalidation = 0.0
        
        if regime == "SHORT_GAMMA":
            if call_wall > 0 and spot >= call_wall * 0.995:
                setup_type = "GAMMA_SQUEEZE"
                bias = "BULLISH"
                trigger = call_wall
                invalidation = flip
            elif put_wall > 0 and spot <= put_wall * 1.005:
                setup_type = "INVENTORY_MIGRATION"
                bias = "BEARISH"
                trigger = put_wall
                invalidation = flip
        elif regime == "LONG_GAMMA":
            if put_wall > 0 and put_wall * 0.99 <= spot <= put_wall * 1.015:
                setup_type = "FLOOR_BOUNCE"
                bias = "BULLISH"
                trigger = put_wall
                invalidation = put_wall * 0.98
            elif call_wall > 0 and call_wall * 0.985 <= spot <= call_wall * 1.01:
                setup_type = "CEILING_REJECTION"
                bias = "BEARISH"
                trigger = call_wall
                invalidation = call_wall * 1.02
        
        if setup_type:
            setups.append({
                "symbol": sym,
                "setup_type": setup_type,
                "bias": bias,
                "trigger_strike": trigger,
                "invalidation_strike": invalidation,
                "gex": gex
            })
            
    # Sort by absolute GEX to surface the most intense structural setups
    setups.sort(key=lambda x: abs(x["gex"]), reverse=True)
    return setups


class LiveStructureEngine:
    """Owns catalog + OI baseline + per-symbol prior-cycle state; run_cycle()
    is called every COMPUTE_CADENCE and returns (structure, new_events)."""

    def __init__(self, key_to_meta: dict[tuple[int, int], dict],
                 oi_baseline: dict[tuple[str, float, str], float],
                 symbol_spot_key: dict[str, tuple[int, int]] = None):
        self.key_to_meta = key_to_meta
        self.oi_baseline = oi_baseline
        self.symbol_spot_key = symbol_spot_key or {}
        self.spot_key_to_symbol = {v: k for k, v in self.symbol_spot_key.items() if v}
        self._confirmed_wall: dict[tuple[str, str], float] = {}
        self._candidate_wall: dict[tuple[str, str], tuple[float, int]] = {}
        self._prev_regime: dict[str, str] = {}
        self._session_open_iv: dict[str, float] = {}
        self._iv_alerted: set[tuple[str, str]] = set()
        self._executor = None   # lazily created — most cycles never need it, see run_cycle()

        self._cached_result = {}
        self._cached_chains = {}

    def run_cycle(self, store, spot_prices: dict[str, float], live_chains_cache: dict) -> tuple[dict, list[dict]]:
        # dirty_keys() is the store's own thread-safe accessor — this used to
        # read store._s directly, racing the feed thread's key inserts.
        dirty_keys = store.dirty_keys()
        dirty_symbols = set()
        for k in dirty_keys:
            if k in self.spot_key_to_symbol:
                dirty_symbols.add(self.spot_key_to_symbol[k])
            elif k in self.key_to_meta:
                dirty_symbols.add(self.key_to_meta[k]["symbol"])

        # First run should compute everything
        if not self._cached_result:
            dirty_symbols = set(spot_prices.keys())

        if not dirty_symbols:
            return self._cached_result, []

        df = build_option_frame(store, self.key_to_meta, self.oi_baseline)
        if df.empty:
            return {}, []

        # Filter for dirty symbols only
        df_dirty = df[df["SYMBOL"].isin(dirty_symbols)]
        symbols = df_dirty["SYMBOL"].unique()

        if len(symbols) == 0:
            return self._cached_result, []

        # Below MIN_ROWS_FOR_POOL, the per-task IPC/pickling cost of farming
        # this out to a subprocess exceeds the Brent-solve time it saves —
        # only worth pooling when a large chunk of the universe went dirty at
        # once (e.g. the first cycle, or a broad market move). Steady-state
        # cycles (a handful of symbols ticking) run inline.
        n_workers = min(6, len(symbols))
        if n_workers <= 1 or len(df_dirty) < MIN_ROWS_FOR_POOL:
            result, chains_json = compute(df_dirty, spot_prices)
        else:
            if self._executor is None:
                self._executor = concurrent.futures.ProcessPoolExecutor(max_workers=6)
            chunks = np.array_split(symbols, n_workers)
            df_chunks = [df_dirty[df_dirty["SYMBOL"].isin(chunk)] for chunk in chunks if len(chunk) > 0]

            futures = []
            for chunk in df_chunks:
                futures.append(self._executor.submit(compute, chunk, spot_prices))

            result = {}
            chains_json = {}
            for f in concurrent.futures.as_completed(futures):
                res_out, res_chains = f.result()
                result.update(res_out)
                chains_json.update(res_chains)
                
        # Merge with caches
        self._cached_result.update(result)
        self._cached_chains.update(chains_json)
        
        # Update the live chains cache (in-memory)
        live_chains_cache.update(self._cached_chains)
        
        events = self._diff_events(self._cached_result)
        
        # Acknowledge processed ticks
        if dirty_keys:
            store.clear_dirty_flags(dirty_keys)
            
        return self._cached_result, events

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
