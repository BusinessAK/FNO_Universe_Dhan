"""
C1 dataset definitions — one Dataset per NSE archive file. Each pins the
exact observed schema (recorded 2026-07-19 from real 2026-07-16 files; see
tests/fixtures/nse_context/) and fails LOUDLY on drift (PRD X3): archive the
raw file, raise, never guess-map columns.

Observed quirks handled here so nothing downstream sees them:
  - participant OI: title line first; some headers carry trailing spaces
  - sec_bhavdata_full: headers AND values carry leading spaces; '-' for
    missing DELIV_* on non-EQ series
  - ind_close_all: '-' in numeric fields (India VIX has no volume);
    values like '-.02'
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date

import pandas as pd


class SchemaDrift(RuntimeError):
    """NSE changed a file's columns — refuse the day, keep the raw for diffing."""


def _require(df: pd.DataFrame, cols: list[str], name: str):
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise SchemaDrift(f"{name}: missing columns {missing}; "
                          f"got {list(df.columns)[:18]}")


def _ddmmyyyy(d: date) -> str:
    return d.strftime("%d%m%Y")


@dataclass(frozen=True)
class Dataset:
    name: str
    url_template: str          # {d} -> DDMMYYYY
    table: str
    ddl: str
    parse: callable            # bytes, date -> DataFrame matching the table

    def url(self, d: date) -> str:
        return self.url_template.format(d=_ddmmyyyy(d))


# ── participant-wise OI ──────────────────────────────────────────────────────

_POI_MAP = {                   # csv header (stripped) -> table column
    "Future Index Long": "fut_idx_long", "Future Index Short": "fut_idx_short",
    "Future Stock Long": "fut_stk_long", "Future Stock Short": "fut_stk_short",
    "Option Index Call Long": "opt_idx_call_long", "Option Index Call Short": "opt_idx_call_short",
    "Option Index Put Long": "opt_idx_put_long", "Option Index Put Short": "opt_idx_put_short",
    "Option Stock Call Long": "opt_stk_call_long", "Option Stock Call Short": "opt_stk_call_short",
    "Option Stock Put Long": "opt_stk_put_long", "Option Stock Put Short": "opt_stk_put_short",
    "Total Long Contracts": "total_long", "Total Short Contracts": "total_short",
}
PARTICIPANTS = ["Client", "DII", "FII", "Pro"]


def parse_participant_oi(raw: bytes, d: date) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(raw), skiprows=1)
    df.columns = [str(c).strip() for c in df.columns]
    _require(df, ["Client Type", *_POI_MAP], "fao_participant_oi")
    df["Client Type"] = df["Client Type"].astype(str).str.strip()
    df = df.set_index("Client Type")
    for p in PARTICIPANTS + ["TOTAL"]:
        if p not in df.index:
            raise SchemaDrift(f"fao_participant_oi: row '{p}' absent")
    # NSE's own invariant: TOTAL == sum of the four participants, per column.
    # A silent row drop or renamed participant fails here, not downstream.
    # Tolerance |diff| <= 5 per column: NSE's published TOTAL row is an
    # independently rounded aggregate with routine ±1 discrepancies vs the
    # participant sum (observed 2026-07-16 on four separate columns). The
    # invariant's job is catching dropped/renamed rows — those miss by
    # thousands-to-millions, not by one.
    body, total = df.loc[PARTICIPANTS, list(_POI_MAP)], df.loc["TOTAL", list(_POI_MAP)]
    diff = (body.sum() - total).abs()
    if (diff > 5).any():
        raise SchemaDrift(f"fao_participant_oi: TOTAL invariant broken for "
                          f"{list(diff[diff > 5].index)}")
    out = body.rename(columns=_POI_MAP).reset_index()
    out.insert(0, "date", pd.Timestamp(d))
    out = out.rename(columns={"Client Type": "participant"})
    out["participant"] = out["participant"].str.upper()      # CLIENT/DII/FII/PRO
    return out


# ── index closes (incl. India VIX) ───────────────────────────────────────────

_IDX_COLS = ["Index Name", "Index Date", "Closing Index Value", "Points Change",
             "Change(%)"]


def parse_index_close(raw: bytes, d: date) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(raw))
    df.columns = [str(c).strip() for c in df.columns]
    _require(df, _IDX_COLS, "ind_close_all")
    out = pd.DataFrame({
        "date": pd.Timestamp(d),
        "index_name": df["Index Name"].astype(str).str.strip(),
        "close": pd.to_numeric(df["Closing Index Value"], errors="coerce"),
        "chg_pct": pd.to_numeric(df["Change(%)"], errors="coerce"),
    })
    pts = pd.to_numeric(df["Points Change"], errors="coerce")
    out["prev_close"] = out["close"] - pts
    out = out.dropna(subset=["close"])
    if not (out["index_name"].str.upper() == "INDIA VIX").any():
        raise SchemaDrift("ind_close_all: 'India VIX' row absent")
    return out[["date", "index_name", "close", "prev_close", "chg_pct"]]


# ── security-wise delivery (cash, series EQ) ─────────────────────────────────

_DLV_COLS = ["SYMBOL", "SERIES", "TTL_TRD_QNTY", "DELIV_QTY", "DELIV_PER"]


def parse_delivery(raw: bytes, d: date) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(raw))
    df.columns = [str(c).strip() for c in df.columns]
    _require(df, _DLV_COLS, "sec_bhavdata_full")
    for c in ("SYMBOL", "SERIES"):
        df[c] = df[c].astype(str).str.strip()
    eq = df[df["SERIES"] == "EQ"].copy()
    if len(eq) < 500:
        raise SchemaDrift(f"sec_bhavdata_full: only {len(eq)} EQ rows — "
                          "series filter or file shape drifted")
    out = pd.DataFrame({
        "date": pd.Timestamp(d),
        "symbol": eq["SYMBOL"],
        "traded_qty": pd.to_numeric(eq["TTL_TRD_QNTY"], errors="coerce"),
        "delivered_qty": pd.to_numeric(eq["DELIV_QTY"], errors="coerce"),
        "delivery_pct": pd.to_numeric(eq["DELIV_PER"], errors="coerce"),
    }).dropna(subset=["traded_qty"])
    return out


# ── F&O ban list (names only; MWPL % deferred — combined-OI zip is gone and
#    the .xls alternative needs a legacy parser; see NSE PRD 2.2 note) ────────

def parse_ban(raw: bytes, d: date) -> pd.DataFrame:
    text = raw.decode("utf-8", errors="replace").strip()
    if "Ban For Trade Date" not in text.splitlines()[0]:
        raise SchemaDrift(f"fo_secban: unexpected header {text.splitlines()[0][:60]!r}")
    syms = []
    for line in text.splitlines()[1:]:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2 and parts[1]:
            syms.append(parts[1])
    # an empty ban day is legitimate — zero rows, not an error
    return pd.DataFrame({"date": pd.Timestamp(d), "symbol": syms})


# ── registry ─────────────────────────────────────────────────────────────────

DATASETS: dict[str, Dataset] = {
    "participant_oi": Dataset(
        name="participant_oi",
        url_template="https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{d}.csv",
        table="daily_participant_oi",
        ddl="""CREATE TABLE IF NOT EXISTS daily_participant_oi (
            date TIMESTAMP, participant VARCHAR,
            fut_idx_long BIGINT, fut_idx_short BIGINT,
            fut_stk_long BIGINT, fut_stk_short BIGINT,
            opt_idx_call_long BIGINT, opt_idx_call_short BIGINT,
            opt_idx_put_long BIGINT, opt_idx_put_short BIGINT,
            opt_stk_call_long BIGINT, opt_stk_call_short BIGINT,
            opt_stk_put_long BIGINT, opt_stk_put_short BIGINT,
            total_long BIGINT, total_short BIGINT)""",
        parse=parse_participant_oi),
    "index_close": Dataset(
        name="index_close",
        url_template="https://nsearchives.nseindia.com/content/indices/ind_close_all_{d}.csv",
        table="daily_index_close",
        ddl="""CREATE TABLE IF NOT EXISTS daily_index_close (
            date TIMESTAMP, index_name VARCHAR, close DOUBLE,
            prev_close DOUBLE, chg_pct DOUBLE)""",
        parse=parse_index_close),
    "delivery": Dataset(
        name="delivery",
        url_template="https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d}.csv",
        table="daily_delivery",
        ddl="""CREATE TABLE IF NOT EXISTS daily_delivery (
            date TIMESTAMP, symbol VARCHAR, traded_qty BIGINT,
            delivered_qty BIGINT, delivery_pct DOUBLE)""",
        parse=parse_delivery),
    "ban": Dataset(
        name="ban",
        url_template="https://nsearchives.nseindia.com/archives/fo/sec_ban/fo_secban_{d}.csv",
        table="daily_ban",
        ddl="CREATE TABLE IF NOT EXISTS daily_ban (date TIMESTAMP, symbol VARCHAR)",
        parse=parse_ban),
}
