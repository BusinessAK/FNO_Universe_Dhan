"""
Dhan instrument master — the security-id catalog the live feed subscribes by.

Parses Dhan's public scrip master into a clean table of NSE equity, index, and
F&O (futures + options) instruments with exactly the fields the subscription
manager and feed handler need. The live WebSocket subscribes by
(feed_segment, security_id), so this table is the foundation of the whole
realtime layer.

Feed segment codes mirror dhanhq.marketfeed:  IDX=0 · NSE=1 (equity) · NSE_FNO=2.

Build:
    python3 -m src.data.instrument_master              # downloads scrip master
    python3 -m src.data.instrument_master --csv PATH   # use a local copy
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SCRIP_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
OUT = ROOT / "data" / "live" / "instrument_master.parquet"

# dhanhq.marketfeed exchange-segment codes
SEG_IDX, SEG_NSE_EQ, SEG_NSE_FNO = 0, 1, 2

# Underlying = everything before the "-MonYYYY" expiry token; non-greedy so
# hyphenated underlyings survive (BAJAJ-AUTO-Jul2026-840-CE → "BAJAJ-AUTO").
_UNDERLYING_RE = re.compile(r"^(.+?)-[A-Z][a-z]{2}\d{4}")


def _underlying(trading_symbol: str) -> str:
    m = _UNDERLYING_RE.match(str(trading_symbol))
    return m.group(1) if m else str(trading_symbol)


def build(csv_path: str | None = None) -> pd.DataFrame:
    src = csv_path or SCRIP_URL
    print(f"[instrument_master] loading scrip master: {src}")
    df = pd.read_csv(src, low_memory=False)

    nse = df[df["SEM_EXM_EXCH_ID"] == "NSE"].copy()
    rows = []

    # ── Equity spot (segment E, series EQ) ────────────────────────────────
    eq = nse[(nse["SEM_SEGMENT"] == "E") & (nse["SEM_SERIES"] == "EQ")]
    for r in eq.itertuples():
        rows.append({
            "security_id": int(r.SEM_SMST_SECURITY_ID), "feed_segment": SEG_NSE_EQ,
            "kind": "EQ", "underlying": str(r.SEM_TRADING_SYMBOL),
            "trading_symbol": str(r.SEM_TRADING_SYMBOL), "expiry": None,
            "strike": 0.0, "option_type": "", "lot_size": _num(r.SEM_LOT_UNITS, 1),
            "tick_size": _num(r.SEM_TICK_SIZE, 0.05),
        })

    # ── Index spot (segment I) ────────────────────────────────────────────
    idx = nse[nse["SEM_SEGMENT"] == "I"]
    for r in idx.itertuples():
        rows.append({
            "security_id": int(r.SEM_SMST_SECURITY_ID), "feed_segment": SEG_IDX,
            "kind": "INDEX", "underlying": str(r.SEM_TRADING_SYMBOL),
            "trading_symbol": str(r.SEM_TRADING_SYMBOL), "expiry": None,
            "strike": 0.0, "option_type": "", "lot_size": 0, "tick_size": 0.05,
        })

    # ── Derivatives (segment D): FUTSTK/FUTIDX + OPTSTK/OPTIDX ─────────────
    deriv = nse[nse["SEM_SEGMENT"] == "D"]
    for r in deriv.itertuples():
        iname = str(r.SEM_INSTRUMENT_NAME)
        if iname.startswith("FUT"):
            kind = "FUT"
        elif iname.startswith("OPT"):
            kind = "OPT"
        else:
            continue
        rows.append({
            "security_id": int(r.SEM_SMST_SECURITY_ID), "feed_segment": SEG_NSE_FNO,
            "kind": kind, "underlying": _underlying(r.SEM_TRADING_SYMBOL),
            "trading_symbol": str(r.SEM_TRADING_SYMBOL),
            "expiry": _date(r.SEM_EXPIRY_DATE),
            "strike": _num(r.SEM_STRIKE_PRICE, 0.0),
            "option_type": str(r.SEM_OPTION_TYPE) if pd.notna(r.SEM_OPTION_TYPE) else "",
            "lot_size": _num(r.SEM_LOT_UNITS, 0), "tick_size": _num(r.SEM_TICK_SIZE, 0.05),
        })

    out = pd.DataFrame(rows)
    out["lot_size"] = out["lot_size"].astype(int)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT, index=False)
    print(f"[instrument_master] {len(out)} instruments "
          f"(EQ {sum(out.kind=='EQ')} · INDEX {sum(out.kind=='INDEX')} · "
          f"FUT {sum(out.kind=='FUT')} · OPT {sum(out.kind=='OPT')}) → {OUT}")
    return out


def _num(v, default):
    try:
        f = float(v)
        return default if f != f else f
    except (TypeError, ValueError):
        return default


def _date(v):
    try:
        return pd.Timestamp(v).strftime("%Y-%m-%d")
    except Exception:
        return None


class InstrumentMaster:
    """Query layer over instrument_master.parquet used by the subscription manager."""

    def __init__(self, path: str | Path = OUT):
        self.df = pd.read_parquet(path)

    def spot(self, symbol: str) -> dict | None:
        m = self.df[(self.df.kind.isin(["EQ", "INDEX"])) & (self.df.underlying == symbol)]
        return m.iloc[0].to_dict() if not m.empty else None

    def futures(self, underlying: str) -> pd.DataFrame:
        return self.df[(self.df.kind == "FUT") & (self.df.underlying == underlying)]

    def expiries(self, underlying: str) -> list:
        m = self.df[(self.df.kind == "OPT") & (self.df.underlying == underlying)]
        return sorted(e for e in m.expiry.dropna().unique())

    def option_chain(self, underlying: str, expiry: str | None = None) -> pd.DataFrame:
        m = self.df[(self.df.kind == "OPT") & (self.df.underlying == underlying)]
        if expiry:
            m = m[m.expiry == expiry]
        return m

    def near_atm(self, underlying: str, spot: float, n_strikes: int = 12,
                 expiry: str | None = None) -> pd.DataFrame:
        """The ±n_strikes CE/PE around spot for one expiry — the T-Live window."""
        chain = self.option_chain(underlying, expiry or self._front_expiry(underlying))
        if chain.empty or spot <= 0:
            return chain
        strikes = sorted(chain.strike.unique())
        atm = min(strikes, key=lambda s: abs(s - spot))
        ai = strikes.index(atm)
        keep = set(strikes[max(0, ai - n_strikes): ai + n_strikes + 1])
        return chain[chain.strike.isin(keep)]

    def _front_expiry(self, underlying: str) -> str | None:
        exps = self.expiries(underlying)
        return exps[0] if exps else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=None)
    args = ap.parse_args()
    build(args.csv)


if __name__ == "__main__":
    main()
