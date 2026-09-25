import os
import unittest
from config import settings
from models import PairMode

class TestConfig(unittest.TestCase):
    def test_configured_pairs_discovery(self):
        pairs = settings.get_configured_pairs()
        self.assertGreaterEqual(len(pairs), 2, "Should discover at least Pair 1 and Pair 2")

        # Check Pair 1 (Ansh)
        p1 = next((p for p in pairs if p.id == 1), None)
        self.assertIsNotNone(p1, "Pair 1 should be found")
        self.assertEqual(p1.mode, PairMode.IMAGE)
        self.assertEqual(p1.channel, "-1001936359682")
        self.assertIn("MT5-Ansh-Tel-Bot", p1.mt5_path)
        self.assertEqual(p1.magic_number, 777999)

        # Check Pair 2 (TWM)
        p2 = next((p for p in pairs if p.id == 2), None)
        self.assertIsNotNone(p2, "Pair 2 should be found")
        self.assertEqual(p2.mode, PairMode.TEXT)
        self.assertEqual(p2.channel, "-1003387639038")
        self.assertIn("MT5_TWM_Forex_Premium_Group", p2.mt5_path)
        self.assertEqual(p2.magic_number, 888123)

    def test_dynamic_lot_settings(self):
        self.assertTrue(settings.USE_DYNAMIC_LOT)
        self.assertEqual(settings.BASE_ACCOUNT_SIZE, 50.0)
        self.assertEqual(settings.LOT_GOLD_PER_50, 0.02)
        self.assertEqual(settings.LOT_BTC_PER_50, 0.03)
        self.assertEqual(settings.LOT_USOIL_PER_50, 0.02)
        self.assertEqual(settings.LOT_US30_PER_50, 0.10)
        self.assertEqual(settings.LOT_FOREX_PER_50, 0.10)

    def test_symbol_mappings(self):
        mappings = settings.load_mappings()
        self.assertIsInstance(mappings, dict)
        self.assertIn("GOLD", mappings)
        self.assertIn("USOIL", mappings)
        self.assertIn("BTCUSD", mappings)

if __name__ == "__main__":
    unittest.main()
