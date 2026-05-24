import unittest
import pandas as pd
from src.core.market_structure_engine import MarketStructureEngine
from src.models.states import MarketState

class TestMarketStructureEngine(unittest.TestCase):
    def setUp(self):
        self.engine = MarketStructureEngine()

    def test_compute_structure_empty(self):
        latest = {"spot_close": 100.0, "call_wall": 105.0, "put_wall": 95.0}
        state = self.engine.compute_structure("TEST", "2026-05-22", pd.DataFrame(), latest)
        self.assertEqual(state.spot, 100.0)
        self.assertEqual(state.call_wall, 105.0)
        self.assertEqual(state.put_wall, 95.0)

    def test_compute_structure_dynamic(self):
        greeks_data = pd.DataFrame([
            {"SYMBOL": "TEST", "SPOT": 101.5, "STRIKE_PR": 95.0, "OPTION_TYP": "PE", "GEX": -50000.0, "OPEN_INT": 1000.0},
            {"SYMBOL": "TEST", "SPOT": 101.5, "STRIKE_PR": 105.0, "OPTION_TYP": "CE", "GEX": 150000.0, "OPEN_INT": 1200.0}
        ])
        latest = {"ifs_score": 25.0}
        state = self.engine.compute_structure("TEST", "2026-05-22", greeks_data, latest)
        self.assertEqual(state.spot, 101.5)
        self.assertEqual(state.call_wall, 105.0)
        self.assertEqual(state.put_wall, 95.0)
        self.assertEqual(state.ifs_score, 25.0)
