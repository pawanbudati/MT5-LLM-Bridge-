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

    def test_pending_orders_conditional(self):
        # 1. BUY ABOVE -> BUY_STOP
        sig1 = RuleSignalParser.parse("buy gold above 2650")
        self.assertEqual(sig1.action, SignalAction.BUY_STOP)
        self.assertEqual(sig1.symbol, "GOLD")
        self.assertEqual(sig1.entry_price, 2650.0)

        # 2. SELL BELOW -> SELL_STOP
        sig2 = RuleSignalParser.parse("sell gold below 2630")
        self.assertEqual(sig2.action, SignalAction.SELL_STOP)
        self.assertEqual(sig2.symbol, "GOLD")
        self.assertEqual(sig2.entry_price, 2630.0)

        # 3. BUY ABOVE with SL and TP
        sig3 = RuleSignalParser.parse("buy gold above 2650 sl 2640 tp 2680")
        self.assertEqual(sig3.action, SignalAction.BUY_STOP)
        self.assertEqual(sig3.symbol, "GOLD")
        self.assertEqual(sig3.entry_price, 2650.0)
        self.assertEqual(sig3.stop_loss, 2640.0)
        self.assertEqual(sig3.take_profit, 2680.0)

        # 4. SELL BELOW with SL and TP
        sig4 = RuleSignalParser.parse("sell gold below 2630 sl 2640 tp 2600")
        self.assertEqual(sig4.action, SignalAction.SELL_STOP)
        self.assertEqual(sig4.symbol, "GOLD")
        self.assertEqual(sig4.entry_price, 2630.0)
        self.assertEqual(sig4.stop_loss, 2640.0)
        self.assertEqual(sig4.take_profit, 2600.0)

        # 5. BUY BELOW -> BUY_LIMIT
        sig5 = RuleSignalParser.parse("buy gold below 2620 sl 2610 tp 2640")
        self.assertEqual(sig5.action, SignalAction.BUY_LIMIT)
        self.assertEqual(sig5.symbol, "GOLD")
        self.assertEqual(sig5.entry_price, 2620.0)
        self.assertEqual(sig5.stop_loss, 2610.0)
        self.assertEqual(sig5.take_profit, 2640.0)

        # 6. SELL ABOVE -> SELL_LIMIT
        sig6 = RuleSignalParser.parse("sell gold above 2660 sl 2670 tp 2640")
        self.assertEqual(sig6.action, SignalAction.SELL_LIMIT)
        self.assertEqual(sig6.symbol, "GOLD")
        self.assertEqual(sig6.entry_price, 2660.0)
        self.assertEqual(sig6.stop_loss, 2670.0)
        self.assertEqual(sig6.take_profit, 2640.0)

        # 7. Explicit BUY STOP without STOP SL collision
        sig7 = RuleSignalParser.parse("BUY STOP 2650 SL 2640 TP 2680")
        self.assertEqual(sig7.action, SignalAction.BUY_STOP)
        self.assertEqual(sig7.entry_price, 2650.0)
        self.assertEqual(sig7.stop_loss, 2640.0)
        self.assertEqual(sig7.take_profit, 2680.0)

        # 8. Explicit SELL STOP
        sig8 = RuleSignalParser.parse("SELL STOP 2630 SL 2640 TP 2600")
        self.assertEqual(sig8.action, SignalAction.SELL_STOP)
        self.assertEqual(sig8.entry_price, 2630.0)
        self.assertEqual(sig8.stop_loss, 2640.0)
        self.assertEqual(sig8.take_profit, 2600.0)

    def test_dual_breakout_multi_parsing(self):
        # 1. Delimited by slash
        text1 = "BUY GOLD ABOVE 2650 SL 2640 TP 2680 / SELL GOLD BELOW 2630 SL 2640 TP 2600"
        signals1 = RuleSignalParser.parse_multi(text1)
        self.assertEqual(len(signals1), 2)
        self.assertEqual(signals1[0].action, SignalAction.BUY_STOP)
        self.assertEqual(signals1[0].symbol, "GOLD")
        self.assertEqual(signals1[0].entry_price, 2650.0)
        self.assertEqual(signals1[0].stop_loss, 2640.0)
        self.assertEqual(signals1[0].take_profit, 2680.0)

        self.assertEqual(signals1[1].action, SignalAction.SELL_STOP)
        self.assertEqual(signals1[1].symbol, "GOLD")
        self.assertEqual(signals1[1].entry_price, 2630.0)
        self.assertEqual(signals1[1].stop_loss, 2640.0)
        self.assertEqual(signals1[1].take_profit, 2600.0)

        # 2. Multi-line with symbol header inheritance
        text2 = "GOLD BREAKOUT SETUP:\nBUY ABOVE 2650 SL 2640 TP 2680\nSELL BELOW 2630 SL 2640 TP 2600"
        signals2 = RuleSignalParser.parse_multi(text2)
        self.assertEqual(len(signals2), 2)
        self.assertEqual(signals2[0].action, SignalAction.BUY_STOP)
        self.assertEqual(signals2[0].symbol, "GOLD")
        self.assertEqual(signals2[0].entry_price, 2650.0)

        self.assertEqual(signals2[1].action, SignalAction.SELL_STOP)
        self.assertEqual(signals2[1].symbol, "GOLD")
        self.assertEqual(signals2[1].entry_price, 2630.0)

if __name__ == "__main__":
    unittest.main()
