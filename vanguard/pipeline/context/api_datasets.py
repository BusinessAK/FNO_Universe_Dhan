"""
C4 — the session-gated nseindia.com API datasets (JSON, current-state, not
date-keyed archives): FII/DII cash provisional flows, results calendar,
corporate actions. Shapes pinned from real responses 2026-07-19 (fixtures in
tests/fixtures/nse_context/*.json).

Forward-only by nature (PRD X10): each run upserts what the API says NOW.
FII/DII keyed by trade date; events/corp-actions upserted by natural key so
postponements replace their row.
"""
from __future__ import annotations

import json

import pandas as pd

API = {
    "fii_dii": "https://www.nseindia.com/api/fiidiiTradeReact",
    "events": "https://www.nseindia.com/api/event-calendar",
    "corp_actions": "https://www.nseindia.com/api/corporates-corporateActions?index=equities",
}

DDL = [
    """CREATE TABLE IF NOT EXISTS daily_fii_dii (
        date TIMESTAMP, category VARCHAR, buy_cr DOUBLE, sell_cr DOUBLE,
        net_cr DOUBLE, provisional BOOLEAN DEFAULT TRUE)""",
    """CREATE TABLE IF NOT EXISTS corporate_events (
        symbol VARCHAR, event_type VARCHAR, event_date TIMESTAMP, details VARCHAR)""",
]


class ApiShapeDrift(RuntimeError):
    pass


def _date(s: str):
    return pd.to_datetime(s, format="%d-%b-%Y", errors="coerce")


def parse_fii_dii(raw: bytes) -> pd.DataFrame:
    rows = json.loads(raw)
    out = []
    for r in rows:
        if not {"category", "date", "buyValue", "sellValue", "netValue"} <= set(r):
            raise ApiShapeDrift(f"fiidiiTradeReact keys drifted: {sorted(r)}")
        cat = "FII" if "FII" in r["category"].upper() else "DII"
        out.append(dict(date=_date(r["date"]), category=cat,
                        buy_cr=float(r["buyValue"]), sell_cr=float(r["sellValue"]),
                        net_cr=float(r["netValue"]), provisional=True))
    if not out:
        raise ApiShapeDrift("fiidiiTradeReact: empty")
    return pd.DataFrame(out)


def parse_events(raw: bytes) -> pd.DataFrame:
    rows = json.loads(raw)
    out = []
    for r in rows:
        if not {"symbol", "purpose", "date"} <= set(r):
            raise ApiShapeDrift(f"event-calendar keys drifted: {sorted(r)}")
        p = (r.get("purpose") or "").strip()
        etype = "RESULTS" if "result" in p.lower() else "OTHER"
        out.append(dict(symbol=r["symbol"], event_type=etype,
                        event_date=_date(r["date"]),
                        details=(r.get("bm_desc") or p)[:300]))
    return pd.DataFrame(out).dropna(subset=["event_date"])


def parse_corp_actions(raw: bytes) -> pd.DataFrame:
    rows = json.loads(raw)
    out = []
    for r in rows:
        if not {"symbol", "subject", "exDate"} <= set(r):
            raise ApiShapeDrift(f"corporateActions keys drifted: {sorted(r)}")
        s = (r.get("subject") or "").lower()
        etype = ("EX_DIVIDEND" if "dividend" in s else
                 "SPLIT" if "split" in s else
                 "BONUS" if "bonus" in s else "CORP_ACTION")
        out.append(dict(symbol=r["symbol"], event_type=etype,
                        event_date=_date(r["exDate"]),
                        details=(r.get("subject") or "")[:300]))
    return pd.DataFrame(out).dropna(subset=["event_date"])


def ingest_api_datasets(client, con) -> dict[str, str]:
    """Fetch + upsert all three. Failure-isolated like the archive datasets."""
    for ddl in DDL:
        con.execute(ddl)
    status = {}
    # FII/DII: replace that trade date's rows
    try:
        df = parse_fii_dii(client.get_bytes(API["fii_dii"]))
        for d in df.date.unique():
            con.execute("DELETE FROM daily_fii_dii WHERE date = ?", [pd.Timestamp(d)])
        con.execute("INSERT INTO daily_fii_dii SELECT * FROM df")
        status["fii_dii"] = f"ok:{len(df)}"
    except Exception as e:                                  # noqa: BLE001
        status["fii_dii"] = f"error:{e}"
    # events + corp actions: replace by (symbol, event_type) natural key
    for name, parse in (("events", parse_events), ("corp_actions", parse_corp_actions)):
        try:
            df = parse(client.get_bytes(API[name]))
            if len(df):
                con.execute("""DELETE FROM corporate_events WHERE (symbol, event_type)
                               IN (SELECT symbol, event_type FROM df)""")
                con.execute("INSERT INTO corporate_events SELECT * FROM df")
            status[name] = f"ok:{len(df)}"
        except Exception as e:                              # noqa: BLE001
            status[name] = f"error:{e}"
    return status
