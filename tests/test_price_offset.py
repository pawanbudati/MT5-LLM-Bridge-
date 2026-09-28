import unittest
from unittest.mock import MagicMock, patch
import os

from config import settings, parse_price_offset
from models import GeminiChartAnalysis, TradeSignal, SignalAction, PairConfig
from mt5_bridge import MT5Bridge


class TestPriceOffset(unittest.TestCase):
    def test_parse_price_offset(self):
        self.assertEqual(parse_price_offset("0.35"), 0.35)
        self.assertEqual(parse_price_offset("+0.50"), 0.50)
        self.assertEqual(parse_price_offset("-0.25"), -0.25)
        self.assertEqual(parse_price_offset(0.42), 0.42)
        self.assertEqual(parse_price_offset(-1), -1.0)
        self.assertEqual(parse_price_offset("auto"), "auto")
        self.assertEqual(parse_price_offset("AUTO"), "auto")
        self.assertIsNone(parse_price_offset(""))
        self.assertIsNone(parse_price_offset(None))
        self.assertEqual(parse_price_offset("0"), 0.0)
        self.assertEqual(parse_price_offset(0), 0.0)
        self.assertIsNone(parse_price_offset("none"))

    def test_is_oil_instrument(self):
        self.assertTrue(settings.is_oil_instrument("USOIL"))
        self.assertTrue(settings.is_oil_instrument("USOILSPOT"))
        self.assertTrue(settings.is_oil_instrument("", "OILCash#"))
        self.assertTrue(settings.is_oil_instrument("WTI"))
        self.assertTrue(settings.is_oil_instrument("CRUDE"))
        self.assertFalse(settings.is_oil_instrument("GOLD"))
        self.assertFalse(settings.is_oil_instrument("BTCUSD"))
        self.assertFalse(settings.is_oil_instrument("EURUSD"))

    def test_config_price_offset_hierarchy(self):
        # 1. Global fallback for USOIL
        with patch.object(settings, "USOIL_PRICE_OFFSET", 0.30):
            with patch.object(settings, "PRICE_OFFSETS", {}):
                offset = settings.get_price_offset_for_instrument("USOILSPOT", broker_symbol="OILCash#")
                self.assertEqual(offset, 0.30)

        # 2. Global PRICE_OFFSETS dict override
        with patch.object(settings, "USOIL_PRICE_OFFSET", 0.30):
            with patch.object(settings, "PRICE_OFFSETS", {"USOIL": 0.45}):
                offset = settings.get_price_offset_for_instrument("USOIL")
                self.assertEqual(offset, 0.45)

        # 3. PairConfig override takes highest precedence
        pair_cfg = PairConfig(
            id=1,
            name="TestOilPair",
            channel_id="123",
            mt5_path="test",
            usoil_price_offset=0.60
        )
        with patch.object(settings, "USOIL_PRICE_OFFSET", 0.30):
            offset = settings.get_price_offset_for_instrument("USOILSPOT", pair_cfg=pair_cfg, broker_symbol="OILCash#")
            self.assertEqual(offset, 0.60)

    def test_apply_price_offset_to_analysis(self):
        pair_cfg = PairConfig(
            id=1,
            name="OilVision",
            channel_id="123",
            mt5_path="test",
            usoil_price_offset=0.30
        )
        bridge = MT5Bridge(pair_config=pair_cfg)

        analysis = GeminiChartAnalysis(
            instrument="USOILSPOT",
            upper_breakout_level=71.20,
            upper_stop_loss=70.50,
            upper_take_profit=72.80,
            lower_breakout_level=70.00,
            lower_stop_loss=70.70,
            lower_take_profit=68.50,
            range_high=71.20,
            range_low=70.00,
            chart_current_price=70.60
        )

        adjusted_analysis, applied = bridge.apply_price_offset_to_analysis(analysis, broker_symbol="OILCash#")

        self.assertEqual(applied, 0.30)
        self.assertEqual(adjusted_analysis.applied_price_offset, 0.30)
        self.assertAlmostEqual(adjusted_analysis.upper_breakout_level, 71.50)
        self.assertAlmostEqual(adjusted_analysis.upper_stop_loss, 70.80)
        self.assertAlmostEqual(adjusted_analysis.upper_take_profit, 73.10)
        self.assertAlmostEqual(adjusted_analysis.lower_breakout_level, 70.30)
        self.assertAlmostEqual(adjusted_analysis.lower_stop_loss, 71.00)
        self.assertAlmostEqual(adjusted_analysis.lower_take_profit, 68.80)
        self.assertAlmostEqual(adjusted_analysis.range_high, 71.50)
        self.assertAlmostEqual(adjusted_analysis.range_low, 70.30)

        # Ensure idempotency (applying again doesn't double-add)
        again, applied_again = bridge.apply_price_offset_to_analysis(adjusted_analysis, broker_symbol="OILCash#")
        self.assertEqual(applied_again, 0.30)
        self.assertAlmostEqual(again.upper_breakout_level, 71.50)

    def test_apply_price_offset_to_signal(self):
        pair_cfg = PairConfig(
            id=1,
            name="OilText",
            channel_id="123",
            mt5_path="test",
            usoil_price_offset=-0.25
        )
        bridge = MT5Bridge(pair_config=pair_cfg)

        signal = TradeSignal(
            symbol="USOIL",
            action=SignalAction.BUY,
            entry_price=70.50,
            stop_loss=69.80,
            take_profit=72.00,
            target_1=71.50,
            target_2=72.00,
            take_profit_levels=[71.50, 72.00]
        )

        adjusted_signal, applied = bridge.apply_price_offset_to_signal(signal, broker_symbol="OILCash#")

        self.assertEqual(applied, -0.25)
        self.assertEqual(adjusted_signal.applied_price_offset, -0.25)
        self.assertAlmostEqual(adjusted_signal.entry_price, 70.25)
        self.assertAlmostEqual(adjusted_signal.stop_loss, 69.55)
        self.assertAlmostEqual(adjusted_signal.take_profit, 71.75)
        self.assertAlmostEqual(adjusted_signal.target_1, 71.25)
        self.assertAlmostEqual(adjusted_signal.target_2, 71.75)
        self.assertEqual(adjusted_signal.take_profit_levels, [71.25, 71.75])

    @patch("mt5_bridge.mt5")
    def test_auto_price_offset(self, mock_mt5):
        # Configure "auto" offset
        pair_cfg = PairConfig(
            id=1,
            name="AutoOilPair",
            channel_id="123",
            mt5_path="test",
            usoil_price_offset="auto"
        )
        bridge = MT5Bridge(pair_config=pair_cfg)
        bridge.connected = True

        # Mock broker tick: MT5 mid = (70.80 + 70.82) / 2 = 70.81
        mock_tick = MagicMock()
        mock_tick.bid = 70.80
        mock_tick.ask = 70.82
        mock_mt5.symbol_info_tick.return_value = mock_tick

        # Chart shows USOILSPOT @ 70.50
        offset = bridge.get_price_offset("USOILSPOT", broker_symbol="OILCash#", chart_price=70.50)

        # Expected offset = 70.81 - 70.50 = +0.31
        self.assertAlmostEqual(offset, 0.31, places=3)

    def test_non_oil_unaffected_by_usoil_offset(self):
        pair_cfg = PairConfig(
            id=1,
            name="GoldPair",
            channel_id="123",
            mt5_path="test",
            usoil_price_offset=0.50
        )
        bridge = MT5Bridge(pair_config=pair_cfg)

        analysis = GeminiChartAnalysis(
            instrument="GOLD",
            upper_breakout_level=2650.0,
            chart_current_price=2645.0
        )

    def test_negative_offset_analysis(self):
        pair_cfg = PairConfig(
            id=1,
            name="OilVisionNeg",
            channel_id="123",
            mt5_path="test",
            usoil_price_offset=-0.40
        )
        bridge = MT5Bridge(pair_config=pair_cfg)

        analysis = GeminiChartAnalysis(
            instrument="USOIL",
            upper_breakout_level=72.00,
            lower_breakout_level=70.00,
            chart_current_price=71.00
        )

        adjusted, applied = bridge.apply_price_offset_to_analysis(analysis, broker_symbol="OILCash#")
        self.assertEqual(applied, -0.40)
        self.assertAlmostEqual(adjusted.upper_breakout_level, 71.60)
        self.assertAlmostEqual(adjusted.lower_breakout_level, 69.60)

    @patch("mt5_bridge.mt5")
    def test_execute_signal_calibrates_offset_automatically(self, mock_mt5):
        pair_cfg = PairConfig(
            id=1,
            name="OilSignal",
            channel_id="123",
            mt5_path="test",
            usoil_price_offset=0.35,
            dry_run=True
        )
        bridge = MT5Bridge(pair_config=pair_cfg)
        bridge.connected = True
        bridge.ensure_connected = MagicMock(return_value=True)
        bridge.resolve_symbol = MagicMock(return_value="OILCash#")

        mock_sym_info = MagicMock()
        mock_sym_info.name = "OILCash#"
        mock_sym_info.visible = True
        mock_sym_info.digits = 2
        mock_sym_info.volume_min = 0.01
        mock_sym_info.volume_max = 50.0
        mock_sym_info.volume_step = 0.01
        mock_sym_info.point = 0.01
        mock_mt5.symbol_info.return_value = mock_sym_info

        mock_acc = MagicMock()
        mock_acc.balance = 50.0
        mock_mt5.account_info.return_value = mock_acc

        mock_tick = MagicMock()
        mock_tick.bid = 70.85
        mock_tick.ask = 70.87
        mock_mt5.symbol_info_tick.return_value = mock_tick

        signal = TradeSignal(
            symbol="USOIL",
            action=SignalAction.BUY,
            entry_price=70.50,
            stop_loss=69.80,
            take_profit=72.00
        )

        res = bridge.execute_signal(signal)

        # Signal levels should be shifted by +0.35
        self.assertEqual(signal.applied_price_offset, 0.35)
        self.assertAlmostEqual(signal.entry_price, 70.85)
        self.assertAlmostEqual(signal.stop_loss, 70.15)
        self.assertAlmostEqual(signal.take_profit, 72.35)


if __name__ == "__main__":
    unittest.main()
