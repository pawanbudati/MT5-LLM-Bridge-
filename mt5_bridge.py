import os
import math
import asyncio
import logging
from typing import Dict, List, Optional, Any, Tuple, Union
import MetaTrader5 as mt5
from colorama import Fore, Style

from config import settings
from models import TradeSignal, SignalAction, OrderTypeRecommended, ExecutionResult, PairConfig, GeminiChartAnalysis

logger = logging.getLogger(__name__)

def map_timeframe_to_mt5(tf_str: Optional[str]) -> int:
    """Map timeframe string (e.g. '15m', '1h', 'H1', '5m') to MT5 TIMEFRAME_* constant."""
    if not tf_str:
        return mt5.TIMEFRAME_M15
    clean = str(tf_str).strip().upper().replace(" ", "").replace("MIN", "M").replace("HOUR", "H").replace("HR", "H").replace("SEC", "S")
    mapping = {
        "M1": mt5.TIMEFRAME_M1, "1M": mt5.TIMEFRAME_M1,
        "M2": mt5.TIMEFRAME_M2, "2M": mt5.TIMEFRAME_M2,
        "M3": mt5.TIMEFRAME_M3, "3M": mt5.TIMEFRAME_M3,
        "M4": mt5.TIMEFRAME_M4, "4M": mt5.TIMEFRAME_M4,
        "M5": mt5.TIMEFRAME_M5, "5M": mt5.TIMEFRAME_M5,
        "M6": mt5.TIMEFRAME_M6, "6M": mt5.TIMEFRAME_M6,
        "M10": mt5.TIMEFRAME_M10, "10M": mt5.TIMEFRAME_M10,
        "M12": mt5.TIMEFRAME_M12, "12M": mt5.TIMEFRAME_M12,
        "M15": mt5.TIMEFRAME_M15, "15M": mt5.TIMEFRAME_M15,
        "M20": mt5.TIMEFRAME_M20, "20M": mt5.TIMEFRAME_M20,
        "M30": mt5.TIMEFRAME_M30, "30M": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1, "1H": mt5.TIMEFRAME_H1, "60M": mt5.TIMEFRAME_H1,
        "H2": mt5.TIMEFRAME_H2, "2H": mt5.TIMEFRAME_H2,
        "H3": mt5.TIMEFRAME_H3, "3H": mt5.TIMEFRAME_H3,
        "H4": mt5.TIMEFRAME_H4, "4H": mt5.TIMEFRAME_H4, "240M": mt5.TIMEFRAME_H4,
        "H6": mt5.TIMEFRAME_H6, "6H": mt5.TIMEFRAME_H6,
        "H8": mt5.TIMEFRAME_H8, "8H": mt5.TIMEFRAME_H8,
        "H12": mt5.TIMEFRAME_H12, "12H": mt5.TIMEFRAME_H12,
        "D1": mt5.TIMEFRAME_D1, "1D": mt5.TIMEFRAME_D1, "DAILY": mt5.TIMEFRAME_D1,
    }
    return mapping.get(clean, mt5.TIMEFRAME_M15)

class MT5Bridge:
    def __init__(self, pair_config: Optional[PairConfig] = None):
        self.pair_config = pair_config
        self.terminal_path = pair_config.mt5_path if pair_config and pair_config.mt5_path else settings.MT5_PATH if hasattr(settings, "MT5_PATH") else ""
        self.magic_number = pair_config.magic_number if pair_config else 777999
        self.login = pair_config.mt5_login if (pair_config and pair_config.mt5_login is not None) else getattr(settings, "MT5_LOGIN", None)
        self.password = pair_config.mt5_password if (pair_config and pair_config.mt5_password is not None) else getattr(settings, "MT5_PASSWORD", None)
        self.server = pair_config.mt5_server if (pair_config and pair_config.mt5_server is not None) else getattr(settings, "MT5_SERVER", None)
        self.dry_run = pair_config.dry_run if (pair_config and pair_config.dry_run is not None) else settings.DRY_RUN
        self.execution_mode = (pair_config.execution_mode if pair_config and pair_config.execution_mode else settings.EXECUTION_MODE).lower()
        self.deviation = settings.MT5_DEVIATION
        self.connected = False
        self._symbol_cache: Dict[str, str] = {}
        self.active_targets: Dict[int, dict] = {}
        self._last_candle_offsets: Dict[str, float] = {}

    def connect(self) -> bool:
        """Initialize connection to MetaTrader 5 terminal executable and handle account login."""
        login_label = f"Account {self.login}" if self.login else "Existing Session"
        logger.info(f"Connecting to MT5 terminal at: {self.terminal_path} (Magic: {self.magic_number}, Login: {login_label})")

        if not self.terminal_path or not os.path.exists(self.terminal_path):
            logger.error(f"MT5 terminal executable not found at specified path: '{self.terminal_path}'")
            self.connected = False
            return False

        # 1. Connect/Initialize to the MT5 terminal instance
        init_args = {"path": self.terminal_path}
        res = mt5.initialize(**init_args)

        # Fallback: If direct initialize failed and credentials are provided, attempt initialize with credentials
        if not res and self.login:
            fallback_args = dict(init_args)
            fallback_args["login"] = int(self.login)
            if self.password:
                fallback_args["password"] = str(self.password)
            if self.server:
                fallback_args["server"] = str(self.server)
            res = mt5.initialize(**fallback_args)

        if not res:
            err = mt5.last_error()
            logger.error(f"MT5 initialization failed for '{self.terminal_path}': {err}")
            self.connected = False
            return False

        self.connected = True
        terminal_info = mt5.terminal_info()
        if terminal_info:
            logger.info(f"MT5 Connected! Terminal: {terminal_info.name} | Path: {terminal_info.path}")
            if not terminal_info.trade_allowed:
                logger.warning(
                    "[!] WARNING: 'Algo Trading' button in MT5 is currently DISABLED (Red). "
                    "Please click the 'Algo Trading' button in MT5 top toolbar to enable automated trades!"
                )

        # 2. Account Login Management
        current_acc = mt5.account_info()
        if self.login:
            target_login = int(self.login)
            is_already_logged_in = False
            if current_acc and getattr(current_acc, "login", None) == target_login:
                if not self.server or (getattr(current_acc, "server", "") or "").strip().lower() == self.server.strip().lower():
                    is_already_logged_in = True

            if is_already_logged_in:
                logger.info(f"MT5 terminal is already logged into account {target_login} on server '{current_acc.server}'. Skipping login.")
            else:
                logger.info(f"Logging into MT5 account {target_login} (Server: {self.server or 'default'})...")
                login_kwargs = {"login": target_login}
                if self.password:
                    login_kwargs["password"] = str(self.password)
                if self.server:
                    login_kwargs["server"] = str(self.server)

                login_ok = mt5.login(**login_kwargs)
                if not login_ok:
                    err = mt5.last_error()
                    logger.error(f"MT5 login failed for account {target_login} (Server: '{self.server}'): {err}")
                    self.connected = False
                    return False
                logger.info(f"MT5 login successful for account {target_login} (Server: '{self.server or 'default'}').")
                current_acc = mt5.account_info()
        else:
            if current_acc:
                logger.info(f"No MT5 login credentials configured. Using existing active session: Account {current_acc.login} | Server {current_acc.server}")
            else:
                logger.warning("No MT5 login credentials configured and no active account session found in MT5 terminal.")

        # 3. Log Account Summary & Lot Sizing
        account_info = current_acc or mt5.account_info()
        if account_info:
            lot_gold = self.calculate_lot(instrument="GOLD")
            lot_btc = self.calculate_lot(instrument="BTCUSD")
            lot_oil = self.calculate_lot(instrument="USOIL")
            lot_us30 = self.calculate_lot(instrument="US30")
            lot_fx = self.calculate_lot(instrument="EURUSD")
            logger.info(
                f"Account: {account_info.login} | Server: {account_info.server} | "
                f"Balance: {account_info.balance:.2f} {account_info.currency} | "
                f"Equity: {account_info.equity:.2f} | Leverage: 1:{account_info.leverage}\n"
                f"  -> Position Sizes ($50 Base): GOLD: {lot_gold} | BTC: {lot_btc} | US OIL: {lot_oil} | US 30: {lot_us30} | Forex: {lot_fx} lots"
            )
        return True

    def disconnect(self):
        """Shutdown MT5 connection."""
        if self.connected:
            mt5.shutdown()
            self.connected = False
            logger.info("MT5 disconnected.")

    def ensure_connected(self) -> bool:
        """Verify MT5 connection and reconnect if necessary."""
        if not self.connected or mt5.terminal_info() is None:
            return self.connect()
        return True

    ALIAS_CLUSTERS = [
        {"USOIL", "USOILSPOT", "USOILCASH", "OILCASH", "OIL", "WTI", "WTICRUDE", "CRUDE", "CRUDESOIL", "CL", "XTIUSD"},
        {"UKOIL", "UKOILSPOT", "BRENT", "BRENTCASH", "BRENTOIL", "XBRUSD"},
        {"GOLD", "XAUUSD", "XAU", "GOLDSPOT"},
        {"SILVER", "XAGUSD", "XAG", "SILVERSPOT"},
        {"US30", "US30CASH", "DJ30", "DOW", "DOWJONES", "WALLSTREET", "US 30"},
        {"NAS100", "US100", "US100CASH", "NASDAQ", "USTEC", "NDX", "NAS"},
        {"SPX500", "US500", "US500CASH", "SP500", "SPX"},
        {"GER40", "GER40CASH", "DAX40", "DAX"},
        {"BTC", "BTCUSD", "BITCOIN", "BTCUSDT"},
    ]

    def resolve_symbol(self, instrument: Optional[str]) -> Optional[str]:
        """Resolve channel/TradingView symbol to active broker-specific symbol in MT5."""
        if not instrument:
            return None

        if settings.FORCE_GOLD_ONLY:
            gold_sym = settings.DEFAULT_GOLD_SYMBOL
            if mt5.symbol_select(gold_sym, True):
                return gold_sym

        clean_symbol = instrument.strip().upper().replace(" ", "")

        if clean_symbol in self._symbol_cache:
            return self._symbol_cache[clean_symbol]

        mappings = settings.load_mappings()
        if clean_symbol in mappings:
            mapped = mappings[clean_symbol]
            if mt5.symbol_select(mapped, True):
                self._symbol_cache[clean_symbol] = mapped
                return mapped

        cluster = None
        for c in self.ALIAS_CLUSTERS:
            if clean_symbol in c or instrument.strip().upper() in c:
                cluster = c
                break
        if not cluster:
            cluster = {clean_symbol}

        for alias in cluster:
            if alias in mappings:
                mapped = mappings[alias]
                if mt5.symbol_select(mapped, True):
                    self._symbol_cache[clean_symbol] = mapped
                    return mapped

        for alias in [clean_symbol] + list(cluster):
            if mt5.symbol_select(alias, True):
                self._symbol_cache[clean_symbol] = alias
                return alias

        all_symbols = mt5.symbols_get()
        if all_symbols:
            stock_exclusions = ("MOTOR", "TULLOW", "CABOT", "MARATHON", "MURPHY", "OILWELL", "BARK", "GOLDEN")
            candidate_symbols = [
                s.name for s in all_symbols 
                if not any(exc in s.name.upper() for exc in stock_exclusions)
            ]

            for sym in candidate_symbols:
                s_up = sym.upper()
                s_base = s_up.replace("#", "").replace(".I", "").replace(".RAW", "").replace("M", "")
                if s_base in cluster or any(alias in s_base for alias in cluster):
                    if mt5.symbol_select(sym, True):
                        self._symbol_cache[clean_symbol] = sym
                        return sym

            for sym in candidate_symbols:
                s_up = sym.upper()
                for alias in cluster:
                    if alias in s_up:
                        if mt5.symbol_select(sym, True):
                            self._symbol_cache[clean_symbol] = sym
                            return sym

        logger.error(f"Could not resolve instrument '{instrument}' to any active MT5 broker symbol!")
        return None

    def classify_instrument(self, instrument: str = "", symbol: str = "", symbol_info=None) -> str:
        """Classify trading instrument into: GOLD, BTC, USOIL, US30, FOREX, or DEFAULT."""
        candidates = []
        if instrument and isinstance(instrument, str):
            candidates.append(instrument.upper().strip())
        if symbol and isinstance(symbol, str):
            candidates.append(symbol.upper().strip())
        if symbol_info and hasattr(symbol_info, "name") and isinstance(symbol_info.name, str):
            candidates.append(symbol_info.name.upper().strip())

        combined = " ".join(candidates)
        clean = combined.replace("#", "").replace(".", " ").replace("_", " ").replace("/", " ").replace("-", " ")
        clean_words = set(clean.split())

        gold_markers = {"GOLD", "XAUUSD", "XAU", "GOLDSPOT", "GOLDI"}
        if any(m in clean_words or m in clean for m in gold_markers):
            return "GOLD"

        btc_markers = {"BTC", "BTCUSD", "BITCOIN", "BTCUSDT"}
        if any(m in clean_words or m in clean for m in btc_markers):
            return "BTC"

        oil_markers = {"USOIL", "WTI", "CRUDE", "CRUDESOIL", "XTIUSD", "OILCASH"}
        if any(m in clean_words or m in clean for m in oil_markers):
            return "USOIL"
        if "OIL" in clean_words and "UKOIL" not in clean and "BRENT" not in clean and "XBRUSD" not in clean:
            return "USOIL"

        us30_markers = {"US30", "DJ30", "DOW", "DOWJONES", "WALLSTREET"}
        if any(m in clean_words or m in clean for m in us30_markers):
            return "US30"

        if symbol_info and hasattr(symbol_info, "path") and symbol_info.path:
            path_lower = symbol_info.path.lower()
            if any(k in path_lower for k in ["derivative", "energies", "metals", "commodit", "indices", "crypto"]):
                pass
            elif "forex" in path_lower or "fx" in path_lower:
                return "FOREX"

        CURRENCIES = {
            "USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD", "SGD", 
            "HKD", "SEK", "NOK", "TRY", "ZAR", "MXN", "PLN", "HUF", "CZK", "DKK", "CNH"
        }
        for cand in candidates:
            c = cand.replace("#", "").replace(".", "").replace("_", "").replace("/", "").replace("-", "").replace(" ", "")
            if len(c) >= 6 and c[:3] in CURRENCIES and c[3:6] in CURRENCIES and c[:3] != c[3:6]:
                return "FOREX"

        if symbol_info and hasattr(symbol_info, "currency_base") and hasattr(symbol_info, "currency_profit"):
            base = getattr(symbol_info, "currency_base", "").upper()
            profit = getattr(symbol_info, "currency_profit", "").upper()
            if base in CURRENCIES and profit in CURRENCIES and base != profit:
                return "FOREX"

        return "DEFAULT"

    def get_base_lot_for_instrument(self, category: str) -> float:
        """Get the base lot size per $50 account size for a given category (checking pair overrides first)."""
        cfg = self.pair_config
        if category == "GOLD":
            if cfg and cfg.lot_gold is not None:
                return cfg.lot_gold
            return settings.LOT_GOLD_PER_50
        elif category == "BTC":
            if cfg and cfg.lot_btc is not None:
                return cfg.lot_btc
            return settings.LOT_BTC_PER_50
        elif category == "USOIL":
            if cfg and cfg.lot_usoil is not None:
                return cfg.lot_usoil
            return settings.LOT_USOIL_PER_50
        elif category == "US30":
            if cfg and cfg.lot_us30 is not None:
                return cfg.lot_us30
            return settings.LOT_US30_PER_50
        elif category == "FOREX":
            if cfg and cfg.lot_forex is not None:
                return cfg.lot_forex
            return settings.LOT_FOREX_PER_50

        if cfg and cfg.lot_default is not None:
            return cfg.lot_default
        return settings.LOT_DEFAULT_PER_50

    def calculate_lot(
        self, 
        symbol_info=None, 
        signal_lot: Optional[float] = None,
        symbol: str = "",
        instrument: str = ""
    ) -> float:
        """
        Dynamically calculate lot size per instrument rules based on account balance ($50 base):
        - GOLD: 0.02 lots per $50
        - BTC: 0.03 lots per $50
        - US OIL: 0.02 lots per $50
        - US 30: 0.10 lots per $50
        - All currency pairs: 0.10 lots per $50
        - Default fallback: 0.02 lots per $50
        """
        if not symbol and instrument and self.connected:
            symbol = self.resolve_symbol(instrument) or ""

        if symbol_info is None and symbol and self.connected:
            symbol_info = mt5.symbol_info(symbol)

        category = self.classify_instrument(
            instrument=instrument, 
            symbol=symbol, 
            symbol_info=symbol_info
        )
        base_lot = self.get_base_lot_for_instrument(category)

        if signal_lot is not None and signal_lot > 0:
            lot = signal_lot
        elif settings.USE_DYNAMIC_LOT:
            acc = mt5.account_info() if self.connected else None
            base_size = settings.BASE_ACCOUNT_SIZE if settings.BASE_ACCOUNT_SIZE > 0 else 50.0
            balance = acc.balance if acc and acc.balance > 0 else base_size

            if balance <= base_size:
                if settings.LOT_BELOW_BASE_MODE == "min_base":
                    multiplier = 1.0
                else:
                    multiplier = max(0.2, balance / base_size)
            else:
                if settings.LOT_SCALING_MODE == "step":
                    multiplier = max(1.0, math.floor(balance / base_size))
                else:
                    multiplier = balance / base_size

            lot = base_lot * multiplier
        else:
            lot = base_lot

        step = 0.01
        min_vol = settings.MIN_LOT_SIZE
        max_vol = 50.0
        if symbol_info:
            step = symbol_info.volume_step if isinstance(getattr(symbol_info, "volume_step", None), (int, float)) else 0.01
            min_vol = symbol_info.volume_min if isinstance(getattr(symbol_info, "volume_min", None), (int, float)) else settings.MIN_LOT_SIZE
            max_vol = symbol_info.volume_max if isinstance(getattr(symbol_info, "volume_max", None), (int, float)) else 50.0

        lot = round(round(lot / step) * step, 2)
        lot = max(min_vol, min(max_vol, lot))
        return lot

    def _get_filling_type(self, symbol_info) -> int:
        """Determine supported filling type to prevent INVALID_FILL errors."""
        filling_mode = symbol_info.filling_mode
        # Bit 0 (1): FOK, Bit 1 (2): IOC
        if filling_mode & 1:
            return mt5.ORDER_FILLING_FOK
        elif filling_mode & 2:
            return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN

    def cancel_pending_orders(self, symbol: str):
        """Cancel any pending orders for the specified symbol."""
        if not self.connected or self.dry_run:
            return
        orders = mt5.orders_get(symbol=symbol)
        if orders:
            for o in orders:
                if o.magic == self.magic_number:
                    req = {
                        "action": mt5.TRADE_ACTION_REMOVE,
                        "order": o.ticket
                    }
                    mt5.order_send(req)
                    logger.info(f"Cancelled old pending order #{o.ticket} on {symbol}")

    def get_recent_candles(
        self,
        symbol: str,
        timeframe_str: str = "15m",
        count: int = 10
    ) -> List[Dict[str, Any]]:
        """Fetch the most recent N candles for a symbol on the specified timeframe."""
        if not self.ensure_connected():
            return []

        mt5_tf = map_timeframe_to_mt5(timeframe_str)
        if self.connected:
            mt5.symbol_select(symbol, True)

        rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, count)
        if rates is None or len(rates) == 0:
            err = mt5.last_error() if hasattr(mt5, "last_error") else "Unknown"
            logger.warning(f"Failed to fetch {timeframe_str} rates for {symbol}: {err}")
            return []

        candles = []
        import datetime
        for r in rates:
            time_val = getattr(r, 'time', None) if not isinstance(r, (tuple, dict, list)) and hasattr(r, 'time') else r['time'] if isinstance(r, dict) or hasattr(r, '__getitem__') else 0
            open_val = getattr(r, 'open', None) if not isinstance(r, (tuple, dict, list)) and hasattr(r, 'open') else r['open'] if isinstance(r, dict) or hasattr(r, '__getitem__') else 0.0
            high_val = getattr(r, 'high', None) if not isinstance(r, (tuple, dict, list)) and hasattr(r, 'high') else r['high'] if isinstance(r, dict) or hasattr(r, '__getitem__') else 0.0
            low_val = getattr(r, 'low', None) if not isinstance(r, (tuple, dict, list)) and hasattr(r, 'low') else r['low'] if isinstance(r, dict) or hasattr(r, '__getitem__') else 0.0
            close_val = getattr(r, 'close', None) if not isinstance(r, (tuple, dict, list)) and hasattr(r, 'close') else r['close'] if isinstance(r, dict) or hasattr(r, '__getitem__') else 0.0

            time_str = ""
            try:
                time_str = datetime.datetime.fromtimestamp(int(time_val)).strftime('%Y-%m-%d %H:%M')
            except Exception:
                pass

            o = round(float(open_val), 3)
            h = round(float(high_val), 3)
            l = round(float(low_val), 3)
            c = round(float(close_val), 3)
            candles.append({
                "time": int(time_val),
                "time_str": time_str,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "is_bullish": bool(c >= o),
                "body_size": round(abs(c - o), 3),
                "range_size": round(h - l, 3),
            })
        return candles

    def determine_candle_match_offset(
        self,
        analysis: GeminiChartAnalysis,
        image_path: Optional[str] = None,
        gemini_client: Optional[Any] = None,
        broker_symbol: Optional[str] = None
    ) -> Tuple[float, str, Optional[str]]:
        """
        Correlate chart candles with MT5 broker candles on the same timeframe to get the exact price offset.
        Returns: (offset, method, details)
        """
        resolved_sym = broker_symbol or self.resolve_symbol(analysis.instrument)
        if not resolved_sym:
            return 0.0, "unresolved_symbol", None

        # 1. Fetch recent MT5 candles on the chart's timeframe
        tf = analysis.timeframe or "15m"
        candles = self.get_recent_candles(resolved_sym, timeframe_str=tf, count=settings.CANDLE_MATCH_COUNT)

        # 2. If candles and Gemini client available, run AI visual matching
        if candles and gemini_client and image_path:
            try:
                logger.info(
                    Fore.CYAN +
                    f"[CANDLE MATCHING] Correlating {analysis.instrument} chart ({tf}) with {len(candles)} MT5 {resolved_sym} candles..." +
                    Style.RESET_ALL
                )
                match_res = gemini_client.match_chart_candles_with_mt5(
                    image_input=image_path,
                    mt5_candles=candles,
                    timeframe=tf,
                    instrument=analysis.instrument or "USOIL",
                    broker_symbol=resolved_sym
                )
                if match_res and match_res.get("matched"):
                    offset = float(match_res.get("price_offset", 0.0))
                    confidence = match_res.get("confidence", "HIGH")
                    details = match_res.get("matched_details") or match_res.get("reasoning")
                    analysis.offset_method = "candle_match"
                    analysis.candle_match_confidence = confidence
                    analysis.candle_match_details = details
                    clean_inst = (analysis.instrument or "").strip().upper()
                    clean_sym = (resolved_sym or "").strip().upper()
                    if clean_inst:
                        self._last_candle_offsets[clean_inst] = offset
                    if clean_sym:
                        self._last_candle_offsets[clean_sym] = offset
                    logger.info(
                        Fore.GREEN + Style.BRIGHT +
                        f"[CANDLE MATCH SUCCESS] Offset = {offset:+.4f} (Confidence: {confidence}) | {details}" +
                        Style.RESET_ALL
                    )
                    return offset, "candle_match", details
                else:
                    logger.warning(
                        f"[CANDLE MATCH] Could not match candles: {match_res.get('reason', 'unmatched')}. Falling back to tick mid."
                    )
            except Exception as e:
                logger.warning(f"Error during candle matching: {e}. Falling back to tick mid.")

        # 3. Fallback to tick mid vs chart_current_price
        if analysis.chart_current_price and analysis.chart_current_price > 0:
            tick = mt5.symbol_info_tick(resolved_sym) if self.connected else None
            if not tick and self.connected:
                mt5.symbol_select(resolved_sym, True)
                tick = mt5.symbol_info_tick(resolved_sym)
            if tick and getattr(tick, "bid", 0.0) > 0 and getattr(tick, "ask", 0.0) > 0:
                mt5_mid = (tick.bid + tick.ask) / 2.0
                offset = round(mt5_mid - analysis.chart_current_price, 4)
                analysis.offset_method = "auto_tick"
                clean_inst = (analysis.instrument or "").strip().upper()
                clean_sym = (resolved_sym or "").strip().upper()
                if clean_inst:
                    self._last_candle_offsets[clean_inst] = offset
                if clean_sym:
                    self._last_candle_offsets[clean_sym] = offset
                logger.info(
                    Fore.CYAN +
                    f"[AUTO TICK FALLBACK] Offset = {offset:+.4f} (MT5 Mid: {mt5_mid:.4f} - Chart Px: {analysis.chart_current_price:.4f})" +
                    Style.RESET_ALL
                )
                return offset, "auto_tick", f"Tick mid {mt5_mid:.4f} - Chart {analysis.chart_current_price:.4f}"

        # 4. Fallback to cached offset if available
        clean_inst = (analysis.instrument or "").strip().upper()
        clean_sym = (resolved_sym or "").strip().upper()
        cached = self._last_candle_offsets.get(clean_inst) or self._last_candle_offsets.get(clean_sym)
        if cached is not None:
            analysis.offset_method = "cached_candle_match"
            return cached, "cached_candle_match", "Using recently matched candle offset"

        return 0.0, "none", None

    def get_price_offset(
        self,
        instrument: str,
        broker_symbol: Optional[str] = None,
        chart_price: Optional[float] = None
    ) -> float:
        """
        Determine the price offset to add to chart prices so they match the MT5 broker contract.
        Formula: MT5_Broker_Price = Chart_Price + Offset

        Offset sources:
        1. Pair-level overrides (pair_config.usoil_price_offset / price_offsets).
        2. Global PRICE_OFFSETS dictionary.
        3. Global USOIL_PRICE_OFFSET for oil instruments.
        4. "candle_match": Uses cached candle match offset if available, else falls back to tick mid.
        5. "auto": Dynamically computes (MT5_mid_tick - chart_price).
        """
        raw_offset = settings.get_price_offset_for_instrument(
            instrument=instrument,
            pair_cfg=self.pair_config,
            broker_symbol=broker_symbol
        )

        if raw_offset is None:
            return 0.0

        if isinstance(raw_offset, (int, float)):
            return float(raw_offset)

        clean_inst = (instrument or "").strip().upper()
        clean_broker = (broker_symbol or "").strip().upper()

        if isinstance(raw_offset, str) and raw_offset.lower() in ("candle_match", "auto"):
            # Check cached candle-matched offset first
            if clean_inst in self._last_candle_offsets:
                return self._last_candle_offsets[clean_inst]
            if clean_broker in self._last_candle_offsets:
                return self._last_candle_offsets[clean_broker]

            if chart_price is None or chart_price <= 0:
                logger.warning(
                    f"Auto/Candle price offset requested for '{instrument}' but no valid chart_current_price available. "
                    f"Using offset 0.0."
                )
                return 0.0

            target_symbol = broker_symbol or self.resolve_symbol(instrument)
            if not target_symbol:
                logger.warning(f"Auto price offset requested but could not resolve symbol for '{instrument}'. Using 0.0.")
                return 0.0

            tick = mt5.symbol_info_tick(target_symbol) if self.connected else None
            if not tick and self.connected:
                mt5.symbol_select(target_symbol, True)
                tick = mt5.symbol_info_tick(target_symbol)

            if tick and getattr(tick, "bid", 0.0) > 0 and getattr(tick, "ask", 0.0) > 0:
                mt5_mid = (tick.bid + tick.ask) / 2.0
                calc_offset = round(mt5_mid - chart_price, 4)
                logger.info(
                    Fore.CYAN + Style.BRIGHT +
                    f"[AUTO PRICE OFFSET] Calibrated {instrument} ({target_symbol}): "
                    f"MT5 Mid ({mt5_mid:.4f}) - Chart Price ({chart_price:.4f}) = Offset {calc_offset:+.4f}" +
                    Style.RESET_ALL
                )
                return calc_offset
            else:
                logger.warning(
                    f"Auto price offset requested for '{instrument}' ({target_symbol}) but MT5 market tick unavailable. "
                    f"Using offset 0.0."
                )
                return 0.0

        try:
            return float(raw_offset)
        except (ValueError, TypeError):
            return 0.0

    def apply_price_offset_to_analysis(
        self,
        analysis: GeminiChartAnalysis,
        broker_symbol: Optional[str] = None,
        image_path: Optional[str] = None,
        gemini_client: Optional[Any] = None
    ) -> Tuple[GeminiChartAnalysis, float]:
        """
        Apply price offset calibration to all price fields of a GeminiChartAnalysis.
        Ensures breakout levels, ranges, SL, and TP match the MT5 broker contract.
        If candle matching is enabled, correlates chart candles with MT5 broker candles on the same timeframe.
        """
        if analysis.applied_price_offset is not None and analysis.applied_price_offset != 0.0:
            return analysis, analysis.applied_price_offset

        resolved_sym = broker_symbol or self.resolve_symbol(analysis.instrument)
        raw_offset = settings.get_price_offset_for_instrument(
            instrument=analysis.instrument,
            pair_cfg=self.pair_config,
            broker_symbol=resolved_sym
        )

        offset = 0.0
        method = "manual"

        # Check if candle matching should be executed
        is_oil = settings.is_oil_instrument(analysis.instrument, resolved_sym)
        should_candle_match = (
            (raw_offset == "candle_match" or settings.CANDLE_MATCHING_ENABLED)
            and is_oil
        )

        if should_candle_match and (image_path or self.connected):
            offset, method, details = self.determine_candle_match_offset(
                analysis=analysis,
                image_path=image_path,
                gemini_client=gemini_client,
                broker_symbol=resolved_sym
            )
            analysis.offset_method = method
        else:
            offset = self.get_price_offset(
                instrument=analysis.instrument,
                broker_symbol=resolved_sym,
                chart_price=analysis.chart_current_price
            )
            analysis.offset_method = "manual" if isinstance(raw_offset, (int, float)) else "auto_tick"

        if abs(offset) < 1e-6:
            analysis.applied_price_offset = 0.0
            return analysis, 0.0

        digits = 2
        if resolved_sym and self.connected:
            s_info = mt5.symbol_info(resolved_sym)
            if s_info and hasattr(s_info, "digits") and isinstance(s_info.digits, int):
                digits = s_info.digits

        def _shift(val: Optional[float]) -> Optional[float]:
            if val is None:
                return None
            return round(val + offset, digits)

        analysis.upper_breakout_level = _shift(analysis.upper_breakout_level)
        analysis.lower_breakout_level = _shift(analysis.lower_breakout_level)
        analysis.upper_stop_loss = _shift(analysis.upper_stop_loss)
        analysis.upper_take_profit = _shift(analysis.upper_take_profit)
        analysis.lower_stop_loss = _shift(analysis.lower_stop_loss)
        analysis.lower_take_profit = _shift(analysis.lower_take_profit)
        analysis.range_high = _shift(analysis.range_high)
        analysis.range_low = _shift(analysis.range_low)
        analysis.entry_price = _shift(analysis.entry_price)
        analysis.entry_zone_min = _shift(analysis.entry_zone_min)
        analysis.entry_zone_max = _shift(analysis.entry_zone_max)
        analysis.stop_loss = _shift(analysis.stop_loss)
        analysis.take_profit_1 = _shift(analysis.take_profit_1)
        analysis.take_profit_2 = _shift(analysis.take_profit_2)
        analysis.take_profit_3 = _shift(analysis.take_profit_3)
        analysis.applied_price_offset = offset

        logger.info(
            Fore.CYAN + Style.BRIGHT +
            f"[PRICE OFFSET APPLIED] Shifted all chart levels for {analysis.instrument} "
            f"({resolved_sym or 'contract'}) by offset: {offset:+.4f} (Method: {analysis.offset_method or method})" +
            Style.RESET_ALL
        )
        return analysis, offset

    def apply_price_offset_to_signal(
        self,
        signal: TradeSignal,
        broker_symbol: Optional[str] = None
    ) -> Tuple[TradeSignal, float]:
        """
        Apply price offset calibration to a TradeSignal.
        """
        if signal.applied_price_offset is not None and signal.applied_price_offset != 0.0:
            return signal, signal.applied_price_offset

        sym = signal.symbol or ""
        resolved_sym = broker_symbol or self.resolve_symbol(sym)
        offset = self.get_price_offset(
            instrument=sym,
            broker_symbol=resolved_sym,
            chart_price=signal.entry_price
        )

        if abs(offset) < 1e-6:
            signal.applied_price_offset = 0.0
            return signal, 0.0

        digits = 2
        if resolved_sym and self.connected:
            s_info = mt5.symbol_info(resolved_sym)
            if s_info and hasattr(s_info, "digits") and isinstance(s_info.digits, int):
                digits = s_info.digits

        def _shift(val: Optional[float]) -> Optional[float]:
            if val is None:
                return None
            return round(val + offset, digits)

        signal.entry_price = _shift(signal.entry_price)
        signal.stop_loss = _shift(signal.stop_loss)
        signal.take_profit = _shift(signal.take_profit)
        signal.target_1 = _shift(signal.target_1)
        signal.target_2 = _shift(signal.target_2)
        signal.target_3 = _shift(signal.target_3)
        if signal.take_profit_levels:
            signal.take_profit_levels = [_shift(tp) for tp in signal.take_profit_levels if tp is not None]
        signal.applied_price_offset = offset

        logger.info(
            Fore.CYAN + Style.BRIGHT +
            f"[PRICE OFFSET APPLIED] Shifted signal levels for {sym} "
            f"({resolved_sym or 'contract'}) by offset: {offset:+.4f}" +
            Style.RESET_ALL
        )
        return signal, offset

    def execute_signal(self, signal: TradeSignal) -> ExecutionResult:
        """Execute a parsed trading signal (either Vision or Text)."""
        if not self.ensure_connected():
            return ExecutionResult(success=False, action=str(signal.action), comment="MT5 not connected")

        if signal.action == SignalAction.NONE:
            return ExecutionResult(success=True, action="NONE", comment="No trade action required")

        sym_input = signal.symbol
        if not sym_input:
            if settings.FORCE_GOLD_ONLY:
                sym_input = settings.DEFAULT_GOLD_SYMBOL
            else:
                return ExecutionResult(success=False, action=str(signal.action), comment="No symbol identified in signal")

        broker_symbol = self.resolve_symbol(sym_input)
        if not broker_symbol:
            return ExecutionResult(
                success=False,
                action=str(signal.action),
                symbol=sym_input,
                comment=f"Broker symbol could not be resolved for '{sym_input}'"
            )

        # Calibrate signal price levels with MT5 broker offset if not already applied
        if signal.applied_price_offset is None:
            signal, _ = self.apply_price_offset_to_signal(signal, broker_symbol=broker_symbol)

        symbol_info = mt5.symbol_info(broker_symbol)
        if not symbol_info:
            return ExecutionResult(
                success=False,
                action=str(signal.action),
                symbol=broker_symbol,
                comment=f"Symbol info unavailable for {broker_symbol}"
            )

        if not symbol_info.visible:
            mt5.symbol_select(broker_symbol, True)

        # Route action
        if signal.action in (SignalAction.BUY, SignalAction.SELL):
            return self._execute_market_order(broker_symbol, symbol_info, signal)
        elif signal.action in (SignalAction.BUY_LIMIT, SignalAction.SELL_LIMIT, SignalAction.BUY_STOP, SignalAction.SELL_STOP):
            return self._execute_pending_order(broker_symbol, symbol_info, signal)
        elif signal.action == SignalAction.UPDATE_SL:
            return self._modify_sl(broker_symbol, symbol_info, signal.stop_loss)
        elif signal.action == SignalAction.UPDATE_TP:
            return self._modify_tp(broker_symbol, symbol_info, signal.take_profit)
        elif signal.action == SignalAction.UPDATE_TARGETS_AND_SL:
            return self._apply_targets_and_sl(broker_symbol, symbol_info, signal)
        elif signal.action == SignalAction.BREAKEVEN:
            return self._move_to_breakeven(broker_symbol, symbol_info)
        elif signal.action == SignalAction.CLOSE_PARTIAL:
            return self._close_positions(broker_symbol, ratio=signal.close_ratio or 0.5)
        elif signal.action in (SignalAction.EXIT, SignalAction.CLOSE):
            return self._close_positions(broker_symbol, ratio=1.0)
        else:
            return ExecutionResult(success=False, action=str(signal.action), comment=f"Unhandled action: {signal.action}")

    def execute_market_trade(
        self,
        symbol: str,
        action: SignalAction,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        lot: Optional[float] = None,
        comment: str = "Market Trade",
        instrument: str = ""
    ) -> ExecutionResult:
        """Direct market trade helper (used by BreakoutMonitor and direct callers)."""
        if not self.ensure_connected():
            return ExecutionResult(success=False, action=str(action), comment="MT5 not connected")

        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            return ExecutionResult(success=False, action=str(action), symbol=symbol, comment=f"Symbol info unavailable for {symbol}")

        if not symbol_info.visible:
            mt5.symbol_select(symbol, True)

        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return ExecutionResult(success=False, action=str(action), symbol=symbol, comment=f"Failed to fetch market tick for {symbol}")

        is_buy = (action == SignalAction.BUY)
        mt5_order_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
        price = tick.ask if is_buy else tick.bid

        final_lot = self.calculate_lot(symbol_info=symbol_info, signal_lot=lot, symbol=symbol, instrument=instrument)

        digits = symbol_info.digits
        price = round(price, digits)
        sl_price = round(sl, digits) if sl is not None else 0.0
        tp_price = round(tp, digits) if tp is not None else 0.0

        if self.dry_run:
            logger.info(
                f"[DRY RUN] Would execute: {action.value} {final_lot} lots of {symbol} @ {price} | "
                f"SL: {sl_price} | TP: {tp_price} | Magic: {self.magic_number}"
            )
            return ExecutionResult(
                success=True,
                action=action.value,
                symbol=symbol,
                ticket=999999,
                price=price,
                volume=final_lot,
                sl=sl_price,
                tp=tp_price,
                comment="Dry Run Simulated Trade"
            )

        filling_type = self._get_filling_type(symbol_info)
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": final_lot,
            "type": mt5_order_type,
            "price": price,
            "sl": sl_price,
            "tp": tp_price,
            "deviation": self.deviation,
            "magic": self.magic_number,
            "comment": comment[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling_type,
        }

        res = mt5.order_send(request)
        if res is None:
            err = mt5.last_error()
            return ExecutionResult(success=False, action=action.value, symbol=symbol, comment=f"order_send failed: {err}")

        if res.retcode == mt5.TRADE_RETCODE_DONE:
            return ExecutionResult(
                success=True,
                action=action.value,
                symbol=symbol,
                ticket=res.order,
                price=res.price,
                volume=res.volume,
                sl=sl_price,
                tp=tp_price,
                retcode=res.retcode,
                comment="Order filled successfully"
            )
        else:
            return ExecutionResult(
                success=False,
                action=action.value,
                symbol=symbol,
                retcode=res.retcode,
                comment=f"MT5 rejected order: {res.comment} (retcode: {res.retcode})"
            )

    def _execute_market_order(self, symbol: str, symbol_info, signal: TradeSignal) -> ExecutionResult:
        """Handle BUY or SELL signal."""
        # Check auto execution mode distance check if entry_price was specified
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return ExecutionResult(success=False, action=str(signal.action), symbol=symbol, comment="Market tick unavailable")

        is_buy = (signal.action == SignalAction.BUY)
        curr_price = tick.ask if is_buy else tick.bid

        if self.execution_mode == "auto" and signal.entry_price is not None:
            point = symbol_info.point or 0.0001
            diff_points = abs(curr_price - signal.entry_price) / point
            if diff_points > settings.MAX_SLIPPAGE_POINTS:
                logger.info(
                    f"Auto mode: Entry {signal.entry_price} is {diff_points:.1f} points away from market ({curr_price}). "
                    f"Placing Pending Order instead of market execution."
                )
                if is_buy:
                    signal.action = SignalAction.BUY_LIMIT if signal.entry_price < curr_price else SignalAction.BUY_STOP
                else:
                    signal.action = SignalAction.SELL_LIMIT if signal.entry_price > curr_price else SignalAction.SELL_STOP
                return self._execute_pending_order(symbol, symbol_info, signal)

        tp = signal.take_profit or signal.target_1
        res = self.execute_market_trade(
            symbol=symbol,
            action=signal.action,
            sl=signal.stop_loss,
            tp=tp,
            lot=signal.lot,
            comment=f"Auto [{signal.symbol or symbol}]",
            instrument=signal.symbol or symbol
        )

        # If trade executed and target 2 exists, register in active targets for 50% partial close monitor
        if res.success and signal.target_2 and res.ticket:
            self.active_targets[res.ticket] = {
                "symbol": symbol,
                "target_1": signal.target_1 or signal.take_profit,
                "target_2": signal.target_2,
                "pos_type": mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL,
                "t1_hit": False,
                "initial_vol": res.volume or self.calculate_lot(symbol_info, signal.lot, symbol)
            }
            logger.info(f"Position #{res.ticket} registered for Multi-Target Monitor (T1={signal.target_1}, T2={signal.target_2})")

        return res

    def _execute_pending_order(self, symbol: str, symbol_info, signal: TradeSignal) -> ExecutionResult:
        """Place pending order (BUY_LIMIT, SELL_LIMIT, BUY_STOP, SELL_STOP)."""
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return ExecutionResult(success=False, action=str(signal.action), symbol=symbol, comment="Market tick unavailable")

        entry_price = signal.entry_price
        if entry_price is None:
            return ExecutionResult(success=False, action=str(signal.action), symbol=symbol, comment="Pending order requires entry price")

        order_type_map = {
            SignalAction.BUY_LIMIT: mt5.ORDER_TYPE_BUY_LIMIT,
            SignalAction.SELL_LIMIT: mt5.ORDER_TYPE_SELL_LIMIT,
            SignalAction.BUY_STOP: mt5.ORDER_TYPE_BUY_STOP,
            SignalAction.SELL_STOP: mt5.ORDER_TYPE_SELL_STOP,
        }
        mt5_order_type = order_type_map.get(signal.action)
        if mt5_order_type is None:
            return ExecutionResult(success=False, action=str(signal.action), comment="Invalid pending order type")

        lot = self.calculate_lot(symbol_info=symbol_info, signal_lot=signal.lot, symbol=symbol, instrument=signal.symbol or symbol)
        digits = symbol_info.digits
        entry = round(entry_price, digits)
        sl = round(signal.stop_loss, digits) if signal.stop_loss is not None else 0.0
        tp = round(signal.take_profit or (signal.target_1 or 0.0), digits) if (signal.take_profit or signal.target_1) else 0.0

        point = symbol_info.point or 0.0001

        # Check if the market has already reached or crossed the pending price trigger
        if signal.action == SignalAction.BUY_STOP and tick.ask >= entry:
            diff_pts = (tick.ask - entry) / point
            if diff_pts <= settings.MAX_SLIPPAGE_POINTS:
                logger.info(
                    f"BUY_STOP level {entry} already breached by current ask {tick.ask} "
                    f"({diff_pts:.1f} pts <= max {settings.MAX_SLIPPAGE_POINTS}). Executing immediate Market BUY."
                )
                return self.execute_market_trade(
                    symbol=symbol,
                    action=SignalAction.BUY,
                    sl=signal.stop_loss,
                    tp=signal.take_profit or signal.target_1,
                    lot=signal.lot,
                    comment=f"Breakout BUY [{signal.symbol or symbol}]",
                    instrument=signal.symbol or symbol
                )
            else:
                logger.warning(
                    f"BUY_STOP level {entry} already exceeded by current ask {tick.ask} "
                    f"({diff_pts:.1f} pts > max {settings.MAX_SLIPPAGE_POINTS}). Skipping stale signal."
                )
                return ExecutionResult(
                    success=False,
                    action=signal.action.value,
                    symbol=symbol,
                    comment=f"Breakout level {entry} already crossed by {diff_pts:.1f} points (> max slippage)"
                )

        elif signal.action == SignalAction.SELL_STOP and tick.bid <= entry:
            diff_pts = (entry - tick.bid) / point
            if diff_pts <= settings.MAX_SLIPPAGE_POINTS:
                logger.info(
                    f"SELL_STOP level {entry} already breached by current bid {tick.bid} "
                    f"({diff_pts:.1f} pts <= max {settings.MAX_SLIPPAGE_POINTS}). Executing immediate Market SELL."
                )
                return self.execute_market_trade(
                    symbol=symbol,
                    action=SignalAction.SELL,
                    sl=signal.stop_loss,
                    tp=signal.take_profit or signal.target_1,
                    lot=signal.lot,
                    comment=f"Breakdown SELL [{signal.symbol or symbol}]",
                    instrument=signal.symbol or symbol
                )
            else:
                logger.warning(
                    f"SELL_STOP level {entry} already exceeded by current bid {tick.bid} "
                    f"({diff_pts:.1f} pts > max {settings.MAX_SLIPPAGE_POINTS}). Skipping stale signal."
                )
                return ExecutionResult(
                    success=False,
                    action=signal.action.value,
                    symbol=symbol,
                    comment=f"Breakdown level {entry} already crossed by {diff_pts:.1f} points (> max slippage)"
                )

        elif signal.action == SignalAction.BUY_LIMIT and tick.ask <= entry:
            diff_pts = (entry - tick.ask) / point
            if diff_pts <= settings.MAX_SLIPPAGE_POINTS:
                logger.info(
                    f"BUY_LIMIT level {entry} already reached by current ask {tick.ask}. "
                    f"Executing immediate Market BUY."
                )
                return self.execute_market_trade(
                    symbol=symbol,
                    action=SignalAction.BUY,
                    sl=signal.stop_loss,
                    tp=signal.take_profit or signal.target_1,
                    lot=signal.lot,
                    comment=f"Limit BUY [{signal.symbol or symbol}]",
                    instrument=signal.symbol or symbol
                )

        elif signal.action == SignalAction.SELL_LIMIT and tick.bid >= entry:
            diff_pts = (tick.bid - entry) / point
            if diff_pts <= settings.MAX_SLIPPAGE_POINTS:
                logger.info(
                    f"SELL_LIMIT level {entry} already reached by current bid {tick.bid}. "
                    f"Executing immediate Market SELL."
                )
                return self.execute_market_trade(
                    symbol=symbol,
                    action=SignalAction.SELL,
                    sl=signal.stop_loss,
                    tp=signal.take_profit or signal.target_1,
                    lot=signal.lot,
                    comment=f"Limit SELL [{signal.symbol or symbol}]",
                    instrument=signal.symbol or symbol
                )

        if self.dry_run:
            logger.info(
                f"[DRY RUN] Would place pending order: {signal.action.value} {lot} lots of {symbol} @ {entry} | "
                f"SL: {sl} | TP: {tp} | Magic: {self.magic_number}"
            )
            return ExecutionResult(
                success=True,
                action=signal.action.value,
                symbol=symbol,
                ticket=888888,
                price=entry,
                volume=lot,
                sl=sl,
                tp=tp,
                comment="Dry Run Simulated Pending Order"
            )

        filling_type = self._get_filling_type(symbol_info)
        request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": lot,
            "type": mt5_order_type,
            "price": entry,
            "sl": sl,
            "tp": tp,
            "deviation": self.deviation,
            "magic": self.magic_number,
            "comment": f"Pending [{signal.symbol or symbol}]"[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling_type,
        }

        res = mt5.order_send(request)
        if res is None:
            err = mt5.last_error()
            return ExecutionResult(success=False, action=signal.action.value, symbol=symbol, comment=f"order_send failed: {err}")

        if res.retcode == mt5.TRADE_RETCODE_DONE:
            return ExecutionResult(
                success=True,
                action=signal.action.value,
                symbol=symbol,
                ticket=res.order,
                price=entry,
                volume=lot,
                sl=sl,
                tp=tp,
                retcode=res.retcode,
                comment="Pending order placed successfully"
            )
        else:
            return ExecutionResult(
                success=False,
                action=signal.action.value,
                symbol=symbol,
                retcode=res.retcode,
                comment=f"MT5 rejected pending order: {res.comment} (retcode: {res.retcode})"
            )

    def get_open_positions(self, symbol: Optional[str] = None) -> List[Any]:
        """Retrieve open positions optionally filtered by symbol and pair magic number."""
        if not self.ensure_connected():
            return []
        try:
            if symbol:
                positions = mt5.positions_get(symbol=symbol)
            else:
                positions = mt5.positions_get()
            if not positions:
                return []
            if self.magic_number:
                filtered = [p for p in positions if p.magic == self.magic_number]
                return filtered if filtered else list(positions)
            return list(positions)
        except Exception as e:
            logger.debug(f"Error fetching open positions: {e}")
            return []

    def has_running_position(self, symbol: str) -> bool:
        """Check if an open position is currently active for this symbol."""
        positions = self.get_open_positions(symbol)
        return len(positions) > 0

    def _modify_sl(self, symbol: str, symbol_info, new_sl: Optional[float]) -> ExecutionResult:
        """Modify stop loss for open positions on this symbol."""
        if new_sl is None:
            return ExecutionResult(success=False, action="UPDATE_SL", symbol=symbol, comment="No SL value provided")

        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            return ExecutionResult(success=False, action="UPDATE_SL", symbol=symbol, comment=f"No open positions for {symbol}")

        updated = 0
        digits = symbol_info.digits
        sl_price = round(new_sl, digits)

        for pos in positions:
            if pos.magic == self.magic_number or self.magic_number == 0:
                if self.dry_run:
                    logger.info(f"[DRY RUN] Would update SL for #{pos.ticket} to {sl_price}")
                    updated += 1
                    continue

                req = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": pos.ticket,
                    "symbol": symbol,
                    "sl": sl_price,
                    "tp": pos.tp,
                }
                res = mt5.order_send(req)
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    updated += 1
                else:
                    logger.warning(f"Failed to update SL for #{pos.ticket}: {res.comment if res else mt5.last_error()}")

        return ExecutionResult(
            success=updated > 0,
            action="UPDATE_SL",
            symbol=symbol,
            sl=sl_price,
            comment=f"Updated SL to {sl_price} on {updated} positions"
        )

    def _modify_tp(self, symbol: str, symbol_info, new_tp: Optional[float]) -> ExecutionResult:
        """Modify take profit for open positions on this symbol."""
        if new_tp is None:
            return ExecutionResult(success=False, action="UPDATE_TP", symbol=symbol, comment="No TP value provided")

        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            return ExecutionResult(success=False, action="UPDATE_TP", symbol=symbol, comment=f"No open positions for {symbol}")

        updated = 0
        digits = symbol_info.digits
        tp_price = round(new_tp, digits)

        for pos in positions:
            if pos.magic == self.magic_number or self.magic_number == 0:
                if self.dry_run:
                    logger.info(f"[DRY RUN] Would update TP for #{pos.ticket} to {tp_price}")
                    updated += 1
                    continue

                req = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": pos.ticket,
                    "symbol": symbol,
                    "sl": pos.sl,
                    "tp": tp_price,
                }
                res = mt5.order_send(req)
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    updated += 1
                else:
                    logger.warning(f"Failed to update TP for #{pos.ticket}: {res.comment if res else mt5.last_error()}")

        return ExecutionResult(
            success=updated > 0,
            action="UPDATE_TP",
            symbol=symbol,
            tp=tp_price,
            comment=f"Updated TP to {tp_price} on {updated} positions"
        )

    def _apply_targets_and_sl(self, symbol: str, symbol_info, signal: TradeSignal) -> ExecutionResult:
        """Apply Targets and SL (e.g. 'TGT1- 4245 TGT2- 4235 SL- 4260')."""
        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            return ExecutionResult(success=False, action="UPDATE_TARGETS_AND_SL", symbol=symbol, comment=f"No open positions for {symbol}")

        digits = symbol_info.digits
        t1 = round(signal.target_1 or (signal.take_profit or 0.0), digits) if (signal.target_1 or signal.take_profit) else None
        t2 = round(signal.target_2, digits) if signal.target_2 else None
        sl = round(signal.stop_loss, digits) if signal.stop_loss else None

        updated = 0
        for pos in positions:
            if pos.magic == self.magic_number or self.magic_number == 0:
                cur_sl = sl if sl is not None else pos.sl
                cur_tp = t1 if t1 is not None else pos.tp

                if self.dry_run:
                    logger.info(f"[DRY RUN] Would set #{pos.ticket} SL={cur_sl}, TP={cur_tp}")
                    if t2:
                        self.active_targets[pos.ticket] = {
                            "symbol": symbol,
                            "target_1": t1,
                            "target_2": t2,
                            "pos_type": pos.type,
                            "t1_hit": False,
                            "initial_vol": pos.volume
                        }
                    updated += 1
                    continue

                req = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": pos.ticket,
                    "symbol": symbol,
                    "sl": cur_sl,
                    "tp": cur_tp,
                }
                res = mt5.order_send(req)
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    updated += 1
                    if t2:
                        self.active_targets[pos.ticket] = {
                            "symbol": symbol,
                            "target_1": t1,
                            "target_2": t2,
                            "pos_type": pos.type,
                            "t1_hit": False,
                            "initial_vol": pos.volume
                        }
                        logger.info(f"🎯 Position #{pos.ticket} registered for 2-target management (T1={t1}, T2={t2})")
                else:
                    logger.warning(f"Failed to update #{pos.ticket}: {res.comment if res else mt5.last_error()}")

        return ExecutionResult(
            success=updated > 0,
            action="UPDATE_TARGETS_AND_SL",
            symbol=symbol,
            sl=sl,
            tp=t1,
            comment=f"Applied targets (T1={t1}, T2={t2}) and SL={sl} on {updated} positions"
        )

    def _move_to_breakeven(self, symbol: str, symbol_info) -> ExecutionResult:
        """Move stop loss to open price (breakeven)."""
        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            return ExecutionResult(success=False, action="BREAKEVEN", symbol=symbol, comment=f"No open positions for {symbol}")

        updated = 0
        digits = symbol_info.digits
        for pos in positions:
            if pos.magic == self.magic_number or self.magic_number == 0:
                be_price = round(pos.price_open, digits)
                if self.dry_run:
                    logger.info(f"[DRY RUN] Would move #{pos.ticket} SL to Breakeven @ {be_price}")
                    updated += 1
                    continue

                req = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": pos.ticket,
                    "symbol": symbol,
                    "sl": be_price,
                    "tp": pos.tp,
                }
                res = mt5.order_send(req)
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    updated += 1
                    logger.info(f"Moved #{pos.ticket} SL to Breakeven ({be_price})")
                else:
                    logger.warning(f"Failed to set breakeven on #{pos.ticket}: {res.comment if res else mt5.last_error()}")

        return ExecutionResult(
            success=updated > 0,
            action="BREAKEVEN",
            symbol=symbol,
            comment=f"Moved {updated} positions to breakeven"
        )

    def _close_positions(self, symbol: str, ratio: float = 1.0) -> ExecutionResult:
        """Close full or partial positions on this symbol."""
        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            return ExecutionResult(success=False, action="CLOSE", symbol=symbol, comment=f"No open positions for {symbol}")

        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            return ExecutionResult(success=False, action="CLOSE", symbol=symbol, comment=f"Symbol info unavailable for {symbol}")

        step = symbol_info.volume_step or 0.01
        min_vol = symbol_info.volume_min or 0.01

        closed = 0
        for pos in positions:
            if pos.magic == self.magic_number or self.magic_number == 0:
                vol_to_close = pos.volume if ratio >= 1.0 else round(round((pos.volume * ratio) / step) * step, 2)
                vol_to_close = max(min_vol, min(pos.volume, vol_to_close))

                if self.dry_run:
                    logger.info(f"[DRY RUN] Would close {vol_to_close} lots of #{pos.ticket} on {symbol}")
                    closed += 1
                    continue

                ok = self._close_ticket(pos.ticket, symbol, symbol_info, vol_to_close, pos.type)
                if ok:
                    closed += 1
                    self.active_targets.pop(pos.ticket, None)

        action_name = "EXIT" if ratio >= 1.0 else f"CLOSE_{int(ratio*100)}%"
        return ExecutionResult(
            success=closed > 0,
            action=action_name,
            symbol=symbol,
            comment=f"Closed {closed} positions (ratio: {ratio})"
        )

    def _close_ticket(self, ticket: int, symbol: str, symbol_info, volume: float, pos_type: int) -> bool:
        """Execute close order for specific ticket."""
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return False

        is_buy = (pos_type == mt5.ORDER_TYPE_BUY)
        close_type = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
        price = tick.bid if is_buy else tick.ask

        filling = self._get_filling_type(symbol_info)
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": symbol,
            "volume": volume,
            "type": close_type,
            "price": price,
            "deviation": self.deviation,
            "magic": self.magic_number,
            "comment": f"Close #{ticket}"[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling,
        }
        res = mt5.order_send(req)
        return bool(res and res.retcode == mt5.TRADE_RETCODE_DONE)

    def check_target_triggers(self):
        """Check active 2-target positions. If Target 1 is reached, close 50%, set breakeven, and aim for Target 2."""
        if not self.active_targets or not self.connected:
            return

        for ticket, info in list(self.active_targets.items()):
            positions = mt5.positions_get(ticket=ticket)
            if not positions:
                self.active_targets.pop(ticket, None)
                continue

            pos = positions[0]
            symbol = info["symbol"]
            target_1 = info.get("target_1")
            target_2 = info.get("target_2")
            pos_type = info["pos_type"]

            tick = mt5.symbol_info_tick(symbol)
            if not tick:
                continue

            symbol_info = mt5.symbol_info(symbol)
            if not symbol_info:
                continue

            t1_reached = False
            current_price = 0.0
            if pos_type == mt5.ORDER_TYPE_BUY:
                current_price = tick.bid
                if target_1 and current_price >= target_1:
                    t1_reached = True
            elif pos_type == mt5.ORDER_TYPE_SELL:
                current_price = tick.ask
                if target_1 and current_price <= target_1:
                    t1_reached = True

            if t1_reached and not info.get("t1_hit"):
                info["t1_hit"] = True
                total_vol = pos.volume
                step = symbol_info.volume_step or 0.01
                min_vol = symbol_info.volume_min or 0.01

                close_vol = round(round((total_vol * 0.5) / step) * step, 2)
                close_vol = max(min_vol, close_vol)
                rem_vol = round(total_vol - close_vol, 2)

                logger.info(
                    f"🎯 [TARGET 1 HIT] {symbol} at {current_price} (Target 1={target_1})! "
                    f"#{ticket} Vol: {total_vol} lots -> Closing 50% ({close_vol} lots)..."
                )

                if self.dry_run:
                    logger.info(
                        f"[DRY RUN] Would close {close_vol} lots of #{ticket}, "
                        f"set remaining {rem_vol} lots TP={target_2}, SL=Breakeven ({pos.price_open})"
                    )
                    self.active_targets.pop(ticket, None)
                    continue

                closed_ok = self._close_ticket(ticket, symbol, symbol_info, close_vol, pos_type)
                if closed_ok:
                    logger.info(f"Target 1 partial close executed: Closed {close_vol} lots of #{ticket}. Remaining: {rem_vol} lots.")
                    if rem_vol >= min_vol and target_2:
                        be_price = round(pos.price_open, symbol_info.digits)
                        tp2_price = round(target_2, symbol_info.digits)
                        req = {
                            "action": mt5.TRADE_ACTION_SLTP,
                            "position": ticket,
                            "symbol": symbol,
                            "sl": be_price,
                            "tp": tp2_price,
                        }
                        res = mt5.order_send(req)
                        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                            logger.info(f"Position #{ticket} remaining {rem_vol} lots: SL moved to Breakeven ({be_price}), TP set to Target 2 ({tp2_price}) on broker!")
                        else:
                            logger.warning(f"Failed to update #{ticket} with Target 2 and Breakeven: {res.comment if res else mt5.last_error()}")

                self.active_targets.pop(ticket, None)

    async def start_position_monitor(self):
        """Async background task that monitors prices for multi-target partial close."""
        while self.connected:
            try:
                self.check_target_triggers()
            except Exception as e:
                logger.error(f"Error in target monitor: {e}")
            await asyncio.sleep(1.0)
