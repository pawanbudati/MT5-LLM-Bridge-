import unittest
from unittest.mock import MagicMock
from mt5_bridge import MT5Bridge
from config import settings

class TestLotSizing(unittest.TestCase):
    def setUp(self):
        self.bridge = MT5Bridge()

    def make_mock_info(self, name, path="", min_vol=0.01, max_vol=50.0, step=0.01, base="USD", profit="USD"):
        info = MagicMock()
        info.name = name
        info.path = path
        info.volume_min = min_vol
        info.volume_max = max_vol
        info.volume_step = step
        info.currency_base = base
        info.currency_profit = profit
        return info

    def test_instrument_classification(self):
        tests = [
            ("GOLD", "GOLD.i#", "GOLD"),
            ("XAUUSD", "GOLD.i#", "GOLD"),
            ("BTC", "BTCUSD#", "BTC"),
            ("BTCUSD", "BTCUSD#", "BTC"),
            ("USOIL", "OILCash#", "USOIL"),
            ("WTI", "OILCash#", "USOIL"),
            ("CRUDE", "OILCash#", "USOIL"),
            ("US30", "US30Cash#", "US30"),
            ("US 30", "US30Cash#", "US30"),
            ("DJ30", "US30Cash#", "US30"),
            ("EURUSD", "EURUSD", "FOREX"),
            ("GBPUSD", "GBPUSD#", "FOREX"),
            ("USDJPY", "USDJPY", "FOREX"),
            ("AUDCAD", "AUDCAD.i#", "FOREX"),
            ("NAS100", "US100Cash#", "DEFAULT"),
        ]

        for inst, sym, expected in tests:
            mock_info = self.make_mock_info(sym)
            cat = self.bridge.classify_instrument(instrument=inst, symbol=sym, symbol_info=mock_info)
            self.assertEqual(cat, expected, f"Classification failed for {inst}/{sym}: got {cat}, expected {expected}")

    def test_base_lots(self):
        self.assertAlmostEqual(self.bridge.get_base_lot_for_instrument("GOLD"), 0.02)
        self.assertAlmostEqual(self.bridge.get_base_lot_for_instrument("BTC"), 0.03)
        self.assertAlmostEqual(self.bridge.get_base_lot_for_instrument("USOIL"), 0.02)
        self.assertAlmostEqual(self.bridge.get_base_lot_for_instrument("US30"), 0.10)
        self.assertAlmostEqual(self.bridge.get_base_lot_for_instrument("FOREX"), 0.10)
        self.assertAlmostEqual(self.bridge.get_base_lot_for_instrument("DEFAULT"), 0.02)

    def test_balance_scaling_simulation(self):
        # Test calculations with simulated balances
        base_size = 50.0

        test_cases = [
            # Balance, Category, Expected Lot
            (50.0, "GOLD", 0.02),
            (50.0, "BTC", 0.03),
            (50.0, "USOIL", 0.02),
            (50.0, "US30", 0.10),
            (50.0, "FOREX", 0.10),

            # Below base: min_base keeps base lot
            (25.0, "GOLD", 0.02),
            (40.0, "US30", 0.10),

            # 2x Multiplier ($100 balance)
            (100.0, "GOLD", 0.04),
            (100.0, "BTC", 0.06),
            (100.0, "USOIL", 0.04),
            (100.0, "US30", 0.20),
            (100.0, "FOREX", 0.20),

            # 3x Multiplier ($150 balance)
            (150.0, "GOLD", 0.06),
            (150.0, "BTC", 0.09),
            (150.0, "US30", 0.30),

            # 10x Multiplier ($500 balance)
            (500.0, "GOLD", 0.20),
            (500.0, "BTC", 0.30),
            (500.0, "USOIL", 0.20),
            (500.0, "US30", 1.00),
            (500.0, "FOREX", 1.00),
        ]

        for balance, category, expected in test_cases:
            base_lot = self.bridge.get_base_lot_for_instrument(category)
            if balance <= base_size:
                if settings.LOT_BELOW_BASE_MODE == "min_base":
                    multiplier = 1.0
                else:
                    multiplier = balance / base_size
            else:
                multiplier = balance / base_size

            lot = round(round((base_lot * multiplier) / 0.01) * 0.01, 2)
            self.assertEqual(lot, expected, f"Failed for Bal: {balance}, Cat: {category}. Got {lot}, expected {expected}")

if __name__ == "__main__":
    unittest.main()
