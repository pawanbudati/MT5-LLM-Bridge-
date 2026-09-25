import unittest
from gemini_vision import GeminiVisionClient
from models import SignalAction, OrderTypeRecommended

class TestVision(unittest.TestCase):
    def setUp(self):
        self.client = GeminiVisionClient(api_key="mock_key", model="gemini-3.8-flash")

    def test_parse_gemini_response_breakout(self):
        mock_raw = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": '''```json
{
  "is_valid_signal": true,
  "instrument": "USOIL",
  "timeframe": "15m",
  "action": "BUY_LIMIT",
  "order_type": "LIMIT",
  "entry_price": 94.85,
  "entry_zone_min": 94.50,
  "entry_zone_max": 94.85,
  "stop_loss": 94.17,
  "take_profit_1": 96.10,
  "take_profit_2": 96.13,
  "take_profit_3": null,
  "is_range_breakout": true,
  "range_high": 95.80,
  "range_low": 94.50,
  "upper_breakout_level": 95.80,
  "upper_stop_loss": 94.85,
  "upper_take_profit": 97.20,
  "lower_breakout_level": 94.50,
  "lower_stop_loss": 95.10,
  "lower_take_profit": 93.20,
  "arrow_indication": {
    "detected": true,
    "direction": "UP",
    "color": "BLACK",
    "description": "Projection arrow"
  },
  "key_levels_found": ["Upper 95.80", "Lower 94.50"],
  "confidence": "HIGH",
  "analysis_summary": "USOIL range breakout setup"
}
```'''
                            }
                        ]
                    }
                }
            ]
        }

        res = self.client._parse_gemini_response(mock_raw)
        self.assertTrue(res.is_valid_signal)
        self.assertEqual(res.instrument, "USOIL")
        self.assertEqual(res.timeframe, "15m")
        self.assertEqual(res.action, SignalAction.BUY_LIMIT)
        self.assertEqual(res.order_type, OrderTypeRecommended.LIMIT)
        self.assertEqual(res.entry_price, 94.85)
        self.assertEqual(res.stop_loss, 94.17)
        self.assertEqual(res.take_profit_1, 96.10)
        self.assertTrue(res.is_range_breakout)
        self.assertEqual(res.upper_breakout_level, 95.80)
        self.assertEqual(res.lower_breakout_level, 94.50)
        self.assertIsNotNone(res.arrow_indication)
        self.assertTrue(res.arrow_indication.detected)
        self.assertEqual(res.arrow_indication.direction, "UP")

if __name__ == "__main__":
    unittest.main()
