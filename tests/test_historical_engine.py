import unittest
from vanguard.core.historical_engine import HistoricalSessionResolver

class TestHistoricalSessionResolver(unittest.TestCase):
    def setUp(self):
        self.resolver = HistoricalSessionResolver("2026-05-22")

    def test_resolve_latest(self):
        self.assertFalse(self.resolver.is_historical("2026-05-22"))
        self.assertTrue(self.resolver.can_render_chain_charts("2026-05-22"))
        self.assertTrue(self.resolver.can_render_greeks_ledger("2026-05-22"))
        self.assertEqual(self.resolver.get_session_warning("2026-05-22"), "")

    def test_resolve_historical(self):
        self.assertTrue(self.resolver.is_historical("2026-05-21"))
        self.assertFalse(self.resolver.can_render_chain_charts("2026-05-21"))
        self.assertFalse(self.resolver.can_render_greeks_ledger("2026-05-21"))
        self.assertIn("GEX profile", self.resolver.get_session_warning("2026-05-21"))
