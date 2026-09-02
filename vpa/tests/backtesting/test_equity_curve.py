"""Tests for daily equity-curve construction (SP-333).

Covers Correctness Property 6 (Equity-curve length and initial value invariant)
via a Hypothesis property test.

Code under test: ``vpa/backtesting/equity_curve.py``.
"""

import math

from hypothesis import given, settings
from hypothesis import strategies as st

from vpa.backtesting.equity_curve import build_equity_curve
from vpa.backtesting.models import PricedTrade, PricePoint, TradeRecord
from vpa.ml_validation.signal_analysis import SignalDirection, SignalType

_strategy_return = st.floats(min_value=-0.99, max_value=5.0, allow_nan=False, allow_infinity=False)


def _iso_date(index: int) -> str:
    """Return a distinct, ascending positional date string for the given index."""
    return f"{index:08d}"


def _make_price_series(count: int) -> list[PricePoint]:
    """Build a Price_Series with distinct ascending dates and positive prices."""
    series: list[PricePoint] = []
    for i in range(count):
        price = 100.0 + i
        series.append(
            PricePoint(date=_iso_date(i), open=price, high=price, low=price, close=price)
        )
    return series


def _make_priced_trade(exit_date: str, strategy_ret: float) -> PricedTrade:
    """Build a PricedTrade closing on ``exit_date`` with the given strategy return."""
    trade = TradeRecord(
        entry_date="00000000",
        exit_date=exit_date,
        entry_price=100.0,
        exit_price=100.0,
        return_pct=strategy_ret,
        signal_type=SignalType.STRONG_BULLISH,
    )
    return PricedTrade(trade=trade, direction=SignalDirection.UP, strategy_return=strategy_ret)


# Feature: vpa-strategy-backtest-report, Property 6: Equity-curve length and initial value invariant
@settings(max_examples=100)
@given(
    date_count=st.integers(min_value=1, max_value=60),
    trades=st.lists(
        st.tuples(
            # An exit_date always follows an entry_date, so no trade closes on the
            # first Price_Series date (index 0). The index may still fall on a later
            # Price_Series date or outside the series entirely.
            st.integers(min_value=1, max_value=200),
            _strategy_return,
        ),
        max_size=30,
    ),
)
def test_property_6_equity_curve_length_and_initial_value(
    date_count: int,
    trades: list[tuple[int, float]],
) -> None:
    """The curve has one point per Price_Series date, ascending, starting at 1.0.

    Validates: Requirements 9.1, 9.2, 9.6.
    """
    price_series = _make_price_series(date_count)
    priced_trades = [
        _make_priced_trade(_iso_date(exit_index), strategy_ret)
        for exit_index, strategy_ret in trades
    ]

    curve = build_equity_curve(price_series, priced_trades)

    # Req 9.6: exactly one point per Price_Series date.
    assert len(curve) == len(price_series)

    # Req 9.1: curve dates equal the Price_Series dates in ascending order.
    curve_dates = [point.date for point in curve]
    expected_dates = [point.date for point in price_series]
    assert curve_dates == expected_dates
    assert curve_dates == sorted(curve_dates)

    # Req 9.2: the first point's equity equals the starting capital of 1.0.
    assert math.isclose(curve[0].equity, 1.0, abs_tol=1e-9)

# Feature: vpa-strategy-backtest-report, Property 7: Same-day compounding is order-independent
@settings(max_examples=100)
@given(
    date_count=st.integers(min_value=2, max_value=40),
    data=st.data(),
)
def test_property_7_same_day_compounding_order_independent(
    date_count: int,
    data: st.DataObject,
) -> None:
    """Same-day compounding is order-independent and no-close days carry forward.

    Validates: Requirements 9.3, 9.4, 9.5.

    A cluster of trades sharing one ``exit_date`` is generated (plus optional
    trades closing on other dates). The equity curve is invariant under any
    permutation of the priced-trades list, the capital carried after the shared
    exit_date equals ``capital_before * product(1 + return_i)`` over the cluster,
    and every date with no closing trade carries the prior day's capital forward.
    """
    price_series = _make_price_series(date_count)

    # Pick a shared exit_date for the same-day cluster. exit_date always follows an
    # entry_date, so the earliest a trade may close is Price_Series index 1.
    cluster_index = data.draw(st.integers(min_value=1, max_value=date_count - 1))
    cluster_date = _iso_date(cluster_index)

    # Two or more trades closing on the shared date (exercises the same-day product).
    cluster_returns = data.draw(
        st.lists(_strategy_return, min_size=2, max_size=6),
    )
    # Optional extra trades closing on other valid dates.
    extra = data.draw(
        st.lists(
            st.tuples(st.integers(min_value=1, max_value=date_count - 1), _strategy_return),
            max_size=8,
        ),
    )

    priced_trades = [_make_priced_trade(cluster_date, r) for r in cluster_returns]
    priced_trades += [_make_priced_trade(_iso_date(i), r) for i, r in extra]

    curve = build_equity_curve(price_series, priced_trades)

    # Req 9.4: invariant under any permutation of the same-day (and all) trades.
    permuted = data.draw(st.permutations(priced_trades))
    permuted_curve = build_equity_curve(price_series, list(permuted))
    assert [p.date for p in permuted_curve] == [p.date for p in curve]
    for original, shuffled in zip(curve, permuted_curve, strict=True):
        assert math.isclose(original.equity, shuffled.equity, abs_tol=1e-9)

    equity_by_date = {point.date: point.equity for point in curve}
    dates = [point.date for point in price_series]

    # Req 9.3/9.4: capital after the shared exit_date equals capital_before times
    # the product of (1 + return) across the whole same-day cluster.
    cluster_pos = dates.index(cluster_date)
    capital_before_cluster = curve[cluster_pos - 1].equity
    cluster_multiplier = math.prod(1 + r for r in cluster_returns)
    # Include any extra trades that happen to close on the same shared date.
    for i, r in extra:
        if _iso_date(i) == cluster_date:
            cluster_multiplier *= 1 + r
    expected_after_cluster = capital_before_cluster * cluster_multiplier
    assert math.isclose(equity_by_date[cluster_date], expected_after_cluster, abs_tol=1e-9)

    # Req 9.5: dates with no closing trade carry the previous day's capital forward.
    closing_dates = {cluster_date}
    closing_dates.update(_iso_date(i) for i, _ in extra)
    for pos in range(1, len(dates)):
        if dates[pos] not in closing_dates:
            assert math.isclose(curve[pos].equity, curve[pos - 1].equity, abs_tol=1e-9)

# Feature: vpa-strategy-backtest-report, example test for the empty Price_Series case
def test_empty_price_series_yields_empty_curve() -> None:
    """An empty Price_Series produces an empty equity curve without error.

    Validates: Requirements 15.7.
    """
    # No trades: an empty Price_Series must yield an empty curve.
    assert build_equity_curve([], []) == []

    # Priced trades present but no dates to place them on: still empty, no error.
    priced_trades = [
        _make_priced_trade(_iso_date(1), 0.05),
        _make_priced_trade(_iso_date(2), -0.10),
    ]
    assert build_equity_curve([], priced_trades) == []
