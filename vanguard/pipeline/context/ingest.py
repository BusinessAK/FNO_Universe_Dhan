"""
C1 ingest orchestrator — raw-first, idempotent, failure-isolated (PRD §3).

Per dataset per date: fetch → archive raw under data/raw/context/<ds>/ →
parse (schema-pinned) → DELETE+INSERT that date's rows. One dataset's failure
never blocks another; the caller gets a status dict per dataset.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb

from vanguard.config.paths import DB, RAW
from vanguard.pipeline.context.client import NseClient, FetchError
from vanguard.pipeline.context.datasets import DATASETS, Dataset, SchemaDrift

RAW_CONTEXT = RAW / "context"


def ensure_tables(con) -> None:
    for ds in DATASETS.values():
        con.execute(ds.ddl)


def _archive(ds: Dataset, d: date, raw: bytes) -> Path:
    p = RAW_CONTEXT / ds.name / Path(ds.url(d)).name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(raw)
    return p


def _upsert(con, ds: Dataset, d: date, df) -> int:
    con.execute(f"DELETE FROM {ds.table} WHERE date = ?", [str(d)])
    con.execute(f"INSERT INTO {ds.table} SELECT * FROM df")
    return len(df)


def ingest_date(d: date, client: NseClient | None = None, con=None,
                only: list[str] | None = None) -> dict[str, str]:
    """Ingest all (or `only`) datasets for one date. Returns {name: status},
    status ∈ 'ok:<rows>' | 'absent' (404 — holiday/未 published) | 'error:<msg>'."""
    client = client or NseClient()
    own_con = con is None
    if own_con:
        con = duckdb.connect(str(DB))
    status: dict[str, str] = {}
    try:
        ensure_tables(con)
        for name, ds in DATASETS.items():
            if only and name not in only:
                continue
            # Raw-first replay: an already-archived file is parsed offline —
            # backfills and re-runs never refetch what we hold.
            cached = RAW_CONTEXT / ds.name / Path(ds.url(d)).name
            try:
                if cached.exists():
                    raw = cached.read_bytes()
                else:
                    raw = client.get_bytes(ds.url(d))
                    _archive(ds, d, raw)
                df = ds.parse(raw, d)
                n = _upsert(con, ds, d, df)
                status[name] = f"ok:{n}"
            except FetchError as e:
                status[name] = "absent" if e.status == 404 else f"error:{e}"
            except SchemaDrift as e:
                status[name] = f"error:{e}"
            except Exception as e:                      # noqa: BLE001 — isolation is the contract
                status[name] = f"error:{type(e).__name__}: {e}"
        return status
    finally:
        if own_con:
            con.close()
