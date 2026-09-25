import sys
import time
import queue
import hashlib
import asyncio
import logging
from pathlib import Path
from typing import Optional
from colorama import Fore, Style

from config import settings
from models import (
    PairConfig, PairMode, TaskMessage, TaskType, TradeSignal,
    SignalAction, GeminiChartAnalysis, BreakoutWatchSetup, OrderTypeRecommended
)
from mt5_bridge import MT5Bridge
from gemini_vision import GeminiVisionClient
from llm_engine import LLMSignalEngine
from breakout_monitor import BreakoutMonitor
from utils import ColoredFormatter

def setup_worker_logging(pair_name: str, pair_id: int):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ColoredFormatter(f"%(asctime)s [%(levelname)s] [Pair-{pair_id}:{pair_name}] %(message)s", datefmt="%H:%M:%S"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [handler]
    logging.getLogger("google.genai").setLevel(logging.ERROR)

class PairWorker:
    def __init__(self, pair_cfg: PairConfig, task_queue, stop_event):
        self.pair_cfg = pair_cfg
        self.task_queue = task_queue
        self.stop_event = stop_event
        self.bridge: Optional[MT5Bridge] = None
        self.gemini: Optional[GeminiVisionClient] = None
        self.llm: Optional[LLMSignalEngine] = None
        self.breakout_monitor: Optional[BreakoutMonitor] = None

    async def run(self):
        setup_worker_logging(self.pair_cfg.name, self.pair_cfg.id)
        logger = logging.getLogger(__name__)

        logger.info(Fore.CYAN + f"Starting Worker for Pair '{self.pair_cfg.name}' (Mode: {self.pair_cfg.mode.value.upper()})" + Style.RESET_ALL)
        logger.info(f"  -> Channel: {self.pair_cfg.channel} | MT5 Path: {self.pair_cfg.mt5_path} | Magic: {self.pair_cfg.magic_number}")

        # 1. Initialize MT5 Bridge
        self.bridge = MT5Bridge(pair_config=self.pair_cfg)
        if not self.bridge.connect():
            logger.error(f"Worker could not connect to MT5 terminal: '{self.pair_cfg.mt5_path}'. Will retry on tasks.")
        
        # 2. Initialize engines
        background_tasks = []

        self.gemini = GeminiVisionClient()
        self.breakout_monitor = BreakoutMonitor(self.bridge)
        if settings.BREAKOUT_MONITOR_ENABLED:
            t1 = asyncio.create_task(self.breakout_monitor.start())
            background_tasks.append(t1)
            logger.info("Real-time Chart Breakout Observer active in background.")

        self.llm = LLMSignalEngine()
        if self.pair_cfg.mode in (PairMode.TEXT, PairMode.BOTH):
            t2 = asyncio.create_task(self.bridge.start_position_monitor())
            background_tasks.append(t2)
            logger.info("Position & Target monitor active in background.")

        logger.info(Fore.GREEN + f"[*] Worker for '{self.pair_cfg.name}' is ready and waiting for signals!" + Style.RESET_ALL)

        # 3. Main task processing loop
        while not self.stop_event.is_set():
            try:
                task: Optional[TaskMessage] = self._get_task_nowait()
                if task:
                    await self._process_task(task)
            except Exception as e:
                logger.error(f"Error in task processing: {e}", exc_info=True)

            await asyncio.sleep(0.1)

        # 4. Clean shutdown
        logger.info("Worker stop signaled. Shutting down background tasks and MT5...")
        if self.breakout_monitor:
            self.breakout_monitor.stop()
        for t in background_tasks:
            t.cancel()
        if self.bridge:
            self.bridge.disconnect()
        logger.info(f"Worker for '{self.pair_cfg.name}' shutdown complete.")

    def _get_task_nowait(self) -> Optional[TaskMessage]:
        try:
            return self.task_queue.get_nowait()
        except (queue.Empty, Exception):
            return None

    async def _process_task(self, task: TaskMessage):
        logger = logging.getLogger(__name__)

        if task.task_type == TaskType.IMAGE_TASK:
            await self._handle_image_task(task)

        elif task.task_type == TaskType.TEXT_TASK:
            await self._handle_text_task(task)

    async def _handle_image_task(self, task: TaskMessage):
        logger = logging.getLogger(__name__)
        logger.info(Fore.YELLOW + "\n" + "=" * 65 + Style.RESET_ALL)
        logger.info(Fore.CYAN + f"[+] New Trade Analysis Image received! (Msg ID: {task.message_id})" + Style.RESET_ALL)
        if task.caption and task.caption.strip():
            logger.info(f"Caption: {task.caption.strip()}")

        if not task.image_path or not Path(task.image_path).exists():
            logger.error(f"Image file does not exist: {task.image_path}")
            return

        # Compute image hash for duplicate/recap identification
        image_hash = None
        if task.image_path and Path(task.image_path).exists():
            try:
                with open(task.image_path, "rb") as f:
                    image_hash = hashlib.sha256(f.read()).hexdigest()
            except Exception:
                pass

        logger.info("Extracting chart information with Gemini Vision AI...")
        analysis: GeminiChartAnalysis = await asyncio.to_thread(
            self.gemini.analyze_chart,
            task.image_path,
            task.caption
        )

        self._print_analysis_report(analysis)

        has_breakout_levels = bool(analysis.upper_breakout_level or analysis.lower_breakout_level)
        exec_mode = (self.pair_cfg.execution_mode or settings.EXECUTION_MODE).lower()

        if self.breakout_monitor and settings.BREAKOUT_MONITOR_ENABLED and has_breakout_levels and exec_mode != "market":
            broker_sym = self.bridge.resolve_symbol(analysis.instrument)
            if broker_sym:
                calc_lot = self.bridge.calculate_lot(symbol=broker_sym, instrument=analysis.instrument)
                setup = BreakoutWatchSetup(
                    setup_id=f"watch_{analysis.instrument}_{task.message_id}",
                    instrument=analysis.instrument,
                    broker_symbol=broker_sym,
                    timeframe=analysis.timeframe,
                    upper_breakout_level=analysis.upper_breakout_level,
                    upper_stop_loss=analysis.upper_stop_loss,
                    upper_take_profit=analysis.upper_take_profit,
                    lower_breakout_level=analysis.lower_breakout_level,
                    lower_stop_loss=analysis.lower_stop_loss,
                    lower_take_profit=analysis.lower_take_profit,
                    lot=calc_lot,
                    summary=analysis.analysis_summary,
                    image_hash=image_hash
                )
                self.breakout_monitor.add_setup(setup, analysis=analysis, caption=task.caption)
                return
            else:
                logger.error(f"Could not resolve broker symbol for '{analysis.instrument}' to watch breakout!")

        if analysis.is_valid_signal and analysis.action != SignalAction.NONE and analysis.instrument:
            if analysis.is_profit_recap or analysis.trade_already_triggered:
                logger.info(
                    Fore.YELLOW + Style.BRIGHT + 
                    f"\n[SMART IGNORE] Chart analyzed as a profit celebration/recap of an already executed {analysis.instrument} trade. "
                    f"No duplicate market order will be placed." + 
                    Style.RESET_ALL
                )
                return

            broker_sym = self.bridge.resolve_symbol(analysis.instrument)
            if broker_sym:
                if self.breakout_monitor:
                    self.breakout_monitor.cancel_setup_for_symbol(broker_sym, instrument=analysis.instrument, reason="SUPERSEDED_BY_DIRECT_SIGNAL")
                self.bridge.cancel_pending_orders(broker_sym)

            tp_target = analysis.take_profit_1
            target_to_use = settings.TARGET_TO_USE.upper()
            if target_to_use == "TP2" and analysis.take_profit_2:
                tp_target = analysis.take_profit_2
            elif target_to_use == "TP3" and analysis.take_profit_3:
                tp_target = analysis.take_profit_3

            tp_levels = [x for x in [analysis.take_profit_1, analysis.take_profit_2, analysis.take_profit_3] if x is not None]

            arrow_text = None
            if analysis.arrow_indication and analysis.arrow_indication.detected:
                arrow_text = f"{analysis.arrow_indication.direction} ({analysis.arrow_indication.color})"

            calc_lot = self.bridge.calculate_lot(instrument=analysis.instrument)

            signal = TradeSignal(
                symbol=analysis.instrument,
                action=analysis.action,
                entry_price=analysis.entry_price,
                stop_loss=analysis.stop_loss,
                take_profit=tp_target,
                target_1=analysis.take_profit_1,
                target_2=analysis.take_profit_2,
                target_3=analysis.take_profit_3,
                take_profit_levels=tp_levels,
                lot=calc_lot,
                order_type=analysis.order_type,
                arrow_note=arrow_text,
                timeframe=analysis.timeframe,
                raw_summary=analysis.analysis_summary
            )

            logger.info(Fore.CYAN + f"Sending signal to MT5: {signal.action.value} {signal.symbol}..." + Style.RESET_ALL)
            result = self.bridge.execute_signal(signal)
            if result.success:
                logger.info(
                    Fore.GREEN + Style.BRIGHT + 
                    f"[SUCCESS] Order Executed! Action: {result.action} | Symbol: {result.symbol} | "
                    f"Ticket: #{result.ticket} | Price: {result.price} | Volume: {result.volume} | "
                    f"SL: {result.sl} | TP: {result.tp}" + 
                    Style.RESET_ALL
                )
            else:
                logger.error(Fore.RED + Style.BRIGHT + f"[FAILED] Trade execution failed: {result.comment}" + Style.RESET_ALL)
        else:
            logger.info(Fore.YELLOW + "[-] No actionable trade setup identified in image. No trade taken." + Style.RESET_ALL)

    async def _handle_text_task(self, task: TaskMessage):
        logger = logging.getLogger(__name__)
        logger.info(Fore.YELLOW + "\n" + "=" * 60 + Style.RESET_ALL)
        logger.info(Fore.CYAN + f"New Telegram Message received (Msg ID: {task.message_id}):\n{task.text}" + Style.RESET_ALL)
        if task.reply_to_text:
            logger.info(f"Reply Context:\n{task.reply_to_text}")

        if not self.llm:
            self.llm = LLMSignalEngine()

        signals: List[TradeSignal] = await asyncio.to_thread(self.llm.parse_messages, task.text or "", task.reply_to_text)
        valid_signals = [s for s in signals if s.action != SignalAction.NONE]

        if not valid_signals:
            logger.info("Message evaluated as non-actionable. No trade taken.")
            logger.info("=" * 60)
            return

        for signal in valid_signals:
            logger.info(
                f"Processing Signal: Action={signal.action.value} | Symbol={signal.symbol} | "
                f"Entry={signal.entry_price} | SL={signal.stop_loss} | TP={signal.take_profit} | "
                f"T1={signal.target_1} | T2={signal.target_2} | Parser={signal.parser_used}"
            )

            if signal.symbol:
                broker_sym = self.bridge.resolve_symbol(signal.symbol)
                if broker_sym and self.breakout_monitor:
                    self.breakout_monitor.cancel_setup_for_symbol(broker_sym, instrument=signal.symbol, reason="SUPERSEDED_BY_TEXT_SIGNAL")

            result = self.bridge.execute_signal(signal)
            if result.success:
                logger.info(Fore.GREEN + Style.BRIGHT + f"[SUCCESS] {result.action} on {result.symbol}: {result.comment}" + Style.RESET_ALL)
            else:
                logger.error(Fore.RED + Style.BRIGHT + f"[FAILED] {result.action} on {result.symbol}: {result.comment}" + Style.RESET_ALL)
        logger.info("=" * 60)

    def _print_analysis_report(self, a: GeminiChartAnalysis):
        print(Fore.MAGENTA + Style.BRIGHT + f"\n--- GEMINI VISION ANALYSIS REPORT ({self.pair_cfg.name}) ---" + Style.RESET_ALL)
        print(f"  Valid Signal   : {'YES' if a.is_valid_signal else 'NO'}")
        print(f"  Instrument     : {a.instrument or 'N/A'}")
        print(f"  Timeframe      : {a.timeframe or 'N/A'}")
        print(f"  Action         : {Fore.GREEN if 'BUY' in a.action.value else Fore.RED}{a.action.value}{Style.RESET_ALL}")
        print(f"  Order Type     : {a.order_type.value if a.order_type else 'MARKET'}")
        print(f"  Entry Price    : {a.entry_price or 'Market'}")
        if a.entry_zone_min and a.entry_zone_max:
            print(f"  Entry Zone     : {a.entry_zone_min} - {a.entry_zone_max}")
        print(f"  Stop Loss (SL) : {a.stop_loss or 'N/A'}")
        print(f"  TP1 (Primary)  : {a.take_profit_1 or 'N/A'}")
        if a.take_profit_2:
            print(f"  TP2 (Target 2) : {a.take_profit_2}")
        if a.take_profit_3:
            print(f"  TP3 (Target 3) : {a.take_profit_3}")

        if a.is_range_breakout or a.upper_breakout_level or a.lower_breakout_level:
            print(Fore.YELLOW + f"  Range Breakout : DUAL RANGES IDENTIFIED" + Style.RESET_ALL)
            if a.range_high and a.range_low:
                print(f"  Range High/Low : {a.range_high} / {a.range_low}")
            if a.upper_breakout_level:
                print(f"  Upper Buy Break: {a.upper_breakout_level} (SL: {a.upper_stop_loss}, TP: {a.upper_take_profit})")
            if a.lower_breakout_level:
                print(f"  Lower Sell Break: {a.lower_breakout_level} (SL: {a.lower_stop_loss}, TP: {a.lower_take_profit})")
        
        if a.arrow_indication and a.arrow_indication.detected:
            arrow = a.arrow_indication
            print(f"  Arrow Markings : Direction: {arrow.direction} | Color: {arrow.color} | Note: {arrow.description}")

        calc_lot = self.bridge.calculate_lot(instrument=a.instrument)
        print(f"  Allocated Lot  : {calc_lot} lots (per $50 account rules)")
        print(f"  Confidence     : {a.confidence}")
        print(f"  Summary        : {a.analysis_summary}")
        print(Fore.MAGENTA + "--------------------------------------\n" + Style.RESET_ALL)

def run_pair_worker(pair_cfg_dict: dict, task_queue, stop_event):
    """Entry point for the pair worker process."""
    try:
        pair_cfg = PairConfig(**pair_cfg_dict)
        worker = PairWorker(pair_cfg, task_queue, stop_event)
        asyncio.run(worker.run())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"[FATAL] Worker exception: {e}")
