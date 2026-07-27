"""
Fyers instrument master — the security-id catalog the live feed subscribes by.

Parses Fyers's public scrip master into a clean table of NSE equity, index, and
F&O (futures + options) instruments with exactly the fields the subscription
manager and feed handler need. The live WebSocket subscribes by
SymbolTicker (e.g., 'NSE:NIFTY24JUL24500CE'), so this table is the foundation of the whole
realtime layer.

Build:
    python3 -m vanguard.data.instrument_master
"""
from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CM_URL = "https://public.fyers.in/sym_details/NSE_CM.csv"
FO_URL = "https://public.fyers.in/sym_details/NSE_FO.csv"
OUT = ROOT / "data" / "live" / "instrument_master.parquet"


def build() -> pd.DataFrame:
    print(f"[instrument_master] loading Fyers CM master: {CM_URL}")
    cm = pd.read_csv(CM_URL, header=None, low_memory=False)
    print(f"[instrument_master] loading Fyers FO master: {FO_URL}")
    fo = pd.read_csv(FO_URL, header=None, low_memory=False)

    rows = []

    # Columns of interest in Fyers CSV:
    # 3: LotSize
    # 4: TickSize
    # 8: ExpiryDate (epoch)
    # 9: SymbolTicker ('NSE:360ONE-EQ', 'NSE:NIFTY50-INDEX')
    # 13: UnderlyingSymbol ('360ONE', 'NIFTY')
    # 15: StrikePrice (-1.0 for EQ/FUT/INDEX)
    # 16: OptionType ('XX' for EQ/FUT, 'CE' or 'PE' for OPT)

    # ── Equity & Index spot ──────────────────────────────────────────────────
    for r in cm.itertuples(index=False):
        ticker = str(r[9])
        if not ticker.startswith("NSE:"):
            continue
        
        # Determine kind
        if "-INDEX" in ticker:
            kind = "INDEX"
        elif "-EQ" in ticker:
            kind = "EQ"
        else:
            continue

        rows.append({
            "security_id": ticker, # Fyers string is the ID
            "feed_segment": 0,     # Not heavily used in Vanguard post-migration
            "kind": kind,
            "underlying": str(r[13]),
            "trading_symbol": ticker,
            "expiry": None,
            "strike": 0.0,
            "option_type": "",
            "lot_size": int(r[3] if pd.notna(r[3]) else 1) or 1,
            "tick_size": float(r[4] if pd.notna(r[4]) else 0.05) or 0.05,
        })

    # ── Futures & Options ────────────────────────────────────────────────────
    for r in fo.itertuples(index=False):
        ticker = str(r[9])
        if not ticker.startswith("NSE:"):
            continue
            
        opt_type = str(r[16])
        if opt_type == "XX":
            kind = "FUT"
            opt_type = ""
        elif opt_type in ("CE", "PE"):
            kind = "OPT"
        else:
            continue
            
        expiry_ts = r[8]
        expiry_str = None
        if pd.notna(expiry_ts):
            expiry_str = pd.to_datetime(expiry_ts, unit='s', utc=True).tz_convert('Asia/Kolkata').strftime('%Y-%m-%d')
            
        rows.append({
            "security_id": ticker,
            "feed_segment": 0,
            "kind": kind,
            "underlying": str(r[13]),
            "trading_symbol": ticker,
            "expiry": expiry_str,
            "strike": float(r[15]) if pd.notna(r[15]) and r[15] != -1.0 else 0.0,
            "option_type": opt_type,
            "lot_size": int(r[3] if pd.notna(r[3]) else 1) or 1,
            "tick_size": float(r[4] if pd.notna(r[4]) else 0.05) or 0.05,
        })

    df_out = pd.DataFrame(rows)
    print(f"[instrument_master] mapped {len(df_out)} instruments.")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_parquet(OUT)
    print(f"[instrument_master] wrote {OUT}")
    return df_out


class InstrumentMaster:
    """Read-only query layer over the compiled parquet."""

    def __init__(self, path: Path | str = OUT):
        p = Path(path)
        if not p.exists():
            build()
        self.df = pd.read_parquet(p)

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
        exs = self.expiries(underlying)
        return exs[0] if exs else None


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.parse_args()
    build()
