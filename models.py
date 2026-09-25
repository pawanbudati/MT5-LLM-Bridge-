from enum import Enum
from typing import List, Optional, Union, Dict, Any
from pydantic import BaseModel, Field

class SignalAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    BUY_LIMIT = "BUY_LIMIT"
    SELL_LIMIT = "SELL_LIMIT"
    BUY_STOP = "BUY_STOP"
    SELL_STOP = "SELL_STOP"
    UPDATE_SL = "UPDATE_SL"
    UPDATE_TP = "UPDATE_TP"
    UPDATE_TARGETS_AND_SL = "UPDATE_TARGETS_AND_SL"
    BREAKEVEN = "BREAKEVEN"
    CLOSE_PARTIAL = "CLOSE_PARTIAL"
    CLOSE = "CLOSE"
    EXIT = "EXIT"
    NONE = "NONE"

class OrderTypeRecommended(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"

class ArrowIndication(BaseModel):
    detected: bool = Field(default=False, description="True if arrow markings are present on chart")
    direction: Optional[str] = Field(default=None, description="UP, DOWN, BREAKOUT_UP, BREAKOUT_DOWN, or null")
    color: Optional[str] = Field(default=None, description="Color of the arrow")
    description: Optional[str] = Field(default=None, description="Description of arrow role or projection")

class GeminiChartAnalysis(BaseModel):
    is_valid_signal: bool = Field(default=False, description="True if valid TradingView chart containing actionable setup")
    instrument: Optional[str] = Field(default=None, description="Instrument or asset name, e.g. XAUUSD, BTCUSD, USOIL, US30")
    timeframe: Optional[str] = Field(default=None, description="Chart timeframe, e.g. 1m, 5m, 15m, 1h, 4h, D1")
    action: SignalAction = Field(default=SignalAction.NONE, description="Trade action: BUY, SELL, BUY_LIMIT, etc.")
    order_type: Optional[OrderTypeRecommended] = Field(default=OrderTypeRecommended.MARKET, description="Recommended order type")
    entry_price: Optional[float] = Field(default=None, description="Primary entry price or key level")
    entry_zone_min: Optional[float] = Field(default=None, description="Lower bound of entry zone")
    entry_zone_max: Optional[float] = Field(default=None, description="Upper bound of entry zone")
    stop_loss: Optional[float] = Field(default=None, description="Stop loss (SL) level")
    take_profit_1: Optional[float] = Field(default=None, description="Primary target / TP1")
    take_profit_2: Optional[float] = Field(default=None, description="Target 2 / TP2")
    take_profit_3: Optional[float] = Field(default=None, description="Target 3 / TP3")
    arrow_indication: Optional[ArrowIndication] = Field(default=None, description="Arrow markings on chart")
    # Dual-direction range breakout fields
    is_range_breakout: bool = Field(default=False, description="True if chart marks a range with breakout triggers on both sides")
    range_high: Optional[float] = Field(default=None, description="Upper boundary of range")
    range_low: Optional[float] = Field(default=None, description="Lower boundary of range")
    upper_breakout_level: Optional[float] = Field(default=None, description="Level to trigger BUY order if broken above")
    upper_stop_loss: Optional[float] = Field(default=None, description="Stop loss for BUY breakout")
    upper_take_profit: Optional[float] = Field(default=None, description="Take profit for BUY breakout")
    lower_breakout_level: Optional[float] = Field(default=None, description="Level to trigger SELL order if broken below")
    lower_stop_loss: Optional[float] = Field(default=None, description="Stop loss for SELL breakout")
    lower_take_profit: Optional[float] = Field(default=None, description="Take profit for SELL breakout")
    key_levels_found: List[str] = Field(default_factory=list, description="List of notable support/resistance levels detected")
    confidence: Optional[str] = Field(default="MEDIUM", description="Confidence level: HIGH, MEDIUM, LOW")
    analysis_summary: str = Field(default="", description="Concise description of trade setup")

class TradeSignal(BaseModel):
    action: SignalAction = SignalAction.NONE
    symbol: Optional[str] = None
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    target_1: Optional[float] = None
    target_2: Optional[float] = None
    target_3: Optional[float] = None
    take_profit_levels: List[float] = Field(default_factory=list)
    close_ratio: Optional[float] = Field(default=None, description="Ratio for partial close (e.g. 0.5 for 50%)")
    lot: Optional[float] = None
    order_type: Optional[OrderTypeRecommended] = OrderTypeRecommended.MARKET
    arrow_note: Optional[str] = None
    timeframe: Optional[str] = None
    confidence: Optional[Union[float, str]] = 1.0
    raw_message: str = ""
    raw_summary: Optional[str] = None
    notes: Optional[str] = None
    parser_used: str = "gemini"

    # Convenient accessors for compatibility between Ansh and TWM conventions
    @property
    def entry(self) -> Optional[float]:
        return self.entry_price

    @entry.setter
    def entry(self, value: Optional[float]):
        self.entry_price = value

    @property
    def sl(self) -> Optional[float]:
        return self.stop_loss

    @sl.setter
    def sl(self, value: Optional[float]):
        self.stop_loss = value

    @property
    def tp(self) -> Optional[float]:
        return self.take_profit

    @tp.setter
    def tp(self, value: Optional[float]):
        self.take_profit = value

    @property
    def tps(self) -> List[float]:
        return self.take_profit_levels

    @tps.setter
    def tps(self, value: List[float]):
        self.take_profit_levels = value

class ExecutionResult(BaseModel):
    success: bool
    action: str
    symbol: Optional[str] = None
    ticket: Optional[int] = None
    order_type: Optional[str] = None
    price: Optional[float] = None
    volume: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    retcode: Optional[int] = None
    comment: str = ""

class BreakoutWatchSetup(BaseModel):
    setup_id: str
    instrument: str
    broker_symbol: str
    timeframe: Optional[str] = None
    upper_breakout_level: Optional[float] = None
    upper_stop_loss: Optional[float] = None
    upper_take_profit: Optional[float] = None
    lower_breakout_level: Optional[float] = None
    lower_stop_loss: Optional[float] = None
    lower_take_profit: Optional[float] = None
    initial_price: float = 0.0
    lot: Optional[float] = None
    created_at: float = 0.0
    status: str = "WATCHING"  # WATCHING, TRIGGERED_BUY, TRIGGERED_SELL, EXPIRED, CANCELLED, SUPERSEDED
    summary: str = ""

class PairMode(str, Enum):
    IMAGE = "image"
    TEXT = "text"
    BOTH = "both"

class PairConfig(BaseModel):
    id: int
    name: str = ""
    channel: str = ""
    mt5_path: str = ""
    mode: PairMode = PairMode.IMAGE
    magic_number: int = 777999
    mt5_login: Optional[int] = None
    mt5_password: Optional[str] = None
    mt5_server: Optional[str] = None
    execution_mode: Optional[str] = None
    dry_run: Optional[bool] = None
    # Optional per-pair lot overrides (None means use global settings)
    lot_gold: Optional[float] = None
    lot_btc: Optional[float] = None
    lot_usoil: Optional[float] = None
    lot_us30: Optional[float] = None
    lot_forex: Optional[float] = None
    lot_default: Optional[float] = None
    past_hours: float = 0.0

class TaskType(str, Enum):
    IMAGE_TASK = "image"
    TEXT_TASK = "text"

class TaskMessage(BaseModel):
    task_type: TaskType
    pair_id: int
    channel_id: str
    message_id: int
    # Image Task payload
    image_path: Optional[str] = None
    caption: Optional[str] = None
    # Text Task payload
    text: Optional[str] = None
    reply_to_text: Optional[str] = None
    timestamp: float = 0.0
