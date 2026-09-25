import os
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
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

                        pairs.append(
                            PairConfig(
                                id=idx,
                                name=p.get("name", f"Pair-{idx}"),
                                channel=str(p.get("channel", "")).strip(),
                                mt5_path=str(p.get("mt5_path", "")).strip(),
                                mode=mode,
                                magic_number=int(p.get("magic", p.get("magic_number", 777000 + idx))),
                                mt5_login=int(p["login"]) if p.get("login") else None,
                                mt5_password=p.get("password"),
                                mt5_server=p.get("server"),
                                execution_mode=p.get("execution_mode"),
                                dry_run=p.get("dry_run"),
                                lot_gold=p.get("lot_gold"),
                                lot_btc=p.get("lot_btc"),
                                lot_usoil=p.get("lot_usoil"),
                                lot_us30=p.get("lot_us30"),
                                lot_forex=p.get("lot_forex"),
                                lot_default=p.get("lot_default"),
                                past_hours=past_hours,
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

            login_str = os.getenv(f"PAIR_{i}_LOGIN")
            login = int(login_str) if login_str and login_str.isdigit() else None
            password = os.getenv(f"PAIR_{i}_PASSWORD") or None
            server = os.getenv(f"PAIR_{i}_SERVER") or None

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
                        past_hours=legacy_past_hours,
                    )
                )

        return pairs

settings = Settings()
settings.DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
