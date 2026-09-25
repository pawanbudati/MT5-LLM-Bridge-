import os
import base64
import json
import logging
import mimetypes
from pathlib import Path
from typing import Optional, Union, Dict, Any
import requests

from config import settings
from models import GeminiChartAnalysis, SignalAction, OrderTypeRecommended, ArrowIndication

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = """
You are an elite institutional trading chart analyst specialized in TradingView charts, technical analysis, price action, and order execution.
Your task is to analyze the provided image (which is a trading chart screenshot, often from TradingView) and extract all actionable trading parameters with maximum precision.

Examine the following elements thoroughly:
1. INSTRUMENT / SYMBOL:
   - Check the top-left corner of the TradingView chart (e.g., "XAUUSD, 15", "BTCUSD, 1h", "EURUSD, 5m", "GOLD", "US30", "NAS100").
   - Check any watermark, analyst text note, or accompanying message text.
   - Standardize to common tickers like XAUUSD, BTCUSD, USOIL, US30, EURUSD, GBPUSD, NAS100, etc.

2. TIMEFRAME:
   - Look at the header or near the symbol (e.g., 1m, 5m, 15m, 30m, 1h, 4h, D, W).

3. ARROW MARKS & DIRECTIONAL INDICATORS:
   - Identify any arrow marks drawn on the chart.
   - Determine direction (e.g. UP, DOWN, BREAKOUT_UP, BREAKOUT_DOWN).
   - Note the arrow color (green, red, yellow, blue, black, etc.) and its meaning.

4. KEY LEVELS & RANGES (ENTRY, STOP LOSS, TARGETS):
   - Look for TradingView "Long Position" or "Short Position" tools:
     * Long Position: Green target area on top, Red stop area below, middle boundary line is ENTRY price.
     * Short Position: Red stop area on top, Green target area below, middle boundary line is ENTRY price.
   - Look for horizontal lines / ray lines with exact price tags highlighted on the right-hand Y-axis.
   - Look for text annotations such as "Entry: 2650.50", "SL: 2642", "TP1: 2665", "TP2: 2678".

5. RANGE BREAKOUT ON BOTH SIDES (CRITICAL):
   - Often charts show a consolidation zone or range with upper and lower boundary levels (ranges on both sides).
   - If the price breaks the upper resistance level -> GO LONG (BUY).
   - If the price breaks the lower support level -> GO SHORT (SELL).
   - If the chart shows ranges/levels on both sides or a breakout projection, set `is_range_breakout: true`.
   - Extract:
     * range_high: upper boundary / resistance price
     * range_low: lower boundary / support price
     * upper_breakout_level: exact price trigger to enter BUY when broken above
     * upper_stop_loss: SL for the BUY order
     * upper_take_profit: TP for the BUY order
     * lower_breakout_level: exact price trigger to enter SELL when broken below
     * lower_stop_loss: SL for the SELL order
     * lower_take_profit: TP for the SELL order

6. TRADE ACTION & ORDER TYPE:
   - Determine action: BUY, SELL, BUY_LIMIT, SELL_LIMIT, BUY_STOP, SELL_STOP, or NONE.
   - Determine order_type: MARKET, LIMIT, or STOP.
   - If the image is not a trading chart setup (e.g., profit screenshot, meme, promotional banner, chat scrap), set is_valid_signal to false and action to NONE.

Output MUST be strictly valid JSON matching this schema:
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
    "description": "Black projection path showing retest and breakout"
  },
  "key_levels_found": ["Upper range 95.80", "Lower range 94.50", "Target 96.10"],
  "confidence": "HIGH",
  "analysis_summary": "Range breakout analysis on USOIL 15m. Watching upper breakout at 95.80 and lower breakdown at 94.50."
}
"""

class GeminiVisionClient:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = model or settings.GEMINI_MODEL
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/models"

    def _get_mime_type(self, file_path: Union[str, Path]) -> str:
        mime_type, _ = mimetypes.guess_type(str(file_path))
        if mime_type and mime_type.startswith("image/"):
            return mime_type
        return "image/jpeg"

    def analyze_chart(
        self, 
        image_input: Union[str, Path, bytes], 
        caption: Optional[str] = None,
        mime_type: Optional[str] = None
    ) -> GeminiChartAnalysis:
        """
        Analyze a TradingView chart image using Google Gemini Vision API.
        """
        if not self.api_key:
            logger.error("GEMINI_API_KEY is not set! Please configure GEMINI_API_KEY in .env")
            return GeminiChartAnalysis(
                is_valid_signal=False,
                action=SignalAction.NONE,
                analysis_summary="GEMINI_API_KEY missing in configuration."
            )

        # 1. Prepare Base64 Image Data
        if isinstance(image_input, (str, Path)):
            path = Path(image_input)
            if not path.exists():
                logger.error(f"Image file not found: {path}")
                return GeminiChartAnalysis(is_valid_signal=False, analysis_summary="File not found")
            if not mime_type:
                mime_type = self._get_mime_type(path)
            with open(path, "rb") as f:
                image_bytes = f.read()
        elif isinstance(image_input, bytes):
            image_bytes = image_input
            if not mime_type:
                mime_type = "image/jpeg"
        else:
            raise ValueError(f"Unsupported image_input type: {type(image_input)}")

        b64_image = base64.b64encode(image_bytes).decode("utf-8")

        # 2. Build User Prompt with Optional Telegram Caption
        prompt_text = "Analyze this TradingView chart image carefully and extract all key levels, instrument, timeframe, arrows, SL, TP, and trade direction."
        if caption and caption.strip():
            prompt_text += f"\n\nAdditional text context provided with message in channel:\n\"{caption.strip()}\""

        # 3. Construct Payload
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": f"{SYSTEM_INSTRUCTION}\n\n{prompt_text}"},
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": b64_image
                            }
                        }
                    ]
                }
            ],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": settings.GEMINI_TEMPERATURE
            }
        }

        # 4. Attempt API Request with Model Fallback
        models_to_try = [self.model]
        for fallback in ["gemini-3.8-flash", "gemini-2.5-flash", "gemini-1.5-flash", "gemini-2.0-flash"]:
            if fallback not in models_to_try:
                models_to_try.append(fallback)

        last_error = None
        for current_model in models_to_try:
            url = f"{self.base_url}/{current_model}:generateContent?key={self.api_key}"
            try:
                logger.info(f"Sending chart image to Gemini Vision API using model: {current_model}...")
                response = requests.post(
                    url, 
                    json=payload, 
                    headers={"Content-Type": "application/json"},
                    timeout=settings.GEMINI_TIMEOUT_SECONDS
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return self._parse_gemini_response(data)
                elif response.status_code == 404:
                    logger.warning(f"Model '{current_model}' returned 404 Not Found. Trying fallback model...")
                    last_error = f"Model {current_model} not found (404)"
                    continue
                else:
                    err_text = response.text[:300]
                    logger.error(f"Gemini API error (Status {response.status_code}): {err_text}")
                    last_error = f"HTTP {response.status_code}: {err_text}"
                    if response.status_code in (400, 401, 403, 429):
                        break
            except Exception as e:
                logger.error(f"Request exception with model {current_model}: {e}")
                last_error = str(e)

        return GeminiChartAnalysis(
            is_valid_signal=False,
            action=SignalAction.NONE,
            analysis_summary=f"Gemini API request failed: {last_error}"
        )

    def _parse_gemini_response(self, data: Dict[str, Any]) -> GeminiChartAnalysis:
        """Parse raw response from Gemini into GeminiChartAnalysis object."""
        try:
            candidates = data.get("candidates", [])
            if not candidates:
                logger.warning("Gemini returned empty candidates list.")
                return GeminiChartAnalysis(is_valid_signal=False, analysis_summary="No content generated")

            parts = candidates[0].get("content", {}).get("parts", [])
            if not parts:
                return GeminiChartAnalysis(is_valid_signal=False, analysis_summary="Empty parts in response")

            raw_text = parts[0].get("text", "").strip()

            if raw_text.startswith("```json"):
                raw_text = raw_text[7:]
            elif raw_text.startswith("```"):
                raw_text = raw_text[3:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]
            raw_text = raw_text.strip()

            parsed_json = json.loads(raw_text)

            raw_action = str(parsed_json.get("action", "NONE")).upper().replace(" ", "_")
            action_enum = SignalAction.NONE
            for act in SignalAction:
                if act.value == raw_action:
                    action_enum = act
                    break

            raw_order_type = str(parsed_json.get("order_type", "MARKET")).upper()
            order_type_enum = OrderTypeRecommended.MARKET
            for ot in OrderTypeRecommended:
                if ot.value == raw_order_type:
                    order_type_enum = ot
                    break

            arrow_data = parsed_json.get("arrow_indication")
            arrow_obj = None
            if arrow_data and isinstance(arrow_data, dict):
                arrow_obj = ArrowIndication(
                    detected=arrow_data.get("detected", False),
                    direction=arrow_data.get("direction"),
                    color=arrow_data.get("color"),
                    description=arrow_data.get("description")
                )

            return GeminiChartAnalysis(
                is_valid_signal=parsed_json.get("is_valid_signal", True),
                instrument=parsed_json.get("instrument"),
                timeframe=parsed_json.get("timeframe"),
                action=action_enum,
                order_type=order_type_enum,
                entry_price=parsed_json.get("entry_price"),
                entry_zone_min=parsed_json.get("entry_zone_min"),
                entry_zone_max=parsed_json.get("entry_zone_max"),
                stop_loss=parsed_json.get("stop_loss"),
                take_profit_1=parsed_json.get("take_profit_1"),
                take_profit_2=parsed_json.get("take_profit_2"),
                take_profit_3=parsed_json.get("take_profit_3"),
                arrow_indication=arrow_obj,
                is_range_breakout=parsed_json.get("is_range_breakout", False),
                range_high=parsed_json.get("range_high"),
                range_low=parsed_json.get("range_low"),
                upper_breakout_level=parsed_json.get("upper_breakout_level"),
                upper_stop_loss=parsed_json.get("upper_stop_loss"),
                upper_take_profit=parsed_json.get("upper_take_profit"),
                lower_breakout_level=parsed_json.get("lower_breakout_level"),
                lower_stop_loss=parsed_json.get("lower_stop_loss"),
                lower_take_profit=parsed_json.get("lower_take_profit"),
                key_levels_found=parsed_json.get("key_levels_found", []),
                confidence=parsed_json.get("confidence", "MEDIUM"),
                analysis_summary=parsed_json.get("analysis_summary", "")
            )
        except Exception as e:
            logger.error(f"Error parsing Gemini response: {e}")
            return GeminiChartAnalysis(
                is_valid_signal=False,
                action=SignalAction.NONE,
                analysis_summary=f"Parsing error: {e}"
            )
