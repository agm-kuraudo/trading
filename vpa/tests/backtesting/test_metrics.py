"""Tests for the performance-metrics helper functions (SP-333).

Covers the Correctness Properties for ``vpa/backtesting/metrics.py`` via
Hypothesis property tests. This module starts with Property 8 (total return and
buy-and-hold formulas); later tasks append the remaining metric properties and
example tests here.

Code under test: ``vpa/backtesting/metrics.py``.
"""

import math
import statistics

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from vpa.backtesting.equity_curve import build_equity_curve
from vpa.backtesting.metrics import (
    TRADING_DAYS_PER_YEAR,
    annualised_return,
    buy_and_hold_return,
    calculate,
    daily_returns,
    expectancy,
    max_drawdown,
    profit_factor,
    sharpe_ratio,
    time_in_market,
    total_return,
    trades_per_year,
    win_rate,
)
from vpa.backtesting.models import EquityPoint, PricedTrade, PricePoint, TradeRecord
from vpa.backtesting.pnl import price_trades
from vpa.ml_validation.signal_analysis import (
    SIGNAL_DIRECTIONS,
    SignalDirection,
    SignalType,
)

# Positive, finite equity/price values kept strictly greater than 0 so the
# formulas never divide by zero. The bounded range mirrors realistic capital
# and SPY-style close prices while keeping the arithmetic well-conditioned.
_positive_value = st.floats(
    min_value=0.01,
    max_value=1e6,
    allow_nan=False,
    allow_infinity=False,
)


def _iso_date(index: int) -> str:
    """Return a distinct, ascending positional date string for the given index."""
    return f"{index:08d}"


def make_equity_curve(equities: list[float]) -> list[EquityPoint]:
    """Build an Equity_Curve with distinct ascending dates and the given equities."""
    return [EquityPoint(date=_iso_date(i), equity=equity) for i, equity in enumerate(equities)]


def make_price_series(closes: list[float]) -> list[PricePoint]:
    """Build a Price_Series with distinct ascending dates and the given closes.

    OHLC fields are derived from each close so ``low <= open, close <= high``
    holds; only the close is exercised by the return formulas here.
    """
    series: list[PricePoint] = []
    for i, close in enumerate(closes):
        series.append(
            PricePoint(date=_iso_date(i), open=close, high=close, low=close, close=close)
        )
    return series


# Feature: vpa-strategy-backtest-report, Property 8: Total return and buy-and-hold formulas
@settings(max_examples=100)
@given(
    equities=st.lists(_positive_value, min_size=2, max_size=60),
    closes=st.lists(_positive_value, min_size=2, max_size=60),
)
def test_property_8_total_return_and_buy_and_hold_formulas(
    equities: list[float],
    closes: list[float],
) -> None:
    """Total_Return and Buy_And_Hold_Return match their defining formulas.

    Validates: Requirements 10.1, 10.2, 10.3.
    """
    equity_curve = make_equity_curve(equities)
    price_series = make_price_series(closes)

    # Req 10.1: Total_Return == (final_equity / initial_equity) - 1.
    expected_total_return = (equities[-1] / equities[0]) - 1
    assert math.isclose(total_return(equity_curve), expected_total_return, abs_tol=1e-9)

    # Req 10.2: Buy_And_Hold_Return == (last_close / first_close) - 1.
    expected_bnh_return = (closes[-1] / closes[0]) - 1
    assert math.isclose(buy_and_hold_return(price_series), expected_bnh_return, abs_tol=1e-9)


# Feature: vpa-strategy-backtest-report, Property 9: Annualisation formula and guards
@settings(max_examples=100)
@given(
    total_ret=st.floats(
        min_value=-0.99,
        max_value=5.0,
        allow_nan=False,
        allow_infinity=False,
    ),
    distinct_dates=st.integers(min_value=2, max_value=60),
    n_trades=st.integers(min_value=0, max_value=1000),
)
def test_property_9_annualisation_formula_and_guards(
    total_ret: float,
    distinct_dates: int,
    n_trades: int,
) -> None:
    """Annualised_Return and Trades_Per_Year match the reference computation.

    For a Price_Series with ``distinct_dates >= 2`` (so ``years > 0``) and
    ``Total_Return > -1``, ``annualised_return`` and ``trades_per_year`` equal
    the reference formulas using ``years = (distinct_dates - 1) / 252``.

    Validates: Requirements 11.2, 11.3, 11.4.
    """
    # A Price_Series with exactly ``distinct_dates`` ascending distinct dates
    # (arbitrary closes; only the date span drives annualisation).
    price_series = make_price_series([1.0] * distinct_dates)

    # Req 11.2: years == (distinct_dates - 1) / 252, computed independently.
    years = (distinct_dates - 1) / TRADING_DAYS_PER_YEAR
    assert years > 0

    # Req 11.3: Annualised_Return == (1 + Total_Return) ** (1 / years) - 1.
    expected_annualised = (1 + total_ret) ** (1 / years) - 1
    assert math.isclose(
        annualised_return(total_ret, price_series), expected_annualised, abs_tol=1e-9
    )

    # Req 11.4: Trades_Per_Year == number_of_trades / years.
    expected_trades_per_year = n_trades / years
    assert math.isclose(
        trades_per_year(n_trades, price_series), expected_trades_per_year, abs_tol=1e-9
    )

# A single trade generator: an entry/exit date pair (indices into the shared
# Price_Series span), a signal type drawn from the direction map so the trade is
# always priceable, and raw prices plus a bounded long-basis return. Prices are
# kept strictly positive so DOWN P&L (entry/exit ratio) never divides by zero,
# and return_pct is bounded so the compounded equity stays well-conditioned and
# never produces NaN.
_signal_type = st.sampled_from(list(SIGNAL_DIRECTIONS.keys()))


@st.composite
def _trade_and_span(draw: st.DrawFn) -> tuple[list[PricePoint], list[TradeRecord], float]:
    """Generate a Price_Series (>= 2 ascending dates) and matching trades.

    Trades carry ISO dates that fall inside the Price_Series span (exit strictly
    after entry) so ``build_equity_curve`` books each close on a real curve date.
    Returns the Price_Series, the trades, and a round-trip cost.
    """
    n_dates = draw(st.integers(min_value=2, max_value=40))
    closes = draw(st.lists(_positive_value, min_size=n_dates, max_size=n_dates))
    price_series = make_price_series(closes)

    round_trip_cost = draw(st.floats(min_value=0.0, max_value=0.02, allow_nan=False, allow_infinity=False))

    n_trades = draw(st.integers(min_value=0, max_value=15))
    trades: list[TradeRecord] = []
    for _ in range(n_trades):
        entry_index = draw(st.integers(min_value=0, max_value=n_dates - 2))
        exit_index = draw(st.integers(min_value=entry_index + 1, max_value=n_dates - 1))
        entry_price = draw(_positive_value)
        exit_price = draw(_positive_value)
        return_pct = draw(st.floats(min_value=-0.9, max_value=0.9, allow_nan=False, allow_infinity=False))
        trades.append(
            TradeRecord(
                entry_date=_iso_date(entry_index),
                exit_date=_iso_date(exit_index),
                entry_price=entry_price,
                exit_price=exit_price,
                return_pct=return_pct,
                signal_type=draw(_signal_type),
            )
        )

    return price_series, trades, round_trip_cost


# Feature: vpa-strategy-backtest-report, Property 17: Determinism of the metrics pipeline
@settings(max_examples=100)
@given(
    span_and_trades=_trade_and_span(),
    risk_free_rate=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)
def test_property_17_metrics_pipeline_determinism(
    span_and_trades: tuple[list[PricePoint], list[TradeRecord], float],
    risk_free_rate: float,
) -> None:
    """Running the metrics pipeline twice on identical inputs is deterministic.

    For a fixed Price_Series, trade set, and risk-free rate, the priced trades,
    the equity curve, and the resulting ``MetricsResult`` are identical across
    two independent runs.

    Validates: Requirements 2.2, 2.3.
    """
    price_series, trades, round_trip_cost = span_and_trades

    # First run of the full pure pipeline: price the trades, build the equity
    # curve, then compute the metrics.
    priced_1, _ = price_trades(trades, round_trip_cost)
    equity_1 = build_equity_curve(price_series, priced_1)
    metrics_1 = calculate(priced_1, equity_1, price_series, risk_free_rate)

    # Second run with the identical inputs.
    priced_2, _ = price_trades(trades, round_trip_cost)
    equity_2 = build_equity_curve(price_series, priced_2)
    metrics_2 = calculate(priced_2, equity_2, price_series, risk_free_rate)

    # Frozen dataclasses of floats/ints/tuples compare by value; the generated
    # inputs avoid NaN, and profit_factor's only non-finite value (inf) compares
    # equal to itself, so == is a sound determinism check.
    assert priced_1 == priced_2
    assert equity_1 == equity_2
    assert metrics_1 == metrics_2

# Feature: vpa-strategy-backtest-report, Property 10: Sharpe ratio equals the reference computation
@settings(max_examples=100)
@given(
    equities=st.lists(_positive_value, min_size=3, max_size=60),
    risk_free_rate=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)
def test_property_10_sharpe_ratio_equals_reference_computation(
    equities: list[float],
    risk_free_rate: float,
) -> None:
    """Sharpe_Ratio equals the reference computation over the daily returns.

    For an Equity_Curve with at least two daily returns (>= 3 equity points) and
    a non-zero sample standard deviation of daily returns, ``sharpe_ratio``
    equals ``((mean_daily - risk_free_rate / 252) / sample_std) * sqrt(252)``
    computed independently via ``statistics``. The sample standard deviation
    uses the N-1 divisor (``statistics.stdev``) and daily returns are
    ``equity_t / equity_{t-1} - 1``.

    The ``std == 0`` degenerate case (where the spec returns 0.0) is guarded out
    with ``assume(...)`` because that guard is covered elsewhere.

    Validates: Requirements 12.3, 12.4, 12.5, 12.6.
    """
    equity_curve = make_equity_curve(equities)

    # Reference daily returns computed independently: equity_t / equity_{t-1} - 1.
    returns = [(equities[i] / equities[i - 1]) - 1 for i in range(1, len(equities))]
    assert len(returns) >= 2

    # Guard the degenerate std == 0 case (spec returns 0.0; covered elsewhere).
    sample_std = statistics.stdev(returns)
    assume(sample_std > 0)

    # Sanity-check that the implementation's daily_returns matches the reference.
    assert daily_returns(equity_curve) == returns

    mean_daily = statistics.mean(returns)
    daily_rf = risk_free_rate / TRADING_DAYS_PER_YEAR
    expected_sharpe = ((mean_daily - daily_rf) / sample_std) * math.sqrt(TRADING_DAYS_PER_YEAR)

    assert math.isclose(sharpe_ratio(equity_curve, risk_free_rate), expected_sharpe, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# Requirement 15 edge-case example tests (task 7.3).
#
# Explicit (non-property) example tests that pin down the documented edge-case
# behaviour of the metrics pipeline: zero trades, all-wins, no-wins-no-losses,
# a single trade, and an empty Price_Series. Reuses make_equity_curve /
# make_price_series / _iso_date above and builds PricedTrade values directly by
# wrapping a TradeRecord and setting strategy_return to the desired sign.
# ---------------------------------------------------------------------------

def _priced_trade(
    strategy_return: float,
    *,
    entry_index: int = 0,
    exit_index: int = 1,
    direction: SignalDirection = SignalDirection.UP,
) -> PricedTrade:
    """Build a PricedTrade directly with the given signed Strategy_Return.

    The wrapped TradeRecord carries plausible positive prices and ISO dates; the
    metric helpers under test read only ``strategy_return`` (and, for
    time-in-market, the trade dates), so the exact price fields are immaterial
    for these value assertions.
    """
    trade = TradeRecord(
        entry_date=_iso_date(entry_index),
        exit_date=_iso_date(exit_index),
        entry_price=100.0,
        exit_price=100.0 * (1 + strategy_return) if strategy_return > -1 else 1.0,
        return_pct=strategy_return,
        signal_type=SignalType.STRONG_BULLISH,
    )
    return PricedTrade(trade=trade, direction=direction, strategy_return=strategy_return)


def test_req_15_1_zero_trades_reports_no_trades_metric_set() -> None:
    """Zero trades yields the no-trades metric set with every metric 0.0.

    Validates: Requirements 15.1.
    """
    result = calculate([], [], [])

    assert result.number_of_trades == 0
    assert result.total_return == 0.0
    assert result.annualised_return == 0.0
    assert result.buy_and_hold_return == 0.0
    assert result.sharpe_ratio == 0.0
    assert result.max_drawdown == 0.0
    assert result.win_rate == 0.0
    assert result.profit_factor == 0.0
    assert result.average_win == 0.0
    assert result.average_loss == 0.0
    assert result.expectancy == 0.0
    assert result.time_in_market == 0.0
    assert result.trades_per_year == 0.0


def test_req_15_1_zero_trades_still_reports_buy_and_hold() -> None:
    """Zero trades over a non-empty Price_Series still reports Buy_And_Hold_Return.

    The no-trades metric set is returned (all metrics 0.0, number_of_trades 0),
    but Buy_And_Hold_Return is still computed from the Price_Series when it has
    two or more points.

    Validates: Requirements 15.1.
    """
    price_series = make_price_series([100.0, 110.0])

    result = calculate([], [], price_series)

    assert result.number_of_trades == 0
    assert result.total_return == 0.0
    # (110 / 100) - 1 == 0.1
    assert math.isclose(result.buy_and_hold_return, 0.1, abs_tol=1e-9)


def test_req_15_2_all_wins_profit_factor_is_infinite() -> None:
    """All winning trades (no losses) yields Profit_Factor of float("inf").

    Validates: Requirements 15.2.
    """
    price_series = make_price_series([100.0, 105.0, 110.0])
    priced = [
        _priced_trade(0.05, entry_index=0, exit_index=1),
        _priced_trade(0.10, entry_index=1, exit_index=2),
    ]
    equity_curve = build_equity_curve(price_series, priced)

    # Direct helper: wins but no losses -> +inf.
    assert profit_factor(priced) == float("inf")

    result = calculate(priced, equity_curve, price_series)
    assert result.number_of_trades == 2
    assert result.profit_factor == float("inf")
    assert result.win_rate == 1.0


def test_req_15_3_no_wins_no_losses_profit_factor_is_zero() -> None:
    """Only zero-return trades yields Profit_Factor of 0.0.

    Zero-return trades count in the trade denominator but are neither wins nor
    losses, so Profit_Factor is 0.0 (not inf).

    Validates: Requirements 15.3.
    """
    price_series = make_price_series([100.0, 100.0, 100.0])
    priced = [
        _priced_trade(0.0, entry_index=0, exit_index=1),
        _priced_trade(0.0, entry_index=1, exit_index=2),
    ]
    equity_curve = build_equity_curve(price_series, priced)

    # Direct helper: neither wins nor losses -> 0.0.
    assert profit_factor(priced) == 0.0

    result = calculate(priced, equity_curve, price_series)
    assert result.number_of_trades == 2
    assert result.profit_factor == 0.0
    assert result.win_rate == 0.0
    assert result.average_win == 0.0
    assert result.average_loss == 0.0


def test_req_15_6_single_trade_computes_metrics_without_error() -> None:
    """A single trade computes Win_Rate, Expectancy, and Profit_Factor cleanly.

    Validates: Requirements 15.6.
    """
    price_series = make_price_series([100.0, 108.0])
    priced = [_priced_trade(0.08, entry_index=0, exit_index=1)]
    equity_curve = build_equity_curve(price_series, priced)

    result = calculate(priced, equity_curve, price_series)

    assert result.number_of_trades == 1
    # Single winning trade: win rate 1.0, expectancy equals the single return,
    # profit factor is +inf (a win with no losing trade).
    assert result.win_rate == 1.0
    assert math.isclose(result.expectancy, 0.08, abs_tol=1e-9)
    assert result.profit_factor == float("inf")


def test_req_15_6_single_losing_trade_computes_metrics_without_error() -> None:
    """A single losing trade computes the per-trade metrics without error.

    Validates: Requirements 15.6.
    """
    price_series = make_price_series([100.0, 96.0])
    priced = [_priced_trade(-0.04, entry_index=0, exit_index=1)]
    equity_curve = build_equity_curve(price_series, priced)

    result = calculate(priced, equity_curve, price_series)

    assert result.number_of_trades == 1
    assert result.win_rate == 0.0
    assert math.isclose(result.expectancy, -0.04, abs_tol=1e-9)
    # A loss with no winning trade: sum_of_winning_returns == 0 -> profit factor 0.0.
    assert result.profit_factor == 0.0


def test_req_15_7_empty_price_series_reports_no_trades_and_empty_curve() -> None:
    """An empty Price_Series yields the no-trades metric set and an empty curve.

    ``build_equity_curve`` on an empty series is empty, and ``calculate`` handles
    the empty inputs gracefully without raising.

    Validates: Requirements 15.7.
    """
    empty_series: list[PricePoint] = []

    # Empty Price_Series -> empty Equity_Curve (Req 15.7).
    equity_curve = build_equity_curve(empty_series, [])
    assert equity_curve == []

    result = calculate([], equity_curve, empty_series)

    assert result.number_of_trades == 0
    assert result.total_return == 0.0
    assert result.buy_and_hold_return == 0.0
    assert result.sharpe_ratio == 0.0
    assert result.max_drawdown == 0.0
    assert result.trades_per_year == 0.0

def _reference_max_drawdown(equities: list[float]) -> float:
    """Reference Max_Drawdown via an independent running-peak loop.

    Tracks the running maximum equity through time t inclusive and takes the
    minimum over all t of ``equity_t / running_peak_t - 1``. This is an
    intentionally separate implementation from ``max_drawdown`` so the property
    checks agreement rather than restating the code under test. Assumes positive
    equities (so the running peak is never 0).
    """
    running_peak = equities[0]
    worst = 0.0
    for equity in equities:
        if equity > running_peak:
            running_peak = equity
        worst = min(worst, (equity / running_peak) - 1)
    return worst


# Feature: vpa-strategy-backtest-report, Property 11: Max drawdown is the deepest peak-relative decline and lies in [-1, 0]  # noqa: E501
@settings(max_examples=100)
@given(equities=st.lists(_positive_value, min_size=1, max_size=60))
def test_property_11_max_drawdown_deepest_peak_relative_decline(
    equities: list[float],
) -> None:
    """Max_Drawdown is the deepest peak-relative decline and lies in [-1, 0].

    For a positive Equity_Curve, ``max_drawdown`` equals the reference
    running-max computation ``min_t(equity_t / running_peak_t - 1)`` and always
    lies in the closed range ``[-1.0, 0.0]``.

    Validates: Requirements 13.1, 13.2, 13.3.
    """
    equity_curve = make_equity_curve(equities)
    result = max_drawdown(equity_curve)

    # Req 13.1 / 13.2: equals the independent running-peak reference computation.
    expected = _reference_max_drawdown(equities)
    assert math.isclose(result, expected, abs_tol=1e-9)

    # Req 13.3: the result lies in the closed range [-1.0, 0.0].
    assert -1.0 <= result <= 0.0


# Feature: vpa-strategy-backtest-report, Property 11: Max drawdown is the deepest peak-relative decline and lies in [-1, 0]  # noqa: E501
@settings(max_examples=100)
@given(
    first=_positive_value,
    increments=st.lists(
        st.floats(min_value=0.0, max_value=1e5, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=60,
    ),
)
def test_property_11_max_drawdown_zero_for_never_declining_curve(
    first: float,
    increments: list[float],
) -> None:
    """Max_Drawdown is 0.0 for a monotonically non-decreasing Equity_Curve.

    A curve built by accumulating non-negative increments never falls below its
    running peak, so the deepest peak-relative decline is exactly 0.0.

    Validates: Requirements 13.1, 13.2, 13.3.
    """
    equities: list[float] = [first]
    for increment in increments:
        equities.append(equities[-1] + increment)

    # The curve is monotonically non-decreasing by construction.
    assert all(later >= earlier for earlier, later in zip(equities, equities[1:], strict=False))

    equity_curve = make_equity_curve(equities)
    assert max_drawdown(equity_curve) == 0.0


# Feature: vpa-strategy-backtest-report, Property 12: Win rate lies in [0, 1] and expectancy is the mean strategy return  # noqa: E501
@settings(max_examples=100)
@given(
    strategy_returns=st.lists(
        st.floats(min_value=-0.9, max_value=0.9, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=60,
    ),
)
def test_property_12_win_rate_and_expectancy(
    strategy_returns: list[float],
) -> None:
    """Win_Rate lies in [0, 1] and Expectancy is the mean Strategy_Return.

    For any set of priced trades, ``win_rate`` equals ``number_of_wins /
    number_of_trades`` (a zero-return trade counts in the denominator but as
    neither a win nor a loss) and always lies in the closed range ``[0.0,
    1.0]``, while ``expectancy`` equals the arithmetic mean of the
    Strategy_Return values across all trades.

    The generated returns deliberately mix positive, negative, and exactly-0.0
    values (0.0 is inside the sampled range) so the neither-win-nor-loss case is
    exercised.

    Validates: Requirements 14.1, 14.2, 14.5.
    """
    priced = [_priced_trade(strategy_return) for strategy_return in strategy_returns]

    # Req 14.1 / 14.2: win_rate == number_of_wins / number_of_trades, where a
    # win is strictly Strategy_Return > 0 (zero-return trades count in the
    # denominator but as neither win nor loss).
    number_of_wins = sum(1 for r in strategy_returns if r > 0)
    expected_win_rate = number_of_wins / len(strategy_returns)
    result_win_rate = win_rate(priced)
    assert math.isclose(result_win_rate, expected_win_rate, abs_tol=1e-9)
    assert 0.0 <= result_win_rate <= 1.0

    # Req 14.5: expectancy == mean of all Strategy_Return values.
    expected_expectancy = statistics.mean(strategy_returns)
    assert math.isclose(expectancy(priced), expected_expectancy, abs_tol=1e-9)


# Feature: vpa-strategy-backtest-report, Property 13: Profit factor equals wins over absolute losses
@settings(max_examples=100)
@given(
    winning_returns=st.lists(
        st.floats(min_value=0.001, max_value=0.9, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=30,
    ),
    losing_returns=st.lists(
        st.floats(min_value=-0.9, max_value=-0.001, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=30,
    ),
)
def test_property_13_profit_factor_equals_wins_over_absolute_losses(
    winning_returns: list[float],
    losing_returns: list[float],
) -> None:
    """Profit_Factor equals winning returns over absolute losing returns.

    For a set of priced trades containing at least one strictly winning trade
    (Strategy_Return > 0) and at least one strictly losing trade
    (Strategy_Return < 0), ``profit_factor`` equals
    ``sum_of_winning_returns / abs(sum_of_losing_returns)``. Generating a
    non-empty list of strictly-positive returns and a non-empty list of
    strictly-negative returns and combining them guarantees the mixed case (so
    the ``inf``/``0.0`` degenerate branches are exercised elsewhere). Returns
    are bounded to ``[-0.9, 0.9]`` to keep the arithmetic well-conditioned.

    Validates: Requirements 14.4.
    """
    returns = winning_returns + losing_returns
    priced = [_priced_trade(strategy_return) for strategy_return in returns]

    # Reference sums computed independently from the code under test.
    sum_of_winning_returns = sum(r for r in returns if r > 0)
    sum_of_losing_returns = sum(r for r in returns if r < 0)
    # Both lists are non-empty and strictly signed, so there is at least one
    # win and one loss and the denominator is strictly positive.
    assert sum_of_winning_returns > 0
    assert sum_of_losing_returns < 0

    expected = sum_of_winning_returns / abs(sum_of_losing_returns)
    assert math.isclose(profit_factor(priced), expected, abs_tol=1e-9)


# Feature: vpa-strategy-backtest-report, Property 14: Time in market counts each open day once and lies in [0, 1]  # noqa: E501
@settings(max_examples=100)
@given(
    n_dates=st.integers(min_value=1, max_value=40),
    intervals=st.lists(
        st.tuples(st.integers(min_value=0), st.integers(min_value=0)),
        min_size=0,
        max_size=20,
    ),
)
def test_property_14_time_in_market_counts_each_open_day_once(
    n_dates: int,
    intervals: list[tuple[int, int]],
) -> None:
    """Time_In_Market counts each open day once and lies in [0, 1].

    A position is open on ``[entry_date, exit_date)`` (entry inclusive, exit
    exclusive). Each Price_Series date covered by any open interval is counted
    exactly once so overlapping STACKING-style trades are not double-counted,
    and ``time_in_market`` equals ``days_with_an_open_position /
    total_days_in_span`` over the distinct Price_Series dates. The result always
    lies in the closed range ``[0.0, 1.0]``.

    The generated ``(entry, exit)`` index pairs are normalised into the span
    with ``entry_index < exit_index`` in ``[0, n_dates]``, and pairs are
    deliberately allowed to overlap so the count-once behaviour is exercised.

    Validates: Requirements 14.6, 14.7.
    """
    # Price_Series with N sequential dates: _iso_date(0..N-1), matching the dates
    # that _priced_trade stamps on its wrapped TradeRecord.
    price_series = make_price_series([100.0] * n_dates)

    # Normalise each raw pair into a valid half-open interval within the span:
    # entry_index in [0, n_dates - 1], exit_index in [entry_index + 1, n_dates].
    priced: list[PricedTrade] = []
    for raw_entry, raw_exit in intervals:
        entry_index = raw_entry % n_dates
        # exit strictly after entry, capped at n_dates (one past the last date).
        span_after_entry = n_dates - entry_index
        exit_index = entry_index + 1 + (raw_exit % span_after_entry)
        priced.append(
            _priced_trade(0.01, entry_index=entry_index, exit_index=exit_index)
        )

    # Reference: independently build the set of covered Price_Series dates where
    # any trade has entry_date <= d < exit_date. Uses the same _iso_date span so
    # each open day is counted exactly once regardless of overlaps.
    span_dates = {point.date for point in price_series}
    open_dates = {
        date
        for date in span_dates
        for pt in priced
        if pt.trade.entry_date <= date < pt.trade.exit_date
    }
    expected = len(open_dates) / len(span_dates)

    result = time_in_market(priced, price_series)

    # Req 14.6 / 14.7: equals covered-days / total-days and lies in [0, 1].
    assert math.isclose(result, expected, abs_tol=1e-9)
    assert 0.0 <= result <= 1.0


# Feature: vpa-strategy-backtest-report, Property 14: Time in market counts each open day once and lies in [0, 1]  # noqa: E501
@settings(max_examples=100)
@given(
    n_dates=st.integers(min_value=2, max_value=40),
    entry_index=st.integers(min_value=0),
    length=st.integers(min_value=1),
)
def test_property_14_overlapping_stacking_trades_not_double_counted(
    n_dates: int,
    entry_index: int,
    length: int,
) -> None:
    """Duplicated/overlapping STACKING trades do not inflate Time_In_Market.

    Booking the same open interval three times (a STACKING-style overlap) covers
    exactly the same Price_Series dates as booking it once, so ``time_in_market``
    is identical for the single-trade and triple-stacked-trade cases.

    Validates: Requirements 14.6, 14.7.
    """
    entry = entry_index % (n_dates - 1)
    exit_index = entry + 1 + (length % (n_dates - entry - 1) if n_dates - entry - 1 > 0 else 0)
    exit_index = min(exit_index if exit_index > entry else entry + 1, n_dates)

    price_series = make_price_series([100.0] * n_dates)

    single = [_priced_trade(0.01, entry_index=entry, exit_index=exit_index)]
    stacked = [
        _priced_trade(0.01, entry_index=entry, exit_index=exit_index),
        _priced_trade(0.02, entry_index=entry, exit_index=exit_index),
        _priced_trade(-0.01, entry_index=entry, exit_index=exit_index),
    ]

    # Overlapping trades cover the same dates, so each open day counts once.
    assert time_in_market(single, price_series) == time_in_market(stacked, price_series)

    expected = (exit_index - entry) / n_dates
    assert math.isclose(time_in_market(single, price_series), expected, abs_tol=1e-9)
    assert 0.0 <= time_in_market(stacked, price_series) <= 1.0
