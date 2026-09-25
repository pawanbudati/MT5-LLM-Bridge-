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


if __name__ == "__main__":
    unittest.main()
