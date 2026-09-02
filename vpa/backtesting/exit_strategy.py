"""Pluggable exit-strategy abstraction for the VPA backtesting engine (SP-317).

Exit resolution is delegated to an ``ExitStrategy`` protocol so that richer,
path-based exit strategies (stop-loss, R-multiple, etc.) can be added later
without rewriting the engine core (Req 9.1, 9.3). SP-317 implements only the
fixed-hold strategy (Req 9.4).
"""

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from vpa.backtesting.models import ExitResult, PricePoint, SkipReason
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
