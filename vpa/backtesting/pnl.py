"""Direction-aware per-trade P&L for the VPA strategy backtest report (SP-333).

This module turns the engine's per-trade log into direction-aware
``Strategy_Return`` values (Req 8). It is pure: it operates only on
caller-supplied in-memory values and performs no network, filesystem, or
``yfinance`` access.

Signal direction is resolved from the existing ``SIGNAL_DIRECTIONS`` map, since
``TradeRecord`` carries ``signal_type`` but not direction. UP signals reuse the
long-basis ``TradeRecord.return_pct``; DOWN signals are priced from the raw
entry/exit prices so the round-trip cost is applied exactly once and never
derived from ``return_pct`` (Req 8.2, 8.4).
"""

from vpa.backtesting.models import PricedTrade, TradeExclusion, TradeRecord
from vpa.ml_validation.signal_analysis import (
    SIGNAL_DIRECTIONS,
    SignalDirection,
    SignalType,
)


def direction_for(signal_type: SignalType) -> SignalDirection | None:
    """Resolve a Signal_Type to its Signal_Direction via ``SIGNAL_DIRECTIONS``.

    Returns ``None`` when the signal type is absent from the map so callers can
    exclude the trade without raising (Req 8.6).
    """
    return SIGNAL_DIRECTIONS.get(signal_type)


def strategy_return(trade: TradeRecord, round_trip_cost: float) -> float:
    """Compute the direction-aware Strategy_Return for a single trade (Req 8.1-8.4).

    UP signals reuse the long-basis net return ``TradeRecord.return_pct``.
    DOWN signals are the short-equivalent of the same price move, computed from
    the raw entry and exit prices as ``(entry_price / exit_price) - 1`` with the
    round-trip cost subtracted exactly once. The DOWN branch never derives from
    ``return_pct`` so the long-basis cost embedded there is not double-counted
    (Req 8.2, 8.4).

    The caller is responsible for excluding trades whose direction is unknown or
    whose ``exit_price`` is zero (see :func:`price_trades`); this function
    assumes a resolvable direction and a non-zero exit price.
    """
    direction = direction_for(trade.signal_type)
    if direction == SignalDirection.UP:
        return trade.return_pct
    return (trade.entry_price / trade.exit_price) - 1 - round_trip_cost


def price_trades(
    trades: list[TradeRecord], round_trip_cost: float
) -> tuple[list[PricedTrade], list[TradeExclusion]]:
    """Map each trade to a ``PricedTrade``; collect exclusions without raising.

    A trade is excluded (never priced) when its ``exit_price`` is zero
    (reason ``"exit_price_zero"``, Req 8.5) or its Signal_Direction is unknown
    (reason ``"unknown_direction"``, Req 8.6). All other trades are priced with
    :func:`strategy_return`. Returns a tuple of the priced trades and the
    exclusions, both in input order.
    """
    priced: list[PricedTrade] = []
    exclusions: list[TradeExclusion] = []

    for trade in trades:
        direction = direction_for(trade.signal_type)
        if direction is None:
            exclusions.append(TradeExclusion(trade=trade, reason="unknown_direction"))
            continue
        if trade.exit_price == 0:
            exclusions.append(TradeExclusion(trade=trade, reason="exit_price_zero"))
            continue
        priced.append(
            PricedTrade(
                trade=trade,
                direction=direction,
                strategy_return=strategy_return(trade, round_trip_cost),
            )
        )

    return priced, exclusions
