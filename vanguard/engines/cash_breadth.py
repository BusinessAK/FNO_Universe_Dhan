"""
Vanguard Institutional Terminal - Cash Market Breadth Engine
Computes price-based breadth across the full NSE EQ universe (2,400+ symbols).

Design constraints:
- NO Streamlit imports — pure data/analytics layer, fully testable in isolation.
- Handles unadjusted NSE bhavcopies: corporate actions (splits, bonuses, dividends)
  produce overnight gaps in raw `close`. We use `prev_close` from the NEXT day's row
  as the true ex-date settlement (NSE populates this correctly), building a ratio-based
  adjustment chain. Affected rows are flagged so UI can optionally surface them.
- Anchor policy: cumulative A/D Line starts at 0 on the first date in the dataset.
  McClellan Oscillator EMAs are also anchored at that date. This is documented and
  consistent — no silent re-anchoring on recompiles.
- Universe size is tracked per day (total_cm_symbols) to prevent ratio jump confusion
  when symbols are added/removed.
"""
from __future__ import annotations

import warnings
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# ── Constants ────────────────────────────────────────────────────────────────

# Threshold for detecting unadjusted corporate actions:
# a single-day close-to-close drop larger than this is treated as a CA event.
_CA_DROP_THRESHOLD = -0.35

# DMA windows
_DMA_SHORT = 20
_DMA_MID   = 50
_DMA_LONG  = 200

# McClellan parameters
_MCL_FAST = 19
_MCL_SLOW = 39

# RSI parameters
_RSI_PERIOD = 14
_RSI_OVERBOUGHT = 70
_RSI_OVERSOLD = 30

# Default parquet path (can be overridden in build_cm_breadth())
_DEFAULT_CM_PARQUET = "data/compiled/cash_market_prices.parquet"
_DEFAULT_OUTPUT     = "data/compiled/daily_cm_breadth.parquet"
_DEFAULT_TIER_OUTPUT = "data/compiled/daily_cm_breadth_by_tier.parquet"

# Money-flow (CMF) bucket window — matches equity_technicals.py's _CMF_WINDOW
_CMF_WINDOW = 20

_TIERS = ("large", "mid", "small", "micro")


# ── Adjustment layer ──────────────────────────────────────────────────────────

def _build_adjusted_close(df: pd.DataFrame) -> pd.DataFrame:
    """
    Produces `adj_close` and `adj_prev_close` columns using a backward ratio-adjustment chain.

    Strategy
    --------
    NSE does not back-adjust for corporate actions. However, we use the adjusted open
    auction price compared to the unadjusted previous close on the ex-date:

        adjustment_ratio on ex-date  =  open[T] / prev_close[T]

    We walk chronologically, accumulate the product of all ratio corrections,
    and apply them forward so that the most-recent close == adj_close (no
    distortion at the current date, only the past is shifted).

    Both negative gaps (splits, bonuses) and positive gaps (reverse splits,
    bonus credits) beyond |35%| are treated as CA events.

    `adj_prev_close` is the shifted adj_close (adj_close[T-1]) — this is what
    `_compute_day` must use for pct_chg, not the raw `prev_close` column.
    Corporate action events are flagged in `ca_adjusted` (bool) for transparency.
    """
    df = df.copy().sort_values(["symbol", "date"])

    adj_closes = []
    adj_highs  = []
    adj_lows   = []
    ca_flags   = []

    for sym, grp in df.groupby("symbol", sort=False):
        grp = grp.sort_values("date").reset_index(drop=True)
        closes      = grp["close"].values.astype(float)
        prev_closes = grp["prev_close"].values.astype(float)
        opens       = grp["open"].values.astype(float)
        highs       = grp["high"].values.astype(float) if "high" in grp.columns else closes
        lows        = grp["low"].values.astype(float) if "low" in grp.columns else closes

        n = len(grp)
        ratios  = np.ones(n)
        ca_flag = np.zeros(n, dtype=bool)

        for i in range(1, n):
            c_prev  = closes[i - 1]
            p_close = prev_closes[i]
            if c_prev > 0 and p_close > 0:
                raw_pct = (closes[i] - c_prev) / c_prev
                # Both large drops (splits/bonuses) and large rises (reverse splits)
                # trigger CA correction.
                if raw_pct < _CA_DROP_THRESHOLD or raw_pct > -_CA_DROP_THRESHOLD:
                    # NSE is inconsistent on ex-dates: sometimes prev_close is left
                    # unadjusted (== prior close), sometimes it is already the
                    # adjusted base. When it differs materially from the prior
                    # close, prev_close/prior_close IS the exact CA factor; using
                    # open/prev_close there would be ~1.0 and leave the cliff in.
                    if abs(p_close / c_prev - 1.0) > 0.05:
                        ratios[i] = p_close / c_prev
                    else:
                        ratios[i] = opens[i] / p_close
                    ca_flag[i] = True

        # Build cumulative factor (most-recent = 1.0, history scaled to match)
        cum_factor = np.ones(n)
        for i in range(n - 2, -1, -1):
            cum_factor[i] = cum_factor[i + 1] * ratios[i + 1]

        adj_closes.extend((closes * cum_factor).tolist())
        adj_highs.extend((highs * cum_factor).tolist())
        adj_lows.extend((lows * cum_factor).tolist())
        ca_flags.extend(ca_flag.tolist())

    df["adj_close"]  = adj_closes
    df["adj_high"]   = adj_highs
    df["adj_low"]    = adj_lows
    df["ca_adjusted"] = ca_flags

    # adj_prev_close = adj_close[T-1] per symbol — used for pct_chg in _compute_day,
    # and for True Range in equity_technicals.py (needs yesterday's adjusted close
    # on the SAME adjustment basis as today's adj_high/adj_low, or a stock with a
    # split between t-1 and t would show a fake multi-hundred-percent "gap").
    df["adj_prev_close"] = df.groupby("symbol")["adj_close"].shift(1)

    return df


# ── Core breadth engine ───────────────────────────────────────────────────────

class CashMarketBreadthEngine:
    """
    Computes daily price-based market breadth across the NSE EQ universe.

    Usage
    -----
    engine = CashMarketBreadthEngine()
    cm_breadth = engine.build_cm_breadth(cm_parquet_path, output_path)
    # Returns a DataFrame indexed by date with all breadth columns.
    """

    def __init__(self) -> None:
        self._cm: Optional[pd.DataFrame] = None     # adjusted CM prices (lazy loaded)
        self._dma_cache: dict = {}                   # precomputed rolling DMAs

    # ── Public API ────────────────────────────────────────────────────────────

    def build_cm_breadth(
        self,
        cm_parquet: str = _DEFAULT_CM_PARQUET,
        output_path: str = _DEFAULT_OUTPUT,
    ) -> pd.DataFrame:
        """
        Full pipeline: load → adjust → compute breadth → persist.
        Returns the breadth DataFrame (one row per trading date).
        """
        print("[CashMarketBreadth] Loading cash market prices...")
        self._load_and_adjust(cm_parquet)

        print("[CashMarketBreadth] Computing DMA participation...")
        self._precompute_dmas()

        print("[CashMarketBreadth] Building daily breadth rows...")
        rows = []
        dates = sorted(self._cm["date"].unique())

        # Anchor state for cumulative metrics
        ad_line_cumulative = 0.0
        mcclellan_fast_ema = None   # EMA19 of net_advances
        mcclellan_slow_ema = None   # EMA39 of net_advances
        k_fast = 2 / (_MCL_FAST + 1)
        k_slow = 2 / (_MCL_SLOW + 1)

        for dt in dates:
            row = self._compute_day(dt)

            # A/D Line (cumulative, anchored at 0 on first date)
            net_adv = row["cm_net_advances"]
            ad_line_cumulative += net_adv
            row["cm_ad_line"] = round(ad_line_cumulative, 0)

            # McClellan Oscillator EMAs
            if mcclellan_fast_ema is None:
                mcclellan_fast_ema = float(net_adv)
                mcclellan_slow_ema = float(net_adv)
            else:
                mcclellan_fast_ema = net_adv * k_fast + mcclellan_fast_ema * (1 - k_fast)
                mcclellan_slow_ema = net_adv * k_slow + mcclellan_slow_ema * (1 - k_slow)
            row["cm_mcclellan_osc"] = round(mcclellan_fast_ema - mcclellan_slow_ema, 2)

            rows.append(row)

        breadth_df = pd.DataFrame(rows)
        breadth_df = breadth_df.sort_values("date").reset_index(drop=True)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        breadth_df.to_parquet(output_path, index=False)
        print(f"[CashMarketBreadth] Saved {len(breadth_df)} rows → {output_path}")
        return breadth_df

    def build_cm_breadth_by_tier(
        self,
        cm_parquet: str = _DEFAULT_CM_PARQUET,
        output_path: str = _DEFAULT_TIER_OUTPUT,
    ) -> pd.DataFrame:
        """
        Same breadth math as build_cm_breadth(), but grouped by market-cap
        tier (large/mid/small/micro, each a real NSE index cohort — see
        cap_tier_universe.py) instead of blended across the whole universe —
        reveals whether DMA/RSI/NH-NL strength is broad or concentrated in a
        handful of index-heavy names. Symbols outside all 4 index lists are
        excluded from this breakdown, not folded into a catch-all bucket.

        Reuses this engine's own _pct_above_dma/_count_new_highs_lows on a
        tier-filtered symbol subset (rather than reimplementing them), plus
        equity_technicals.py's _compute_cmf for money-flow buckets. Emits one
        row per (date, tier); does not touch or replace the blended
        build_cm_breadth() output.
        """
        if self._cm is None:
            print("[CashMarketBreadth] Loading cash market prices...")
            self._load_and_adjust(cm_parquet)
        if not self._dma_cache:
            print("[CashMarketBreadth] Computing DMA participation...")
            self._precompute_dmas()

        # Local import: equity_technicals.py imports CashMarketBreadthEngine
        # from this module, so importing it back at module level would be
        # circular. Also avoids paying that import's cost for callers who
        # never touch tiered breadth.
        from vanguard.engines.equity_technicals import _compute_cmf
        from vanguard.pipeline.context.cap_tier_universe import get_symbol_tier_map

        print("[CashMarketBreadth] Fetching cap-tier symbol map...")
        all_symbols = sorted(self._cm["symbol"].unique().tolist())
        tier_map = get_symbol_tier_map(all_symbols)

        print("[CashMarketBreadth] Computing money-flow (CMF) table...")
        high_pivot = self._cm.pivot_table(index="date", columns="symbol", values="adj_high", aggfunc="last")
        low_pivot = self._cm.pivot_table(index="date", columns="symbol", values="adj_low", aggfunc="last")
        close_pivot = self._cm.pivot_table(index="date", columns="symbol", values="adj_close", aggfunc="last")
        vol_pivot = self._cm.pivot_table(index="date", columns="symbol", values="volume", aggfunc="last")
        cmf_table = _compute_cmf(high_pivot, low_pivot, close_pivot, vol_pivot, _CMF_WINDOW)

        print("[CashMarketBreadth] Building per-tier daily breadth rows...")
        rows = []
        dates = sorted(self._cm["date"].unique())
        for dt in dates:
            date_str = pd.Timestamp(dt).strftime("%Y-%m-%d")
            day_slice = self._cm[self._cm["date"] == dt]
            if day_slice.empty:
                for tier in _TIERS:
                    rows.append(self._empty_tier_row(date_str, tier))
                continue

            closes_today = day_slice.set_index("symbol")["adj_close"]
            syms_by_tier: dict[str, list] = {tier: [] for tier in _TIERS}
            for sym in day_slice["symbol"]:
                # Symbols outside all 4 NSE index lists (illiquid/unclassified
                # tail — ~1,700 of ~2,459 valid symbols) are excluded from the
                # tier breakdown entirely rather than dumped into a catch-all
                # bucket — see cap_tier_universe.py's 2026-08-14 docstring note.
                tier = tier_map.get(sym)
                if tier in syms_by_tier:
                    syms_by_tier[tier].append(sym)

            for tier in _TIERS:
                tier_syms = syms_by_tier[tier]
                if not tier_syms:
                    rows.append(self._empty_tier_row(date_str, tier))
                    continue
                rsi_counts = self._compute_rsi_quartile_counts(dt, tier_syms)
                cmf_counts = self._compute_cmf_bucket_counts(dt, tier_syms, cmf_table)
                new_highs, new_lows = self._count_new_highs_lows(dt, tier_syms, closes_today)
                rows.append({
                    "date":               date_str,
                    "tier":               tier,
                    "n_stocks":           len(tier_syms),
                    "pct_above_20dma":    self._pct_above_dma(dt, tier_syms, closes_today, _DMA_SHORT),
                    "pct_above_50dma":    self._pct_above_dma(dt, tier_syms, closes_today, _DMA_MID),
                    "pct_above_200dma":   self._pct_above_dma(dt, tier_syms, closes_today, _DMA_LONG),
                    "rsi_oversold_n":     rsi_counts["oversold"],
                    "rsi_neutral_low_n":  rsi_counts["neutral_low"],
                    "rsi_neutral_high_n": rsi_counts["neutral_high"],
                    "rsi_overbought_n":   rsi_counts["overbought"],
                    "cmf_strong_pos_n":   cmf_counts["strong_pos"],
                    "cmf_pos_n":          cmf_counts["pos"],
                    "cmf_neg_n":          cmf_counts["neg"],
                    "cmf_strong_neg_n":   cmf_counts["strong_neg"],
                    "new_highs":          new_highs,
                    "new_lows":           new_lows,
                })

        tier_df = pd.DataFrame(rows).sort_values(["date", "tier"]).reset_index(drop=True)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        tier_df.to_parquet(output_path, index=False)
        print(f"[CashMarketBreadth] Saved {len(tier_df)} rows → {output_path}")
        return tier_df

    def compute_single_day(self, date_str: str, cm_parquet: str = _DEFAULT_CM_PARQUET) -> dict:
        """
        Compute breadth for a single date only (used by incremental compiler).
        Returns a dict (same schema as one row from build_cm_breadth).
        NOTE: DMAs still require the full history — load it but only emit one date.
        """
        if self._cm is None:
            self._load_and_adjust(cm_parquet)
            self._precompute_dmas()
        row = self._compute_day(date_str)
        # Cumulative fields (A/D line, McClellan) cannot be computed in isolation
        # without the prior state — caller is responsible for threading these through.
        row["cm_ad_line"]       = None
        row["cm_mcclellan_osc"] = None
        return row

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _load_and_adjust(self, cm_parquet: str) -> None:
        cm = pd.read_parquet(cm_parquet)
        cm["date"] = pd.to_datetime(cm["date"]).dt.normalize()

        # EQ series only (already filtered in cash_market_builder but be defensive)
        if "series" in cm.columns:
            cm = cm[cm["series"].astype(str).str.strip().eq("EQ")].copy()

        cm = _build_adjusted_close(cm)
        self._cm = cm.sort_values(["symbol", "date"]).reset_index(drop=True)

    def _precompute_dmas(self) -> None:
        """
        Compute rolling DMAs and RSI on adj_close for each symbol, pivoted into
        wide DataFrames keyed by (symbol, date) for fast daily lookups.
        """
        pivot = self._cm.pivot_table(
            index="date", columns="symbol", values="adj_close", aggfunc="last"
        )
        self._dma_cache = {
            _DMA_SHORT: pivot.rolling(_DMA_SHORT, min_periods=_DMA_SHORT).mean(),
            _DMA_MID:   pivot.rolling(_DMA_MID,   min_periods=_DMA_MID).mean(),
            _DMA_LONG:  pivot.rolling(_DMA_LONG,   min_periods=_DMA_LONG).mean(),
        }
        # 52-week high/low: min_periods=90 enforces a minimum 90-day baseline to prevent
        # early-window lookback noise, while still allowing metrics to show in our 246-day dataset.
        self._dma_cache["52w_high"] = pivot.rolling(252, min_periods=90).max()
        self._dma_cache["52w_low"]  = pivot.rolling(252, min_periods=90).min()

        # 14-period Wilder's RSI computed on the same pivot
        delta = pivot.diff()
        gain  = delta.clip(lower=0)
        loss  = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1/_RSI_PERIOD, min_periods=_RSI_PERIOD, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/_RSI_PERIOD, min_periods=_RSI_PERIOD, adjust=False).mean()
        rs  = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        # 0/0 (flat price, no movement) -> NaN; map to neutral 50.
        # All-gains (avg_loss==0) already resolves to 100 via inf division, no special-case needed.
        rsi = rsi.mask((avg_gain == 0) & (avg_loss == 0), 50.0)
        self._dma_cache["rsi14"] = rsi

    def _compute_day(self, date_str: str) -> dict:
        """
        Compute all breadth metrics for a single trading date.
        Returns a flat dict (one row of the breadth table).
        """
        dt = pd.Timestamp(date_str)
        day_slice = self._cm[self._cm["date"] == dt].copy()

        if day_slice.empty:
            return self._empty_row(date_str)

        # ── Basic price change (both numerator and denominator on adj scale) ──
        day_slice = day_slice.copy()
        day_slice["pct_chg"] = (
            (day_slice["adj_close"] - day_slice["adj_prev_close"]) / day_slice["adj_prev_close"]
        ).replace([np.inf, -np.inf], np.nan)

        valid = day_slice.dropna(subset=["pct_chg", "adj_close"])
        total = len(valid)
        if total == 0:
            return self._empty_row(date_str)

        advances  = int((valid["pct_chg"] > 0).sum())
        declines  = int((valid["pct_chg"] < 0).sum())
        unchanged = int((valid["pct_chg"] == 0).sum())
        net_adv   = advances - declines
        ad_ratio  = round(advances / max(declines, 1), 3)

        # ── Volume A/D ratio ──────────────────────────────────────────────────
        vol_adv = float(valid.loc[valid["pct_chg"] > 0, "volume"].sum())
        vol_dec = float(valid.loc[valid["pct_chg"] < 0, "volume"].sum())
        vol_ad_ratio = round(vol_adv / max(vol_dec, 1), 3)

        # ── Turnover concentration: top-20 % of total turnover ────────────────
        if "turnover" in valid.columns:
            total_turnover = float(valid["turnover"].sum())
            top20_turnover = float(valid.nlargest(20, "turnover")["turnover"].sum())
            turnover_top20_pct = round(top20_turnover / max(total_turnover, 1) * 100, 1)
        else:
            turnover_top20_pct = float("nan")

        # ── DMA participation ─────────────────────────────────────────────────
        syms = valid["symbol"].tolist()
        closes_today = valid.set_index("symbol")["adj_close"]

        pct_above_20  = self._pct_above_dma(dt, syms, closes_today, _DMA_SHORT)
        pct_above_50  = self._pct_above_dma(dt, syms, closes_today, _DMA_MID)
        pct_above_200 = self._pct_above_dma(dt, syms, closes_today, _DMA_LONG)

        # ── RSI participation ─────────────────────────────────────────────────
        pct_overbought_70, pct_oversold_30 = self._compute_rsi_breadth(dt, syms)

        # ── New highs / new lows ──────────────────────────────────────────────
        new_highs, new_lows = self._count_new_highs_lows(dt, syms, closes_today)
        
        # Guard against None values
        if new_highs is None or new_lows is None:
            nh_nl_ratio = None
        else:
            nh_nl_ratio = round(new_highs / max(new_lows, 1), 2)

        # Calculate lookback elapsed days and days remaining
        high_table = self._dma_cache.get("52w_high")
        elapsed_days = int((high_table.index <= dt).sum())
        days_remaining = max(0, 252 - elapsed_days)

        # ── Corporate action flag (how many adjusted today) ───────────────────
        ca_count = int(day_slice["ca_adjusted"].sum())

        return {
            "date":                  date_str,
            "cm_total_symbols":      total,
            "cm_advances":           advances,
            "cm_declines":           declines,
            "cm_unchanged":          unchanged,
            "cm_net_advances":       net_adv,
            "cm_ad_ratio":           ad_ratio,
            "cm_advance_pct":        round(advances / total * 100, 1),
            "cm_volume_ad_ratio":    vol_ad_ratio,
            "cm_pct_above_20dma":    pct_above_20,
            "cm_pct_above_50dma":    pct_above_50,
            "cm_pct_above_200dma":   pct_above_200,
            "cm_pct_overbought_70":  pct_overbought_70,
            "cm_pct_oversold_30":    pct_oversold_30,
            "cm_new_highs":          new_highs,
            "cm_new_lows":           new_lows,
            "cm_nh_nl_ratio":        nh_nl_ratio,
            "cm_days_remaining":     days_remaining,
            "cm_turnover_top20_pct": turnover_top20_pct,
            "cm_ca_count":           ca_count,   # transparency: how many CAs adjusted today
            # cumulative fields filled in by caller
            "cm_ad_line":            0.0,
            "cm_mcclellan_osc":      0.0,
        }

    def _pct_above_dma(
        self, dt: pd.Timestamp, syms: list, closes: pd.Series, window: int
    ) -> float:
        dma_table = self._dma_cache.get(window)
        if dma_table is None:
            return float("nan")
        if dt not in dma_table.index:
            return float("nan")
        dma_row = dma_table.loc[dt]
        above = 0
        valid_count = 0
        for sym in syms:
            dma_val = dma_row.get(sym, np.nan)
            if pd.isna(dma_val):
                continue
            valid_count += 1
            if closes.get(sym, np.nan) > dma_val:
                above += 1
        if valid_count == 0:
            return float("nan")
        return round(above / valid_count * 100, 1)

    def _compute_rsi_breadth(self, dt: pd.Timestamp, syms: list) -> tuple[float, float]:
        """
        Compute percentage of overbought (RSI > 70) and oversold (RSI < 30) symbols.
        """
        rsi_table = self._dma_cache.get("rsi14")
        if rsi_table is None:
            return float("nan"), float("nan")
        if dt not in rsi_table.index:
            return float("nan"), float("nan")
        rsi_row = rsi_table.loc[dt]
        overbought = 0
        oversold = 0
        valid_count = 0
        for sym in syms:
            rsi_val = rsi_row.get(sym, np.nan)
            if pd.isna(rsi_val):
                continue
            valid_count += 1
            if rsi_val > _RSI_OVERBOUGHT:
                overbought += 1
            elif rsi_val < _RSI_OVERSOLD:
                oversold += 1
        if valid_count == 0:
            return float("nan"), float("nan")
        return (
            round(overbought / valid_count * 100, 1),
            round(oversold / valid_count * 100, 1)
        )

    def _count_new_highs_lows(
        self, dt: pd.Timestamp, syms: list, closes: pd.Series
    ) -> tuple[Optional[int], Optional[int]]:
        high_table = self._dma_cache.get("52w_high")
        low_table  = self._dma_cache.get("52w_low")
        if high_table is None or low_table is None:
            return None, None
        if dt not in high_table.index:
            return None, None
        high_row = high_table.loc[dt]
        low_row  = low_table.loc[dt]
        new_highs = 0
        new_lows  = 0
        valid_count = 0
        for sym in syms:
            c = closes.get(sym, np.nan)
            h = high_row.get(sym, np.nan)
            l = low_row.get(sym, np.nan)
            if pd.isna(c) or pd.isna(h) or pd.isna(l):
                continue
            valid_count += 1
            if c >= h:
                new_highs += 1
            elif c <= l:
                new_lows += 1
        if valid_count == 0:
            return None, None
        return new_highs, new_lows

    def _compute_rsi_quartile_counts(self, dt: pd.Timestamp, syms: list) -> dict:
        """RSI14 split into 4 buckets (finer than the blended overbought/
        oversold %): <30 oversold, 30-50, 50-70, >70 overbought."""
        counts = {"oversold": 0, "neutral_low": 0, "neutral_high": 0, "overbought": 0}
        rsi_table = self._dma_cache.get("rsi14")
        if rsi_table is None or dt not in rsi_table.index:
            return counts
        rsi_row = rsi_table.loc[dt]
        for sym in syms:
            v = rsi_row.get(sym, np.nan)
            if pd.isna(v):
                continue
            if v < _RSI_OVERSOLD:
                counts["oversold"] += 1
            elif v < 50:
                counts["neutral_low"] += 1
            elif v < _RSI_OVERBOUGHT:
                counts["neutral_high"] += 1
            else:
                counts["overbought"] += 1
        return counts

    @staticmethod
    def _compute_cmf_bucket_counts(dt: pd.Timestamp, syms: list, cmf_table: pd.DataFrame) -> dict:
        """Chaikin Money Flow split into 4 buckets: strong distribution
        (<-0.25), distribution (-0.25 to 0), accumulation (0 to 0.25), strong
        accumulation (>0.25)."""
        counts = {"strong_pos": 0, "pos": 0, "neg": 0, "strong_neg": 0}
        if dt not in cmf_table.index:
            return counts
        cmf_row = cmf_table.loc[dt]
        for sym in syms:
            v = cmf_row.get(sym, np.nan)
            if pd.isna(v):
                continue
            if v > 0.25:
                counts["strong_pos"] += 1
            elif v > 0:
                counts["pos"] += 1
            elif v > -0.25:
                counts["neg"] += 1
            else:
                counts["strong_neg"] += 1
        return counts

    @staticmethod
    def _empty_tier_row(date_str: str, tier: str) -> dict:
        return {
            "date": date_str, "tier": tier, "n_stocks": 0,
            "pct_above_20dma": float("nan"), "pct_above_50dma": float("nan"),
            "pct_above_200dma": float("nan"),
            "rsi_oversold_n": 0, "rsi_neutral_low_n": 0,
            "rsi_neutral_high_n": 0, "rsi_overbought_n": 0,
            "cmf_strong_pos_n": 0, "cmf_pos_n": 0,
            "cmf_neg_n": 0, "cmf_strong_neg_n": 0,
            "new_highs": None, "new_lows": None,
        }

    @staticmethod
    def _empty_row(date_str: str) -> dict:
        return {
            "date": date_str,
            "cm_total_symbols": 0,
            "cm_advances": 0, "cm_declines": 0, "cm_unchanged": 0,
            "cm_net_advances": 0, "cm_ad_ratio": 1.0, "cm_advance_pct": 0.0,
            "cm_volume_ad_ratio": 1.0,
            "cm_pct_above_20dma": float("nan"), "cm_pct_above_50dma": float("nan"),
            "cm_pct_above_200dma": float("nan"),
            "cm_pct_overbought_70": float("nan"),
            "cm_pct_oversold_30": float("nan"),
            "cm_new_highs": None, "cm_new_lows": None, "cm_nh_nl_ratio": None,
            "cm_days_remaining": 252,
            "cm_turnover_top20_pct": float("nan"),
            "cm_ca_count": 0,
            "cm_ad_line": 0.0, "cm_mcclellan_osc": 0.0,
        }
