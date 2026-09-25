import unittest
import datetime
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from queue import Queue

from models import PairConfig, PairMode, TaskType
from telegram_listener import MasterTelegramDispatcher
from telethon.tl import types as telethon_types

class DummyMessage:
    def __init__(self, msg_id: int, date: datetime.datetime, text: str = "", photo=None, document=None):
        self.id = msg_id
        self.date = date
        self.message = text
        self.photo = photo
        self.document = document
        self.is_reply = False
        self.peer_id = MagicMock()
        self.chat_id = -1001936359682

    async def get_reply_message(self):
        return None

    async def download_media(self, file=None):
        return None

class TestPastMessages(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self):
        self.loop.run_until_complete(asyncio.sleep(0))
        self.loop.close()

    def test_past_messages_retrieval_and_order(self):
        """Verify that past messages within cutoff are fetched, ordered chronologically, and dispatched."""
        pair1 = PairConfig(
            id=1,
            name="Pair-1-Test",
            channel="-1001936359682",
            mt5_path="dummy_path",
            mode=PairMode.TEXT,
            past_hours=2.0
        )
        pair2 = PairConfig(
            id=2,
            name="Pair-2-Test",
            channel="-1001936359682",
            mt5_path="dummy_path",
            mode=PairMode.TEXT,
            past_hours=0.0
        )

        q1 = Queue()
        q2 = Queue()
        dispatcher = MasterTelegramDispatcher(pairs=[pair1, pair2], pair_queues={1: q1, 2: q2})

        mock_entity = MagicMock()
        dispatcher.pair_entities[1] = mock_entity
        dispatcher.pair_entities[2] = mock_entity

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        m_recent = DummyMessage(103, now_utc - datetime.timedelta(minutes=30), text="EURUSD BUY 1.0800")
        m_mid = DummyMessage(102, now_utc - datetime.timedelta(minutes=90), text="GOLD BUY 2650")
        m_old = DummyMessage(101, now_utc - datetime.timedelta(hours=3), text="OLD SIGNAL 3H AGO")

        # iter_messages yields newest to oldest: 103, 102, 101
        async def mock_iter_messages(entity, limit=1000):
            for msg in [m_recent, m_mid, m_old]:
                yield msg

        mock_client = MagicMock()
        mock_client.iter_messages = mock_iter_messages
        dispatcher.client = mock_client

        # Run past messages processing
        self.loop.run_until_complete(dispatcher._fetch_and_process_past_messages())

        # Pair 1 (past_hours=2.0) should receive 102 then 103 (chronological order)
        self.assertEqual(q1.qsize(), 2)
        task_first = q1.get()
        task_second = q1.get()

        self.assertEqual(task_first.message_id, 102)
        self.assertEqual(task_first.text, "GOLD BUY 2650")

        self.assertEqual(task_second.message_id, 103)
        self.assertEqual(task_second.text, "EURUSD BUY 1.0800")

        # Pair 2 (past_hours=0.0) should NOT receive any past messages
        self.assertEqual(q2.qsize(), 0)

        # Check deduplication tracking: Msg 102 and 103 are recorded in dispatched_msg_ids
        self.assertIn(102, dispatcher.dispatched_msg_ids[1])
        self.assertIn(103, dispatcher.dispatched_msg_ids[1])

    def test_deduplication_prevents_duplicate_dispatch(self):
        """Verify that a message already processed as past message is ignored if received live."""
        pair = PairConfig(
            id=1,
            name="Pair-1-Test",
            channel="-1001936359682",
            mt5_path="dummy_path",
            mode=PairMode.TEXT,
            past_hours=1.0
        )
        q = Queue()
        dispatcher = MasterTelegramDispatcher(pairs=[pair], pair_queues={1: q})

        msg = DummyMessage(201, datetime.datetime.now(datetime.timezone.utc), text="BTC BUY 90000")

        # First dispatch as past message
        self.loop.run_until_complete(dispatcher._dispatch_message(msg, matching_pairs=[pair], is_past=True))
        self.assertEqual(q.qsize(), 1)
        task = q.get()
        self.assertEqual(task.message_id, 201)

        # Second dispatch of the same message (e.g. live event)
        self.loop.run_until_complete(dispatcher._dispatch_message(msg, matching_pairs=[pair], is_past=False))
        self.assertEqual(q.qsize(), 0, "Duplicate message should not be dispatched again")

    def test_service_messages_skipped(self):
        """Verify that Telethon MessageService objects are ignored during past message retrieval."""
        pair = PairConfig(
            id=1,
            name="Pair-1-Test",
            channel="-1001936359682",
            mt5_path="dummy_path",
            mode=PairMode.TEXT,
            past_hours=2.0
        )
        q = Queue()
        dispatcher = MasterTelegramDispatcher(pairs=[pair], pair_queues={1: q})
        dispatcher.pair_entities[1] = MagicMock()

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        normal_msg = DummyMessage(301, now_utc - datetime.timedelta(minutes=10), text="BUY GOLD")
        service_msg = telethon_types.MessageService(id=302, peer_id=MagicMock(), date=now_utc - datetime.timedelta(minutes=5), action=MagicMock())

        async def mock_iter(entity, limit=1000):
            yield service_msg
            yield normal_msg

        mock_client = MagicMock()
        mock_client.iter_messages = mock_iter
        dispatcher.client = mock_client

        self.loop.run_until_complete(dispatcher._fetch_and_process_past_messages())

        # Only the normal message should be queued
        self.assertEqual(q.qsize(), 1)
        t = q.get()
        self.assertEqual(t.message_id, 301)

if __name__ == "__main__":
    unittest.main()
