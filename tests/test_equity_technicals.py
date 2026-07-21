"""
Unit tests for vanguard/engines/equity_technicals.py (Track B / E1).

PRD §8.1: golden tests against hand-built synthetic OHLCV, plus a
CA-adjustment/DMA/RSI reuse test that guards against equity_technicals'
per-symbol output ever silently drifting from CashMarketBreadthEngine's own
aggregate computation (same underlying pivot tables, by construction).
"""
import os
import tempfile

import numpy as np
import pandas as pd
import pytest

from vanguard.engines.cash_breadth import CashMarketBreadthEngine
from vanguard.engines.equity_technicals import build_equity_technicals


def _make_symbol(symbol: str, n: int, start_close: float, start_date: str,
                  daily_delta: float = 1.0, volume: float = 100_000.0,
                  vol_spike_from: int | None = None, vol_spike_to: float = 300_000.0,
                  delivery_pct: float = 50.0, delivery_spike_from: int | None = None,
                  delivery_spike_to: float = 80.0,
                  high_offset: float = 0.0, low_offset: float = 0.0) -> pd.DataFrame:
    """A clean (no corporate-action gaps) daily series: close[i] = start_close + i*daily_delta,
    prev_close[i] = close[i-1] exactly, open == prev_close (no overnight gap).
    high/low default to == close (degenerate, exercises the H==L guard);
    high_offset/low_offset add a constant spread for NATR/CMF tests."""
    dates = pd.date_range(start_date, periods=n, freq="D")
    closes = [start_close + i * daily_delta for i in range(n)]
    prev_closes = [np.nan] + closes[:-1]
    vols = [volume] * n
    if vol_spike_from is not None:
        for i in range(vol_spike_from, n):
            vols[i] = vol_spike_to
    dlv = [delivery_pct] * n
    if delivery_spike_from is not None:
        for i in range(delivery_spike_from, n):
            dlv[i] = delivery_spike_to
    deliverable_qty = [v * d / 100.0 for v, d in zip(vols, dlv)]
    highs = [c + high_offset for c in closes]
    lows = [c - low_offset for c in closes]
    return pd.DataFrame({
        "date": dates, "symbol": symbol, "series": "EQ",
        "open": [prev_closes[0] if i == 0 else prev_closes[i] for i in range(n)],
        "high": highs, "low": lows, "close": closes, "last": closes,
        "prev_close": prev_closes, "volume": vols, "turnover": [v * c for v, c in zip(vols, closes)],
        "trades": 100, "deliverable_qty": deliverable_qty, "delivery_pct": dlv,
    })


@pytest.fixture
def fixture_parquet(tmp_path):
    n = 30
    aaa = _make_symbol("AAA", n, start_close=100.0, start_date="2026-01-01",
                       daily_delta=1.0, vol_spike_from=20, delivery_spike_from=20)
    bbb = _make_symbol("BBB", n, start_close=50.0, start_date="2026-01-01", daily_delta=0.5)
    df = pd.concat([aaa, bbb], ignore_index=True)
    df.loc[0, "open"] = df.loc[0, "close"]  # first row has no prev_close; avoid NaN open
    path = tmp_path / "cm_prices.parquet"
    df.to_parquet(path, index=False)
    return str(path)


@pytest.fixture
def natr_cmf_fixture_parquet(tmp_path):
    """Flat close (no trend) with a constant high/low spread, so True Range
    and the Money Flow Multiplier converge to exact, hand-verifiable
    constants rather than needing a full independent recompute."""
    n = 20
    # CCC: close exactly at the midpoint of [low, high] every day -> MFM = 0.0
    ccc = _make_symbol("CCC", n, start_close=100.0, start_date="2026-01-01",
                       daily_delta=0.0, high_offset=2.0, low_offset=2.0)
    # DDD: close exactly at the high every day (low_offset=4 -> low sits below
    # close; high_offset=0 -> high == close) -> MFM = 1.0 (max)
    ddd = _make_symbol("DDD", n, start_close=100.0, start_date="2026-01-01",
                       daily_delta=0.0, high_offset=0.0, low_offset=4.0)
    df = pd.concat([ccc, ddd], ignore_index=True)
    df.loc[df.index[0], "open"] = df.loc[df.index[0], "close"]
    df.loc[df.index[n], "open"] = df.loc[df.index[n], "close"]  # DDD's first row
    path = tmp_path / "cm_prices_natr_cmf.parquet"
    df.to_parquet(path, index=False)
    return str(path)


def test_natr14_manual_calculation_flat_series(natr_cmf_fixture_parquet):
    """CCC: high=102, low=98, close=100 every day -> True Range = max(4, 2, 2)
    = 4 for every day after the first; Wilder's EMA of a constant series
    equals that constant exactly -> ATR14 = 4.0 -> NATR14 = 4/100*100 = 4.0."""
    out = build_equity_technicals(natr_cmf_fixture_parquet, output_path=None)
    ccc = out[out.symbol == "CCC"].sort_values("date").reset_index(drop=True)
    tail_natr = ccc.loc[14:, "natr14"]
    assert np.allclose(tail_natr, 4.0)


def test_cmf_zero_when_close_at_midpoint(natr_cmf_fixture_parquet):
    out = build_equity_technicals(natr_cmf_fixture_parquet, output_path=None)
    ccc = out[out.symbol == "CCC"].sort_values("date").reset_index(drop=True)
    assert ccc.loc[19, "money_flow_20d"] == pytest.approx(0.0, abs=1e-9)


def test_cmf_one_when_close_at_high(natr_cmf_fixture_parquet):
    out = build_equity_technicals(natr_cmf_fixture_parquet, output_path=None)
    ddd = out[out.symbol == "DDD"].sort_values("date").reset_index(drop=True)
    assert ddd.loc[19, "money_flow_20d"] == pytest.approx(1.0, abs=1e-9)


def test_circuit_lock_high_equals_low_gives_zero_not_nan_or_inf(fixture_parquet):
    """E-X6: the default fixture already has high == low == close (a full
    session's worth of circuit-lock-shaped days) for AAA/BBB — money_flow_20d
    must resolve to a finite number (the MFM=0.0 guard), never NaN/inf, for
    every one of those degenerate days once the window is full."""
    out = build_equity_technicals(fixture_parquet, output_path=None)
    for sym in ("AAA", "BBB"):
        mf = out[out.symbol == sym].sort_values("date").reset_index(drop=True)["money_flow_20d"]
        populated = mf.dropna()
        assert not populated.empty
        assert np.isfinite(populated).all()
        assert np.allclose(populated, 0.0)   # H==L every day -> MFM=0.0 every day -> CMF=0.0


def test_no_corporate_action_means_adj_close_equals_close(fixture_parquet):
    out = build_equity_technicals(fixture_parquet, output_path=None)
    aaa = out[out.symbol == "AAA"].sort_values("date").reset_index(drop=True)
    assert np.allclose(aaa["adj_close"], aaa["close"])


def test_dma20_manual_calculation(fixture_parquet):
    out = build_equity_technicals(fixture_parquet, output_path=None)
    aaa = out[out.symbol == "AAA"].sort_values("date").reset_index(drop=True)
    # day index 19 (20th row): DMA20 = mean(close[0:20]) = mean(100..119) = 109.5
    assert aaa.loc[19, "dma20"] == pytest.approx(109.5)
    # independent cross-check via plain rolling mean, not the implementation itself
    expected = aaa["close"].rolling(20, min_periods=20).mean()
    assert np.allclose(aaa["dma20"].dropna(), expected.dropna())


def test_roc_manual_calculation(fixture_parquet):
    out = build_equity_technicals(fixture_parquet, output_path=None)
    aaa = out[out.symbol == "AAA"].sort_values("date").reset_index(drop=True)
    # ROC_5d at index 24: (124/119 - 1) * 100
    assert aaa.loc[24, "roc_5d"] == pytest.approx((124 / 119 - 1) * 100, rel=1e-9)
    # ROC_20d at index 29 (last row): (129/109 - 1) * 100
    assert aaa.loc[29, "roc_20d"] == pytest.approx((129 / 109 - 1) * 100, rel=1e-9)


def test_rsi14_is_exactly_100_for_monotonic_increase(fixture_parquet):
    """Every day is a gain, never a loss -> avg_loss stays 0 for the life of the
    series -> RS = inf -> RSI = 100 exactly (matches cash_breadth.py's own
    documented behavior for the all-gains case, not a special-cased mock)."""
    out = build_equity_technicals(fixture_parquet, output_path=None)
    aaa = out[out.symbol == "AAA"].sort_values("date").reset_index(drop=True)
    tail_rsi = aaa.loc[20:, "rsi14"]
    assert (tail_rsi == 100.0).all()


def test_volume_ratio_reflects_spike(fixture_parquet):
    out = build_equity_technicals(fixture_parquet, output_path=None)
    aaa = out[out.symbol == "AAA"].sort_values("date").reset_index(drop=True)
    expected = aaa["volume"].rolling(20, min_periods=20).mean()
    ratio = aaa["volume"] / expected
    assert np.allclose(aaa["volume_ratio_20d"].dropna(), ratio.dropna())
    # last row: window is 10 days @100k + 10 days @300k -> mean 200k; today's 300k / 200k = 1.5 exactly
    assert aaa.loc[29, "volume_ratio_20d"] == pytest.approx(1.5)


def test_delivery_ratios_reflect_spike(fixture_parquet):
    out = build_equity_technicals(fixture_parquet, output_path=None)
    aaa = out[out.symbol == "AAA"].sort_values("date").reset_index(drop=True)
    assert aaa.loc[29, "delivery_pct_ratio_20d"] > 1.2
    assert aaa.loc[29, "deliverable_vol_ratio_20d"] > 1.5


def test_range_high_10d_is_trailing_10_session_high_of_adj_high(fixture_parquet):
    """2026-07-21 addition, feeding IMBALANCE_CONSOLIDATION's re-anchored
    trigger (see equity_playbook.py). AAA's high == close (high_offset=0
    default) and rises 1.0/day, so the trailing-10-session max of adj_high
    at any row >= index 9 is just that row's own close (monotonic series)."""
    out = build_equity_technicals(fixture_parquet, output_path=None)
    aaa = out[out.symbol == "AAA"].sort_values("date").reset_index(drop=True)
    assert aaa.loc[8, "range_high_10d"] != aaa.loc[8, "range_high_10d"]  # NaN, <10 sessions
    assert aaa.loc[9, "range_high_10d"] == pytest.approx(aaa.loc[9, "close"])
    assert aaa.loc[20, "range_high_10d"] == pytest.approx(aaa.loc[20, "close"])


def test_symbols_are_independent(fixture_parquet):
    out = build_equity_technicals(fixture_parquet, output_path=None)
    bbb = out[out.symbol == "BBB"].sort_values("date").reset_index(drop=True)
    # BBB never spikes volume/delivery -> ratios should stay near 1.0 throughout
    assert bbb.loc[29, "volume_ratio_20d"] == pytest.approx(1.0, abs=1e-6)


def test_short_history_leaves_dma200_and_52w_null(fixture_parquet):
    """E-X1: a symbol with <200/<90 sessions must not fabricate a DMA200 or
    52w high/low — they stay null until enough history accrues, and the row
    itself is NOT dropped (only adj_close-missing rows are dropped)."""
    out = build_equity_technicals(fixture_parquet, output_path=None)
    aaa = out[out.symbol == "AAA"]
    assert aaa["dma200"].isna().all()          # only 30 rows, need 200
    assert aaa["high_52w"].isna().all()         # only 30 rows, need 90 (min_periods)
    assert aaa["rsi14"].notna().any()           # but RSI14 (needs only 14) is populated
    assert len(aaa) == 30                       # rows not dropped just because DMA200 is null


def test_zero_average_volume_gives_nan_not_inf(fixture_parquet):
    """A stretch of zero volume must not produce inf/crash on the ratio."""
    df = pd.read_parquet(fixture_parquet)
    df.loc[(df.symbol == "AAA") & (df.index < 20), "volume"] = 0.0
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "zero_vol.parquet")
        df.to_parquet(p, index=False)
        out = build_equity_technicals(p, output_path=None)
    aaa = out[out.symbol == "AAA"].sort_values("date").reset_index(drop=True)
    assert not np.isinf(aaa["volume_ratio_20d"].dropna()).any()


def test_null_cm_delivery_columns_yield_no_delivery_ratios_without_delivery_df(fixture_parquet):
    """Reproduces the real 2026-07-21 finding: cash_market_prices.parquet's
    own delivery_pct/deliverable_qty are 100% null in production. Simulated
    here by nulling them in the fixture — without delivery_df, the ratio
    columns must come out entirely null, not silently zero/garbage."""
    df = pd.read_parquet(fixture_parquet)
    df["delivery_pct"] = float("nan")
    df["deliverable_qty"] = float("nan")
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "null_delivery.parquet")
        df.to_parquet(p, index=False)
        out = build_equity_technicals(p, output_path=None)
    assert "delivery_pct_ratio_20d" not in out.columns
    assert "deliverable_vol_ratio_20d" not in out.columns


def test_delivery_df_backfills_null_cm_delivery_columns(fixture_parquet):
    """The actual fix: passing daily_delivery's real data through delivery_df
    must override the null cm columns and produce real ratios."""
    df = pd.read_parquet(fixture_parquet)
    df["delivery_pct"] = float("nan")
    df["deliverable_qty"] = float("nan")
    aaa_dates = df.loc[df.symbol == "AAA", "date"]
    delivery_df = pd.DataFrame({
        "date": aaa_dates,
        "symbol": "AAA",
        "delivery_pct": [50.0] * 20 + [80.0] * 10,
        "delivered_qty": [40_000.0] * 20 + [120_000.0] * 10,   # named like daily_delivery's real column
    })
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "null_delivery.parquet")
        df.to_parquet(p, index=False)
        out = build_equity_technicals(p, output_path=None, delivery_df=delivery_df)
    aaa = out[out.symbol == "AAA"].sort_values("date").reset_index(drop=True)
    assert "delivery_pct_ratio_20d" in out.columns
    assert aaa.loc[29, "delivery_pct_ratio_20d"] > 1.2
    assert aaa.loc[29, "deliverable_vol_ratio_20d"] == pytest.approx(1.5)
    # BBB wasn't in delivery_df at all -> stays null, not fabricated
    bbb = out[out.symbol == "BBB"]
    assert bbb["delivery_pct_ratio_20d"].isna().all()


class TestReusesCashBreadthEngineExactly:
    """PRD §8.1: the per-symbol table must be literally the same computation
    CashMarketBreadthEngine uses for its aggregates, not a reimplementation
    that could silently diverge from it."""

    def test_dma_rsi_52w_match_engine_pivot_tables(self, fixture_parquet):
        engine = CashMarketBreadthEngine()
        engine._load_and_adjust(fixture_parquet)
        engine._precompute_dmas()

        out = build_equity_technicals(fixture_parquet, output_path=None)
        out = out.set_index(["date", "symbol"])

        for sym in ("AAA", "BBB"):
            dma20_col = engine._dma_cache[20][sym]
            rsi_col = engine._dma_cache["rsi14"][sym]
            for dt in dma20_col.index:
                if (dt, sym) not in out.index:
                    continue
                row = out.loc[(dt, sym)]
                expected_dma20 = dma20_col.loc[dt]
                expected_rsi = rsi_col.loc[dt]
                if pd.isna(expected_dma20):
                    assert pd.isna(row["dma20"])
                else:
                    assert row["dma20"] == pytest.approx(expected_dma20)
                if pd.isna(expected_rsi):
                    assert pd.isna(row["rsi14"])
                else:
                    assert row["rsi14"] == pytest.approx(expected_rsi)


if __name__ == "__main__":
    import unittest
    unittest.main()
