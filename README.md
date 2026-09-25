# Telegram Multi-Channel & Multi-MT5 Terminal Unified Bot

A unified trading bot combining chart image analysis (**Telegram-Bot-Ansh**) and direct text signal processing (**Telegram-Bot-TWM**) into an extensible multi-channel, multi-terminal architecture.

---

## 🌟 Key Architecture & Highlights

- **Single Master Telegram Listener**: Runs one authenticated Telethon client session that resolves and monitors all configured Telegram channels concurrently without database locks or duplicate sessions.
- **Dedicated Worker Process per MT5 Terminal**: Because the `MetaTrader5` Python library uses process-level IPC and cannot connect to multiple MT5 terminals in the same OS process, each Channel–MT5 pair runs in its own isolated Python process with its own MT5 connection and background observers.
- **Configurable Channel Modes**:
  - `image` (Ansh Bot): Multimodal Gemini Vision AI analyzes TradingView chart images, extracts dual-range breakout levels, and executes breakout or market trades.
  - `text` (TWM Bot): AI LLM engine (with regex rule parser fallback) extracts direct text signals, updates SL/TP, executes partial closures, and monitors targets.
  - `both`: Automatically routes image posts to Vision AI and text messages to the text signal engine.
- **Scalable to N Pairs**: Easily configure 2, 5, 10, or more channel-to-terminal pairs simply by defining `PAIR_1_*`, `PAIR_2_*`, `PAIR_3_*`, etc., in `.env`.
- **Dynamic Lot Sizing per Instrument ($50 Base)**:
  - **GOLD**: 0.02 lots per $50 balance
  - **BITCOIN (BTC)**: 0.03 lots per $50 balance
  - **US OIL (WTI/Crude)**: 0.02 lots per $50 balance
  - **US 30 (Dow Jones)**: 0.10 lots per $50 balance
  - **Currency Pairs (Forex)**: 0.10 lots per $50 balance
  - **Default**: 0.02 lots per $50 balance
  - Automatic scaling with balance (`proportional` or `step`).
- **BreakoutWatcherEA Support**: Includes `BreakoutWatcherEA.mq5` to draw visual breakout levels, labels, and entry triggers on live MT5 charts.

---

## 📁 Project Structure

```
Telegram-Bot-Unified/
├── .env.example             # Complete reference configuration template
├── .env                     # Active configuration with user credentials
├── requirements.txt         # Dependencies
├── run_unified_bot.bat      # Windows batch runner
├── main.py                  # Master process orchestrator & Telegram dispatcher
├── config.py                # Configuration loader, pair discovery & lot rules
├── models.py                # Pydantic data models & signal definitions
├── pair_worker.py           # Isolated worker process managing MT5 & signal execution
├── mt5_bridge.py            # Unified MT5 bridge: orders, modifications, lots, targets
├── gemini_vision.py         # Google Gemini Vision chart analyzer
├── llm_engine.py            # Gemini LLM text signal extractor
├── rule_parser.py           # High-speed regex signal parser & fallback
├── breakout_monitor.py      # Real-time tick observer for dual-side range breakouts
├── utils.py                 # Scrap message detection & colored logging
├── BreakoutWatcherEA.mq5    # Expert Advisor for MT5 chart visualization
├── downloads/               # Directory for downloaded chart images
└── tests/                   # Complete test suite
    ├── test_config.py       # Configuration & pair discovery tests
    ├── test_lot_sizing.py   # Instrument classification & balance scaling tests
    ├── test_signals.py      # Signal extraction & noise filtering tests
    ├── test_vision.py       # Gemini Vision response parsing tests
    └── test_mt5_mock.py     # MT5 Bridge order execution logic tests
```

---

## ⚙️ How to Configure Channel-MT5 Pairs

Open `.env` in the project root. You can add as many pairs as you want using `PAIR_1_*`, `PAIR_2_*`, `PAIR_3_*`, ...

```env
# ---------------------------------------------------------------------
# PAIR 1: Ansh Channel (Image Chart Vision Analysis)
# ---------------------------------------------------------------------
PAIR_1_NAME=Ansh-Chart-Vision
PAIR_1_CHANNEL=-1001936359682
PAIR_1_MT5_PATH=C:\Users\Administrator\Desktop\MT5-Ansh-Tel-Bot\terminal64.exe
PAIR_1_MODE=image
PAIR_1_MAGIC=777999
PAIR_1_EXECUTION_MODE=auto

# ---------------------------------------------------------------------
# PAIR 2: TWM Channel (Direct Text Messages & Signals)
# ---------------------------------------------------------------------
PAIR_2_NAME=TWM-Text-Signals
PAIR_2_CHANNEL=-1003387639038
PAIR_2_MT5_PATH=C:\Users\Administrator\Desktop\MT5_TWM_Forex_Premium_Group\terminal64.exe
PAIR_2_MODE=text
PAIR_2_MAGIC=888123

# ---------------------------------------------------------------------
# PAIR 3: Add more pairs as needed!
# ---------------------------------------------------------------------
# PAIR_3_NAME=VIP-Forex-Group
# PAIR_3_CHANNEL=-1001234567890
# PAIR_3_MT5_PATH=C:\Program Files\MetaTrader 5\terminal64.exe
# PAIR_3_MODE=text
# PAIR_3_MAGIC=999111
```

### Supported Modes:
- `image`: Extracts TradingView chart images using Gemini Vision AI (Ansh bot logic).
- `text`: Parses direct text signals (buy/sell, update SL, update TP, breakeven, close partial, exit) using AI and regex rules (TWM bot logic).
- `both`: Supports both images and text messages on the same channel.

---

## 📊 Dynamic Lot Size Configuration

Configure instrument position sizes directly in `.env`:

```env
USE_DYNAMIC_LOT=true
BASE_ACCOUNT_SIZE=50.0

LOT_GOLD_PER_50=0.02
LOT_BTC_PER_50=0.03
LOT_USOIL_PER_50=0.02
LOT_US30_PER_50=0.10
LOT_FOREX_PER_50=0.10
LOT_DEFAULT_PER_50=0.02

# Scaling Mode: "proportional" (continuous) or "step" (discrete $50 blocks)
LOT_SCALING_MODE=proportional

# When account balance is below base ($50):
# "min_base" keeps the base lot size; "proportional" scales down
LOT_BELOW_BASE_MODE=min_base
MIN_LOT_SIZE=0.01
MT5_DEFAULT_LOT=0.02
```

### Optional Per-Pair Lot Overrides
If a specific MT5 terminal requires different lot sizes, specify pair-specific keys in `.env`:
```env
PAIR_1_LOT_GOLD=0.01
PAIR_1_LOT_US30=0.05
```

---

## 🚀 Running the Bot

### Method 1: Using Batch Script
Double-click `run_unified_bot.bat` or run in terminal:
```cmd
run_unified_bot.bat
```

### Method 2: Using Python
```cmd
python main.py
```

### Running Unit Tests
```cmd
python -m unittest discover -s tests -p "test_*.py"
```

---

## 🛡️ Safety & Dry Run Mode

To test signal parsing, image extraction, and MT5 resolution without placing live broker trades, set:
```env
DRY_RUN=true
```
When ready for real trading, set `DRY_RUN=false`.
