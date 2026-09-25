import unittest
from rule_parser import RuleSignalParser
from models import SignalAction
from utils import is_scrap_message

class TestSignals(unittest.TestCase):
    def test_scrap_detection(self):
        scrap_messages = [
            "Good morning guys! Have a wonderful trading day.",
            "Check out our new YouTube video: https://youtu.be/xyz",
            "300 PIPS RUNNING BOOKED PROFIT ENJOY!",
            "TP1 HIT BOOM CONGRATULATIONS TO ALL VIP MEMBERS!",
            "Join our VIP channel now: t.me/joinchat",
            "Please share your experience and feedback in comments!",
        ]
        for msg in scrap_messages:
            self.assertTrue(is_scrap_message(msg), f"Should detect as scrap: {msg}")

        trading_messages = [
            "GOLD BUY NOW @2650 SL 2640 TP 2670",
            "US 30 SELL 42100 SL 42250 TP 41800",
            "TGT1- 4245 TGT2- 4235 SL- 4260",
            "Move SL to Breakeven",
            "Close 50% now",
            "Exit now",
        ]
        for msg in trading_messages:
            self.assertFalse(is_scrap_message(msg), f"Should NOT detect as scrap: {msg}")

    def test_rule_parser_orders(self):
        # 1. Market BUY
        sig1 = RuleSignalParser.parse("GOLD BUY NOW 2650 SL 2642 TP 2668")
        self.assertEqual(sig1.action, SignalAction.BUY)
        self.assertEqual(sig1.symbol, "GOLD")
        self.assertEqual(sig1.entry_price, 2650.0)
        self.assertEqual(sig1.stop_loss, 2642.0)
        self.assertEqual(sig1.take_profit, 2668.0)

        # 2. Market SELL
        sig2 = RuleSignalParser.parse("BTC SELL @95200 SL 96000 TP 93000")
        self.assertEqual(sig2.action, SignalAction.SELL)
        self.assertEqual(sig2.symbol, "BTC")
        self.assertEqual(sig2.entry_price, 95200.0)
        self.assertEqual(sig2.stop_loss, 96000.0)
        self.assertEqual(sig2.take_profit, 93000.0)

        # 3. Targets and SL update
        sig3 = RuleSignalParser.parse("TGT1- 4245\nTGT2- 4235\nSL- 4260")
        self.assertEqual(sig3.action, SignalAction.UPDATE_TARGETS_AND_SL)
        self.assertEqual(sig3.target_1, 4245.0)
        self.assertEqual(sig3.target_2, 4235.0)
        self.assertEqual(sig3.stop_loss, 4260.0)

        # 4. Breakeven
        sig4 = RuleSignalParser.parse("Move SL to Breakeven")
        self.assertEqual(sig4.action, SignalAction.BREAKEVEN)

        # 5. Partial Close
        sig5 = RuleSignalParser.parse("Close half now")
        self.assertEqual(sig5.action, SignalAction.CLOSE_PARTIAL)
        self.assertEqual(sig5.close_ratio, 0.5)

        # 6. Exit
        sig6 = RuleSignalParser.parse("Exit now")
        self.assertEqual(sig6.action, SignalAction.EXIT)

if __name__ == "__main__":
    unittest.main()
