import os
import base64
import json
import logging
import mimetypes
from pathlib import Path
from typing import Optional, Union, Dict, Any, List
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

7. COMPLETED TRADE / PROFIT RECAP DETECTION:
   - Often channels re-share a chart AFTER the breakout or entry already occurred to celebrate the win (e.g., price has already broken out and hit TP/targets, chart caption says "TP1 Hit", "running in profit", "+50 pips", "Boom", "Enjoy profit").
   - If the chart shows a trade that has ALREADY broken out or already reached targets/completed, set `is_profit_recap: true` and `trade_already_triggered: true`.
   - If the chart is an upcoming / fresh trade waiting for breakout, set both to false.

8. CURRENT LIVE CHART PRICE:
   - Check the right-hand Y-axis price scale for the highlighted active market price badge or the current candle close price.
   - Extract this value as `chart_current_price` (float or null).

Output MUST be strictly valid JSON matching this schema:
{
  "is_valid_signal": true,
  "instrument": "USOIL",
  "timeframe": "15m",
  "action": "BUY_LIMIT",
  "order_type": "LIMIT",
  "chart_current_price": 95.12,
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
  "analysis_summary": "Range breakout analysis on USOIL 15m. Watching upper breakout at 95.80 and lower breakdown at 94.50.",
  "is_profit_recap": false,
  "trade_already_triggered": false
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
                chart_current_price=parsed_json.get("chart_current_price"),
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
                analysis_summary=parsed_json.get("analysis_summary", ""),
                is_profit_recap=bool(parsed_json.get("is_profit_recap", False)),
                trade_already_triggered=bool(parsed_json.get("trade_already_triggered", False))
            )
        except Exception as e:
            logger.error(f"Error parsing Gemini response: {e}")
            return GeminiChartAnalysis(
                is_valid_signal=False,
                action=SignalAction.NONE,
                analysis_summary=f"Parsing error: {e}"
            )

    def match_chart_candles_with_mt5(
        self,
        image_input: Union[str, Path, bytes],
        mt5_candles: List[Dict[str, Any]],
        timeframe: str = "15m",
        instrument: str = "USOIL",
        broker_symbol: str = "OILCash#",
        mime_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Correlate the visual candle structure in the chart image with the MT5 broker's recent candles
        for the same timeframe to calculate the exact price offset (MT5_Price - Chart_Price).
        Formula: MT5_Broker_Price = Chart_Price + Offset
        """
        if not self.api_key:
            logger.error("GEMINI_API_KEY is not set! Skipping candle matching.")
            return {"matched": False, "price_offset": 0.0, "confidence": "NONE", "reason": "No API key"}

        if not mt5_candles:
            return {"matched": False, "price_offset": 0.0, "confidence": "NONE", "reason": "No MT5 candles provided"}

        # 1. Prepare Base64 Image Data
        if isinstance(image_input, (str, Path)):
            path = Path(image_input)
            if not path.exists():
                logger.error(f"Image file not found: {path}")
                return {"matched": False, "price_offset": 0.0, "confidence": "NONE", "reason": "File not found"}
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

        # Format MT5 candles
        candle_lines = []
        for i, c in enumerate(mt5_candles, 1):
            t_str = c.get("time_str", "")
            direction = "BULLISH (GREEN)" if c.get("is_bullish") else "BEARISH (RED)"
            o = c.get("open")
            h = c.get("high")
            l = c.get("low")
            cl = c.get("close")
            candle_lines.append(
                f"  Candle #{i} ({t_str}): {direction} | Open: {o}, High: {h}, Low: {l}, Close: {cl} (Range: {c.get('range_size', '')})"
            )
        formatted_candles = "\n".join(candle_lines)

        prompt_text = f"""
You are an expert quantitative technical analyst and candle pattern correlation specialist.
Your task is to correlate the price scale of this TradingView chart image ({instrument}, timeframe: {timeframe}) with the live MetaTrader 5 broker contract ({broker_symbol}).

Due to broker contract specifications (e.g. USOILSPOT on TradingView vs OILCash on MT5), there is a price spread/offset between the chart's Y-axis price levels and MT5 broker prices. However, the candle structures (wicks, bodies, green/red sequences, swing peaks and swing troughs) are identical because they represent the same underlying crude oil market.

Here are the latest {len(mt5_candles)} candles from the MT5 broker terminal ({broker_symbol}, timeframe: {timeframe}):
{formatted_candles}

INSTRUCTIONS:
1. LOCATE AND MATCH THE CANDLES:
   - Look at the rightmost sequence of completed and forming candles visible in the chart image.
   - Match the visual pattern (bullish green vs bearish red candles, long wicks, dojis, engulfing bars, swing highs/lows) with the MT5 candle sequence listed above.
2. EXTRACT CHART PRICES FOR MATCHED CANDLES:
   - For 2 to 5 matched candles, read their exact or closest prices (High, Low, Close, or Open) using the chart's right-hand Y-axis scale and/or top-left OHLC display.
3. COMPUTE THE PRICE OFFSET:
   - Formula: Price Offset = MT5_Price - Chart_Price
   - (So that: MT5_Broker_Price = Chart_Price + Offset)
   - If MT5 price is higher than the chart price, Offset is POSITIVE (e.g. +0.35).
   - If MT5 price is lower than the chart price, Offset is NEGATIVE (e.g. -0.25).
4. RETURN STRICT JSON matching this schema:
{{
  "matched": true,
  "price_offset": 0.35,
  "confidence": "HIGH",
  "chart_sample_price": 70.50,
  "mt5_sample_price": 70.85,
  "matched_candles_count": 3,
  "matched_details": "Rightmost red candle on chart matches MT5 candle at 14:15. Chart High is 70.90, MT5 High is 71.25 -> diff +0.35.",
  "reasoning": "Consistent +0.35 spread across matched candles."
}}
If unable to correlate candles (e.g. chart timeframe doesn't match or image too blurry), set "matched": false, "price_offset": 0.0, "confidence": "LOW".
"""

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt_text},
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
                "temperature": 0.1
            }
        }

        models_to_try = [self.model]
        for fallback in ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-2.0-flash"]:
            if fallback not in models_to_try:
                models_to_try.append(fallback)

        for current_model in models_to_try:
            url = f"{self.base_url}/{current_model}:generateContent?key={self.api_key}"
            try:
                response = requests.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=settings.GEMINI_TIMEOUT_SECONDS
                )
                if response.status_code == 200:
                    data = response.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        content_parts = candidates[0].get("content", {}).get("parts", [])
                        if content_parts:
                            raw_text = content_parts[0].get("text", "")
                            parsed = self._extract_json_block(raw_text)
                            if parsed and isinstance(parsed, dict):
                                return parsed
            except Exception as e:
                logger.warning(f"Error calling Gemini candle matching with model {current_model}: {e}")

        return {"matched": False, "price_offset": 0.0, "confidence": "NONE", "reason": "Failed to call Gemini"}
