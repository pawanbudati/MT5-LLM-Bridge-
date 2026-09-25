import sys
import asyncio
import logging
import multiprocessing
from pathlib import Path
from typing import List, Dict
import colorama
from colorama import Fore, Style

from config import settings
from models import PairConfig, PairMode
from utils import ColoredFormatter
from pair_worker import run_pair_worker
from telegram_listener import MasterTelegramDispatcher

colorama.init(autoreset=True)

def setup_logging():
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ColoredFormatter("%(asctime)s [%(levelname)s] [Main] %(message)s", datefmt="%H:%M:%S"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [handler]
    logging.getLogger("google.genai").setLevel(logging.ERROR)

def print_banner(pairs: List[PairConfig]):
    banner = f"""{Fore.GREEN}{Style.BRIGHT}
===============================================================================
       TELEGRAM MULTI-CHANNEL -> MULTI-MT5 TERMINAL UNIFIED BOT
===============================================================================
  * Multi-Channel & Multi-Terminal Orchestration Engine
  * Dual Signal Analysis Modes:
      [IMAGE] : Gemini Vision Multimodal Chart & Breakout Level Extractor
      [TEXT]  : Gemini AI & Regex Direct Text Signal & Position Manager
  * Real-Time Range Breakout Observer & BreakoutWatcherEA Integration
  * Advanced Dynamic Lot Management ($50 Base Account Scaling)
  * Independent Isolated Process per MT5 Terminal Instance
==============================================================================={Style.RESET_ALL}"""
    print(banner)

    print(Fore.CYAN + Style.BRIGHT + "  Configured Channel <-> MT5 Terminal Pairs:" + Style.RESET_ALL)
    for p in pairs:
        mode_color = Fore.MAGENTA if p.mode == PairMode.IMAGE else (Fore.BLUE if p.mode == PairMode.TEXT else Fore.YELLOW)
        past_str = f"{p.past_hours:g}h" if p.past_hours > 0 else "OFF"
        print(
            f"   [{p.id}] {Fore.WHITE}{Style.BRIGHT}{p.name:18}{Style.RESET_ALL} | "
            f"Mode: {mode_color}{p.mode.value.upper():5}{Style.RESET_ALL} | "
            f"Channel: {Fore.YELLOW}{p.channel:16}{Style.RESET_ALL} | "
            f"Past: {Fore.CYAN}{past_str:4}{Style.RESET_ALL} | "
            f"Magic: {p.magic_number:7} | "
            f"MT5: {Path(p.mt5_path).parent.name if p.mt5_path else 'N/A'}"
        )
    print(Fore.GREEN + "===============================================================================\n" + Style.RESET_ALL)

def preflight_checks(pairs: List[PairConfig]) -> bool:
    """Validate critical configurations before launching."""
    ok = True

    # 1. Telegram Credentials
    if not settings.TELEGRAM_API_ID or not settings.TELEGRAM_API_HASH:
        logging.error("TELEGRAM_API_ID or TELEGRAM_API_HASH is missing in .env!")
        logging.error("Please configure them from https://my.telegram.org in your .env file.")
        ok = False

    # 2. Gemini API Key
    if not settings.GEMINI_API_KEY:
        logging.warning("GEMINI_API_KEY is not set in .env! (Vision and LLM features will fall back to rule parser)")
    else:
        masked_key = settings.GEMINI_API_KEY[:6] + "..." + settings.GEMINI_API_KEY[-4:]
        logging.info(f"Gemini AI API Key configured: {masked_key} (Model: {settings.GEMINI_MODEL})")

    # 3. Check Pairs
    if not pairs:
        logging.error("No Channel-MT5 pairs configured in .env! Please define PAIR_1_CHANNEL and PAIR_1_MT5_PATH.")
        ok = False
    else:
        for p in pairs:
            if not p.channel:
                logging.error(f"Pair #{p.id} [{p.name}] is missing channel configuration.")
                ok = False
            if not p.mt5_path:
                logging.error(f"Pair #{p.id} [{p.name}] is missing MT5 terminal path.")
                ok = False
            elif not Path(p.mt5_path).exists():
                logging.warning(f"Pair #{p.id} [{p.name}] MT5 executable not found at: {p.mt5_path}")

    # Lot rules overview
    logging.info(
        f"Lot Sizing Config: Dynamic={settings.USE_DYNAMIC_LOT} | Base=${settings.BASE_ACCOUNT_SIZE} | "
        f"GOLD={settings.LOT_GOLD_PER_50} | BTC={settings.LOT_BTC_PER_50} | OIL={settings.LOT_USOIL_PER_50} | "
        f"US30={settings.LOT_US30_PER_50} | FOREX={settings.LOT_FOREX_PER_50} | Mode={settings.LOT_SCALING_MODE}"
    )
    logging.info(f"Global Dry Run: {Fore.YELLOW if settings.DRY_RUN else Fore.GREEN}{settings.DRY_RUN}{Style.RESET_ALL}")
    return ok

async def async_main(pairs: List[PairConfig], pair_queues: Dict[int, multiprocessing.Queue], stop_event: multiprocessing.Event):
    dispatcher = MasterTelegramDispatcher(pairs, pair_queues)
    try:
        await dispatcher.start()
        await dispatcher.run_until_disconnected()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logging.error(f"Dispatcher error: {e}", exc_info=True)
    finally:
        await dispatcher.disconnect()

def main():
    multiprocessing.freeze_support()
    setup_logging()

    pairs = settings.get_configured_pairs()
    print_banner(pairs)

    if not preflight_checks(pairs):
        logging.error("Preflight checks encountered critical errors. Please verify your .env file.")
        return

    # Create queues and stop event for IPC with worker processes
    pair_queues: Dict[int, multiprocessing.Queue] = {}
    worker_processes: List[multiprocessing.Process] = []
    stop_event = multiprocessing.Event()

    # Launch dedicated OS process for each configured pair
    for pair in pairs:
        q = multiprocessing.Queue()
        pair_queues[pair.id] = q
        p = multiprocessing.Process(
            target=run_pair_worker,
            args=(pair.model_dump(), q, stop_event),
            name=f"Worker-{pair.id}-{pair.name}"
        )
        p.daemon = True
        p.start()
        worker_processes.append(p)
        logging.info(f"Launched Worker Process [PID: {p.pid}] for Pair #{pair.id} [{pair.name}]")

    # Run Master Telegram listener in main process
    try:
        asyncio.run(async_main(pairs, pair_queues, stop_event))
    except KeyboardInterrupt:
        logging.info("\nShutdown requested by user (Ctrl+C). Terminating...")
    finally:
        stop_event.set()
        logging.info("Waiting for worker processes to terminate...")
        for p in worker_processes:
            p.join(timeout=3.0)
            if p.is_alive():
                p.terminate()
        logging.info("All workers stopped. Clean shutdown complete.")

if __name__ == "__main__":
    main()
