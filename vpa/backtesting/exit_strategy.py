"""Pluggable exit-strategy abstraction for the VPA backtesting engine (SP-317).

Exit resolution is delegated to an ``ExitStrategy`` protocol so that richer,
path-based exit strategies (stop-loss, R-multiple, etc.) can be added later
without rewriting the engine core (Req 9.1, 9.3). SP-317 implements only the
fixed-hold strategy (Req 9.4).
"""

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from vpa.backtesting.models import ExitReason, ExitResult, PricePoint, SkipReason
from vpa.ml_validation.signal_analysis import SignalDirection


@runtime_checkable
class ExitStrategy(Protocol):
    """Determines a trade's Exit_Index and exit price (Req 9.1).

    An implementation receives the open trade's Entry_Index and the full
    forward Price_Series -- including each ``PricePoint``'s ``open``, ``high``,
    and ``low`` -- so that future path-based strategies (stop-loss, R-multiple)
    can plug in without changing the Backtest_Engine core (Req 9.3). SP-317
    implements only the fixed-hold strategy (Req 9.4).
    """

    def resolve_exit(self, entry_index: int, price_series: list[PricePoint], hold_period: int) -> ExitResult: ...


class FixedHoldExitStrategy:
    """Exit ``hold_period`` trading days after entry at ``close[t+1+N]`` (Req 9.2)."""

    def resolve_exit(self, entry_index: int, price_series: list[PricePoint], hold_period: int) -> ExitResult:
        exit_index = entry_index + hold_period
        if exit_index > len(price_series) - 1:
            # Exit horizon runs past the end of the series (Req 7.2).
            return ExitResult(None, None, SkipReason.INSUFFICIENT_FUTURE_DATA_EXIT)
        return ExitResult(exit_index, price_series[exit_index].close, None)


@dataclass(frozen=True)
class StopLossExitStrategy:
    """Path-based stop-loss exit resolving on the first forward stop breach (SP-333, Req 7).

    ``threshold`` is a negative fraction (e.g. ``-0.02`` for -2%). ``direction``
    selects the long vs short stop test. When the stop is not breached within
    ``hold_period``, resolution delegates verbatim to a wrapped
    ``FixedHoldExitStrategy`` (Req 7.8), which also yields
    ``INSUFFICIENT_FUTURE_DATA_EXIT`` when the horizon runs past the series end.

    Pure: reads only the supplied ``price_series`` (Req 2.1). Raw prices are
    returned; the engine validates them via ``_is_valid_price``.
    """

    threshold: float  # negative fraction, e.g. -0.02 (Req 7.2, 7.9)
    direction: SignalDirection = SignalDirection.UP
    _fixed_hold: FixedHoldExitStrategy = field(default_factory=FixedHoldExitStrategy)

    def resolve_exit(self, entry_index: int, price_series: list[PricePoint], hold_period: int) -> ExitResult:
        entry_price = price_series[entry_index].close
        stop = entry_price * (1 + self.threshold)  # Req 7.2

        last_index = len(price_series) - 1
        # Include the hold boundary so a same-day stop breach wins the tie (Req 7.7).
        horizon = min(entry_index + hold_period, last_index)

        is_long = self.direction is SignalDirection.UP
        for j in range(entry_index + 1, horizon + 1):
            bar = price_series[j]
            if is_long:
                if bar.low <= stop:  # Req 7.3
                    # Exit at the open when it has already gapped through the stop (Req 7.6).
                    exit_price = bar.open if bar.open <= stop else stop  # Req 7.5
                    return ExitResult(j, exit_price, None)
            else:
                if bar.high >= stop:  # Req 7.4
                    exit_price = bar.open if bar.open >= stop else stop  # Req 7.5, 7.6
                    return ExitResult(j, exit_price, None)

        # No breach within the hold window: delegate to the fixed-hold fallback (Req 7.8).
        return self._fixed_hold.resolve_exit(entry_index, price_series, hold_period)


@dataclass(frozen=True)
class RecentExtremeExitStrategy:
    """Recent-extreme stop + risk-based target exit (SP-354 Req 1-9).

    GEOMETRY ONLY: ``direction`` selects long vs short stop/target placement and
    which bar field triggers a breach. It does NOT set the P&L sign -- that is
    resolved downstream by ``pnl.strategy_return`` from ``SIGNAL_DIRECTIONS``
    (see Design Decision 3).

    The stop is placed from a recent price extreme (lowest ``low`` for longs,
    highest ``high`` for shorts) measured over the ``lookback`` bars strictly
    before entry (Req 3). The profit target is derived from the resulting risk
    distance via the ``reward_risk`` multiplier (Req 4). The strategy scans
    forward OHLC bars and exits on the first stop or target breach, with the
    stop winning when both breach on the same bar (Req 5.6); gap-through opens
    resolve at the open (Req 5.7, 5.8). When neither level is breached within
    the hold window, resolution delegates to the wrapped
    ``FixedHoldExitStrategy`` (Req 5.9).

    Pure: reads only the supplied ``price_series`` (Req 1.4), returns RAW prices
    (the engine validates them via ``_is_valid_price``), never mutates inputs
    (Req 1.5), and is deterministic (Req 1.6).
    """

    lookback: int  # L, positive int (Req 2.1, 2.3)
    reward_risk: float  # M, strictly > 0 (Req 2.1, 2.5)
    buffer: float = 0.0  # >= 0, default 0 at the extreme (Req 2.1, 2.4, 2.6)
    direction: SignalDirection = SignalDirection.UP  # default UP/long (Req 2.2)
    _fixed_hold: FixedHoldExitStrategy = field(default_factory=FixedHoldExitStrategy)

    def __post_init__(self) -> None:
        # Reject bool-as-int before the int check, mirroring validate_hold_period.
        if isinstance(self.lookback, bool) or not isinstance(self.lookback, int):
            raise ValueError(f"lookback must be a positive int, got {self.lookback!r}")  # Req 2.3
        if self.lookback < 1:
            raise ValueError(f"lookback must be a positive int, got {self.lookback}")  # Req 2.3
        if self.buffer < 0:
            raise ValueError(f"buffer must be >= 0, got {self.buffer}")  # Req 2.4
        if not self.reward_risk > 0:
            raise ValueError(f"reward_risk must be > 0, got {self.reward_risk}")  # Req 2.5

    def resolve_exit(self, entry_index: int, price_series: list[PricePoint], hold_period: int) -> ExitResult:
        last_index = len(price_series) - 1

        # --- Recent extreme over bars strictly before entry (Req 3.1-3.3, 6.1) ---
        start = entry_index - self.lookback
        if start < 0:  # fewer than L prior bars exist
            return ExitResult(None, None, SkipReason.UNAVAILABLE_RECENT_EXTREME)  # Req 6.1
        window = price_series[start:entry_index]  # indices entry_index-L .. entry_index-1

        is_long = self.direction is SignalDirection.UP
        if is_long:
            extreme = min(bar.low for bar in window)  # lowest low (Req 3.1)
            stop = extreme - self.buffer  # Req 3.4
        else:
            extreme = max(bar.high for bar in window)  # highest high (Req 3.2)
            stop = extreme + self.buffer  # Req 3.5

        # --- Risk distance + target (Req 4) ---
        entry_price = price_series[entry_index].close  # Req 4.1
        risk = abs(entry_price - stop)  # Req 4.1
        # Degenerate: zero risk, or stop on the wrong (non-adverse) side (Req 6.2, 6.3).
        if risk == 0 or (is_long and stop >= entry_price) or (not is_long and stop <= entry_price):
            return ExitResult(None, None, SkipReason.DEGENERATE_RISK_DISTANCE)  # Req 6.2, 6.3
        # Req 4.2, 4.3
        target = entry_price + risk * self.reward_risk if is_long else entry_price - risk * self.reward_risk

        # --- Forward scan: first breach wins, stop-first on same bar (Req 5) ---
        horizon = min(entry_index + hold_period, last_index)  # Req 5.1
        for j in range(entry_index + 1, horizon + 1):
            bar = price_series[j]
            if is_long:
                if bar.low <= stop:  # stop breach (Req 5.2); stop-first (Req 5.6)
                    exit_price = bar.open if bar.open <= stop else stop  # gap-through (Req 5.7)
                    return ExitResult(j, exit_price, None, stop, target, ExitReason.STOP)
                if bar.high >= target:  # target breach (Req 5.3)
                    exit_price = bar.open if bar.open >= target else target  # gap-through (Req 5.8)
                    return ExitResult(j, exit_price, None, stop, target, ExitReason.TARGET)
            else:
                if bar.high >= stop:  # stop breach (Req 5.4); stop-first (Req 5.6)
                    exit_price = bar.open if bar.open >= stop else stop  # gap-through (Req 5.7)
                    return ExitResult(j, exit_price, None, stop, target, ExitReason.STOP)
                if bar.low <= target:  # target breach (Req 5.5)
                    exit_price = bar.open if bar.open <= target else target  # gap-through (Req 5.8)
                    return ExitResult(j, exit_price, None, stop, target, ExitReason.TARGET)

        # --- No breach: delegate to fixed-hold fallback and carry stop/target (Req 5.9) ---
        fallback = self._fixed_hold.resolve_exit(entry_index, price_series, hold_period)
        if fallback.reason is not None:
            return fallback  # horizon past series end -> INSUFFICIENT_FUTURE_DATA_EXIT, no extras
        return ExitResult(fallback.exit_index, fallback.exit_price, None, stop, target, ExitReason.FIXED_HOLD)
