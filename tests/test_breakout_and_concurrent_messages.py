import unittest
import asyncio
import datetime
from unittest.mock import MagicMock, patch, AsyncMock
from queue import Queue

from models import (
    PairConfig, PairMode, TaskMessage, TaskType, BreakoutWatchSetup,
    SignalAction, ExecutionResult, GeminiChartAnalysis
)
from breakout_monitor import BreakoutMonitor
from telegram_listener import MasterTelegramDispatcher
from pair_worker import PairWorker


class DummyEvent:
    def __init__(self, chat_id, message_id=1, text="", photo=None, document=None):
        self.chat_id = chat_id
        self.message = MagicMock()
        self.message.id = message_id
        self.message.message = text
        self.message.photo = photo
        self.message.document = document
        self.message.is_reply = False
        self.message.peer_id = MagicMock()
        self.message.date = datetime.datetime.now(datetime.timezone.utc)
        self.chat = MagicMock()
        self.chat.id = chat_id
        self.chat.title = "Test Channel"
        self.chat.username = "test_channel"


class TestBreakoutAndConcurrentMessages(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self):
        self.loop.run_until_complete(asyncio.sleep(0))
        self.loop.close()

    def test_breakout_monitor_multiple_instruments_simultaneously(self):
        """Verify that BreakoutMonitor tracks multiple different instruments concurrently."""
        mock_bridge = MagicMock()
        mock_bridge.calculate_lot.return_value = 0.02
        mock_bridge.get_open_positions.return_value = []

        monitor = BreakoutMonitor(mock_bridge)

        setup_btc = BreakoutWatchSetup(
            setup_id="watch_BTCUSD_1",
            instrument="BTCUSD",
            broker_symbol="BTCUSD#",
            upper_breakout_level=65000.0,
            lower_breakout_level=64000.0
        )
        setup_oil = BreakoutWatchSetup(
            setup_id="watch_USOIL_2",
            instrument="USOIL",
            broker_symbol="OILCash#",
            upper_breakout_level=72.0,
            lower_breakout_level=70.0
        )

        with patch("MetaTrader5.symbol_info_tick", return_value=MagicMock(bid=64500.0, ask=64505.0)), \
             patch("MetaTrader5.terminal_info", return_value=None):
            monitor.add_setup(setup_btc)

        with patch("MetaTrader5.symbol_info_tick", return_value=MagicMock(bid=71.0, ask=71.05)), \
             patch("MetaTrader5.terminal_info", return_value=None):
            monitor.add_setup(setup_oil)

        # Both setups must be active simultaneously
        self.assertEqual(len(monitor.active_setups), 2)
        self.assertIn("watch_BTCUSD_1", monitor.active_setups)
        self.assertIn("watch_USOIL_2", monitor.active_setups)

        # Adding a newer setup for BTCUSD should supersede the old BTCUSD setup but keep USOIL intact
        setup_btc_new = BreakoutWatchSetup(
            setup_id="watch_BTCUSD_3",
            instrument="BTCUSD",
            broker_symbol="BTCUSD#",
            upper_breakout_level=65200.0,
            lower_breakout_level=63800.0
        )
        with patch("MetaTrader5.symbol_info_tick", return_value=MagicMock(bid=64600.0, ask=64605.0)), \
             patch("MetaTrader5.terminal_info", return_value=None):
            monitor.add_setup(setup_btc_new)

        self.assertEqual(len(monitor.active_setups), 2)
        self.assertNotIn("watch_BTCUSD_1", monitor.active_setups, "Old BTC setup should be superseded")
        self.assertIn("watch_BTCUSD_3", monitor.active_setups, "New BTC setup should be active")
        self.assertIn("watch_USOIL_2", monitor.active_setups, "USOIL setup must still be active")

    def test_live_text_message_dispatched_in_image_mode(self):
        """Verify that when a pair is in IMAGE mode, text-only messages are dispatched as TEXT_TASK rather than ignored."""
        pair = PairConfig(
            id=1,
            name="Ansh-Chart-Vision",
            channel="-1001936359682",
            mt5_path="dummy",
            mode=PairMode.IMAGE,
            past_hours=0.0
        )
        q = Queue()
        dispatcher = MasterTelegramDispatcher(pairs=[pair], pair_queues={1: q})
        dispatcher.channel_pairs_map["-1001936359682"] = [pair]

        event = DummyEvent(
            chat_id=-1001936359682,
            message_id=501,
            text="USOIL BUY 71.50 SL 70.80 TP 73.00"
        )

        self.loop.run_until_complete(dispatcher._handle_incoming_event(event, is_edit=False))

        self.assertEqual(q.qsize(), 1, "Text message must be dispatched even if pair mode is IMAGE")
        task: TaskMessage = q.get()
        self.assertEqual(task.task_type, TaskType.TEXT_TASK)
        self.assertEqual(task.message_id, 501)
        self.assertIn("USOIL BUY", task.text)

    def test_edited_messages_are_processed_and_not_deduplicated(self):
        """Verify that message edits are allowed through deduplication."""
        pair = PairConfig(
            id=1,
            name="Pair-Test",
            channel="-1001936359682",
            mt5_path="dummy",
            mode=PairMode.TEXT,
            past_hours=0.0
        )
        q = Queue()
        dispatcher = MasterTelegramDispatcher(pairs=[pair], pair_queues={1: q})
        dispatcher.channel_pairs_map["-1001936359682"] = [pair]

        # Initial message
        event1 = DummyEvent(chat_id=-1001936359682, message_id=601, text="Initial text")
        self.loop.run_until_complete(dispatcher._handle_incoming_event(event1, is_edit=False))
        self.assertEqual(q.qsize(), 1)
        q.get()

        # Duplicate initial message (not edit) should be skipped
        self.loop.run_until_complete(dispatcher._handle_incoming_event(event1, is_edit=False))
        self.assertEqual(q.qsize(), 0, "Duplicate non-edit message should be skipped")

        # Edited message should be dispatched
        event_edited = DummyEvent(chat_id=-1001936359682, message_id=601, text="Updated signal: BUY GOLD 2655")
        self.loop.run_until_complete(dispatcher._handle_incoming_event(event_edited, is_edit=True))
        self.assertEqual(q.qsize(), 1, "Edited message must be dispatched")
        task = q.get()
        self.assertIn("BUY GOLD 2655", task.text)

    def test_smart_ignore_when_trade_already_triggered(self):
        """Verify that when a setup was already executed, re-sharing the same chart/levels is smartly ignored."""
        mock_bridge = MagicMock()
        mock_bridge.calculate_lot.return_value = 0.02
        mock_bridge.get_open_positions.return_value = []

        monitor = BreakoutMonitor(mock_bridge)

        setup_btc = BreakoutWatchSetup(
            setup_id="watch_BTCUSD_10",
            instrument="BTCUSD",
            broker_symbol="BTCUSD#",
            upper_breakout_level=65000.0,
            lower_breakout_level=64000.0,
            image_hash="hash_abc_123"
        )

        with patch("MetaTrader5.symbol_info_tick", return_value=MagicMock(bid=64500.0, ask=64505.0)), \
             patch("MetaTrader5.terminal_info", return_value=None):
            monitor.add_setup(setup_btc)
            self.assertEqual(len(monitor.active_setups), 1)

            # Simulate breakout triggering BUY
            monitor.record_triggered_setup(setup_btc, "BUY")
            del monitor.active_setups[setup_btc.setup_id]

        # Admin posts the same successful breakout image later celebrating profit
        reposted_setup = BreakoutWatchSetup(
            setup_id="watch_BTCUSD_11",
            instrument="BTCUSD",
            broker_symbol="BTCUSD#",
            upper_breakout_level=65000.0,
            lower_breakout_level=64000.0,
            image_hash="hash_abc_123"
        )
        with patch("MetaTrader5.symbol_info_tick", return_value=MagicMock(bid=65400.0, ask=65405.0)), \
             patch("MetaTrader5.terminal_info", return_value=None):
            monitor.add_setup(reposted_setup, caption="BTCUSD BOOM +400 pips running in profit!")

        # It must NOT be added to active setups
        self.assertEqual(len(monitor.active_setups), 0, "Duplicate/profit recap setup must be smartly ignored")

    def test_smart_ignore_when_open_position_running_in_profit(self):
        """Verify that when MT5 already has an active profitable position on a symbol and price is past breakout, setup is ignored."""
        mock_pos = MagicMock()
        mock_pos.type = 0  # POSITION_TYPE_BUY
        mock_pos.profit = 25.50

        mock_bridge = MagicMock()
        mock_bridge.calculate_lot.return_value = 0.02
        mock_bridge.get_open_positions.return_value = [mock_pos]

        monitor = BreakoutMonitor(mock_bridge)

        setup_gold = BreakoutWatchSetup(
            setup_id="watch_GOLD_20",
            instrument="GOLD",
            broker_symbol="GOLD.i#",
            upper_breakout_level=2650.0,
            lower_breakout_level=2635.0
        )

        # Current price is 2655 (past the 2650 breakout level)
        with patch("MetaTrader5.symbol_info_tick", return_value=MagicMock(bid=2654.5, ask=2655.0)), \
             patch("MetaTrader5.terminal_info", return_value=None), \
             patch("MetaTrader5.POSITION_TYPE_BUY", 0):
            monitor.add_setup(setup_gold, caption="GOLD TP1 Hit, running in profit!")

        self.assertEqual(len(monitor.active_setups), 0, "Setup with existing profitable running position must be ignored")

    def test_smart_ignore_gemini_recap_flag(self):
        """Verify that when Gemini Vision identifies chart as a profit recap, it is ignored."""
        mock_bridge = MagicMock()
        mock_bridge.get_open_positions.return_value = []
        monitor = BreakoutMonitor(mock_bridge)

        setup_oil = BreakoutWatchSetup(
            setup_id="watch_USOIL_30",
            instrument="USOIL",
            broker_symbol="OILCash#",
            upper_breakout_level=71.0,
            lower_breakout_level=69.0
        )
        analysis = GeminiChartAnalysis(
            is_valid_signal=True,
            instrument="USOIL",
            upper_breakout_level=71.0,
            lower_breakout_level=69.0,
            is_profit_recap=True,
            trade_already_triggered=True
        )

        with patch("MetaTrader5.symbol_info_tick", return_value=MagicMock(bid=70.0, ask=70.05)), \
             patch("MetaTrader5.terminal_info", return_value=None):
            monitor.add_setup(setup_oil, analysis=analysis)

        self.assertEqual(len(monitor.active_setups), 0, "Profit recap chart must be ignored")

    def test_cancel_pending_breakout_when_direct_signal_arrives(self):
        """Verify that cancel_setup_for_symbol invalidates pending breakout observation."""
        mock_bridge = MagicMock()
        mock_bridge.get_open_positions.return_value = []
        monitor = BreakoutMonitor(mock_bridge)

        setup = BreakoutWatchSetup(
            setup_id="watch_BTCUSD_40",
            instrument="BTCUSD",
            broker_symbol="BTCUSD#",
            upper_breakout_level=65000.0,
            lower_breakout_level=64000.0
        )
        with patch("MetaTrader5.symbol_info_tick", return_value=MagicMock(bid=64500.0, ask=64505.0)), \
             patch("MetaTrader5.terminal_info", return_value=None):
            monitor.add_setup(setup)
            self.assertIn("watch_BTCUSD_40", monitor.active_setups)

            # Direct signal arrives for BTCUSD
            monitor.cancel_setup_for_symbol("BTCUSD#", instrument="BTCUSD", reason="SUPERSEDED_BY_DIRECT_SIGNAL")

        self.assertEqual(len(monitor.active_setups), 0, "Pending breakout must be cancelled by cancel_setup_for_symbol")

    def test_worker_handles_dual_breakout_text_signals(self):
        """Verify that _handle_text_task executes both BUY_STOP and SELL_STOP for dual breakout message."""
        pair_cfg = PairConfig(
            id=1,
            name="Pair1",
            channel="-1001111111",
            mt5_path="C:\\mock\\terminal64.exe",
            mode=PairMode.TEXT,
            magic_number=111111,
            dry_run=True
        )
        task_q = Queue()
        stop_event = asyncio.Event()
        worker = PairWorker(pair_cfg, task_q, stop_event)
        worker.bridge = MagicMock()
        worker.bridge.resolve_symbol.return_value = "GOLD.i#"
        worker.bridge.execute_signal.return_value = ExecutionResult(success=True, action="PENDING", comment="OK")

        task = TaskMessage(
            task_type=TaskType.TEXT_TASK,
            pair_id=1,
            channel_id="-1001111111",
            message_id=99,
            text="BUY GOLD ABOVE 2650 SL 2640 TP 2680 / SELL GOLD BELOW 2630 SL 2640 TP 2600"
        )

        self.loop.run_until_complete(worker._handle_text_task(task))

        # Check that execute_signal was called twice
        self.assertEqual(worker.bridge.execute_signal.call_count, 2)
        call_signals = [call.args[0] for call in worker.bridge.execute_signal.call_args_list]

        # First signal: BUY_STOP @ 2650
        self.assertEqual(call_signals[0].action, SignalAction.BUY_STOP)
        self.assertEqual(call_signals[0].entry_price, 2650.0)
        self.assertEqual(call_signals[0].stop_loss, 2640.0)
        self.assertEqual(call_signals[0].take_profit, 2680.0)

        # Second signal: SELL_STOP @ 2630
        self.assertEqual(call_signals[1].action, SignalAction.SELL_STOP)
        self.assertEqual(call_signals[1].entry_price, 2630.0)
        self.assertEqual(call_signals[1].stop_loss, 2640.0)
        self.assertEqual(call_signals[1].take_profit, 2600.0)


if __name__ == "__main__":
    unittest.main()
