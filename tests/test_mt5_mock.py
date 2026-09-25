import unittest
from unittest.mock import MagicMock, patch
from mt5_bridge import MT5Bridge
from models import TradeSignal, SignalAction, PairConfig, PairMode

class TestMT5Mock(unittest.TestCase):
    def setUp(self):
        pair = PairConfig(
            id=1,
            name="Mock-Pair",
            channel="-1001111111",
            mt5_path="C:\\mock\\terminal64.exe",
            mode=PairMode.BOTH,
            magic_number=123456,
            dry_run=True
        )
        self.bridge = MT5Bridge(pair_config=pair)
        self.bridge.connected = True

    def test_dry_run_market_trade(self):
        with patch("mt5_bridge.mt5") as mock_mt5:
            # Mock tick
            mock_tick = MagicMock()
            mock_tick.bid = 2650.0
            mock_tick.ask = 2650.5
            mock_mt5.symbol_info_tick.return_value = mock_tick

            # Mock symbol info
            mock_info = MagicMock()
            mock_info.name = "GOLD.i#"
            mock_info.digits = 2
            mock_info.volume_min = 0.01
            mock_info.volume_max = 50.0
            mock_info.volume_step = 0.01
            mock_info.visible = True
            mock_mt5.symbol_info.return_value = mock_info
            mock_mt5.symbol_select.return_value = True

            # Mock account
            mock_acc = MagicMock()
            mock_acc.balance = 50.0
            mock_mt5.account_info.return_value = mock_acc

            sig = TradeSignal(
                action=SignalAction.BUY,
                symbol="GOLD",
                stop_loss=2640.0,
                take_profit=2670.0
            )

            res = self.bridge.execute_signal(sig)
            self.assertTrue(res.success)
            self.assertEqual(res.action, "BUY")
            self.assertEqual(res.volume, 0.02)
            self.assertEqual(res.sl, 2640.0)
            self.assertEqual(res.tp, 2670.0)

    def test_dry_run_pending_trade(self):
        with patch("mt5_bridge.mt5") as mock_mt5:
            mock_tick = MagicMock()
            mock_tick.bid = 2650.0
            mock_tick.ask = 2650.5
            mock_mt5.symbol_info_tick.return_value = mock_tick

            mock_info = MagicMock()
            mock_info.name = "GOLD.i#"
            mock_info.digits = 2
            mock_info.volume_min = 0.01
            mock_info.volume_max = 50.0
            mock_info.volume_step = 0.01
            mock_info.visible = True
            mock_mt5.symbol_info.return_value = mock_info
            mock_mt5.symbol_select.return_value = True

            mock_acc = MagicMock()
            mock_acc.balance = 50.0
            mock_mt5.account_info.return_value = mock_acc

            sig = TradeSignal(
                action=SignalAction.BUY_LIMIT,
                symbol="GOLD",
                entry_price=2630.0,
                stop_loss=2620.0,
                take_profit=2650.0
            )

            res = self.bridge.execute_signal(sig)
            self.assertTrue(res.success)
            self.assertEqual(res.action, "BUY_LIMIT")
            self.assertEqual(res.price, 2630.0)
            self.assertEqual(res.sl, 2620.0)
            self.assertEqual(res.tp, 2650.0)

    def test_dry_run_buy_stop_pending(self):
        with patch("mt5_bridge.mt5") as mock_mt5:
            mock_tick = MagicMock()
            mock_tick.bid = 2649.5
            mock_tick.ask = 2650.0
            mock_mt5.symbol_info_tick.return_value = mock_tick

            mock_info = MagicMock()
            mock_info.name = "GOLD.i#"
            mock_info.digits = 2
            mock_info.point = 0.01
            mock_info.volume_min = 0.01
            mock_info.volume_max = 50.0
            mock_info.volume_step = 0.01
            mock_info.visible = True
            mock_mt5.symbol_info.return_value = mock_info
            mock_mt5.symbol_select.return_value = True

            mock_acc = MagicMock()
            mock_acc.balance = 50.0
            mock_mt5.account_info.return_value = mock_acc

            sig = TradeSignal(
                action=SignalAction.BUY_STOP,
                symbol="GOLD",
                entry_price=2655.0,
                stop_loss=2645.0,
                take_profit=2675.0
            )

            res = self.bridge.execute_signal(sig)
            self.assertTrue(res.success)
            self.assertEqual(res.action, "BUY_STOP")
            self.assertEqual(res.price, 2655.0)
            self.assertEqual(res.sl, 2645.0)
            self.assertEqual(res.tp, 2675.0)

    def test_dry_run_sell_stop_pending(self):
        with patch("mt5_bridge.mt5") as mock_mt5:
            mock_tick = MagicMock()
            mock_tick.bid = 2650.0
            mock_tick.ask = 2650.5
            mock_mt5.symbol_info_tick.return_value = mock_tick

            mock_info = MagicMock()
            mock_info.name = "GOLD.i#"
            mock_info.digits = 2
            mock_info.point = 0.01
            mock_info.volume_min = 0.01
            mock_info.volume_max = 50.0
            mock_info.volume_step = 0.01
            mock_info.visible = True
            mock_mt5.symbol_info.return_value = mock_info
            mock_mt5.symbol_select.return_value = True

            mock_acc = MagicMock()
            mock_acc.balance = 50.0
            mock_mt5.account_info.return_value = mock_acc

            sig = TradeSignal(
                action=SignalAction.SELL_STOP,
                symbol="GOLD",
                entry_price=2640.0,
                stop_loss=2650.0,
                take_profit=2620.0
            )

            res = self.bridge.execute_signal(sig)
            self.assertTrue(res.success)
            self.assertEqual(res.action, "SELL_STOP")
            self.assertEqual(res.price, 2640.0)
            self.assertEqual(res.sl, 2650.0)
            self.assertEqual(res.tp, 2620.0)

    def test_pending_order_breached_within_slippage_executes_market(self):
        with patch("mt5_bridge.mt5") as mock_mt5:
            mock_tick = MagicMock()
            mock_tick.bid = 2650.1
            mock_tick.ask = 2650.2  # 2650.2 > 2650.0 entry (20 points difference with point=0.01 <= 50 max slippage)
            mock_mt5.symbol_info_tick.return_value = mock_tick

            mock_info = MagicMock()
            mock_info.name = "GOLD.i#"
            mock_info.digits = 2
            mock_info.point = 0.01
            mock_info.volume_min = 0.01
            mock_info.volume_max = 50.0
            mock_info.volume_step = 0.01
            mock_info.visible = True
            mock_mt5.symbol_info.return_value = mock_info
            mock_mt5.symbol_select.return_value = True

            mock_acc = MagicMock()
            mock_acc.balance = 50.0
            mock_mt5.account_info.return_value = mock_acc

            sig = TradeSignal(
                action=SignalAction.BUY_STOP,
                symbol="GOLD",
                entry_price=2650.0,
                stop_loss=2640.0,
                take_profit=2670.0
            )

            res = self.bridge.execute_signal(sig)
            self.assertTrue(res.success)
            self.assertEqual(res.action, "BUY")  # Executed as immediate market order
            self.assertEqual(res.price, 2650.2)

    def test_pending_order_breached_beyond_slippage_rejected(self):
        with patch("mt5_bridge.mt5") as mock_mt5:
            mock_tick = MagicMock()
            mock_tick.bid = 2660.0
            mock_tick.ask = 2660.5  # 2660.5 is 1050 points past 2650.0 (way beyond max slippage)
            mock_mt5.symbol_info_tick.return_value = mock_tick

            mock_info = MagicMock()
            mock_info.name = "GOLD.i#"
            mock_info.digits = 2
            mock_info.point = 0.01
            mock_info.volume_min = 0.01
            mock_info.volume_max = 50.0
            mock_info.volume_step = 0.01
            mock_info.visible = True
            mock_mt5.symbol_info.return_value = mock_info
            mock_mt5.symbol_select.return_value = True

            mock_acc = MagicMock()
            mock_acc.balance = 50.0
            mock_mt5.account_info.return_value = mock_acc

            sig = TradeSignal(
                action=SignalAction.BUY_STOP,
                symbol="GOLD",
                entry_price=2650.0,
                stop_loss=2640.0,
                take_profit=2670.0
            )

            res = self.bridge.execute_signal(sig)
            self.assertFalse(res.success)
            self.assertIn("already crossed", res.comment)

if __name__ == "__main__":
    unittest.main()
