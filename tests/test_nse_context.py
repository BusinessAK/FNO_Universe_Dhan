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

    def test_arming_gate_excludes_banned(self):
        from vanguard.live.trigger_engine import load_armed_book
        con = duckdb.connect()
        con.execute("CREATE TABLE daily_setups (date TIMESTAMP, symbol VARCHAR, "
                    "setup_type VARCHAR, bias VARCHAR, trigger_strike DOUBLE, "
                    "invalidation_strike DOUBLE)")
        con.execute("INSERT INTO daily_setups VALUES "
                    "('2026-07-17','KAYNES','GAMMA_SQUEEZE','Bullish Breakout',100,90),"
                    "('2026-07-17','RELIANCE','PINCH_ZONE','Compression',1300,1315)")
        con.execute("CREATE TABLE daily_ban (date TIMESTAMP, symbol VARCHAR)")
        con.execute("INSERT INTO daily_ban VALUES ('2026-07-17','KAYNES')")
        book = load_armed_book(con, ban_arming="exclude")
        self.assertNotIn("KAYNES", book)
        self.assertIn("RELIANCE", book)
        book2 = load_armed_book(con, ban_arming="annotate")
        self.assertIn("KAYNES", book2)
