import os
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from dotenv import load_dotenv

from models import PairConfig, PairMode

BASE_DIR = Path(__file__).resolve().parent

# Load environment variables from .env in project directory
env_path = BASE_DIR / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

logger = logging.getLogger(__name__)

def parse_past_hours(val: Any) -> float:
    """Parse past_hours from env or dict. Returns 0.0 if blank, None, <=0, or invalid."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return max(0.0, float(val))
    str_val = str(val).strip()
    if not str_val:
        return 0.0
    try:
        hours = float(str_val)
        return max(0.0, hours)
    except (ValueError, TypeError):
        logger.warning(f"Invalid past_hours value '{val}'. Defaulting to 0.0 (disabled).")
        return 0.0

def parse_price_offset(val: Any) -> Optional[Union[float, str]]:
    """Parse price offset value. Can be a float (e.g. 0.25, -0.30) or 'auto', or None if blank/invalid."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    str_val = str(val).strip()
    if not str_val:
        return None
    lower_val = str_val.lower()
    if lower_val in ("candle_match", "candle", "candles", "match", "candle-match", "candlematch"):
        return "candle_match"
    if lower_val == "auto":
        return "auto"
    try:
        return float(str_val)
    except (ValueError, TypeError):
        logger.warning(f"Invalid price offset value '{val}'. Ignoring.")
        return None

def parse_login(val: Any) -> Optional[int]:
    """Parse MT5 login/account number. Returns None if blank, None, <=0, or non-numeric."""
    if val is None:
        return None
    if isinstance(val, int):
        return val if val > 0 else None
    str_val = str(val).strip()
    if not str_val:
        return None
    if str_val.isdigit():
        login_int = int(str_val)
        return login_int if login_int > 0 else None
    return None

def parse_str_credential(val: Any) -> Optional[str]:
    """Parse string credential (password/server). Returns None if blank, None, or whitespace."""
    if val is None:
        return None
    str_val = str(val).strip()
    return str_val if str_val else None

class Settings:
    BASE_DIR: Path = BASE_DIR
    DOWNLOADS_DIR: Path = BASE_DIR / "downloads"

    # =========================================================================
    # Telegram API Configuration
    # =========================================================================
    TELEGRAM_API_ID: int = int(os.getenv("TELEGRAM_API_ID", "0")) if os.getenv("TELEGRAM_API_ID", "").strip().isdigit() else 0
    TELEGRAM_API_HASH: str = os.getenv("TELEGRAM_API_HASH", "").strip()
    TELEGRAM_PHONE: Optional[str] = os.getenv("TELEGRAM_PHONE", "").strip() or None
    TELEGRAM_SESSION_NAME: str = os.getenv("TELEGRAM_SESSION_NAME", "trading_unified_session").strip()

    # =========================================================================
    # Google Gemini AI Configuration
    # =========================================================================
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip()
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
    GEMINI_TEMPERATURE: float = float(os.getenv("GEMINI_TEMPERATURE", "0.1"))
    GEMINI_TIMEOUT_SECONDS: int = int(os.getenv("GEMINI_TIMEOUT_SECONDS", "30"))

    # =========================================================================
    # General MT5 & Execution Settings
    # =========================================================================
    MT5_DEVIATION: int = int(os.getenv("MT5_DEVIATION", "20"))
    DRY_RUN: bool = os.getenv("DRY_RUN", "false").lower() in ("true", "1", "yes")
    FORCE_GOLD_ONLY: bool = os.getenv("FORCE_GOLD_ONLY", "false").lower() in ("true", "1", "yes")
    DEFAULT_GOLD_SYMBOL: str = os.getenv("DEFAULT_GOLD_SYMBOL", "GOLD.i#").strip()

    # MT5 Global Login Credentials (Optional fallback: leave blank if already logged in)
    MT5_LOGIN: Optional[int] = parse_login(os.getenv("MT5_LOGIN") or os.getenv("LOGIN"))
    MT5_PASSWORD: Optional[str] = parse_str_credential(os.getenv("MT5_PASSWORD") or os.getenv("PASSWORD"))
    MT5_SERVER: Optional[str] = parse_str_credential(os.getenv("MT5_SERVER") or os.getenv("SERVER"))

    # Ansh / Vision specific options
    EXECUTION_MODE: str = os.getenv("EXECUTION_MODE", "auto").lower()  # auto, breakout, market, pending
    MAX_SLIPPAGE_POINTS: int = int(os.getenv("MAX_SLIPPAGE_POINTS", "60"))
    TARGET_TO_USE: str = os.getenv("TARGET_TO_USE", "TP1").upper()
    BREAKOUT_MONITOR_ENABLED: bool = os.getenv("BREAKOUT_MONITOR_ENABLED", "true").lower() in ("true", "1", "yes")
    BREAKOUT_CHECK_INTERVAL_SEC: float = float(os.getenv("BREAKOUT_CHECK_INTERVAL_SEC", "1.0"))
    WATCHER_EXPIRY_HOURS: int = int(os.getenv("WATCHER_EXPIRY_HOURS", "24"))

    # =========================================================================
    # Lot Size Configuration (Per $50 Base Account Size)
    # =========================================================================
    USE_DYNAMIC_LOT: bool = os.getenv("USE_DYNAMIC_LOT", "true").lower() in ("true", "1", "yes")
    
    # Base account balance (e.g. $50.0)
    BASE_ACCOUNT_SIZE: float = float(
        os.getenv("BASE_ACCOUNT_SIZE") or os.getenv("LOT_ACCOUNT_SIZE_BASE", "50.0")
    )
    
    # Per-instrument base lots per $50 balance
    LOT_GOLD_PER_50: float = float(
        os.getenv("LOT_GOLD_PER_50") or os.getenv("LOT_PER_BASE_GOLD", "0.02")
    )
    LOT_BTC_PER_50: float = float(
        os.getenv("LOT_BTC_PER_50") or os.getenv("LOT_PER_BASE_BTC", "0.03")
    )
    LOT_USOIL_PER_50: float = float(
        os.getenv("LOT_USOIL_PER_50") or os.getenv("LOT_PER_BASE_US_OIL", "0.02")
    )
    LOT_US30_PER_50: float = float(
        os.getenv("LOT_US30_PER_50") or os.getenv("LOT_PER_BASE_US30", "0.10")
    )
    LOT_FOREX_PER_50: float = float(
        os.getenv("LOT_FOREX_PER_50") or os.getenv("LOT_PER_BASE_FOREX", "0.10")
    )
    LOT_DEFAULT_PER_50: float = float(os.getenv("LOT_DEFAULT_PER_50", "0.02"))

    LOT_SCALING_MODE: str = os.getenv("LOT_SCALING_MODE", "proportional").lower()  # "proportional" or "step"
    # When balance < base ($50): "min_base" (keeps base lot) or "proportional" (scales down)
    LOT_BELOW_BASE_MODE: str = os.getenv("LOT_BELOW_BASE_MODE", "min_base").lower()
    MIN_LOT_SIZE: float = float(os.getenv("MIN_LOT_SIZE", "0.01"))
    MT5_DEFAULT_LOT: float = float(os.getenv("MT5_DEFAULT_LOT", "0.02"))

    # =========================================================================
    # Symbol Mappings (JSON format)
    # =========================================================================
    RAW_SYMBOL_MAPPINGS: str = os.getenv(
        "SYMBOL_MAPPINGS",
        '{"USOIL": "OILCash#", "USOILCASH": "OILCash#", "USOILSPOT": "OILCash#", "WTI": "OILCash#", "CRUDE": "OILCash#", "OIL": "OILCash#", "UKOIL": "BRENTCash#", "BRENT": "BRENTCash#", "GOLD": "GOLD.i#", "XAUUSD": "GOLD.i#", "SILVER": "SILVER.i#", "XAGUSD": "SILVER.i#", "BTC": "BTCUSD#", "BTCUSD": "BTCUSD#", "BITCOIN": "BTCUSD#", "US 30": "US30Cash#", "US30": "US30Cash#", "NAS100": "US100Cash#", "US100": "US100Cash#", "SPX500": "US500Cash#", "GER40": "GER40Cash#", "EURUSD": "EURUSD#", "GBPUSD": "GBPUSD#", "USDJPY": "USDJPY#"}'
    )

    def load_mappings(self) -> Dict[str, str]:
        """Parse SYMBOL_MAPPINGS JSON string into dict."""
        try:
            raw = json.loads(self.RAW_SYMBOL_MAPPINGS)
            return {k.strip().upper(): v.strip() for k, v in raw.items()}
        except Exception as e:
            logger.warning(f"Failed to parse SYMBOL_MAPPINGS JSON: {e}. Using empty dict.")
            return {}

    # =========================================================================
    # Price Offsets (e.g. USOILSPOT on chart vs OILCash on MT5)
    # =========================================================================
    USOIL_PRICE_OFFSET: Optional[Union[float, str]] = parse_price_offset(
        os.getenv("USOIL_PRICE_OFFSET") or 
        os.getenv("OFFSET_USOIL") or 
        os.getenv("USOIL_OFFSET") or 
        os.getenv("PRICE_OFFSET_USOIL") or 
        os.getenv("OILCASH_PRICE_OFFSET") or 
        "0.0"
    )
    PRICE_OFFSETS: str = os.getenv("PRICE_OFFSETS", "{}")
    CANDLE_MATCHING_ENABLED: bool = os.getenv("CANDLE_MATCHING_ENABLED", "true").lower() in ("true", "1", "yes")
    CANDLE_MATCH_COUNT: int = int(os.getenv("CANDLE_MATCH_COUNT", "10"))

    def load_price_offsets(self) -> Dict[str, Union[float, str]]:
        """Parse PRICE_OFFSETS JSON string or dict into normalized dictionary."""
        try:
            if isinstance(self.PRICE_OFFSETS, dict):
                raw = self.PRICE_OFFSETS
            else:
                raw = json.loads(self.PRICE_OFFSETS) if self.PRICE_OFFSETS else {}
            res = {}
            for k, v in raw.items():
                parsed = parse_price_offset(v)
                if parsed is not None:
                    res[k.strip().upper()] = parsed
            return res
        except Exception as e:
            logger.warning(f"Failed to parse PRICE_OFFSETS JSON: {e}. Using empty dict.")
            return {}

    def is_oil_instrument(self, instrument: str = "", broker_symbol: str = "") -> bool:
        """Check if instrument or broker_symbol is US Oil / WTI / Crude / OILCash."""
        oil_markers = {"USOIL", "USOILSPOT", "USOILCASH", "OILCASH", "OIL", "WTI", "WTICRUDE", "CRUDE", "CRUDESOIL", "CL", "XTIUSD"}
        cand = f"{instrument} {broker_symbol}".upper()
        clean = cand.replace("#", "").replace(".", " ").replace("_", " ").replace("/", " ").replace("-", " ")
        words = set(clean.split())
        return any(m in words for m in oil_markers)

    def get_price_offset_for_instrument(
        self,
        instrument: str,
        pair_cfg: Optional[PairConfig] = None,
        broker_symbol: Optional[str] = None
    ) -> Optional[Union[float, str]]:
        """
        Get configured price offset for a specific instrument.
        Checks:
        1. Pair-specific overrides (pair_cfg.usoil_price_offset, pair_cfg.price_offsets).
        2. Global PRICE_OFFSETS dict.
        3. Global USOIL_PRICE_OFFSET for oil instruments.
        """
        clean_inst = (instrument or "").strip().upper()
        clean_broker = (broker_symbol or "").strip().upper()

        # 1. Check pair_config if provided
        if pair_cfg:
            if clean_inst in pair_cfg.price_offsets:
                return pair_cfg.price_offsets[clean_inst]
            if clean_broker in pair_cfg.price_offsets:
                return pair_cfg.price_offsets[clean_broker]
            if pair_cfg.usoil_price_offset is not None and self.is_oil_instrument(clean_inst, clean_broker):
                return pair_cfg.usoil_price_offset

        # 2. Check global PRICE_OFFSETS dict
        global_offsets = self.load_price_offsets()
        if clean_inst in global_offsets:
            return global_offsets[clean_inst]
        if clean_broker in global_offsets:
            return global_offsets[clean_broker]

        # 3. Check global USOIL_PRICE_OFFSET or CANDLE_MATCHING_ENABLED
        if self.is_oil_instrument(clean_inst, clean_broker):
            if self.USOIL_PRICE_OFFSET is not None and str(self.USOIL_PRICE_OFFSET).strip() not in ("0.0", "0"):
                return self.USOIL_PRICE_OFFSET
            if self.CANDLE_MATCHING_ENABLED:
                return "candle_match"
            if self.USOIL_PRICE_OFFSET is not None:
                return self.USOIL_PRICE_OFFSET

        return 0.0

    # =========================================================================
    # Telegram Channel <-> MT5 Terminal Pairs Discovery
    # =========================================================================
    def get_configured_pairs(self) -> List[PairConfig]:
        """
        Dynamically discover and parse all configured Channel-MT5 pairs.
        Supports:
        1. PAIR_1_*, PAIR_2_*, PAIR_3_*, ... indexed environment variables.
        2. PAIRS=[{...}] JSON array.
        3. Backward compatibility fallback to single MT5_PATH & TELEGRAM_CHANNEL.
        """
        pairs: List[PairConfig] = []

        # 1. Check for JSON array in PAIRS
        raw_pairs = os.getenv("PAIRS", "").strip()
        if raw_pairs:
            try:
                pairs_data = json.loads(raw_pairs)
                if isinstance(pairs_data, list):
                    for idx, p in enumerate(pairs_data, start=1):
                        mode_str = p.get("mode", "image").lower()
                        mode = PairMode.IMAGE
                        if mode_str in ("text", "twm", "message"):
                            mode = PairMode.TEXT
                        elif mode_str in ("both", "all"):
                            mode = PairMode.BOTH

                        past_hours_raw = p.get("past_hours", p.get("fetch_past_hours", p.get("read_past_hours")))
                        past_hours = parse_past_hours(past_hours_raw)

                        usoil_offset = parse_price_offset(p.get("usoil_price_offset", p.get("usoil_offset", p.get("price_offset"))))
                        p_offsets = {}
                        if isinstance(p.get("price_offsets"), dict):
                            for ok, ov in p["price_offsets"].items():
                                parsed_v = parse_price_offset(ov)
                                if parsed_v is not None:
                                    p_offsets[ok.strip().upper()] = parsed_v

                        login_val = None
                        login_specified = False
                        for lk in ("mt5_login", "login", "account", "mt5_account"):
                            if lk in p:
                                login_specified = True
                                val = p[lk]
                                if val is not None and str(val).strip():
                                    login_val = val
                                    break
                        mt5_login = parse_login(login_val) if login_specified else self.MT5_LOGIN

                        pass_val = None
                        pass_specified = False
                        for pk in ("mt5_password", "password", "pass", "mt5_pass"):
                            if pk in p:
                                pass_specified = True
                                val = p[pk]
                                if val is not None and str(val).strip():
                                    pass_val = val
                                    break
                        mt5_password = parse_str_credential(pass_val) if pass_specified else self.MT5_PASSWORD

                        server_val = None
                        server_specified = False
                        for sk in ("mt5_server", "server"):
                            if sk in p:
                                server_specified = True
                                val = p[sk]
                                if val is not None and str(val).strip():
                                    server_val = val
                                    break
                        mt5_server = parse_str_credential(server_val) if server_specified else self.MT5_SERVER

                        pairs.append(
                            PairConfig(
                                id=idx,
                                name=p.get("name", f"Pair-{idx}"),
                                channel=str(p.get("channel", "")).strip(),
                                mt5_path=str(p.get("mt5_path", "")).strip(),
                                mode=mode,
                                magic_number=int(p.get("magic", p.get("magic_number", 777000 + idx))),
                                mt5_login=mt5_login,
                                mt5_password=mt5_password,
                                mt5_server=mt5_server,
                                execution_mode=p.get("execution_mode"),
                                dry_run=p.get("dry_run"),
                                lot_gold=p.get("lot_gold"),
                                lot_btc=p.get("lot_btc"),
                                lot_usoil=p.get("lot_usoil"),
                                lot_us30=p.get("lot_us30"),
                                lot_forex=p.get("lot_forex"),
                                lot_default=p.get("lot_default"),
                                past_hours=past_hours,
                                usoil_price_offset=usoil_offset,
                                price_offsets=p_offsets,
                            )
                        )
                    if pairs:
                        return pairs
            except Exception as e:
                logger.warning(f"Failed to parse PAIRS JSON: {e}")

        # 2. Check for PAIR_1_*, PAIR_2_*, ... indexed env vars
        for i in range(1, 101):
            chan_key = f"PAIR_{i}_CHANNEL"
            path_key = f"PAIR_{i}_MT5_PATH"

            channel = os.getenv(chan_key, "").strip()
            mt5_path = os.getenv(path_key, "").strip()

            if not channel and not mt5_path:
                # If neither channel nor path is defined for this index, continue
                continue

            name = os.getenv(f"PAIR_{i}_NAME", f"Pair-{i}").strip()
            mode_str = os.getenv(f"PAIR_{i}_MODE", "image").strip().lower()
            if mode_str in ("text", "twm", "message"):
                mode = PairMode.TEXT
            elif mode_str in ("both", "all"):
                mode = PairMode.BOTH
            else:
                mode = PairMode.IMAGE

            magic_str = os.getenv(f"PAIR_{i}_MAGIC") or os.getenv(f"PAIR_{i}_MAGIC_NUMBER")
            magic = int(magic_str) if magic_str and magic_str.isdigit() else (777000 + i)

            login_key_found = False
            login_raw = None
            for lk in (f"PAIR_{i}_MT5_LOGIN", f"PAIR_{i}_LOGIN", f"PAIR_{i}_ACCOUNT", f"PAIR_{i}_MT5_ACCOUNT"):
                if lk in os.environ:
                    login_key_found = True
                    val = os.environ[lk].strip()
                    if val:
                        login_raw = val
                        break
            login = parse_login(login_raw) if login_key_found else self.MT5_LOGIN

            pass_key_found = False
            pass_raw = None
            for pk in (f"PAIR_{i}_MT5_PASSWORD", f"PAIR_{i}_PASSWORD", f"PAIR_{i}_PASS", f"PAIR_{i}_MT5_PASS"):
                if pk in os.environ:
                    pass_key_found = True
                    val = os.environ[pk].strip()
                    if val:
                        pass_raw = val
                        break
            password = parse_str_credential(pass_raw) if pass_key_found else self.MT5_PASSWORD

            server_key_found = False
            server_raw = None
            for sk in (f"PAIR_{i}_MT5_SERVER", f"PAIR_{i}_SERVER"):
                if sk in os.environ:
                    server_key_found = True
                    val = os.environ[sk].strip()
                    if val:
                        server_raw = val
                        break
            server = parse_str_credential(server_raw) if server_key_found else self.MT5_SERVER

            exec_mode = os.getenv(f"PAIR_{i}_EXECUTION_MODE")
            dry_run_val = os.getenv(f"PAIR_{i}_DRY_RUN")
            dry_run = dry_run_val.lower() in ("true", "1", "yes") if dry_run_val else None

            # Optional lot overrides
            lot_gold = float(os.getenv(f"PAIR_{i}_LOT_GOLD")) if os.getenv(f"PAIR_{i}_LOT_GOLD") else None
            lot_btc = float(os.getenv(f"PAIR_{i}_LOT_BTC")) if os.getenv(f"PAIR_{i}_LOT_BTC") else None
            lot_usoil = float(os.getenv(f"PAIR_{i}_LOT_USOIL")) if os.getenv(f"PAIR_{i}_LOT_USOIL") else None
            lot_us30 = float(os.getenv(f"PAIR_{i}_LOT_US30")) if os.getenv(f"PAIR_{i}_LOT_US30") else None
            lot_forex = float(os.getenv(f"PAIR_{i}_LOT_FOREX")) if os.getenv(f"PAIR_{i}_LOT_FOREX") else None
            lot_default = float(os.getenv(f"PAIR_{i}_LOT_DEFAULT")) if os.getenv(f"PAIR_{i}_LOT_DEFAULT") else None

            # Past hours configuration (set to >0 to retrieve past hours chat, blank/0 to disable)
            past_hours_raw = None
            for pk in (f"PAIR_{i}_PAST_HOURS", f"PAIR_{i}_FETCH_PAST_HOURS", f"PAIR_{i}_READ_PAST_HOURS"):
                if pk in os.environ:
                    past_hours_raw = os.environ[pk]
                    break
            if past_hours_raw is None:
                for gk in ("PAST_HOURS", "FETCH_PAST_HOURS", "READ_PAST_HOURS"):
                    if gk in os.environ:
                        past_hours_raw = os.environ[gk]
                        break
            past_hours = parse_past_hours(past_hours_raw)

            # Optional pair price offset
            usoil_offset_raw = None
            for ok in (f"PAIR_{i}_USOIL_PRICE_OFFSET", f"PAIR_{i}_USOIL_OFFSET", f"PAIR_{i}_PRICE_OFFSET", f"PAIR_{i}_OFFSET_USOIL"):
                if ok in os.environ:
                    usoil_offset_raw = os.environ[ok]
                    break
            usoil_offset = parse_price_offset(usoil_offset_raw)

            pairs.append(
                PairConfig(
                    id=i,
                    name=name,
                    channel=channel,
                    mt5_path=mt5_path,
                    mode=mode,
                    magic_number=magic,
                    mt5_login=login,
                    mt5_password=password,
                    mt5_server=server,
                    execution_mode=exec_mode,
                    dry_run=dry_run,
                    lot_gold=lot_gold,
                    lot_btc=lot_btc,
                    lot_usoil=lot_usoil,
                    lot_us30=lot_us30,
                    lot_forex=lot_forex,
                    lot_default=lot_default,
                    past_hours=past_hours,
                    usoil_price_offset=usoil_offset,
                )
            )

        # 3. Fallback: single pair from legacy MT5_PATH / TELEGRAM_CHANNEL
        if not pairs:
            legacy_path = os.getenv("MT5_PATH", "").strip()
            legacy_chan = os.getenv("TELEGRAM_CHANNEL", "").strip()
            legacy_mode = os.getenv("PAIR_MODE", "image").strip().lower()
            if legacy_path or legacy_chan:
                legacy_past_hours_raw = None
                for gk in ("PAST_HOURS", "FETCH_PAST_HOURS", "READ_PAST_HOURS"):
                    if gk in os.environ:
                        legacy_past_hours_raw = os.environ[gk]
                        break
                legacy_past_hours = parse_past_hours(legacy_past_hours_raw)

                pairs.append(
                    PairConfig(
                        id=1,
                        name="Default-Pair",
                        channel=legacy_chan,
                        mt5_path=legacy_path,
                        mode=PairMode.TEXT if legacy_mode == "text" else PairMode.IMAGE,
                        magic_number=int(os.getenv("MT5_MAGIC_NUMBER", "777999")),
                        mt5_login=self.MT5_LOGIN,
                        mt5_password=self.MT5_PASSWORD,
                        mt5_server=self.MT5_SERVER,
                        past_hours=legacy_past_hours,
                    )
                )

        return pairs

settings = Settings()
settings.DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
