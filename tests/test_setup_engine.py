import unittest
from src.core.setup_detector import SetupEngine
from src.config.setup_registry import SETUP_REGISTRY

class TestSetupEngine(unittest.TestCase):
    def setUp(self):
        self.engine = SetupEngine()

    def test_scan_setups_empty(self):
        result = self.engine.scan_setups({}, [], "2026-05-22")
        for key in ["GAMMA_SQUEEZE", "VOLATILITY_COIL", "FLOOR_BOUNCE", "DEALER_DEFENSE", "REGIME_SHIFT", "INVENTORY_MIGRATION"]:
            self.assertEqual(len(result[key]), 0)

    def test_scan_setups_matching(self):
        history = {
            "TEST": {
                "2026-05-22": {
                    "setups": ["GAMMA_SQUEEZE", "VOLATILITY_COIL"],
                    "ifs_score": 50.0
                }
            }
        }
        result = self.engine.scan_setups(history, ["TEST"], "2026-05-22")
        self.assertEqual(len(result["GAMMA_SQUEEZE"]), 1)
        self.assertEqual(result["GAMMA_SQUEEZE"][0][0], "TEST")
