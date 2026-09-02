"""Daily equity-curve construction for the VPA strategy backtest report (SP-333).

This module turns a Price_Series and a set of priced trades into a daily
Equity_Curve (Req 9). It is pure: it operates only on caller-supplied in-memory
values and performs no network, filesystem, or ``yfinance`` access.

The curve holds one ``EquityPoint`` per Price_Series date in ascending order,
starting at a capital of 1.0 on the first date. On each date, carried capital is
multiplied by the product of ``(1 + Strategy_Return)`` across every trade whose
``exit_date`` equals that date; dates with no closing trade carry the previous
capital forward unchanged. The same-day product is order-independent (Req 9.4).
"""

import math

from vpa.backtesting.models import EquityPoint, PricedTrade, PricePoint


def build_equity_curve(
    price_series: list[PricePoint], priced_trades: list[PricedTrade]
) -> list[EquityPoint]:
    """Build the daily Equity_Curve from the Price_Series and priced trades (Req 9).

    Produces exactly one ``EquityPoint`` per date in ``price_series``, ordered
    chronologically ascending (Req 9.1, 9.6), starting at a capital of 1.0 on the
    first date (Req 9.2). For each date, the carried capital is multiplied by
    ``math.prod(1 + r for r in returns_that_day)`` across all trades whose
    ``exit_date`` equals that date; this is independent of the order in which the
    same-day closing trades are applied (Req 9.3, 9.4). Dates on which no trade
    closes carry the previous cumulative capital forward unchanged (Req 9.5).

    An empty ``price_series`` yields an empty curve without error (Req 15.7).
    """
    if not price_series:
        return []

    returns_by_exit_date: dict[str, list[float]] = {}
    for priced in priced_trades:
        returns_by_exit_date.setdefault(priced.trade.exit_date, []).append(
            priced.strategy_return
        )

    curve: list[EquityPoint] = []
    capital = 1.0
    for point in price_series:
        returns_that_day = returns_by_exit_date.get(point.date)
        if returns_that_day:
            capital *= math.prod(1 + r for r in returns_that_day)
        curve.append(EquityPoint(date=point.date, equity=capital))

    return curve
