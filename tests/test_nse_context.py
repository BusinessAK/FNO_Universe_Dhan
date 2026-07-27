"""
C1 tests (PRD §7.1/§7.2): golden parsers over recorded real fixtures
(2026-07-16), schema-drift loudness, NSE's TOTAL-row invariant, ingest
idempotence and failure isolation on a temp DuckDB.
"""
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import duckdb

from vanguard.pipeline.context import ingest as ing
from vanguard.pipeline.context.client import FetchError
from vanguard.pipeline.context.datasets import (
    DATASETS, SchemaDrift, parse_participant_oi, parse_index_close, parse_delivery)

FIX = Path(__file__).parent / "fixtures" / "nse_context"
D = date(2026, 7, 16)


def fx(name: str) -> bytes:
    return (FIX / name).read_bytes()


class TestParticipantOI(unittest.TestCase):
    def test_golden(self):
        df = parse_participant_oi(fx("fao_participant_oi_16072026.csv"), D)
        self.assertEqual(len(df), 4)
        self.assertEqual(sorted(df.participant), ["CLIENT", "DII", "FII", "PRO"])
        cl = df[df.participant == "CLIENT"].iloc[0]
        self.assertEqual(cl.fut_idx_long, 228686)
        dii = df[df.participant == "DII"].iloc[0]
        self.assertEqual(dii.fut_stk_short, 4264717)

    def test_total_invariant_tamper(self):
        # a materially wrong cell (±5 tolerance absorbs NSE's own rounding)
        raw = fx("fao_participant_oi_16072026.csv").replace(b"228686", b"328686")
        with self.assertRaises(SchemaDrift):
            parse_participant_oi(raw, D)

    def test_missing_column_drift(self):
        raw = fx("fao_participant_oi_16072026.csv").replace(
            b"Future Index Long", b"Fut Idx Long")
        with self.assertRaises(SchemaDrift):
            parse_participant_oi(raw, D)


class TestIndexClose(unittest.TestCase):
    def test_golden_vix(self):
        df = parse_index_close(fx("ind_close_all_16072026.csv"), D)
        vix = df[df.index_name.str.upper() == "INDIA VIX"].iloc[0]
        self.assertAlmostEqual(vix.close, 12.88)
        self.assertAlmostEqual(vix.prev_close, 13.27, places=2)   # close - points_chg
        self.assertAlmostEqual(vix.chg_pct, -2.92)
        n50 = df[df.index_name == "Nifty 50"].iloc[0]
        self.assertAlmostEqual(n50.close, 24072.75)

    def test_vix_absent_drift(self):
        lines = fx("ind_close_all_16072026.csv").decode().splitlines()
        raw = "\n".join(l for l in lines if not l.startswith("India VIX")).encode()
        with self.assertRaises(SchemaDrift):
            parse_index_close(raw, D)


class TestDelivery(unittest.TestCase):
    def test_golden_eq_only(self):
        df = parse_delivery(fx("sec_bhavdata_full_16072026.csv"), D)
        self.assertEqual(len(df), 600)                            # fixture EQ rows
        m = df[df.symbol == "20MICRONS"].iloc[0]
        self.assertAlmostEqual(m.delivery_pct, 47.31)
        self.assertEqual(m.traded_qty, 134100)

    def test_too_few_eq_rows_drift(self):
        lines = fx("sec_bhavdata_full_16072026.csv").decode().splitlines()
        raw = "\n".join(lines[:100]).encode()                     # < 500 EQ rows
        with self.assertRaises(SchemaDrift):
            parse_delivery(raw, D)


class FakeClient:
    """Serves fixture bytes; optionally raises per-dataset."""

    def __init__(self, fail: dict | None = None):
        self.fail = fail or {}
        self.calls = 0

    def get_bytes(self, url: str) -> bytes:
        self.calls += 1
        for key, exc in self.fail.items():
            if key in url:
                raise exc
        name = url.rsplit("/", 1)[-1]
        return fx(name)


class TestIngest(unittest.TestCase):
    def _run(self, client, tmp):
        con = duckdb.connect(str(Path(tmp) / "t.duckdb"))
        try:
            with patch.object(ing, "RAW_CONTEXT", Path(tmp) / "rawctx"):
                s1 = ing.ingest_date(D, client=client, con=con)
                s2 = ing.ingest_date(D, client=client, con=con)   # idempotence
            counts = {ds.table: con.execute(
                f"SELECT COUNT(*) FROM {ds.table}").fetchone()[0]
                for ds in DATASETS.values()}
            return s1, s2, counts
        finally:
            con.close()

    def test_ingest_idempotent_and_archived(self):
        with tempfile.TemporaryDirectory() as tmp:
            s1, s2, counts = self._run(FakeClient(), tmp)
        self.assertEqual(s1["participant_oi"], "ok:4")
        self.assertEqual(s1["index_close"], "ok:13")
        self.assertEqual(s1["delivery"], "ok:600")
        self.assertEqual(s1, s2)
        self.assertEqual(counts["daily_participant_oi"], 4)       # not 8 — replaced
        self.assertEqual(counts["daily_delivery"], 600)

    def test_failure_isolation(self):
        client = FakeClient(fail={"fao_participant": RuntimeError("boom")})
        with tempfile.TemporaryDirectory() as tmp:
            s1, _, counts = self._run(client, tmp)
        self.assertTrue(s1["participant_oi"].startswith("error:"))
        self.assertEqual(s1["index_close"], "ok:13")              # others land
        self.assertEqual(counts["daily_participant_oi"], 0)

    def test_absent_on_404(self):
        client = FakeClient(fail={"ind_close": FetchError("404", status=404)})
        with tempfile.TemporaryDirectory() as tmp:
            s1, _, _ = self._run(client, tmp)
        self.assertEqual(s1["index_close"], "absent")


if __name__ == "__main__":
    unittest.main()


class TestBan(unittest.TestCase):
    def test_parse_golden(self):
        from vanguard.pipeline.context.datasets import parse_ban
        df = parse_ban(fx("fo_secban_17072026.csv"), date(2026, 7, 17))
        self.assertEqual(df.symbol.tolist(), ["KAYNES"])

    def test_empty_ban_day_ok(self):
        from vanguard.pipeline.context.datasets import parse_ban
        df = parse_ban(b"Securities in Ban For Trade Date 01-JAN-2026:\n", date(2026, 1, 1))
        self.assertEqual(len(df), 0)

    # NOTE: the ban-arming gate test (load_armed_book) moved to archive/ with
    # the live trigger engine when the intraday layer was archived — covered by
    # archive/tests/test_trigger_engine.py.


class TestApiDatasets(unittest.TestCase):
    def test_fii_dii_golden(self):
        from vanguard.pipeline.context.api_datasets import parse_fii_dii
        df = parse_fii_dii(fx("fiidii.json"))
        self.assertEqual(sorted(df.category), ["DII", "FII"])
        fii = df[df.category == "FII"].iloc[0]
        self.assertAlmostEqual(fii.net_cr, -376.41)

    def test_events_results_classified(self):
        from vanguard.pipeline.context.api_datasets import parse_events
        df = parse_events(fx("events.json"))
        self.assertGreater((df.event_type == "RESULTS").sum(), 50)
        self.assertIn("ACE", set(df.symbol))

    def test_corp_actions_typed(self):
        from vanguard.pipeline.context.api_datasets import parse_corp_actions
        df = parse_corp_actions(fx("corpact.json"))
        self.assertIn("EX_DIVIDEND", set(df.event_type))

    def test_shape_drift_raises(self):
        from vanguard.pipeline.context.api_datasets import parse_fii_dii, ApiShapeDrift
        with self.assertRaises(ApiShapeDrift):
            parse_fii_dii(b'[{"category":"FII"}]')


class TestFpiSectorFlow(unittest.TestCase):
    def test_latest_report_discovery(self):
        from vanguard.pipeline.context.fpi_sector_flow import latest_report

        class Client:
            def get_bytes(self, url):
                return fx("fpi_fortnightly_selection.html")

        label, url = latest_report(Client())
        self.assertEqual(label, "JUL 15, 2026")
        self.assertTrue(url.endswith("FIIInvestSector_Jul152026.html"))
        self.assertTrue(url.startswith("https://www.fpi.nsdl.co.in/"))

    def test_parse_golden(self):
        import pandas as pd
        from vanguard.pipeline.context.fpi_sector_flow import parse_sector_flow

        df = parse_sector_flow(fx("FIIInvestSector_Jul152026.html"),
                                pd.Timestamp("2026-07-15"))
        self.assertEqual(len(df), 24)                          # 24 sectors, Grand Total dropped
        self.assertNotIn("Grand Total", set(df.sector))
        metals = df[df.sector == "Metals & Mining"].iloc[0]
        self.assertAlmostEqual(metals.equity_net_inv_cr, 5993.0)
        self.assertTrue((df.fortnight_end == pd.Timestamp("2026-07-15")).all())

    def test_parse_drift_on_missing_table(self):
        from vanguard.pipeline.context.fpi_sector_flow import parse_sector_flow, ApiShapeDrift
        import pandas as pd
        with self.assertRaises(ApiShapeDrift):
            parse_sector_flow(b"<html><body>no tables here</body></html>",
                              pd.Timestamp("2026-07-15"))

    def test_ingest_idempotent(self):
        from vanguard.pipeline.context.fpi_sector_flow import ingest_fpi_sector_flow

        class Client:
            calls = 0

            def get_bytes(self, url):
                self.calls += 1
                if "Selection" in url:
                    return fx("fpi_fortnightly_selection.html")
                return fx("FIIInvestSector_Jul152026.html")

        with tempfile.TemporaryDirectory() as tmp:
            with patch("vanguard.pipeline.context.fpi_sector_flow.RAW_DIR", Path(tmp) / "raw"):
                con = duckdb.connect(str(Path(tmp) / "t.duckdb"))
                try:
                    client = Client()
                    s1 = ingest_fpi_sector_flow(client, con)
                    n_after_first = con.execute(
                        "SELECT COUNT(*) FROM fpi_sector_flow").fetchone()[0]
                    calls_after_first = client.calls
                    s2 = ingest_fpi_sector_flow(client, con)     # idempotence: same fortnight
                    n_after_second = con.execute(
                        "SELECT COUNT(*) FROM fpi_sector_flow").fetchone()[0]
                finally:
                    con.close()
        self.assertEqual(s1, "ok:24")
        self.assertEqual(n_after_first, 24)
        self.assertEqual(n_after_second, 24)                    # no duplicate rows
        self.assertEqual(s2, "ok:0 (up to date)")
        # second run still re-fetches the selection page to check what's
        # latest, but must not re-fetch the already-cached report itself
        self.assertEqual(client.calls, calls_after_first + 1)


class TestIndustryMap(unittest.TestCase):
    """E6: NSE Nifty 500 Industry classification -> equity_industry_map."""

    def test_parse_golden(self):
        from vanguard.pipeline.context.industry_map import parse_industry_map

        df = parse_industry_map(fx("ind_nifty500list_sample.csv"), date(2026, 7, 21))
        self.assertEqual(len(df), 5)
        self.assertTrue((df.as_of_date == date(2026, 7, 21)).all())
        reliance = df[df.symbol == "RELIANCE"].iloc[0]
        self.assertEqual(reliance.company_name, "Reliance Industries Ltd.")
        self.assertEqual(reliance["isin"], "INE002A01018")   # .isin is a Series method, use subscript

    def test_normalizes_comma_variant_industry_names(self):
        """The only two spots NSE's own Industry column differs from
        fpi_sector_flow's NSDL sector spelling (verified 2026-07-21: 18/20
        categories are identical strings) -- normalized so a plain join
        needs no separate mapping table."""
        from vanguard.pipeline.context.industry_map import parse_industry_map

        df = parse_industry_map(fx("ind_nifty500list_sample.csv"), date(2026, 7, 21))
        self.assertEqual(df[df.symbol == "RELIANCE"].iloc[0].industry,
                         "Oil, Gas & Consumable Fuels")
        self.assertEqual(df[df.symbol == "ZEEL"].iloc[0].industry,
                         "Media, Entertainment & Publication")
        # Already-identical names pass through unchanged
        self.assertEqual(df[df.symbol == "360ONE"].iloc[0].industry, "Financial Services")

    def test_parse_drift_on_missing_columns(self):
        from vanguard.pipeline.context.industry_map import parse_industry_map, ApiShapeDrift

        with self.assertRaises(ApiShapeDrift):
            parse_industry_map(b"Company,Symbol\nFoo,FOO\n", date(2026, 7, 21))

    def test_ingest_idempotent_per_day(self):
        from vanguard.pipeline.context.industry_map import ingest_industry_map

        class Client:
            calls = 0

            def get_bytes(self, url):
                self.calls += 1
                return fx("ind_nifty500list_sample.csv")

        with tempfile.TemporaryDirectory() as tmp:
            with patch("vanguard.pipeline.context.industry_map.RAW_DIR", Path(tmp) / "raw"):
                con = duckdb.connect(str(Path(tmp) / "t.duckdb"))
                try:
                    client = Client()
                    s1 = ingest_industry_map(client, con, today=date(2026, 7, 21))
                    n1 = con.execute("SELECT COUNT(*) FROM equity_industry_map").fetchone()[0]
                    s2 = ingest_industry_map(client, con, today=date(2026, 7, 21))
                    n2 = con.execute("SELECT COUNT(*) FROM equity_industry_map").fetchone()[0]
                finally:
                    con.close()
        self.assertEqual(s1, "ok:5")
        self.assertEqual(n1, 5)
        self.assertEqual(n2, 5)                                 # no duplicate rows
        self.assertEqual(s2, "ok:0 (up to date)")
        self.assertEqual(client.calls, 1)                       # second call served from cache

    def test_latest_symbol_industry_map(self):
        from vanguard.pipeline.context.industry_map import (
            ingest_industry_map, latest_symbol_industry_map)

        class Client:
            def get_bytes(self, url):
                return fx("ind_nifty500list_sample.csv")

        with tempfile.TemporaryDirectory() as tmp:
            with patch("vanguard.pipeline.context.industry_map.RAW_DIR", Path(tmp) / "raw"):
                con = duckdb.connect(str(Path(tmp) / "t.duckdb"))
                try:
                    ingest_industry_map(Client(), con, today=date(2026, 7, 21))
                    m = latest_symbol_industry_map(con)
                finally:
                    con.close()
        self.assertEqual(m["RELIANCE"], "Oil, Gas & Consumable Fuels")
        self.assertEqual(m["ABB"], "Capital Goods")
        self.assertNotIn("NOT_A_SYMBOL", m)

    def test_latest_symbol_industry_map_empty_when_table_missing(self):
        from vanguard.pipeline.context.industry_map import latest_symbol_industry_map

        with tempfile.TemporaryDirectory() as tmp:
            con = duckdb.connect(str(Path(tmp) / "empty.duckdb"))
            try:
                self.assertEqual(latest_symbol_industry_map(con), {})
            finally:
                con.close()
