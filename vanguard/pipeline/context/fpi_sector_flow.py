"""
NSDL Fortnightly Sector-wise FPI Investment data — sector-layer context, not a
per-stock signal (see the smart-money-map planning discussion: this is a slow,
twice-a-month tilt overlay, never a trigger input).

No JSON API — a <select> on FPI_Fortnightly_Selection.aspx lists one dated
report per fortnight (newest first), each a static HTML page with a 4-level
colspan/rowspan header over ~98 columns for 24 sector rows + Grand Total.
Header is flattened generically by content match, not hardcoded by index, so
NSDL adding/removing a category later doesn't silently misalign columns.

Raw-first, like the rest of the context layer: an already-archived fortnight
is parsed offline and never refetched. Only the newest fortnight not yet in
data/raw/context/fpi_sector_flow/ triggers a network call.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

from vanguard.config.paths import RAW
from vanguard.pipeline.context.client import NseClient, FetchError

SELECTION_URL = "https://www.fpi.nsdl.co.in/web/Reports/FPI_Fortnightly_Selection.aspx"
BASE = "https://www.fpi.nsdl.co.in"
RAW_DIR = RAW / "context" / "fpi_sector_flow"

DDL = """CREATE TABLE IF NOT EXISTS fpi_sector_flow (
    fortnight_end DATE, sector VARCHAR,
    equity_net_inv_cr DOUBLE, total_net_inv_cr DOUBLE)"""


class ApiShapeDrift(RuntimeError):
    pass


def latest_report(client: NseClient) -> tuple[str, str]:
    """(label, url) for the newest fortnight in the selection page's dropdown."""
    html = client.get_bytes(SELECTION_URL).decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    opt = soup.find("option", value=re.compile(r"StaticReports"))
    if opt is None:
        raise ApiShapeDrift("FPI_Fortnightly_Selection.aspx: no dated report options found")
    label = opt.get_text(strip=True)
    url = opt["value"].lstrip("~")
    return label, BASE + url


def _fortnight_end_from_label(label: str) -> pd.Timestamp:
    # "JUL 15, 2026" -> Timestamp. NSDL's own label, not a filename guess.
    return pd.to_datetime(label, format="%b %d, %Y", errors="raise")


def _flatten_header(table, header_rows: int, ncols: int) -> list[str]:
    rows = table.find_all("tr")[:header_rows]
    grid = [[None] * ncols for _ in range(header_rows)]
    occupied_until = [0] * ncols
    for r_i, row in enumerate(rows):
        col = 0
        for cell in row.find_all(["th", "td"]):
            while col < ncols and occupied_until[col] > r_i:
                col += 1
            text = cell.get_text(strip=True)
            colspan = int(cell.get("colspan", 1))
            rowspan = int(cell.get("rowspan", 1))
            for c in range(col, min(col + colspan, ncols)):
                grid[r_i][c] = text
                if rowspan > 1:
                    occupied_until[c] = r_i + rowspan
            col += colspan
    paths = []
    for c in range(ncols):
        parts, seen = [grid[r][c] for r in range(header_rows) if grid[r][c]], []
        for p in parts:
            if not seen or seen[-1] != p:
                seen.append(p)
        paths.append(" | ".join(seen))
    return paths


def _to_number(s: str) -> float:
    s = s.strip().replace(",", "")
    if s in ("", "-"):
        return 0.0
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        v = float(s)
    except ValueError:
        return 0.0
    return -v if neg else v


def parse_sector_flow(raw: bytes, fortnight_end: pd.Timestamp) -> pd.DataFrame:
    """Sector-wise Equity + Total Net Investment (₹ Cr) for the most recent of
    the two fortnights this report shows. Raises ApiShapeDrift if NSDL's
    layout no longer has two Net-Investment period blocks to pick from."""
    soup = BeautifulSoup(raw.decode("utf-8", errors="replace"), "html.parser")
    tables = soup.find_all("table")
    if not tables:
        raise ApiShapeDrift("no <table> found in report")
    table = max(tables, key=lambda t: len(t.find_all("tr")))
    rows = table.find_all("tr")
    if len(rows) < 5:
        raise ApiShapeDrift(f"sector table only has {len(rows)} rows")
    ncols = len(rows[3].find_all(["th", "td"]))
    paths = _flatten_header(table, header_rows=4, ncols=ncols)

    def find_cols(suffix: str) -> list[int]:
        return [i for i, p in enumerate(paths)
                if p.startswith("Net Investment") and "IN INR Cr." in p
                and "Mutual Funds" not in p and "Debt" not in p and p.endswith(suffix)]

    equity_cols, total_cols = find_cols("Equity"), find_cols("Total")
    if len(equity_cols) < 2 or len(total_cols) < 2:
        raise ApiShapeDrift(f"expected 2 Net-Investment periods, "
                            f"found equity={equity_cols} total={total_cols}")
    curr_eq_col, curr_tot_col = max(equity_cols), max(total_cols)

    out = []
    for row in rows[4:]:
        cells = row.find_all(["th", "td"])
        if len(cells) != ncols:
            continue
        sector = cells[1].get_text(strip=True)
        if not sector or sector == "Grand Total":
            continue
        out.append({
            "fortnight_end": fortnight_end,
            "sector": sector,
            "equity_net_inv_cr": _to_number(cells[curr_eq_col].get_text()),
            "total_net_inv_cr": _to_number(cells[curr_tot_col].get_text()),
        })
    if not out:
        raise ApiShapeDrift("parsed 0 sector rows")
    return pd.DataFrame(out)


def ingest_fpi_sector_flow(client: NseClient | None = None, con=None) -> str:
    """Idempotent: no-ops (returns 'ok:0 (up to date)') if the latest
    fortnight NSDL has published is already in the table. Failure-isolated —
    exceptions are the caller's problem to catch, matching this module's
    single call site in poll_context.py."""
    client = client or NseClient()
    label, url = latest_report(client)
    fortnight_end = _fortnight_end_from_label(label)

    con.execute(DDL)
    already = con.execute(
        "SELECT COUNT(*) FROM fpi_sector_flow WHERE fortnight_end = ?",
        [fortnight_end.date()]).fetchone()[0]
    if already:
        return "ok:0 (up to date)"

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache = RAW_DIR / (Path(url).name or f"{fortnight_end.date()}.html")
    if cache.exists():
        raw = cache.read_bytes()
    else:
        raw = client.get_bytes(url)
        cache.write_bytes(raw)

    df = parse_sector_flow(raw, fortnight_end)
    con.execute("DELETE FROM fpi_sector_flow WHERE fortnight_end = ?", [fortnight_end.date()])
    con.execute("INSERT INTO fpi_sector_flow SELECT * FROM df")
    return f"ok:{len(df)}"
