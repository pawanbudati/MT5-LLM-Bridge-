import re
from typing import Optional, List
from models import TradeSignal, SignalAction
from utils import is_scrap_message
from config import settings

class RuleSignalParser:
    """
    Fast rule-based regex signal parser.
    Acts as a high-speed parser and fallback when the LLM is busy or unreachable.
    Supports single signals, multi-clause breakout setups (BUY_STOP & SELL_STOP), and pending orders.
    """

    KNOWN_SYMBOLS = [
        "GOLD", "XAUUSD", "SILVER", "XAGUSD", "EURUSD", "GBPUSD", "USDJPY",
        "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY",
        "US 30", "US30", "NAS100", "US100", "SPX500", "US500",
        "BTCUSD", "BTC", "BITCOIN", "ETHUSD", "US OIL", "USOIL", "OIL", "WTI", "CRUDE", "BRENT"
    ]

    @classmethod
    def parse_multi(cls, text: str) -> List[TradeSignal]:
        """
        Parse one or more trading signals from a message.
        Handles dual breakout setups (e.g. 'BUY GOLD ABOVE 2650 ... / SELL GOLD BELOW 2630 ...').
        """
        raw = text.strip()
        cleaned = re.sub(r'[*_`#]', '', raw).upper()

        if is_scrap_message(text) or len(cleaned) < 5:
            return [TradeSignal(action=SignalAction.NONE, symbol="XAUUSD", raw_message=text, parser_used="rule")]

        # Determine primary symbol from whole text to inherit in sub-clauses if needed
        primary_symbol = None
        for sym in cls.KNOWN_SYMBOLS:
            if re.search(r'\b' + re.escape(sym) + r'\b', cleaned):
                primary_symbol = sym
                break

        has_buy = bool(re.search(r'\bBUY\b', cleaned))
        has_sell = bool(re.search(r'\bSELL\b', cleaned))

        # If both BUY and SELL are present, attempt multi-clause split
        if has_buy and has_sell:
            parts = re.split(r'[\r\n]+|\s+/\s+|\s+OR\s+|\s+AND\s+|;\s*', raw, flags=re.IGNORECASE)
            valid_parts = [p.strip() for p in parts if re.search(r'\b(?:BUY|SELL)\b', p.upper())]
            if len(valid_parts) < 2:
                # Try continuous split at second action
                b_idx = cleaned.find("BUY")
                s_idx = cleaned.find("SELL")
                split_pos = max(b_idx, s_idx)
                if split_pos > 0:
                    valid_parts = [raw[:split_pos].strip(), raw[split_pos:].strip()]

            signals: List[TradeSignal] = []
            for p in valid_parts:
                sig = cls.parse_single(p, inherited_symbol=primary_symbol)
                if sig.action != SignalAction.NONE:
                    signals.append(sig)

            if len(signals) >= 2:
                return signals

        # Single signal parse
        return [cls.parse_single(raw, inherited_symbol=primary_symbol)]

    @classmethod
    def parse(cls, text: str) -> TradeSignal:
        """Parse text into a single TradeSignal (returns the first signal if multiple are found)."""
        signals = cls.parse_multi(text)
        return signals[0] if signals else TradeSignal(action=SignalAction.NONE, symbol="XAUUSD", raw_message=text, parser_used="rule")

    @classmethod
    def parse_single(cls, text: str, inherited_symbol: Optional[str] = None) -> TradeSignal:
        raw = text.strip()
        cleaned = re.sub(r'[*_`#]', '', raw).upper()

        if is_scrap_message(text) or len(cleaned) < 5:
            return TradeSignal(action=SignalAction.NONE, symbol="XAUUSD", raw_message=text, parser_used="rule")

        # 2. Find Symbol
        symbol = None
        for sym in cls.KNOWN_SYMBOLS:
            if re.search(r'\b' + re.escape(sym) + r'\b', cleaned):
                symbol = sym
                break

        if not symbol:
            symbol = inherited_symbol

        if settings.FORCE_GOLD_ONLY and not symbol:
            symbol = "XAUUSD"

        # 3. Detect Action
        # Check Breakeven / Move SL to Entry
        if any(p in cleaned for p in ["BREAKEVEN", "BREAK EVEN", "MOVE SL TO ENTRY", "SL TO ENTRY", "SL ENTRY", "MOVE SL TO COST"]):
            return TradeSignal(action=SignalAction.BREAKEVEN, symbol=symbol or "XAUUSD", raw_message=text, parser_used="rule")

        # Check Close / Exit
        if any(p in cleaned for p in ["CLOSE ALL", "EXIT ALL", "CLOSE NOW", "EXIT NOW", "CLOSE POSITION", "CLOSE FULL"]):
            return TradeSignal(action=SignalAction.EXIT, symbol=symbol or "XAUUSD", raw_message=text, parser_used="rule")

        # Check Partial Close
        partial_match = re.search(r'(?:CLOSE|TAKE|BOOK)\s+(HALF|PARTIAL|50%|80%|70%|30%)', cleaned)
        if partial_match:
            ratio_str = partial_match.group(1)
            ratio = 0.5
            if "50%" in ratio_str or "HALF" in ratio_str:
                ratio = 0.5
            elif "80%" in ratio_str:
                ratio = 0.8
            elif "70%" in ratio_str:
                ratio = 0.7
            elif "30%" in ratio_str:
                ratio = 0.3
            return TradeSignal(action=SignalAction.CLOSE_PARTIAL, symbol=symbol or "XAUUSD", close_ratio=ratio, raw_message=text, parser_used="rule")

        # Check Targets and SL updates (e.g. "TGT1- 4245 TGT2- 4235 SL- 4260", "SL 4260", "TP 4240")
        tgt_matches = re.findall(r'(?:TGT[1-4]?|TARGET[1-4]?|TP[1-4]?)\s*[-:=@]?\s*([0-9]+(?:\.[0-9]+)?)', cleaned)
        extracted_targets = [float(t) for t in tgt_matches]
        target_1 = extracted_targets[0] if len(extracted_targets) > 0 else None
        target_2 = extracted_targets[1] if len(extracted_targets) > 1 else None

        # Robust SL extraction avoiding collision with BUY STOP / SELL STOP
        sl_update_match = re.search(
            r'(?:UPDATE|MODIFY|MOVE|CHANGE|NEW|SET)?\s*(?<!BUY\s)(?<!SELL\s)\b(?:SL|STOP\s*LOSS|STOPLOSS|S/L)\b\s*[-:=@]?\s*([0-9]+(?:\.[0-9]+)?)',
            cleaned
        )
        if not sl_update_match:
            sl_update_match = re.search(
                r'(?<!BUY\s)(?<!SELL\s)\bSTOP\b\s*[-:=@]?\s*([0-9]+(?:\.[0-9]+)?)',
                cleaned
            )
        extracted_sl = float(sl_update_match.group(1)) if sl_update_match else None

        if not any(k in cleaned for k in ["BUY", "SELL"]):
            if extracted_targets and extracted_sl:
                return TradeSignal(
                    action=SignalAction.UPDATE_TARGETS_AND_SL,
                    symbol=symbol or "XAUUSD",
                    stop_loss=extracted_sl,
                    take_profit=target_1,
                    target_1=target_1,
                    target_2=target_2,
                    take_profit_levels=[target_1] + ([target_2] if target_2 else []),
                    raw_message=text,
                    parser_used="rule"
                )
            elif extracted_targets and not extracted_sl:
                return TradeSignal(
                    action=SignalAction.UPDATE_TP,
                    symbol=symbol or "XAUUSD",
                    take_profit=target_1,
                    target_1=target_1,
                    target_2=target_2,
                    take_profit_levels=[target_1] + ([target_2] if target_2 else []),
                    raw_message=text,
                    parser_used="rule"
                )
            elif extracted_sl and not extracted_targets:
                return TradeSignal(
                    action=SignalAction.UPDATE_SL,
                    symbol=symbol or "XAUUSD",
                    stop_loss=extracted_sl,
                    raw_message=text,
                    parser_used="rule"
                )

        # Pending order & Market order checks
        if "BUY LIMIT" in cleaned:
            action = SignalAction.BUY_LIMIT
        elif "SELL LIMIT" in cleaned:
            action = SignalAction.SELL_LIMIT
        elif "BUY STOP" in cleaned:
            action = SignalAction.BUY_STOP
        elif "SELL STOP" in cleaned:
            action = SignalAction.SELL_STOP
        elif re.search(r'\bBUY\b', cleaned):
            if re.search(r'\b(?:ABOVE|BREAKS?\s+ABOVE|BREAKOUT\s+ABOVE|BREAKS?|BREAKOUT)\b', cleaned):
                action = SignalAction.BUY_STOP
            elif re.search(r'\bBELOW\b', cleaned):
                action = SignalAction.BUY_LIMIT
            else:
                action = SignalAction.BUY
        elif re.search(r'\bSELL\b', cleaned):
            if re.search(r'\b(?:BELOW|BREAKS?\s+BELOW|BREAKDOWN\s+BELOW|BREAKS?|BREAKDOWN)\b', cleaned):
                action = SignalAction.SELL_STOP
            elif re.search(r'\bABOVE\b', cleaned):
                action = SignalAction.SELL_LIMIT
            else:
                action = SignalAction.SELL
        else:
            return TradeSignal(action=SignalAction.NONE, symbol=symbol or "XAUUSD", raw_message=text, parser_used="rule")

        # 4. Extract Entry Price
        entry = None

        # 4a. Conditional triggers: ABOVE, BELOW, BREAKOUT, IF BREAKS
        cond_match = re.search(
            r'\b(?:ABOVE|BREAKS?\s+ABOVE|BREAKOUT\s+ABOVE|BELOW|BREAKS?\s+BELOW|BREAKDOWN\s+BELOW|IF\s+BREAKS?)\s*[-:=@]?\s*([0-9]+(?:\.[0-9]+)?)',
            cleaned
        )
        if cond_match:
            entry = float(cond_match.group(1))

        # 4b. Explicit order types: BUY STOP, SELL STOP, BUY LIMIT, SELL LIMIT
        if entry is None:
            order_type_match = re.search(
                r'\b(?:BUY\s+STOP|SELL\s+STOP|BUY\s+LIMIT|SELL\s+LIMIT)\s*[-:=@]?\s*([0-9]+(?:\.[0-9]+)?)',
                cleaned
            )
            if order_type_match:
                entry = float(order_type_match.group(1))

        # 4c. Explicit keywords: ENTRY, PRICE, LEVEL, TRIGGER, @, AT, NOW
        if entry is None:
            entry_kw_match = re.search(
                r'\b(?:ENTRY|PRICE|ENTRY\s+PRICE|EP|LEVEL|TRIGGER|NOW|@|AT)\s*[-:=@]?\s*([0-9]+(?:\.[0-9]+)?)',
                cleaned
            )
            if entry_kw_match:
                val = float(entry_kw_match.group(1))
                if extracted_sl is None or abs(val - extracted_sl) > 0.01:
                    entry = val

        # 4d. Action + optional symbol + optional NOW + price (e.g. 'BUY GOLD 2650', 'SELL BTC 95200')
        if entry is None and symbol:
            sym_pattern = re.escape(symbol) + r'\s+'
            m_sym = re.search(r'\b(?:BUY|SELL)\s+(?:' + sym_pattern + r')?(?:NOW\s+)?[-:=@]?\s*([0-9]+(?:\.[0-9]+)?)', cleaned)
            if m_sym:
                val = float(m_sym.group(1))
                if extracted_sl is None or abs(val - extracted_sl) > 0.01:
                    entry = val

        # 4e. Direct BUY/SELL + price fallback
        if entry is None:
            entry_match = re.search(r'\b(?:BUY|SELL)\s*[-:=@]?\s*([0-9]+(?:\.[0-9]+)?)', cleaned)
            if entry_match:
                val = float(entry_match.group(1))
                if extracted_sl is None or abs(val - extracted_sl) > 0.01:
                    entry = val

        return TradeSignal(
            action=action,
            symbol=symbol or "XAUUSD",
            entry_price=entry,
            stop_loss=extracted_sl,
            take_profit=target_1,
            target_1=target_1,
            target_2=target_2,
            take_profit_levels=[t for t in [target_1, target_2] if t is not None],
            raw_message=text,
            parser_used="rule"
        )
