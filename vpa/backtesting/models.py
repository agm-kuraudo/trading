"""Data models and enums for the VPA backtesting engine (SP-317).

All record types are frozen dataclasses to guarantee inputs are not mutated
(Req 7.6) and that results are safe to reuse. SignalType / SignalDirection are
reused from the SP-314 signal analysis module rather than redefined.
"""

from dataclasses import dataclass, field
from enum import Enum

from vpa.ml_validation.signal_analysis import SignalDirection, SignalType


class PositionMode(Enum):
    """Trade-tracking behaviour (Req 5.1)."""

    NO_OVERLAP = "no_overlap"
    STACKING = "stacking"


class SkipReason(Enum):
    """Reason a Signal_Entry did not produce a trade."""

    MISSING_PRICE_DATE = "missing_price_date"  # Req 1.5
    OVERLAPPING_POSITION = "overlapping_position"  # Req 5.2, 5.5
    INSUFFICIENT_FUTURE_DATA_ENTRY = "insufficient_future_data_entry"  # Req 7.1
    INSUFFICIENT_FUTURE_DATA_EXIT = "insufficient_future_data_exit"  # Req 7.2
    INVALID_ENTRY_PRICE = "invalid_entry_price"  # Req 7.4
    INVALID_EXIT_PRICE = "invalid_exit_price"  # Req 7.5


@dataclass(frozen=True)
class PricePoint:
    """One trading day of raw OHLC price data. Immutable (Req 7.6)."""

    date: str  # ISO 8601 YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class SignalEntry:
    """A single input signal record for the Signal_Log."""

    date: str  # ISO 8601 YYYY-MM-DD
    signal_type: SignalType
    direction: SignalDirection


@dataclass(frozen=True)
class TradeRecord:
    """A single simulated trade in the Trade_Log."""

    entry_date: str  # ISO 8601 YYYY-MM-DD
    exit_date: str  # ISO 8601 YYYY-MM-DD
    entry_price: float
    exit_price: float
    return_pct: float  # Net_Return (Gross_Return - Round_Trip_Cost)
    signal_type: SignalType


@dataclass(frozen=True)
class SkippedSignal:
    """Record that a Signal_Entry was skipped, with the reason (Req 1.5, 5.2, 7.x)."""

    signal_date: str
    signal_type: SignalType
    reason: SkipReason


@dataclass(frozen=True)
class ExitResult:
    """Outcome of an Exit_Strategy resolution."""

    exit_index: int | None
    exit_price: float | None
    reason: SkipReason | None  # set when exit cannot be resolved (Req 7.2)


@dataclass(frozen=True)
class BacktestResult:
    """Engine output: the Trade_Log plus skipped signals."""

    trades: list[TradeRecord] = field(default_factory=list)
    skipped: list[SkippedSignal] = field(default_factory=list)


@dataclass(frozen=True)
class PricedTrade:
    """A TradeRecord paired with its direction-aware Strategy_Return (SP-333, Req 8.1)."""

    trade: TradeRecord
    direction: SignalDirection
    strategy_return: float


@dataclass(frozen=True)
class TradeExclusion:
    """An indication that a trade was excluded from P&L (SP-333, Req 8.5, 8.6)."""

    trade: TradeRecord
    reason: str  # "exit_price_zero" | "unknown_direction"


@dataclass(frozen=True)
class EquityPoint:
    """One day of cumulative strategy capital on the Equity_Curve (SP-333, Req 9.1)."""

    date: str  # ISO 8601 YYYY-MM-DD
    equity: float


@dataclass(frozen=True)
class MetricsResult:
    """Complete performance-metrics suite for one Strategy_Variation (SP-333, Req 10-15)."""

    total_return: float
    annualised_return: float
    buy_and_hold_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    profit_factor: float  # may be float("inf") (Req 15.2)
    average_win: float
    average_loss: float
    expectancy: float
    time_in_market: float
    number_of_trades: int
    trades_per_year: float
    notes: tuple[str, ...] = ()  # zero-denominator / exclusion indications (Req 10.5, 13.5)
