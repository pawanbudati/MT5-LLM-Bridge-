import time
import json
import asyncio
import logging
from pathlib import Path
from typing import Dict, Optional, List
import MetaTrader5 as mt5
from colorama import Fore, Style

from config import settings
from models import BreakoutWatchSetup, SignalAction, ExecutionResult

logger = logging.getLogger(__name__)

class BreakoutMonitor:
    def __init__(self, mt5_bridge):
        self.bridge = mt5_bridge
        self.active_setups: Dict[str, BreakoutWatchSetup] = {}
        self.running: bool = False
        self._last_heartbeat_time: float = 0.0

    def add_setup(self, setup: BreakoutWatchSetup):
        """Add a new chart range/breakout setup to active real-time observation."""
        if not setup.upper_breakout_level and not setup.lower_breakout_level:
            logger.warning(f"Setup {setup.setup_id} has neither upper nor lower breakout level. Skipping.")
            return

        # Check if an analysis for the same chart/symbol is already pending
        for existing_id, existing in list(self.active_setups.items()):
            if (existing.broker_symbol == setup.broker_symbol or 
                existing.instrument.upper() == setup.instrument.upper()):
                logger.info(
                    Fore.YELLOW + Style.BRIGHT + 
                    f"\n[SUPERSEDED] Existing pending analysis for {setup.instrument} ({setup.broker_symbol}) detected!\n"
                    f"  -> Invalidating previous setup #{existing_id}\n"
                    f"  -> Adopting latest chart analysis as active execution plan." + 
                    Style.RESET_ALL
                )
                existing.status = "SUPERSEDED"
                del self.active_setups[existing_id]

        # Cancel any existing pending broker orders for this symbol on MT5
        self.bridge.cancel_pending_orders(setup.broker_symbol)

        # Fetch initial market tick to know starting position
        tick = mt5.symbol_info_tick(setup.broker_symbol)
        if tick:
            setup.initial_price = (tick.bid + tick.ask) / 2.0
        else:
            s_info = mt5.symbol_info(setup.broker_symbol)
            setup.initial_price = s_info.bid if s_info else 0.0

        setup.created_at = time.time()
        setup.status = "WATCHING"
        if not setup.lot:
            setup.lot = self.bridge.calculate_lot(symbol=setup.broker_symbol, instrument=setup.instrument)
        self.active_setups[setup.setup_id] = setup

        # Synchronize task to MT5 Files directory for BreakoutWatcherEA
        self._write_ea_task_file(setup, "WATCHING")

        # Print banner for user
        print(Fore.YELLOW + Style.BRIGHT + "\n" + "=" * 70)
        print(f" [*] ACTIVE REAL-TIME CHART OBSERVER STARTED (LATEST PLAN)")
        print("=" * 70 + Style.RESET_ALL)
        print(f"  Setup ID       : {setup.setup_id}")
        print(f"  Instrument     : {setup.instrument} (Broker: {Fore.CYAN}{setup.broker_symbol}{Style.RESET_ALL})")
        print(f"  Allocated Lot  : {Fore.GREEN}{setup.lot} lots{Style.RESET_ALL} (per $50 account rules)")
        print(f"  Timeframe      : {setup.timeframe or 'N/A'}")
        print(f"  Current Price  : {setup.initial_price:.4f}")
        
        if setup.upper_breakout_level:
            dist_up = setup.upper_breakout_level - setup.initial_price
            print(
                f"  {Fore.GREEN}[+] Upper Breakout (BUY)  :{Style.RESET_ALL} Trigger: {setup.upper_breakout_level} "
                f"(Distance: {dist_up:+.4f}) | SL: {setup.upper_stop_loss or 'None'} | TP: {setup.upper_take_profit or 'None'}"
            )
        else:
            print(f"  Upper Breakout (BUY)  : Not specified")

        if setup.lower_breakout_level:
            dist_down = setup.lower_breakout_level - setup.initial_price
            print(
                f"  {Fore.RED}[-] Lower Breakdown (SELL):{Style.RESET_ALL} Trigger: {setup.lower_breakout_level} "
                f"(Distance: {dist_down:+.4f}) | SL: {setup.lower_stop_loss or 'None'} | TP: {setup.lower_take_profit or 'None'}"
            )
        else:
            print(f"  Lower Breakdown (SELL): Not specified")

        print(
            Fore.YELLOW + 
            f"  Status         : Observing live tick prices every {settings.BREAKOUT_CHECK_INTERVAL_SEC}s. "
            f"Will enter market order on break of either side!\n"
            f"  EA Support     : Synced with BreakoutWatcherEA (draws visual lines on MT5 chart)" + 
            Style.RESET_ALL
        )
        print(Fore.YELLOW + "=" * 70 + "\n" + Style.RESET_ALL)

    def _write_ea_task_file(self, setup: BreakoutWatchSetup, status: str = "WATCHING"):
        """Write task JSON file to MT5 Common and Local Files folders for BreakoutWatcherEA."""
        try:
            term = mt5.terminal_info()
            if not term:
                return

            task_lot = setup.lot or self.bridge.calculate_lot(symbol=setup.broker_symbol, instrument=setup.instrument)

            task_data = {
                "id": setup.setup_id,
                "symbol": setup.broker_symbol,
                "upper_trigger": setup.upper_breakout_level or 0.0,
                "upper_sl": setup.upper_stop_loss or 0.0,
                "upper_tp": setup.upper_take_profit or 0.0,
                "lower_trigger": setup.lower_breakout_level or 0.0,
                "lower_sl": setup.lower_stop_loss or 0.0,
                "lower_tp": setup.lower_take_profit or 0.0,
                "lot": task_lot,
                "status": status
            }

            json_text = json.dumps(task_data)

            target_dirs = []
            if term.commondata_path:
                target_dirs.append(Path(term.commondata_path) / "Files")
            if term.data_path:
                target_dirs.append(Path(term.data_path) / "MQL5" / "Files")

            clean_sym = setup.broker_symbol.replace("#", "").replace(".", "_")
            symbol_file_name = f"breakout_task_{clean_sym}.json"
            direct_sym_file_name = f"breakout_task_{setup.broker_symbol}.json"

            for d in target_dirs:
                if d.exists():
                    with open(d / "breakout_tasks.json", "w", encoding="utf-8") as f:
                        f.write(json_text)
                    with open(d / direct_sym_file_name, "w", encoding="utf-8") as f:
                        f.write(json_text)
                    if clean_sym != setup.broker_symbol:
                        with open(d / symbol_file_name, "w", encoding="utf-8") as f:
                            f.write(json_text)
        except Exception as e:
            logger.debug(f"Could not update EA task file: {e}")

    def _read_ea_task_status(self, symbol: str = "") -> Optional[str]:
        """Check if BreakoutWatcherEA executed trade and updated status for this symbol."""
        try:
            term = mt5.terminal_info()
            if not term or not term.commondata_path:
                return None

            files_to_check = []
            if symbol:
                clean_sym = symbol.replace("#", "").replace(".", "_")
                files_to_check.append(f"breakout_task_{symbol}.json")
                files_to_check.append(f"breakout_task_{clean_sym}.json")
            files_to_check.append("breakout_tasks.json")

            base_dir = Path(term.commondata_path) / "Files"
            for fname in files_to_check:
                fpath = base_dir / fname
                if fpath.exists():
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if symbol and data.get("symbol") != symbol:
                            continue
                        status = data.get("status")
                        if status:
                            return status
        except Exception:
            return None
        return None

    async def start(self):
        """Start the background observer loop."""
        self.running = True
        logger.info("Real-time Breakout Monitor loop is active.")
        while self.running:
            try:
                await self._check_setups()
            except Exception as e:
                logger.error(f"Error in BreakoutMonitor loop: {e}", exc_info=True)
            await asyncio.sleep(settings.BREAKOUT_CHECK_INTERVAL_SEC)

    def stop(self):
        """Stop the background observer."""
        self.running = False
        logger.info("Real-time Breakout Monitor stopped.")

    async def _check_setups(self):
        """Check all active setups against current MT5 market ticks."""
        if not self.active_setups:
            return

        now = time.time()
        expiry_seconds = settings.WATCHER_EXPIRY_HOURS * 3600

        # Heartbeat log every N seconds
        should_log_heartbeat = (now - self._last_heartbeat_time) >= 30.0
        if should_log_heartbeat:
            self._last_heartbeat_time = now

        for setup_id, setup in list(self.active_setups.items()):
            if setup.status != "WATCHING":
                continue

            # Check if BreakoutWatcherEA already triggered the trade in MT5 for this symbol
            ea_status = self._read_ea_task_status(setup.broker_symbol)
            if ea_status in ("TRIGGERED_BUY", "TRIGGERED_SELL"):
                logger.info(
                    Fore.GREEN + Style.BRIGHT + 
                    f"\n[EA EXECUTED] BreakoutWatcherEA successfully executed {ea_status} directly on MT5 chart!\n" + 
                    Style.RESET_ALL
                )
                setup.status = ea_status
                del self.active_setups[setup_id]
                continue

            # Check expiration
            if (now - setup.created_at) > expiry_seconds:
                setup.status = "EXPIRED"
                logger.info(Fore.YELLOW + f"Watcher for setup {setup.instrument} ({setup.broker_symbol}) expired after {settings.WATCHER_EXPIRY_HOURS} hours." + Style.RESET_ALL)
                self._write_ea_task_file(setup, "EXPIRED")
                del self.active_setups[setup_id]
                continue

            # Get live tick
            tick = mt5.symbol_info_tick(setup.broker_symbol)
            if not tick:
                continue

            current_ask = tick.ask
            current_bid = tick.bid

            # 1. Check UPPER Breakout (BUY Trigger)
            if setup.upper_breakout_level is not None:
                if current_ask >= setup.upper_breakout_level:
                    logger.info(
                        Fore.GREEN + Style.BRIGHT + 
                        f"\n[!!! BREAKOUT CONFIRMED !!!] Price broke UPPER level on {setup.instrument} ({setup.broker_symbol})!\n"
                        f"Trigger: {setup.upper_breakout_level} | Current Ask: {current_ask}\n"
                        f"Executing immediate BUY Market Order..." + 
                        Style.RESET_ALL
                    )
                    setup.status = "TRIGGERED_BUY"
                    self._write_ea_task_file(setup, "TRIGGERED_BUY")
                    
                    result = self.bridge.execute_market_trade(
                        symbol=setup.broker_symbol,
                        action=SignalAction.BUY,
                        sl=setup.upper_stop_loss,
                        tp=setup.upper_take_profit,
                        lot=setup.lot,
                        comment=f"Breakout BUY [{setup.instrument}]",
                        instrument=setup.instrument
                    )

                    self._log_trade_result(result, setup, "BUY")
                    del self.active_setups[setup_id]
                    continue

            # 2. Check LOWER Breakdown (SELL Trigger)
            if setup.lower_breakout_level is not None:
                if current_bid <= setup.lower_breakout_level:
                    logger.info(
                        Fore.RED + Style.BRIGHT + 
                        f"\n[!!! BREAKDOWN CONFIRMED !!!] Price broke LOWER level on {setup.instrument} ({setup.broker_symbol})!\n"
                        f"Trigger: {setup.lower_breakout_level} | Current Bid: {current_bid}\n"
                        f"Executing immediate SELL Market Order..." + 
                        Style.RESET_ALL
                    )
                    setup.status = "TRIGGERED_SELL"
                    self._write_ea_task_file(setup, "TRIGGERED_SELL")

                    result = self.bridge.execute_market_trade(
                        symbol=setup.broker_symbol,
                        action=SignalAction.SELL,
                        sl=setup.lower_stop_loss,
                        tp=setup.lower_take_profit,
                        lot=setup.lot,
                        comment=f"Breakdown SELL [{setup.instrument}]",
                        instrument=setup.instrument
                    )

                    self._log_trade_result(result, setup, "SELL")
                    del self.active_setups[setup_id]
                    continue

            if should_log_heartbeat:
                up_msg = f"Upper BUY: {setup.upper_breakout_level} (Diff: {setup.upper_breakout_level - current_ask:+.2f})" if setup.upper_breakout_level else "Upper: None"
                down_msg = f"Lower SELL: {setup.lower_breakout_level} (Diff: {setup.lower_breakout_level - current_bid:+.2f})" if setup.lower_breakout_level else "Lower: None"
                logger.info(
                    f"[OBSERVING] {setup.instrument} ({setup.broker_symbol}) | Price: {current_bid:.2f}/{current_ask:.2f} | "
                    f"{up_msg} | {down_msg}"
                )

    def _log_trade_result(self, result: ExecutionResult, setup: BreakoutWatchSetup, direction: str):
        """Format and log execution result of breakout order."""
        if result.success:
            print(Fore.GREEN + Style.BRIGHT + "\n" + "=" * 65)
            print(f" [SUCCESS] RANGE BREAKOUT TRADE FILLED IN MT5!")
            print("=" * 65)
            print(f"  Instrument  : {setup.instrument} -> {setup.broker_symbol}")
            print(f"  Direction   : {direction}")
            print(f"  Ticket #    : {result.ticket}")
            print(f"  Price       : {result.price}")
            print(f"  Volume      : {result.volume} lots")
            print(f"  Stop Loss   : {result.sl}")
            print(f"  Take Profit : {result.tp}")
            print("=" * 65 + "\n" + Style.RESET_ALL)
        else:
            print(Fore.RED + Style.BRIGHT + "\n" + "=" * 65)
            print(f" [FAILED] Breakout trade failed to execute in MT5!")
            print(f" Reason: {result.comment}")
            print("=" * 65 + "\n" + Style.RESET_ALL)
