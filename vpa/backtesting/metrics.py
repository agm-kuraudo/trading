"""Performance-metrics calculator for the VPA strategy backtest report (SP-333).

Pure module: operates only on caller-supplied in-memory values, performs no
network or filesystem access, and never imports ``yfinance`` (Req 2.1). The
metric helpers are small, independently testable pure functions computed off
the canonical equity curve and the Price_Series so that reported numbers stay
internally consistent (Req 9-14).

This slice implements the return/annualisation helpers
(``total_return``, ``buy_and_hold_return``, ``annualised_return``,
``trades_per_year``) plus the daily-return/Sharpe/drawdown helpers
(``daily_returns``, ``sharpe_ratio``, ``max_drawdown``) plus the per-trade
quality helpers (``win_rate``, ``profit_factor``, ``average_win``,
``average_loss``, ``expectancy``, ``time_in_market``) plus the ``calculate``
orchestrator that combines them into a single ``MetricsResult`` (Req 2.3, 2.4,
15.1, 15.6, 15.7).
"""

import math
import statistics

from vpa.backtesting.models import EquityPoint, MetricsResult, PricedTrade, PricePoint

TRADING_DAYS_PER_YEAR = 252  # Trading_Days_Per_Year annualisation constant (Req 11.2)
DEFAULT_RISK_FREE_RATE = 0.04  # Default annual Risk_Free_Rate (Req 12.2)


def total_return(equity_curve: list[EquityPoint]) -> float:
    """Total_Return over the equity curve (Req 10.1, 10.4, 10.5).

    ``(final_equity / initial_equity) - 1`` when the curve has two or more
    points. Returns ``0.0`` for fewer than two points (Req 10.4). Also returns
    ``0.0`` when the initial equity is 0 to avoid dividing by zero; the caller
    (``calculate``) surfaces the zero-baseline indication on the
    ``MetricsResult.notes`` (Req 10.5).
    """
    if len(equity_curve) < 2:
        return 0.0
    initial_equity = equity_curve[0].equity
    if initial_equity == 0:
        return 0.0
    final_equity = equity_curve[-1].equity
    return (final_equity / initial_equity) - 1


def buy_and_hold_return(price_series: list[PricePoint]) -> float:
    """Buy_And_Hold_Return over the Price_Series (Req 10.2, 10.4, 10.5).

    ``(last_close / first_close) - 1`` when the series has two or more points.
    Returns ``0.0`` for fewer than two points (Req 10.4). Also returns ``0.0``
    when the first close is 0 to avoid dividing by zero; the caller
    (``calculate``) surfaces the zero-baseline indication on the
    ``MetricsResult.notes`` (Req 10.5).
    """
    if len(price_series) < 2:
        return 0.0
    first_close = price_series[0].close
    if first_close == 0:
        return 0.0
    last_close = price_series[-1].close
    return (last_close / first_close) - 1


def _years_in_span(price_series: list[PricePoint]) -> float:
    """Years spanned by the Price_Series (Req 11.1, 11.2).

    ``trading_days_in_span = distinct_dates - 1`` and
    ``years = trading_days_in_span / 252``. Returns ``0.0`` for fewer than two
    distinct dates.
    """
    distinct_dates = len({point.date for point in price_series})
    trading_days_in_span = distinct_dates - 1
    if trading_days_in_span <= 0:
        return 0.0
    return trading_days_in_span / TRADING_DAYS_PER_YEAR


def annualised_return(total_ret: float, price_series: list[PricePoint]) -> float:
    """Annualised_Return from Total_Return over the Price_Series span (Req 11).

    ``(1 + total_ret) ** (1 / years) - 1`` where
    ``years = (distinct_dates - 1) / 252`` (Req 11.2, 11.3). Returns ``0.0``
    when ``years == 0`` (Req 11.5) and ``-1.0`` when ``total_ret <= -1``,
    without evaluating the negative-base power (Req 11.6).

    A large gain compounded over a tiny span (e.g. a 2-date span gives a ~252
    exponent) can make the power expression exceed the float range. Rather than
    raising ``OverflowError`` on that degenerate case, the function returns
    ``float("inf")`` — a mathematically faithful, deterministic representation
    of an unbounded annualised return. All other behaviour is unchanged.
    """
    if total_ret <= -1:
        return -1.0
    years = _years_in_span(price_series)
    if years == 0:
        return 0.0
    try:
        return (1 + total_ret) ** (1 / years) - 1
    except OverflowError:
        return float("inf")


def trades_per_year(n_trades: int, price_series: list[PricePoint]) -> float:
    """Trades_Per_Year over the Price_Series span (Req 11.4, 11.5).

    ``number_of_trades / years`` where ``years = (distinct_dates - 1) / 252``.
    Returns ``0.0`` when ``years == 0`` (Req 11.5).
    """
    years = _years_in_span(price_series)
    if years == 0:
        return 0.0
    return n_trades / years


def daily_returns(equity_curve: list[EquityPoint]) -> list[float]:
    """Daily strategy returns from the Equity_Curve (Req 12.3).

    The fractional day-over-day change of Equity_Curve capital, producing one
    daily return per consecutive pair of Equity_Curve data points:
    ``equity_t / equity_{t-1} - 1``. Returns an empty list for fewer than two
    points. A zero prior-day equity is skipped to avoid dividing by zero.
    """
    returns: list[float] = []
    for previous, current in zip(equity_curve, equity_curve[1:], strict=False):
        prior_equity = previous.equity
        if prior_equity == 0:
            continue
        returns.append((current.equity / prior_equity) - 1)
    return returns


def sharpe_ratio(equity_curve: list[EquityPoint], risk_free_rate: float) -> float:
    """Annualised Sharpe_Ratio of the Equity_Curve (Req 12.4, 12.5, 12.6, 12.7, 12.8).

    ``daily_risk_free_rate = risk_free_rate / 252``; the standard deviation of
    daily returns is the sample standard deviation (N-1 divisor) via
    ``statistics.stdev``. When ``std > 0`` and at least two daily returns are
    available, ``Sharpe_Ratio = ((mean_daily - daily_rf) / std) * sqrt(252)``.
    Returns ``0.0`` when fewer than two daily returns are available (Req 12.8)
    or when ``std == 0`` (Req 12.7).
    """
    returns = daily_returns(equity_curve)
    if len(returns) < 2:
        return 0.0
    std_daily_return = statistics.stdev(returns)
    if std_daily_return == 0:
        return 0.0
    daily_risk_free_rate = risk_free_rate / TRADING_DAYS_PER_YEAR
    mean_daily_return = statistics.mean(returns)
    return ((mean_daily_return - daily_risk_free_rate) / std_daily_return) * math.sqrt(TRADING_DAYS_PER_YEAR)


def max_drawdown(equity_curve: list[EquityPoint]) -> float:
    """Max_Drawdown of the Equity_Curve (Req 13.1, 13.2, 13.3, 13.4, 13.5).

    A single forward pass tracks the running peak (running maximum equity from
    the first point through time t inclusive) and takes the minimum over all t
    of ``equity_t / peak_t - 1``, clamped to ``[-1.0, 0.0]``. Returns ``0.0``
    for an empty curve (Req 13.4) and for a zero running peak, avoiding
    division by zero; the caller (``calculate``) surfaces the zero-peak
    indication on ``MetricsResult.notes`` (Req 13.5).
    """
    if not equity_curve:
        return 0.0
    running_peak = equity_curve[0].equity
    worst_drawdown = 0.0
    for point in equity_curve:
        if point.equity > running_peak:
            running_peak = point.equity
        if running_peak == 0:
            return 0.0
        drawdown = (point.equity / running_peak) - 1
        worst_drawdown = min(worst_drawdown, drawdown)
    return max(worst_drawdown, -1.0)


def win_rate(priced_trades: list[PricedTrade]) -> float:
    """Win_Rate over the priced trades (Req 14.1, 14.2).

    ``number_of_wins / number_of_trades`` where a win is a trade whose
    Strategy_Return is strictly greater than 0. A zero-return trade counts in
    the ``number_of_trades`` denominator but is neither a win nor a loss
    (Req 14.1). Returns ``0.0`` for an empty trade list. The result lies in the
    range ``[0.0, 1.0]``.
    """
    if not priced_trades:
        return 0.0
    number_of_wins = sum(1 for pt in priced_trades if pt.strategy_return > 0)
    return number_of_wins / len(priced_trades)


def profit_factor(priced_trades: list[PricedTrade]) -> float:
    """Profit_Factor over the priced trades (Req 14.4, 15.2, 15.3).

    ``sum_of_winning_returns / abs(sum_of_losing_returns)``. When there are
    winning trades but no losing trades, returns ``float("inf")`` (Req 15.2).
    When there are neither winning nor losing trades (empty list, or only
    zero-return trades), returns ``0.0`` (Req 15.3).
    """
    sum_of_winning_returns = sum(pt.strategy_return for pt in priced_trades if pt.strategy_return > 0)
    sum_of_losing_returns = sum(pt.strategy_return for pt in priced_trades if pt.strategy_return < 0)
    if sum_of_losing_returns == 0:
        if sum_of_winning_returns == 0:
            return 0.0
        return float("inf")
    return sum_of_winning_returns / abs(sum_of_losing_returns)


def average_win(priced_trades: list[PricedTrade]) -> float:
    """Average_Win over the priced trades (Req 14.3, 15.4).

    The mean Strategy_Return of winning trades only (Strategy_Return > 0).
    Returns ``0.0`` when there are no winning trades (Req 15.4).
    """
    winners = [pt.strategy_return for pt in priced_trades if pt.strategy_return > 0]
    if not winners:
        return 0.0
    return statistics.mean(winners)


def average_loss(priced_trades: list[PricedTrade]) -> float:
    """Average_Loss over the priced trades (Req 14.3, 15.5).

    The mean Strategy_Return of losing trades only (Strategy_Return < 0).
    Returns ``0.0`` when there are no losing trades (Req 15.5).
    """
    losers = [pt.strategy_return for pt in priced_trades if pt.strategy_return < 0]
    if not losers:
        return 0.0
    return statistics.mean(losers)


def expectancy(priced_trades: list[PricedTrade]) -> float:
    """Expectancy over the priced trades (Req 14.5).

    The mean Strategy_Return across all trades. Returns ``0.0`` for an empty
    trade list.
    """
    if not priced_trades:
        return 0.0
    return statistics.mean(pt.strategy_return for pt in priced_trades)


def time_in_market(priced_trades: list[PricedTrade], price_series: list[PricePoint]) -> float:
    """Time_In_Market over the Price_Series span (Req 14.6, 14.7).

    A position is open on ``[entry_date, exit_date)`` — entry inclusive, exit
    exclusive. Each Price_Series date covered by any open interval is counted
    exactly once so overlapping STACKING trades are not double-counted
    (Req 14.6). ``Time_In_Market = days_with_an_open_position /
    total_days_in_span`` where ``total_days_in_span`` is the number of distinct
    Price_Series dates (Req 14.7). Returns ``0.0`` when the Price_Series is
    empty. The result lies in the range ``[0.0, 1.0]``.
    """
    span_dates = {point.date for point in price_series}
    if not span_dates:
        return 0.0
    open_dates: set[str] = set()
    for pt in priced_trades:
        entry_date = pt.trade.entry_date
        exit_date = pt.trade.exit_date
        for date in span_dates:
            if entry_date <= date < exit_date:
                open_dates.add(date)
    return len(open_dates) / len(span_dates)


def _no_trades_result(price_series: list[PricePoint], notes: tuple[str, ...] = ()) -> MetricsResult:
    """The no-trades ``MetricsResult`` (Req 15.1, 15.7).

    Every metric is ``0.0`` and ``number_of_trades`` is ``0``, except
    ``buy_and_hold_return`` which is still computed from the Price_Series when
    it has two or more points. Never raises.
    """
    return MetricsResult(
        total_return=0.0,
        annualised_return=0.0,
        buy_and_hold_return=buy_and_hold_return(price_series),
        sharpe_ratio=0.0,
        max_drawdown=0.0,
        win_rate=0.0,
        profit_factor=0.0,
        average_win=0.0,
        average_loss=0.0,
        expectancy=0.0,
        time_in_market=0.0,
        number_of_trades=0,
        trades_per_year=0.0,
        notes=notes,
    )


def calculate(
    priced_trades: list[PricedTrade],
    equity_curve: list[EquityPoint],
    price_series: list[PricePoint],
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> MetricsResult:
    """Combine the metric helpers into a single ``MetricsResult`` (Req 2.3, 2.4, 15).

    Computes the full performance-metrics suite from the direction-aware priced
    trades, the canonical Equity_Curve, and the Price_Series so that reported
    numbers stay internally consistent. Determinism is guaranteed for identical
    inputs because every helper is pure (Req 2.3).

    A required in-memory input that was not supplied at all (``None``) is
    rejected with a ``ValueError`` naming it (Req 2.4). A normal zero-trades or
    empty-Price_Series case is NOT an error: it returns the no-trades
    ``MetricsResult`` (all metrics ``0.0``, ``number_of_trades = 0``) without
    raising, while still computing ``buy_and_hold_return`` when the Price_Series
    has two or more points (Req 15.1, 15.7).

    Zero-denominator / zero-baseline conditions are surfaced as concise strings
    on ``MetricsResult.notes`` rather than raising: a zero initial equity or
    zero first close (Req 10.5) and a zero running peak in the drawdown pass
    (Req 13.5).
    """
    if priced_trades is None:
        msg = "priced_trades is required and must not be None"
        raise ValueError(msg)
    if price_series is None:
        msg = "price_series is required and must not be None"
        raise ValueError(msg)
    if equity_curve is None:
        msg = "equity_curve is required and must not be None"
        raise ValueError(msg)

    notes = _collect_notes(equity_curve, price_series)

    number_of_trades = len(priced_trades)
    if number_of_trades == 0 or not price_series:
        return _no_trades_result(price_series, notes)

    total_ret = total_return(equity_curve)
    return MetricsResult(
        total_return=total_ret,
        annualised_return=annualised_return(total_ret, price_series),
        buy_and_hold_return=buy_and_hold_return(price_series),
        sharpe_ratio=sharpe_ratio(equity_curve, risk_free_rate),
        max_drawdown=max_drawdown(equity_curve),
        win_rate=win_rate(priced_trades),
        profit_factor=profit_factor(priced_trades),
        average_win=average_win(priced_trades),
        average_loss=average_loss(priced_trades),
        expectancy=expectancy(priced_trades),
        time_in_market=time_in_market(priced_trades, price_series),
        number_of_trades=number_of_trades,
        trades_per_year=trades_per_year(number_of_trades, price_series),
        notes=notes,
    )


def _collect_notes(equity_curve: list[EquityPoint], price_series: list[PricePoint]) -> tuple[str, ...]:
    """Collect zero-denominator / zero-baseline indications (Req 10.5, 13.5).

    Returns concise note strings for a zero initial equity or zero first close
    (the affected return metric is reported ``0.0``; Req 10.5) and for a zero
    running peak encountered during the drawdown pass (Req 13.5). The notes are
    informational only and never interrupt the run.
    """
    notes: list[str] = []
    if len(equity_curve) >= 2 and equity_curve[0].equity == 0:
        notes.append("initial equity is 0; total_return reported as 0.0")
    if len(price_series) >= 2 and price_series[0].close == 0:
        notes.append("first close is 0; buy_and_hold_return reported as 0.0")
    if _has_zero_running_peak(equity_curve):
        notes.append("running peak is 0 in drawdown; max_drawdown reported as 0.0")
    return tuple(notes)


def _has_zero_running_peak(equity_curve: list[EquityPoint]) -> bool:
    """True when the running peak is 0 at any point of the drawdown pass (Req 13.5)."""
    if not equity_curve:
        return False
    running_peak = equity_curve[0].equity
    for point in equity_curve:
        if point.equity > running_peak:
            running_peak = point.equity
        if running_peak == 0:
            return True
    return False
