"""Pluggable exit-strategy abstraction for the VPA backtesting engine (SP-317).

Exit resolution is delegated to an ``ExitStrategy`` protocol so that richer,
path-based exit strategies (stop-loss, R-multiple, etc.) can be added later
without rewriting the engine core (Req 9.1, 9.3). SP-317 implements only the
fixed-hold strategy (Req 9.4).
"""

from typing import Protocol, runtime_checkable

from vpa.backtesting.models import ExitResult, PricePoint, SkipReason


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
