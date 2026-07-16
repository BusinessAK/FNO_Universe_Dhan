#!/usr/bin/env python3
"""
Stock swing backtester for Vanguard setup signals.

FO positioning is treated as a signal source; the tested instrument is the
stock. When cash-market OHLC data is available, entries use the next session
cash open, exits use cash closes, and stops are checked against intraperiod lows.
"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from typing import Iterable

import duckdb
import numpy as np
import pandas as pd


INDEX_SYMBOLS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"}
DEFAULT_HOLDING_PERIODS = (3, 5, 10, 15)
DEFAULT_COST_BPS = 20.0
DEFAULT_STOP_LOSS_PCT = 7.0
MIN_TRADES_FOR_REPORTING = 10
DEFAULT_PRICE_DATA_PATH = "data/compiled/cash_market_prices.parquet"


@dataclass(frozen=True)
class BacktestConfig:
    db_path: str = "data/compiled/vanguard.duckdb"
    output_dir: str = "data/research"
    price_data_path: str = DEFAULT_PRICE_DATA_PATH
    use_cash_ohlc: bool = True
    use_trend_filter: bool = True
    holding_periods: tuple[int, ...] = DEFAULT_HOLDING_PERIODS
    cost_bps: float = DEFAULT_COST_BPS
    stop_loss_pct: float = DEFAULT_STOP_LOSS_PCT
    min_trades: int = MIN_TRADES_FOR_REPORTING
    start_date: str | None = None
    end_date: str | None = None


def load_research_frame(db_path: str, holding_periods: Iterable[int] = DEFAULT_HOLDING_PERIODS) -> pd.DataFrame:
    """Load one row per stock/setup/date with forward closes attached."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"DuckDB database not found: {db_path}")

    con = duckdb.connect(db_path, read_only=True)
    try:
        # ml_breakout_prob only exists on ML-enriched databases; COALESCE cannot
        # save a missing *column*, so probe the schema and substitute a literal.
        ms_cols = {
            r[0] for r in con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'daily_market_structure'"
            ).fetchall()
        }
        ml_expr = (
            "COALESCE(s.ml_breakout_prob, 0.0)" if "ml_breakout_prob" in ms_cols else "0.0"
        )
        query = f"""
            SELECT
                s.symbol,
                s.sector,
                s.date,
                s.spot_close,
                s.spot_change_pct,
                s.futures_oi,
                s.futures_oi_chg,
                s.pcr,
                s.net_inv_shift,
                s.ifs_score,
                s.smart_money_persistence,
                s.conviction_score,
                s.priority_score,
                s.structural_bias,
                s.regime_transition,
                s.call_wall,
                s.put_wall,
                s.gamma_flip,
                s.gex,
                s.gex_intensity,
                s.gex_shift,
                s.gamma_regime,
                s.iv,
                s.iv_shift,
                s.suggested_strategy,
                {ml_expr} AS ml_breakout_prob,
                st.setup_type,
                st.bias,
                st.trigger_strike,
                st.invalidation_strike,
                st.expected_behavior,
                st.dealer_behavior,
                b.bullish_pct AS market_bullish_pct,
                b.bearish_pct AS market_bearish_pct,
                b.expansion_pct AS market_expansion_pct,
                b.compression_pct AS market_compression_pct,
                b.macro_regime_prob
            FROM daily_setups st
            JOIN daily_market_structure s
              ON s.symbol = st.symbol AND s.date = st.date
            LEFT JOIN daily_market_breadth b
              ON b.date = st.date
            WHERE st.setup_type != 'NONE'
        """
        df = con.execute(query).df()
    finally:
        con.close()

    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["symbol", "date", "setup_type"]).reset_index(drop=True)
    return attach_forward_closes(df, holding_periods)


def load_cash_price_data(path: str = DEFAULT_PRICE_DATA_PATH) -> pd.DataFrame:
    """Load normalized cash OHLCV data if it has been built."""
    if not path or not os.path.exists(path):
        return pd.DataFrame()

    prices = pd.read_parquet(path)
    required = {"symbol", "date", "open", "high", "low", "close"}
    missing = required - set(prices.columns)
    if missing:
        raise ValueError(f"Cash price data missing columns: {sorted(missing)}")

    prices = prices.copy()
    prices["date"] = pd.to_datetime(prices["date"])
    prices["symbol"] = prices["symbol"].astype(str).str.upper().str.strip()
    for col in ["open", "high", "low", "close"]:
        prices[col] = pd.to_numeric(prices[col], errors="coerce")
    prices = prices.dropna(subset=["symbol", "date", "open", "high", "low", "close"])
    prices = prices.sort_values(["symbol", "date"]).drop_duplicates(["symbol", "date"], keep="last")
    return prices


def load_index_trend_data(db_path: str, index_symbol: str = "NIFTY") -> pd.DataFrame:
    """Load index close and 20-session return for relative strength."""
    if not os.path.exists(db_path):
        return pd.DataFrame(columns=["date", "market_ret_20"])

    con = duckdb.connect(db_path, read_only=True)
    try:
        index_df = con.execute(
            """
            SELECT date, spot_close
            FROM daily_market_structure
            WHERE symbol = ?
            ORDER BY date
            """,
            [index_symbol],
        ).df()
    finally:
        con.close()

    if index_df.empty:
        return pd.DataFrame(columns=["date", "market_ret_20"])

    index_df["date"] = pd.to_datetime(index_df["date"])
    index_df["spot_close"] = pd.to_numeric(index_df["spot_close"], errors="coerce")
    index_df["market_ret_20"] = index_df["spot_close"].pct_change(20) * 100.0
    return index_df[["date", "market_ret_20"]]


def build_trend_features(cash_prices: pd.DataFrame, db_path: str) -> pd.DataFrame:
    """Build stock trend and relative-strength features by symbol/date."""
    if cash_prices.empty:
        return pd.DataFrame()

    prices = cash_prices[["symbol", "date", "close", "volume"]].copy()
    prices = prices.sort_values(["symbol", "date"])
    grouped = prices.groupby("symbol", group_keys=False)

    prices["trend_sma20"] = grouped["close"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    prices["trend_sma50"] = grouped["close"].transform(lambda s: s.rolling(50, min_periods=50).mean())
    prices["trend_ret20_pct"] = grouped["close"].transform(lambda s: s.pct_change(20) * 100.0)
    prices["trend_ret50_pct"] = grouped["close"].transform(lambda s: s.pct_change(50) * 100.0)
    prices["trend_vol20"] = grouped["volume"].transform(lambda s: s.rolling(20, min_periods=20).mean())

    market = load_index_trend_data(db_path)
    prices = prices.merge(market, on="date", how="left")
    prices["trend_rs20_pct"] = prices["trend_ret20_pct"] - prices["market_ret_20"]

    prices["trend_above_sma20"] = prices["close"] > prices["trend_sma20"]
    prices["trend_sma20_above_sma50"] = prices["trend_sma20"] > prices["trend_sma50"]
    prices["trend_ret20_positive"] = prices["trend_ret20_pct"] > 0
    prices["trend_rs20_positive"] = prices["trend_rs20_pct"] > 0
    prices["trend_pass"] = (
        prices["trend_above_sma20"]
        & prices["trend_sma20_above_sma50"]
        & prices["trend_ret20_positive"]
        & prices["trend_rs20_positive"]
    )
    # Mirror-image downtrend gate for short candidates
    prices["trend_pass_short"] = (
        (prices["close"] < prices["trend_sma20"])
        & (prices["trend_sma20"] < prices["trend_sma50"])
        & (prices["trend_ret20_pct"] < 0)
        & (prices["trend_rs20_pct"] < 0)
    )

    return prices[[
        "symbol", "date", "trend_sma20", "trend_sma50", "trend_ret20_pct",
        "trend_ret50_pct", "trend_rs20_pct", "trend_vol20", "trend_above_sma20",
        "trend_sma20_above_sma50", "trend_ret20_positive", "trend_rs20_positive",
        "trend_pass", "trend_pass_short",
    ]]


def attach_trend_features(signals: pd.DataFrame, cash_prices: pd.DataFrame, db_path: str) -> pd.DataFrame:
    """Merge trend features into signal rows on symbol/date."""
    if signals.empty or cash_prices.empty:
        return signals
    trend = build_trend_features(cash_prices, db_path)
    if trend.empty:
        return signals
    out = signals.copy()
    out["date"] = pd.to_datetime(out["date"])
    return out.merge(trend, on=["symbol", "date"], how="left")


def attach_forward_closes(signal_df: pd.DataFrame, holding_periods: Iterable[int] = DEFAULT_HOLDING_PERIODS) -> pd.DataFrame:
    """Attach next-close entry and future close columns per symbol/date."""
    base_cols = ["symbol", "date", "spot_close"]
    close_df = (
        signal_df[base_cols]
        .drop_duplicates(["symbol", "date"])
        .sort_values(["symbol", "date"])
        .copy()
    )

    grouped = close_df.groupby("symbol", group_keys=False)
    close_df["entry_date"] = grouped["date"].shift(-1)
    close_df["entry_close"] = grouped["spot_close"].shift(-1)

    for hold in holding_periods:
        close_df[f"exit_date_{hold}d"] = grouped["date"].shift(-(hold + 1))
        close_df[f"exit_close_{hold}d"] = grouped["spot_close"].shift(-(hold + 1))

    return signal_df.merge(close_df.drop(columns=["spot_close"]), on=["symbol", "date"], how="left")


def classify_long_candidate(row: pd.Series) -> bool:
    """Cash-equity long filter from setup text, flow, and dealer context."""
    symbol = str(row.get("symbol", ""))
    if symbol in INDEX_SYMBOLS:
        return False

    bias = str(row.get("bias", ""))
    behavior = str(row.get("expected_behavior", ""))
    strategy = str(row.get("suggested_strategy", ""))
    setup = str(row.get("setup_type", ""))

    bearish_text = f"{bias} {behavior} {strategy}".lower()
    if any(term in bearish_text for term in ["bearish", "bear call", "bear put", "downside"]):
        return False

    bullish_terms = ["bullish", "support", "breakout", "accumulation", "floor rise"]
    text_is_bullish = any(term in bearish_text for term in bullish_terms)

    if setup in {"FLOOR_BOUNCE", "GAMMA_SQUEEZE"} and float(row.get("ifs_score") or 0.0) >= 0:
        return True
    if setup in {"INVENTORY_MIGRATION", "REGIME_SHIFT", "IV_SKEW_ACCUMULATION"} and text_is_bullish:
        return True
    if setup == "PINCH_ZONE" and float(row.get("ifs_score") or 0.0) > 15:
        return True

    return text_is_bullish and float(row.get("ifs_score") or 0.0) > 10


def classify_short_candidate(row: pd.Series) -> bool:
    """Cash-equity short filter — mirror image of the long filter."""
    symbol = str(row.get("symbol", ""))
    if symbol in INDEX_SYMBOLS:
        return False

    bias = str(row.get("bias", ""))
    behavior = str(row.get("expected_behavior", ""))
    strategy = str(row.get("suggested_strategy", ""))
    setup = str(row.get("setup_type", ""))

    text = f"{bias} {behavior} {strategy}".lower()
    if any(term in text for term in ["bullish", "bull call", "bull put", "upside", "support floor rise"]):
        return False

    bearish_terms = ["bearish", "breakdown", "collapse", "downside", "ceiling drop"]
    text_is_bearish = any(term in text for term in bearish_terms)

    if setup in {"INVENTORY_MIGRATION", "REGIME_SHIFT", "IV_SKEW_ACCUMULATION"} and text_is_bearish:
        return True
    if setup == "PINCH_ZONE" and float(row.get("ifs_score") or 0.0) < -15:
        return True

    return text_is_bearish and float(row.get("ifs_score") or 0.0) < -10


def compute_alpha_score(row: pd.Series) -> float:
    """Heuristic score used for candidate ranking; expectancy validates it later."""
    ifs = float(row.get("ifs_score") or 0.0)
    conviction = float(row.get("conviction_score") or 0.0)
    persistence = float(row.get("smart_money_persistence") or 0.0)
    macro = float(row.get("macro_regime_prob") or 0.0)
    futures_oi_chg = float(row.get("futures_oi_chg") or 0.0)
    net_inv = float(row.get("net_inv_shift") or 0.0)
    spot_change = float(row.get("spot_change_pct") or 0.0)
    ml_prob = float(row.get("ml_breakout_prob") or 0.0)

    trend_score = min(25.0, max(0.0, spot_change) * 6.0)
    flow_score = min(25.0, max(0.0, ifs) * 0.35 + max(0.0, net_inv) / 250000.0)
    oi_score = 10.0 if futures_oi_chg > 0 else 0.0
    quality_score = min(20.0, conviction * 0.12 + persistence * 0.08 + ml_prob * 0.04)
    regime_score = min(15.0, macro * 0.15)

    raw = trend_score + flow_score + oi_score + quality_score + regime_score
    return round(max(0.0, min(100.0, raw)), 2)


def simulate_trades(df: pd.DataFrame, config: BacktestConfig) -> pd.DataFrame:
    """Create one simulated stock trade for each long candidate and holding period."""
    if df.empty:
        return pd.DataFrame()

    work = df.copy()
    if config.start_date:
        work = work[work["date"] >= pd.to_datetime(config.start_date)]
    if config.end_date:
        work = work[work["date"] <= pd.to_datetime(config.end_date)]

    work["long_candidate"] = work.apply(classify_long_candidate, axis=1)
    work["short_candidate"] = work.apply(classify_short_candidate, axis=1) & ~work["long_candidate"]
    work["alpha_score"] = work.apply(compute_alpha_score, axis=1)
    work = work[work["long_candidate"] | work["short_candidate"]].copy()
    work["direction"] = np.where(work["long_candidate"], "LONG", "SHORT")

    cash_prices = load_cash_price_data(config.price_data_path) if config.use_cash_ohlc else pd.DataFrame()
    if not cash_prices.empty and config.use_trend_filter:
        work = attach_trend_features(work, cash_prices, config.db_path)
        long_ok = (work["direction"] == "LONG") & work["trend_pass"].fillna(False)
        short_ok = (work["direction"] == "SHORT") & work["trend_pass_short"].fillna(False)
        work = work[long_ok | short_ok].copy()

    if not cash_prices.empty:
        return simulate_trades_with_cash_ohlc(work, cash_prices, config)

    rows = []
    cost_pct = config.cost_bps / 10000.0

    for _, row in work.iterrows():
        entry = float(row.get("entry_close") or np.nan)
        if not np.isfinite(entry) or entry <= 0:
            continue

        direction = str(row.get("direction", "LONG"))
        is_long = direction == "LONG"
        invalidation = float(row.get("invalidation_strike") or 0.0)
        if is_long:
            pct_stop = entry * (1.0 - config.stop_loss_pct / 100.0)
            stop_level = max(invalidation, pct_stop) if 0 < invalidation < entry else pct_stop
        else:
            pct_stop = entry * (1.0 + config.stop_loss_pct / 100.0)
            stop_level = min(invalidation, pct_stop) if invalidation > entry else pct_stop

        for hold in config.holding_periods:
            exit_close = float(row.get(f"exit_close_{hold}d") or np.nan)
            if not np.isfinite(exit_close) or exit_close <= 0:
                continue

            stopped = exit_close <= stop_level if is_long else exit_close >= stop_level
            effective_exit = stop_level if stopped else exit_close
            price_move = (effective_exit / entry) - 1.0
            gross_return = price_move if is_long else -price_move
            net_return = gross_return - cost_pct

            rows.append({
                "symbol": row["symbol"],
                "sector": row["sector"],
                "direction": direction,
                "signal_date": row["date"].date().isoformat(),
                "entry_date": pd.to_datetime(row["entry_date"]).date().isoformat(),
                "exit_date": pd.to_datetime(row[f"exit_date_{hold}d"]).date().isoformat(),
                "holding_days": hold,
                "setup_type": row["setup_type"],
                "bias": row["bias"],
                "entry_close": round(entry, 4),
                "exit_close": round(effective_exit, 4),
                "raw_exit_close": round(exit_close, 4),
                "stop_level": round(stop_level, 4),
                "stopped": bool(stopped),
                "net_return_pct": round(net_return * 100.0, 4),
                "gross_return_pct": round(gross_return * 100.0, 4),
                "alpha_score": row["alpha_score"],
                "ifs_score": row["ifs_score"],
                "conviction_score": row["conviction_score"],
                "priority_score": row["priority_score"],
                "macro_regime_prob": row["macro_regime_prob"],
                "gamma_regime": row["gamma_regime"],
                "structural_bias": row["structural_bias"],
                "suggested_strategy": row["suggested_strategy"],
                "trend_pass": bool(row.get("trend_pass", False)),
                "trend_ret20_pct": row.get("trend_ret20_pct", np.nan),
                "trend_rs20_pct": row.get("trend_rs20_pct", np.nan),
            })

    return pd.DataFrame(rows)


def simulate_trades_with_cash_ohlc(
    candidates: pd.DataFrame,
    cash_prices: pd.DataFrame,
    config: BacktestConfig,
) -> pd.DataFrame:
    """
    Simulate long stock swings with next-session cash open entries, close exits,
    and intraperiod low-based stop checks.
    """
    rows = []
    cost_pct = config.cost_bps / 10000.0
    price_groups = {
        symbol: group.sort_values("date").reset_index(drop=True)
        for symbol, group in cash_prices.groupby("symbol", sort=False)
    }

    for _, row in candidates.iterrows():
        symbol = str(row["symbol"]).upper()
        prices = price_groups.get(symbol)
        if prices is None or prices.empty:
            continue

        signal_date = pd.to_datetime(row["date"])
        future = prices[prices["date"] > signal_date]
        if future.empty:
            continue

        entry_bar = future.iloc[0]
        entry = float(entry_bar["open"])
        if not np.isfinite(entry) or entry <= 0:
            continue

        direction = str(row.get("direction", "LONG"))
        is_long = direction == "LONG"
        invalidation = float(row.get("invalidation_strike") or 0.0)
        if is_long:
            pct_stop = entry * (1.0 - config.stop_loss_pct / 100.0)
            stop_level = max(invalidation, pct_stop) if 0 < invalidation < entry else pct_stop
        else:
            pct_stop = entry * (1.0 + config.stop_loss_pct / 100.0)
            stop_level = min(invalidation, pct_stop) if invalidation > entry else pct_stop

        for hold in config.holding_periods:
            window = future.head(hold)
            if len(window) < hold:
                continue

            stop_hits = window[window["low"] <= stop_level] if is_long \
                else window[window["high"] >= stop_level]
            if not stop_hits.empty:
                exit_bar = stop_hits.iloc[0]
                # Gap-through: a bar that opens through the stop fills at the open,
                # not at the stop price (otherwise a gap entry can book a
                # guaranteed-loss trade as a profitable stop-out).
                bar_open = float(exit_bar["open"])
                effective_exit = min(stop_level, bar_open) if is_long else max(stop_level, bar_open)
                raw_exit = float(exit_bar["close"])
                stopped = True
            else:
                exit_bar = window.iloc[-1]
                effective_exit = float(exit_bar["close"])
                raw_exit = effective_exit
                stopped = False

            price_move = (effective_exit / entry) - 1.0
            gross_return = price_move if is_long else -price_move
            net_return = gross_return - cost_pct
            up_move = ((float(window["high"].max()) / entry) - 1.0) * 100.0
            dn_move = ((float(window["low"].min()) / entry) - 1.0) * 100.0
            mfe_pct = up_move if is_long else -dn_move
            mae_pct = dn_move if is_long else -up_move

            rows.append({
                "symbol": row["symbol"],
                "sector": row["sector"],
                "direction": direction,
                "signal_date": signal_date.date().isoformat(),
                "entry_date": pd.to_datetime(entry_bar["date"]).date().isoformat(),
                "exit_date": pd.to_datetime(exit_bar["date"]).date().isoformat(),
                "holding_days": hold,
                "setup_type": row["setup_type"],
                "bias": row["bias"],
                "entry_close": round(entry, 4),
                "exit_close": round(effective_exit, 4),
                "raw_exit_close": round(raw_exit, 4),
                "stop_level": round(stop_level, 4),
                "stopped": bool(stopped),
                "net_return_pct": round(net_return * 100.0, 4),
                "gross_return_pct": round(gross_return * 100.0, 4),
                "mfe_pct": round(mfe_pct, 4),
                "mae_pct": round(mae_pct, 4),
                "alpha_score": row["alpha_score"],
                "ifs_score": row["ifs_score"],
                "conviction_score": row["conviction_score"],
                "priority_score": row["priority_score"],
                "macro_regime_prob": row["macro_regime_prob"],
                "gamma_regime": row["gamma_regime"],
                "structural_bias": row["structural_bias"],
                "suggested_strategy": row["suggested_strategy"],
                "price_source": "cash_ohlc",
                "trend_pass": bool(row.get("trend_pass", False)),
                "trend_ret20_pct": row.get("trend_ret20_pct", np.nan),
                "trend_rs20_pct": row.get("trend_rs20_pct", np.nan),
            })

    return pd.DataFrame(rows)


def summarize_trades(trades: pd.DataFrame, by: Iterable[str], min_trades: int) -> pd.DataFrame:
    """Aggregate expectancy stats for a chosen grouping."""
    if trades.empty:
        return pd.DataFrame()

    grouped = trades.groupby(list(by), dropna=False)
    summary = grouped["net_return_pct"].agg(
        trades="count",
        avg_return_pct="mean",
        median_return_pct="median",
        total_return_pct="sum",
        best_return_pct="max",
        worst_return_pct="min",
    ).reset_index()
    wins = grouped["net_return_pct"].apply(lambda s: (s > 0).mean() * 100.0).reset_index(name="win_rate_pct")
    stopped = grouped["stopped"].mean().mul(100.0).reset_index(name="stop_rate_pct")
    summary = summary.merge(wins, on=list(by)).merge(stopped, on=list(by))
    summary = summary[summary["trades"] >= min_trades].copy()
    if summary.empty:
        return summary

    summary["expectancy_rank"] = (
        summary["avg_return_pct"] * np.sqrt(summary["trades"]) * (summary["win_rate_pct"] / 100.0)
    )
    numeric_cols = [
        "avg_return_pct", "median_return_pct", "total_return_pct", "best_return_pct",
        "worst_return_pct", "win_rate_pct", "stop_rate_pct", "expectancy_rank"
    ]
    summary[numeric_cols] = summary[numeric_cols].round(3)
    return summary.sort_values(["expectancy_rank", "avg_return_pct"], ascending=False).reset_index(drop=True)


def add_diagnostic_buckets(trades: pd.DataFrame) -> pd.DataFrame:
    """Attach stable research buckets for conditional edge analysis."""
    if trades.empty:
        return trades

    out = trades.copy()
    out["alpha_score_bucket"] = pd.cut(
        out["alpha_score"],
        bins=[-0.01, 20, 40, 60, 80, 100],
        labels=["00-20", "20-40", "40-60", "60-80", "80-100"],
    )
    out["macro_regime_bucket"] = pd.cut(
        out["macro_regime_prob"].fillna(0.0),
        bins=[-0.01, 25, 50, 75, 100],
        labels=["macro_00_25", "macro_25_50", "macro_50_75", "macro_75_100"],
    )
    out["ifs_bucket"] = pd.cut(
        out["ifs_score"],
        bins=[-100, 0, 15, 30, 60, 100],
        labels=["ifs_le_0", "ifs_0_15", "ifs_15_30", "ifs_30_60", "ifs_60_100"],
    )
    if "trend_rs20_pct" in out.columns:
        out["rs20_bucket"] = pd.cut(
            out["trend_rs20_pct"],
            bins=[-100, -5, 0, 5, 10, 100],
            labels=["rs_lt_-5", "rs_-5_0", "rs_0_5", "rs_5_10", "rs_gt_10"],
        )
    return out


def write_markdown_report(
    config: BacktestConfig,
    trades: pd.DataFrame,
    setup_summary: pd.DataFrame,
    sector_summary: pd.DataFrame,
    alpha_summary: pd.DataFrame,
    output_path: str,
) -> None:
    """Write a compact research report for review."""
    stop_note = (
        "Entries use next-session cash open; stops are triggered when cash low breaches the stop."
        if config.use_cash_ohlc and os.path.exists(config.price_data_path)
        else "Stops are evaluated on the planned exit close in this first pass because cash OHLC data was unavailable."
    )
    lines = [
        "# Vanguard Stock Swing Backtest Report",
        "",
        "This is a stock swing validation using compiled Vanguard signals.",
        stop_note,
        "",
        "## Configuration",
        "",
        f"- Database: `{config.db_path}`",
        f"- Cash OHLC path: `{config.price_data_path}`",
        f"- Cash OHLC enabled: `{config.use_cash_ohlc}`",
        f"- Trend filter enabled: `{config.use_trend_filter}`",
        f"- Holding periods: `{', '.join(str(x) for x in config.holding_periods)}` sessions",
        f"- Round-trip cost/slippage: `{config.cost_bps:.1f}` bps",
        f"- Fallback stop loss: `{config.stop_loss_pct:.1f}%`",
        f"- Minimum trades per report row: `{config.min_trades}`",
        "",
        "## Overall",
        "",
    ]

    if trades.empty:
        lines.extend(["No long stock candidates were generated.", ""])
    else:
        lines.extend([
            f"- Simulated trades: `{len(trades):,}`",
            f"- Average net return: `{trades['net_return_pct'].mean():.3f}%`",
            f"- Median net return: `{trades['net_return_pct'].median():.3f}%`",
            f"- Win rate: `{(trades['net_return_pct'].gt(0).mean() * 100.0):.2f}%`",
            f"- Stop rate: `{(trades['stopped'].mean() * 100.0):.2f}%`",
            f"- Price source: `{trades.get('price_source', pd.Series(['fo_close_proxy'])).iloc[0] if not trades.empty and 'price_source' in trades.columns else 'fo_close_proxy'}`",
            "",
        ])

    lines.extend(["## Best Setup / Holding Period Buckets", ""])
    lines.append(_markdown_table(setup_summary.head(15)))
    lines.extend(["", "## Best Alpha Diagnostic Buckets", ""])
    lines.append(_markdown_table(alpha_summary.head(15)))
    lines.extend(["", "## Best Sector Buckets", ""])
    lines.append(_markdown_table(sector_summary.head(15)))
    lines.append("")

    with open(output_path, "w") as f:
        f.write("\n".join(lines))


def _markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_No rows met the minimum trade threshold._"
    return df.to_markdown(index=False)


def run_backtest(config: BacktestConfig) -> dict[str, str]:
    """Run the full backtest and write reports."""
    os.makedirs(config.output_dir, exist_ok=True)

    frame = load_research_frame(config.db_path, config.holding_periods)
    trades = add_diagnostic_buckets(simulate_trades(frame, config))

    setup_summary = summarize_trades(trades, ["direction", "setup_type", "holding_days"], config.min_trades)
    sector_summary = summarize_trades(trades, ["sector", "holding_days"], config.min_trades)
    symbol_summary = summarize_trades(trades, ["symbol", "holding_days"], config.min_trades)
    alpha_summary = summarize_trades(trades, ["setup_type", "alpha_score_bucket", "holding_days"], config.min_trades)
    macro_summary = summarize_trades(trades, ["macro_regime_bucket", "holding_days"], config.min_trades)
    trend_summary = (
        summarize_trades(trades, ["setup_type", "rs20_bucket", "holding_days"], config.min_trades)
        if "rs20_bucket" in trades.columns else pd.DataFrame()
    )

    paths = {
        "trades": os.path.join(config.output_dir, "swing_stock_trades.csv"),
        "setup_summary": os.path.join(config.output_dir, "swing_setup_expectancy.csv"),
        "sector_summary": os.path.join(config.output_dir, "swing_sector_expectancy.csv"),
        "symbol_summary": os.path.join(config.output_dir, "swing_symbol_expectancy.csv"),
        "alpha_summary": os.path.join(config.output_dir, "swing_alpha_diagnostics.csv"),
        "macro_summary": os.path.join(config.output_dir, "swing_macro_diagnostics.csv"),
        "trend_summary": os.path.join(config.output_dir, "swing_trend_diagnostics.csv"),
        "report": os.path.join(config.output_dir, "swing_backtest_report.md"),
    }

    trades.to_csv(paths["trades"], index=False)
    setup_summary.to_csv(paths["setup_summary"], index=False)
    sector_summary.to_csv(paths["sector_summary"], index=False)
    symbol_summary.to_csv(paths["symbol_summary"], index=False)
    alpha_summary.to_csv(paths["alpha_summary"], index=False)
    macro_summary.to_csv(paths["macro_summary"], index=False)
    trend_summary.to_csv(paths["trend_summary"], index=False)
    write_markdown_report(config, trades, setup_summary, sector_summary, alpha_summary, paths["report"])
    return paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest Vanguard stock swing setup candidates.")
    parser.add_argument("--db", default="data/compiled/vanguard.duckdb", help="Path to compiled Vanguard DuckDB.")
    parser.add_argument("--output-dir", default="data/research", help="Directory for CSV/Markdown outputs.")
    parser.add_argument("--price-data", default=DEFAULT_PRICE_DATA_PATH, help="Optional cash OHLC parquet path.")
    parser.add_argument("--no-cash-ohlc", action="store_true", help="Force FO close-proxy mode even if cash OHLC exists.")
    parser.add_argument("--no-trend-filter", action="store_true", help="Disable cash trend/relative-strength filter.")
    parser.add_argument("--holding-periods", default="3,5,10,15", help="Comma-separated holding periods in sessions.")
    parser.add_argument("--cost-bps", type=float, default=DEFAULT_COST_BPS, help="Round-trip cost/slippage in basis points.")
    parser.add_argument("--stop-loss-pct", type=float, default=DEFAULT_STOP_LOSS_PCT, help="Fallback close-to-close stop loss percent.")
    parser.add_argument("--min-trades", type=int, default=MIN_TRADES_FOR_REPORTING, help="Minimum trades for summary rows.")
    parser.add_argument("--start-date", default=None, help="Optional inclusive YYYY-MM-DD signal start date.")
    parser.add_argument("--end-date", default=None, help="Optional inclusive YYYY-MM-DD signal end date.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    holds = tuple(int(x.strip()) for x in args.holding_periods.split(",") if x.strip())
    config = BacktestConfig(
        db_path=args.db,
        output_dir=args.output_dir,
        price_data_path=args.price_data,
        use_cash_ohlc=not args.no_cash_ohlc,
        use_trend_filter=not args.no_trend_filter,
        holding_periods=holds,
        cost_bps=args.cost_bps,
        stop_loss_pct=args.stop_loss_pct,
        min_trades=args.min_trades,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    paths = run_backtest(config)
    print("[SUCCESS] Stock swing backtest complete.")
    for label, path in paths.items():
        print(f"{label}: {path}")


if __name__ == "__main__":
    main()
