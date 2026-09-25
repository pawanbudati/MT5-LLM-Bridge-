import re
import json
import logging
from typing import Optional, List
from config import settings
from models import TradeSignal, SignalAction
from rule_parser import RuleSignalParser
from utils import is_scrap_message

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert trading signal extractor supporting Gold, Bitcoin, US Oil, US 30, and Currency pairs.
Extract trading signals accurately into the specified JSON schema.
If an explicit symbol is provided in the message (e.g., GOLD, XAUUSD, BTC, BTCUSD, US OIL, USOIL, WTI, US 30, US30, EURUSD, GBPUSD, USDJPY, etc.), normalize and set it in "symbol".
If no symbol is mentioned in the message, default "symbol": "XAUUSD".

Allowed "action" values:
- "BUY" (immediate market buy)
- "SELL" (immediate market sell)
- "BUY_STOP" (buy breakout pending order, e.g. "BUY ABOVE <price>", "BUY IF BREAKS ABOVE <price>", "BUY STOP <price>")
- "SELL_STOP" (sell breakdown pending order, e.g. "SELL BELOW <price>", "SELL IF BREAKS BELOW <price>", "SELL STOP <price>")
- "BUY_LIMIT" (buy limit pending order, e.g. "BUY BELOW <price>", "BUY LIMIT <price>")
- "SELL_LIMIT" (sell limit pending order, e.g. "SELL ABOVE <price>", "SELL LIMIT <price>")
- "UPDATE_TARGETS_AND_SL" (set targets and stop loss, e.g. "TGT1- 4245 TGT2- 4235 SL- 4260")
- "UPDATE_SL" (change or update stop loss, e.g. "SL 4260", "Update SL 4260")
- "UPDATE_TP" (change or update take profit, e.g. "TP 4240", "Target 4240")
- "BREAKEVEN" (move stop loss to entry / cost / breakeven)
- "CLOSE_PARTIAL" (close half, 50%, partial position)
- "EXIT" (close all, exit trade now)
- "NONE" (casual chat, greeting, non-actionable message)

PENDING ORDER RULES:
- "BUY ABOVE <price>" or "BUY IF BREAKS ABOVE <price>" or "BUY STOP <price>": Action MUST be "BUY_STOP", with "entry": <price>. Do NOT output "BUY" (market order)!
- "SELL BELOW <price>" or "SELL IF BREAKS BELOW <price>" or "SELL STOP <price>": Action MUST be "SELL_STOP", with "entry": <price>. Do NOT output "SELL" (market order)!
- "BUY BELOW <price>" or "BUY LIMIT <price>": Action MUST be "BUY_LIMIT", with "entry": <price>.
- "SELL ABOVE <price>" or "SELL LIMIT <price>": Action MUST be "SELL_LIMIT", with "entry": <price>.
- NEVER execute market order ("BUY" or "SELL") when a conditional breakout/stop level ("ABOVE", "BELOW", "IF BREAKS", "STOP", "LIMIT") is stated!

RULES FOR TARGETS AND SL:
- When a message lists targets (TGT1, TGT2, TGT3, TP1, TP2) and/or SL:
  - This is an UPDATE_TARGETS_AND_SL action, NEVER EXIT!
  - Consider Target 1 as primary target, Target 2 as secondary target. Ignore Target 3.
  - Set "action": "UPDATE_TARGETS_AND_SL"
- ONLY set "action": "EXIT" if the message explicitly says "EXIT", "CLOSE NOW", or "CLOSE ALL". NEVER output EXIT for target or SL updates!

JSON Schema:
{
  "action": "BUY" | "SELL" | "BUY_STOP" | "SELL_STOP" | "BUY_LIMIT" | "SELL_LIMIT" | "UPDATE_TARGETS_AND_SL" | "UPDATE_SL" | "UPDATE_TP" | "BREAKEVEN" | "CLOSE_PARTIAL" | "EXIT" | "NONE",
  "symbol": "XAUUSD" | "BTCUSD" | "USOIL" | "US30" | "EURUSD" | string,
  "entry": float or null,
  "sl": float or null,
  "tp": float or null,
  "target_1": float or null,
  "target_2": float or null,
  "tps": [float, ...] or [],
  "close_ratio": float or null,
  "notes": "brief note" or null
}
"""

class LLMSignalEngine:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = model or settings.GEMINI_MODEL
        self.client = None
        self._init_client()

    def _init_client(self):
        if self.api_key and self.api_key.strip():
            try:
                from google import genai
                self.client = genai.Client(api_key=self.api_key.strip())
                logger.info(f"Gemini API client initialized successfully with model: {self.model}")
            except Exception as e:
                logger.error(f"Failed to initialize Gemini client: {e}")
                self.client = None

    def _get_client(self):
        if self.client is None:
            self._init_client()
        return self.client

    def parse_messages(self, message_text: str, reply_to_text: Optional[str] = None) -> List[TradeSignal]:
        """
        Parse a Telegram message into one or more TradeSignals.
        Supports dual breakout messages (e.g. BUY_STOP above X and SELL_STOP below Y).
        """
        if not message_text or not message_text.strip():
            return [TradeSignal(action=SignalAction.NONE, raw_message=message_text, parser_used="none")]

        if is_scrap_message(message_text):
            logger.info(f"Ignored non-signal/scrap message: '{message_text.strip()[:60]}'")
            return [TradeSignal(action=SignalAction.NONE, symbol="XAUUSD", raw_message=message_text, parser_used="filter")]

        # Check if the message contains multi-order setups (e.g. dual breakout)
        rule_multi = RuleSignalParser.parse_multi(message_text)
        if len(rule_multi) >= 2:
            logger.info(f"Detected multi-order signal setup ({len(rule_multi)} orders): {[s.action.value for s in rule_multi]}")
            return rule_multi

        # Single signal: delegate to parse_message
        return [self.parse_message(message_text, reply_to_text)]

    def parse_message(self, message_text: str, reply_to_text: Optional[str] = None) -> TradeSignal:
        """
        Parse a Telegram message using Google Gemini API.
        If Gemini fails, returns malformed output, or has no API key configured, automatically falls back to RuleSignalParser.
        """
        if not message_text or not message_text.strip():
            return TradeSignal(action=SignalAction.NONE, raw_message=message_text, parser_used="none")

        # Fast filter for scrap / chatter / pips hype messages
        if is_scrap_message(message_text):
            logger.info(f"Ignored non-signal/scrap message: '{message_text.strip()[:60]}'")
            return TradeSignal(action=SignalAction.NONE, symbol="XAUUSD", raw_message=message_text, parser_used="filter")

        client = self._get_client()
        if not client:
            logger.warning("Gemini API client not available. Falling back to RuleSignalParser.")
            return RuleSignalParser.parse(message_text)

        full_prompt = message_text
        if reply_to_text:
            full_prompt = f"[Context / Previous Message: {reply_to_text}]\n[New Message: {message_text}]"

        try:
            from google.genai import types
            response = client.models.generate_content(
                model=self.model,
                contents=f"Extract signal from this message: {full_prompt}",
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    temperature=0.1,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                )
            )
            raw_text = response.text or "{}"
            raw_json = raw_text.strip()
            if raw_json.startswith("```json"):
                raw_json = raw_json[7:]
            if raw_json.startswith("```"):
                raw_json = raw_json[3:]
            if raw_json.endswith("```"):
                raw_json = raw_json[:-3]
            raw_json = raw_json.strip()

            parsed = json.loads(raw_json)

            action_str = str(parsed.get("action", "NONE")).upper().strip()
            try:
                action = SignalAction(action_str)
            except ValueError:
                action = SignalAction.NONE

            symbol = parsed.get("symbol")
            if symbol:
                symbol = str(symbol).upper().strip()

            entry = float(parsed["entry"]) if parsed.get("entry") is not None else None
            sl = float(parsed["sl"]) if parsed.get("sl") is not None else None
            tp = float(parsed["tp"]) if parsed.get("tp") is not None else None

            tps = []
            if isinstance(parsed.get("tps"), list):
                for v in parsed["tps"]:
                    try:
                        tps.append(float(v))
                    except (ValueError, TypeError):
                        pass
            if tp is not None and tp not in tps:
                tps.insert(0, tp)
            elif not tp and tps:
                tp = tps[0]

            close_ratio = float(parsed["close_ratio"]) if parsed.get("close_ratio") is not None else None
            notes = parsed.get("notes")

            # Post-processing heuristics to handle common shorthand signals accurately
            text_upper = message_text.upper()
            if any(w in text_upper for w in ["BREAKEVEN", "BREAK EVEN", "SL TO ENTRY", "SL ENTRY", "SL TO COST"]):
                action = SignalAction.BREAKEVEN
                sl = None

            if any(w in text_upper for w in ["CLOSE ALL", "EXIT ALL", "EXIT NOW", "CLOSE THIS TRADE", "EXIT THIS TRADE"]):
                action = SignalAction.EXIT

            # Post-processing heuristics to handle conditional pending orders accurately
            if action == SignalAction.BUY:
                if re.search(r'\b(?:ABOVE|BREAKS?\s+ABOVE|BREAKOUT\s+ABOVE|BREAKS?|BREAKOUT|BUY\s+STOP)\b', text_upper):
                    action = SignalAction.BUY_STOP
                elif re.search(r'\b(?:BELOW|BUY\s+LIMIT)\b', text_upper):
                    action = SignalAction.BUY_LIMIT

            elif action == SignalAction.SELL:
                if re.search(r'\b(?:BELOW|BREAKS?\s+BELOW|BREAKDOWN\s+BELOW|BREAKS?|BREAKDOWN|SELL\s+STOP)\b', text_upper):
                    action = SignalAction.SELL_STOP
                elif re.search(r'\b(?:ABOVE|SELL\s+LIMIT)\b', text_upper):
                    action = SignalAction.SELL_LIMIT

            # If entry was missed by LLM on order signals, extract from text
            if entry is None and action in (
                SignalAction.BUY, SignalAction.SELL,
                SignalAction.BUY_LIMIT, SignalAction.SELL_LIMIT,
                SignalAction.BUY_STOP, SignalAction.SELL_STOP
            ):
                rule_res = RuleSignalParser.parse(message_text)
                if rule_res.entry_price is not None:
                    entry = rule_res.entry_price

            # Guard against hallucinating SL or TP when not in the message
            has_sl_keyword = any(k in text_upper for k in ["SL", "STOPLOSS", "STOP LOSS", "S/L"]) or bool(re.search(r'(?<!BUY\s)(?<!SELL\s)\bSTOP\b', text_upper))
            if not has_sl_keyword:
                sl = None
            elif entry is not None and sl is not None and abs(sl - entry) < 1e-6:
                if not any(k in text_upper for k in ["BREAKEVEN", "ENTRY"]):
                    sl = None

            has_tp_keyword = any(k in text_upper for k in ["TP", "TARGET", "TAKE PROFIT", "T/P"])
            if not has_tp_keyword:
                tp = None
                tps = []

            # Extract targets and SL from text if available
            tgt_matches = re.findall(r'(?:TGT[1-4]?|TARGET[1-4]?|TP[1-4]?)\s*[-:=@]?\s*([0-9]+(?:\.[0-9]+)?)', text_upper)
            extracted_targets = [float(t) for t in tgt_matches]
            target_1 = extracted_targets[0] if len(extracted_targets) > 0 else (float(parsed["target_1"]) if parsed.get("target_1") else None)
            target_2 = extracted_targets[1] if len(extracted_targets) > 1 else (float(parsed["target_2"]) if parsed.get("target_2") else None)

            sl_match = re.search(
                r'(?:UPDATE|MODIFY|MOVE|CHANGE|NEW|SET)?\s*(?<!BUY\s)(?<!SELL\s)\b(?:SL|STOP\s*LOSS|STOPLOSS|S/L)\b\s*[-:=@]?\s*([0-9]+(?:\.[0-9]+)?)',
                text_upper
            )
            if sl_match and sl is None:
                sl = float(sl_match.group(1))

            return TradeSignal(
                action=action,
                symbol=symbol or "XAUUSD",
                entry_price=entry,
                stop_loss=sl,
                take_profit=tp or target_1,
                target_1=target_1,
                target_2=target_2,
                take_profit_levels=tps or ([target_1] if target_1 else []),
                close_ratio=close_ratio,
                raw_message=message_text,
                notes=notes,
                parser_used="gemini_llm"
            )

        except Exception as e:
            logger.warning(f"Gemini API parse failed: {e}. Falling back to RuleSignalParser.")
            return RuleSignalParser.parse(message_text)
