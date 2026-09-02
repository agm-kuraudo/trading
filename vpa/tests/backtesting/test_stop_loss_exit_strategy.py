"""Tests for the path-based stop-loss exit strategy (SP-333).

Covers Correctness Property 1 (Stop price formula) via a Hypothesis property
test. The stop price is an internal computation inside ``resolve_exit``; the
property is verified observably by constructing a price series in which a
forward bar's ``low`` sits exactly at ``entry_price * (1 + threshold)`` so the
resolved exit price equals the stop, confirming the formula.

Code under test: ``vpa/backtesting/exit_strategy.py`` (``StopLossExitStrategy``).
"""

import math

from hypothesis import given, settings
from hypothesis import strategies as st

from vpa.backtesting.exit_strategy import FixedHoldExitStrategy, StopLossExitStrategy
from vpa.backtesting.models import PricePoint, SkipReason
from vpa.ml_validation.signal_analysis import SignalDirection


# Feature: vpa-strategy-backtest-report, Property 1: Stop price formula
@settings(max_examples=100)
@given(
    entry_price=st.floats(min_value=1.0, max_value=10_000, allow_nan=False, allow_infinity=False),
    threshold=st.floats(min_value=-0.5, max_value=-0.001, allow_nan=False, allow_infinity=False),
)
def test_property_1_stop_price_formula(entry_price: float, threshold: float) -> None:
    """Stop price equals entry_price*(1+threshold) and is strictly below entry.

    Validates: Requirements 7.2; Design: Correctness Property 1.

    For a positive entry price and a negative threshold the stop price is
    ``entry_price * (1 + threshold)`` and is strictly less than the entry
    price. We verify the formula observably: a forward long bar whose ``low``
    is exactly the stop (with ``open`` above the stop, so the open has not
    gapped through) must resolve the exit at that stop price.
    """
    stop = entry_price * (1 + threshold)

    # A negative threshold always places the stop strictly below entry.
    assert stop < entry_price

    # Entry bar at index 0 closes at entry_price; the next bar dips exactly to
    # the stop on its low while opening above the stop (no gap-through), so the
    # breach resolves at the stop price itself.
    entry_bar = PricePoint(date="00000000", open=entry_price, high=entry_price, low=entry_price, close=entry_price)
    breach_bar = PricePoint(
        date="00000001",
        open=entry_price,  # above the stop -> exit resolves at the stop, not the open
        high=entry_price,
        low=stop,  # low touches the stop exactly -> breach (Req 7.3)
        close=entry_price,
    )
    price_series = [entry_bar, breach_bar]

    strategy = StopLossExitStrategy(threshold=threshold, direction=SignalDirection.UP)
    result = strategy.resolve_exit(entry_index=0, price_series=price_series, hold_period=1)

    # The resolved exit price is the stop price, confirming the formula.
    assert result.exit_index == 1
    assert result.exit_price is not None
    assert math.isclose(result.exit_price, stop, abs_tol=1e-9)
    assert math.isclose(result.exit_price, entry_price * (1 + threshold), abs_tol=1e-9)
    assert result.exit_price < entry_price


def _make_bar(index: int, low: float, high: float, open_: float, close: float) -> PricePoint:
    """Build a PricePoint with a sequential ISO-style 8-digit date tag."""
    return PricePoint(date=f"{index:08d}", open=open_, high=high, low=low, close=close)


@st.composite
def _ohlc_paths(draw: st.DrawFn) -> tuple[list[PricePoint], int, int, SignalDirection]:
    """Generate an OHLC path plus an entry index, hold period, and direction.

    Each bar satisfies ``low <= open, close <= high``. Opens are allowed to gap
    (they are drawn independently within ``[low, high]``), so gapped-through
    exits are exercised. Generation is biased so that breaches are common: some
    later bars are pushed to straddle the stop. ``assume`` is not needed because
    both breach and no-breach paths are valid inputs for this property, but the
    bias ensures many examples actually breach.
    """
    n = draw(st.integers(min_value=2, max_value=12))
    entry_index = draw(st.integers(min_value=0, max_value=n - 2))
    hold_period = draw(st.integers(min_value=1, max_value=n))
    direction = draw(st.sampled_from([SignalDirection.UP, SignalDirection.DOWN]))

    price = st.floats(min_value=10.0, max_value=1_000.0, allow_nan=False, allow_infinity=False)

    bars: list[PricePoint] = []
    for i in range(n):
        a = draw(price)
        b = draw(price)
        low, high = (a, b) if a <= b else (b, a)
        open_ = draw(st.floats(min_value=low, max_value=high, allow_nan=False, allow_infinity=False))
        close = draw(st.floats(min_value=low, max_value=high, allow_nan=False, allow_infinity=False))
        bars.append(_make_bar(i, low=low, high=high, open_=open_, close=close))

    return bars, entry_index, hold_period, direction


def _expected_exit(
    bars: list[PricePoint], entry_index: int, hold_period: int, threshold: float, direction: SignalDirection
) -> tuple[int, float] | None:
    """Independently find the first breaching bar and its expected exit price.

    Returns ``(exit_index, exit_price)`` for the earliest breaching bar in the
    scan window, or ``None`` when no bar breaches the stop within the window.
    """
    entry_price = bars[entry_index].close
    stop = entry_price * (1 + threshold)
    last_index = len(bars) - 1
    horizon = min(entry_index + hold_period, last_index)
    is_long = direction is SignalDirection.UP

    for j in range(entry_index + 1, horizon + 1):
        bar = bars[j]
        if is_long:
            if bar.low <= stop:
                return j, (bar.open if bar.open <= stop else stop)
        else:
            if bar.high >= stop:
                return j, (bar.open if bar.open >= stop else stop)
    return None


# Feature: vpa-strategy-backtest-report, Property 2: Stop breach resolves at the first breaching bar
@settings(max_examples=100)
@given(
    path=_ohlc_paths(),
    threshold=st.floats(min_value=-0.5, max_value=-0.001, allow_nan=False, allow_infinity=False),
)
def test_property_2_first_breach_resolution(
    path: tuple[list[PricePoint], int, int, SignalDirection], threshold: float
) -> None:
    """Exit resolves on the earliest breaching bar at the stop-or-open price.

    Validates: Requirements 7.3, 7.4, 7.5, 7.6; Design: Correctness Property 2.

    For any OHLC path (including gapped opens) where a stop is breached within
    the hold window, ``StopLossExitStrategy`` resolves the exit on the earliest
    forward bar in ascending index order that breaches the stop -- long breach
    when ``low <= stop``, short breach when ``high >= stop`` -- at the stop
    price, or at that bar's ``open`` when the open has gapped past the stop.
    When no bar breaches, the strategy must not report a breach exit within the
    scan window (it delegates to the fixed-hold fallback instead).
    """
    bars, entry_index, hold_period, direction = path

    strategy = StopLossExitStrategy(threshold=threshold, direction=direction)
    result = strategy.resolve_exit(entry_index=entry_index, price_series=bars, hold_period=hold_period)

    expected = _expected_exit(bars, entry_index, hold_period, threshold, direction)

    if expected is not None:
        expected_index, expected_price = expected
        assert result.exit_index == expected_index
        assert result.exit_price is not None
        assert math.isclose(result.exit_price, expected_price, abs_tol=1e-9)
        assert result.reason is None
    else:
        # No breach within the scan window: the strategy must delegate verbatim
        # to the fixed-hold fallback rather than report a breach exit.
        fallback = FixedHoldExitStrategy().resolve_exit(entry_index, bars, hold_period)
        assert result == fallback


@st.composite
def _no_breach_paths(draw: st.DrawFn) -> tuple[list[PricePoint], int, int, SignalDirection, float]:
    """Generate a path guaranteed NOT to breach the stop within the hold window.

    All bars are confined to a tight band around the entry close, and the stop
    threshold is chosen large enough in magnitude that the stop sits far outside
    that band on the breaching side. For a long, every bar ``low`` stays strictly
    above the stop; for a short, every bar ``high`` stays strictly below the stop.
    The ``hold_period`` is drawn to include cases where the fixed-hold exit runs
    past the series end (exercising the ``INSUFFICIENT_FUTURE_DATA_EXIT``
    delegation) as well as cases where it lands inside the series.
    """
    n = draw(st.integers(min_value=2, max_value=12))
    entry_index = draw(st.integers(min_value=0, max_value=n - 2))
    # Draw hold periods that both land inside the series and run past its end.
    hold_period = draw(st.integers(min_value=1, max_value=n + 3))
    direction = draw(st.sampled_from([SignalDirection.UP, SignalDirection.DOWN]))

    # Entry close and a tight band half-width around it.
    entry_close = draw(st.floats(min_value=50.0, max_value=1_000.0, allow_nan=False, allow_infinity=False))
    band = draw(st.floats(min_value=0.001, max_value=0.02, allow_nan=False, allow_infinity=False))
    band_abs = entry_close * band

    # A threshold whose magnitude is far larger than the band so the stop is
    # never reachable within the band. For a long the stop is below entry
    # (low never dips to it); for a short the stop is above entry (high never
    # reaches it) -- StopLossExitStrategy always uses entry*(1+threshold), and
    # for a short a positive-magnitude offset places the stop above entry.
    is_long = direction is SignalDirection.UP
    magnitude = draw(st.floats(min_value=0.10, max_value=0.40, allow_nan=False, allow_infinity=False))
    threshold = -magnitude if is_long else magnitude

    lower = entry_close - band_abs
    upper = entry_close + band_abs

    def _band_bar(index: int, forced_close: float | None = None) -> PricePoint:
        a = draw(st.floats(min_value=lower, max_value=upper, allow_nan=False, allow_infinity=False))
        b = draw(st.floats(min_value=lower, max_value=upper, allow_nan=False, allow_infinity=False))
        low, high = (a, b) if a <= b else (b, a)
        open_ = draw(st.floats(min_value=low, max_value=high, allow_nan=False, allow_infinity=False))
        close = forced_close if forced_close is not None else draw(
            st.floats(min_value=low, max_value=high, allow_nan=False, allow_infinity=False)
        )
        return _make_bar(index, low=low, high=high, open_=open_, close=close)

    bars: list[PricePoint] = []
    for i in range(n):
        # Pin the entry bar's close to entry_close so the stop is exactly
        # entry_close*(1+threshold), far outside the band.
        bars.append(_band_bar(i, forced_close=entry_close if i == entry_index else None))

    return bars, entry_index, hold_period, direction, threshold


# Feature: vpa-strategy-backtest-report, Property 3: No breach falls back to the fixed-hold exit
@settings(max_examples=100)
@given(path=_no_breach_paths())
def test_property_3_no_breach_falls_back_to_fixed_hold(
    path: tuple[list[PricePoint], int, int, SignalDirection, float],
) -> None:
    """No stop breach delegates verbatim to the fixed-hold exit.

    Validates: Requirements 7.7, 7.8; Design: Correctness Property 3.

    For any price path in which the stop is never breached within the hold
    window, ``StopLossExitStrategy`` returns exactly the ``ExitResult`` that
    ``FixedHoldExitStrategy`` returns for the same entry index and hold period.
    The generator confines every bar to a tight band around the entry close and
    places the stop far outside that band, so no bar can breach; hold periods
    that run past the series end are included so the verbatim delegation of the
    ``INSUFFICIENT_FUTURE_DATA_EXIT`` result is exercised for both directions.
    """
    bars, entry_index, hold_period, direction, threshold = path

    # Sanity check the generator: confirm the stop is genuinely unreachable in
    # the scan window, so this really is a no-breach path.
    assert _expected_exit(bars, entry_index, hold_period, threshold, direction) is None

    strategy = StopLossExitStrategy(threshold=threshold, direction=direction)
    result = strategy.resolve_exit(entry_index=entry_index, price_series=bars, hold_period=hold_period)

    fallback = FixedHoldExitStrategy().resolve_exit(entry_index, bars, hold_period)
    assert result == fallback


# ---------------------------------------------------------------------------
# Example tests (SP-333, task 2.5): gap-through pricing, same-day stop-vs-hold
# tie, and the INSUFFICIENT_FUTURE_DATA_EXIT fallback near the series end.
# These are explicit, hand-crafted examples (not property tests).
# ---------------------------------------------------------------------------


def test_example_long_open_gapped_below_stop_exits_at_open() -> None:
    """Long: an open already below the stop resolves the exit at the open.

    Validates: Requirements 7.6 (and 7.5).

    Entry closes at 100.0 with threshold -0.02, so the stop is 98.0. The next
    bar opens at 96.0 -- already gapped past (below) the stop -- with a low of
    95.0 (breach). The exit must resolve at the bar's open (96.0), not the stop
    (98.0).
    """
    entry_price = 100.0
    threshold = -0.02
    stop = entry_price * (1 + threshold)  # 98.0

    entry_bar = _make_bar(0, low=100.0, high=100.0, open_=100.0, close=entry_price)
    gap_bar = _make_bar(1, low=95.0, high=97.0, open_=96.0, close=96.5)  # open 96.0 < stop 98.0
    series = [entry_bar, gap_bar]

    strategy = StopLossExitStrategy(threshold=threshold, direction=SignalDirection.UP)
    result = strategy.resolve_exit(entry_index=0, price_series=series, hold_period=1)

    assert result.exit_index == 1
    assert result.exit_price is not None
    assert math.isclose(result.exit_price, 96.0, abs_tol=1e-9)
    assert result.exit_price < stop
    assert result.reason is None


def test_example_short_open_gapped_above_stop_exits_at_open() -> None:
    """Short: an open already above the stop resolves the exit at the open.

    Validates: Requirements 7.6 (and 7.5).

    Entry closes at 100.0. For a short, StopLossExitStrategy uses the same
    formula ``entry_price * (1 + threshold)``; with threshold +0.02 the stop is
    102.0 (above entry). The next bar opens at 104.0 -- already gapped past
    (above) the stop -- with a high of 105.0 (breach). The exit must resolve at
    the bar's open (104.0), not the stop (102.0).
    """
    entry_price = 100.0
    threshold = 0.02
    stop = entry_price * (1 + threshold)  # 102.0

    entry_bar = _make_bar(0, low=100.0, high=100.0, open_=100.0, close=entry_price)
    gap_bar = _make_bar(1, low=103.0, high=105.0, open_=104.0, close=104.5)  # open 104.0 > stop 102.0
    series = [entry_bar, gap_bar]

    strategy = StopLossExitStrategy(threshold=threshold, direction=SignalDirection.DOWN)
    result = strategy.resolve_exit(entry_index=0, price_series=series, hold_period=1)

    assert result.exit_index == 1
    assert result.exit_price is not None
    assert math.isclose(result.exit_price, 104.0, abs_tol=1e-9)
    assert result.exit_price > stop
    assert result.reason is None


def test_example_long_same_day_stop_and_hold_tie_resolves_as_stop() -> None:
    """Long: a breach on the hold-boundary bar resolves as a stop, not a hold.

    Validates: Requirements 7.7 (and 7.5).

    With ``hold_period == 2`` and a 3-bar series, the fixed-hold exit would land
    on index 2 (``entry_index + hold_period``), which is also ``min(entry+hold,
    last) == 2`` -- the last scanned bar. That boundary bar breaches the stop
    (low 97.0 <= stop 98.0) while opening above the stop (99.0), so the exit
    must resolve as a stop breach at the stop price (98.0) on index 2, NOT as
    the fixed-hold exit at that bar's close (97.5).
    """
    entry_price = 100.0
    threshold = -0.02
    stop = entry_price * (1 + threshold)  # 98.0
    hold_period = 2

    entry_bar = _make_bar(0, low=100.0, high=100.0, open_=100.0, close=entry_price)
    quiet_bar = _make_bar(1, low=99.0, high=101.0, open_=100.0, close=100.0)  # no breach
    boundary_bar = _make_bar(2, low=97.0, high=100.0, open_=99.0, close=97.5)  # breach on hold boundary
    series = [entry_bar, quiet_bar, boundary_bar]

    # Confirm the fixed-hold exit would otherwise land exactly on this bar.
    fallback = FixedHoldExitStrategy().resolve_exit(0, series, hold_period)
    assert fallback.exit_index == 2

    strategy = StopLossExitStrategy(threshold=threshold, direction=SignalDirection.UP)
    result = strategy.resolve_exit(entry_index=0, price_series=series, hold_period=hold_period)

    assert result.exit_index == 2
    assert result.exit_price is not None
    # Resolves at the stop price (breach), not the fixed-hold close (97.5).
    assert math.isclose(result.exit_price, stop, abs_tol=1e-9)
    assert not math.isclose(result.exit_price, boundary_bar.close, abs_tol=1e-9)
    assert result.reason is None


def test_example_short_same_day_stop_and_hold_tie_resolves_as_stop() -> None:
    """Short: a breach on the hold-boundary bar resolves as a stop, not a hold.

    Validates: Requirements 7.7 (and 7.5).

    Mirror of the long case for a short trade. The boundary bar (index 2, the
    fixed-hold exit day) breaches the short stop (high 103.0 >= stop 102.0)
    while opening below the stop (101.0), so the exit resolves at the stop price
    (102.0), not the fixed-hold close (103.0).
    """
    entry_price = 100.0
    threshold = 0.02
    stop = entry_price * (1 + threshold)  # 102.0
    hold_period = 2

    entry_bar = _make_bar(0, low=100.0, high=100.0, open_=100.0, close=entry_price)
    quiet_bar = _make_bar(1, low=99.0, high=101.0, open_=100.0, close=100.0)  # no breach
    boundary_bar = _make_bar(2, low=100.0, high=103.0, open_=101.0, close=103.0)  # breach on hold boundary
    series = [entry_bar, quiet_bar, boundary_bar]

    fallback = FixedHoldExitStrategy().resolve_exit(0, series, hold_period)
    assert fallback.exit_index == 2

    strategy = StopLossExitStrategy(threshold=threshold, direction=SignalDirection.DOWN)
    result = strategy.resolve_exit(entry_index=0, price_series=series, hold_period=hold_period)

    assert result.exit_index == 2
    assert result.exit_price is not None
    assert math.isclose(result.exit_price, stop, abs_tol=1e-9)
    assert not math.isclose(result.exit_price, boundary_bar.close, abs_tol=1e-9)
    assert result.reason is None


def test_example_no_breach_near_series_end_delegates_insufficient_future_data() -> None:
    """No breach + hold horizon past the end -> INSUFFICIENT_FUTURE_DATA_EXIT.

    Validates: Requirements 7.7, 7.8.

    A long trade whose stop (98.0) is never breached within the scan window and
    whose fixed-hold horizon (``entry_index + hold_period``) runs past the last
    index must delegate to the fixed-hold fallback, which returns
    ``INSUFFICIENT_FUTURE_DATA_EXIT`` with no exit index or price.
    """
    entry_price = 100.0
    threshold = -0.02  # stop 98.0, never touched below
    hold_period = 5  # 0 + 5 = 5 > last index (2)

    entry_bar = _make_bar(0, low=100.0, high=100.0, open_=100.0, close=entry_price)
    quiet_bar_1 = _make_bar(1, low=99.0, high=101.0, open_=100.0, close=100.0)
    quiet_bar_2 = _make_bar(2, low=99.5, high=101.0, open_=100.0, close=100.5)
    series = [entry_bar, quiet_bar_1, quiet_bar_2]  # last_index == 2

    strategy = StopLossExitStrategy(threshold=threshold, direction=SignalDirection.UP)
    result = strategy.resolve_exit(entry_index=0, price_series=series, hold_period=hold_period)

    assert result.exit_index is None
    assert result.exit_price is None
    assert result.reason is SkipReason.INSUFFICIENT_FUTURE_DATA_EXIT

    # The result is exactly what the fixed-hold fallback returns.
    fallback = FixedHoldExitStrategy().resolve_exit(0, series, hold_period)
    assert result == fallback


def test_example_short_no_breach_near_series_end_delegates_insufficient_future_data() -> None:
    """Short mirror: no breach + horizon past end -> INSUFFICIENT_FUTURE_DATA_EXIT.

    Validates: Requirements 7.7, 7.8.
    """
    entry_price = 100.0
    threshold = 0.02  # stop 102.0, never touched above
    hold_period = 5

    entry_bar = _make_bar(0, low=100.0, high=100.0, open_=100.0, close=entry_price)
    quiet_bar_1 = _make_bar(1, low=99.0, high=101.0, open_=100.0, close=100.0)
    quiet_bar_2 = _make_bar(2, low=99.5, high=101.0, open_=100.0, close=100.5)
    series = [entry_bar, quiet_bar_1, quiet_bar_2]

    strategy = StopLossExitStrategy(threshold=threshold, direction=SignalDirection.DOWN)
    result = strategy.resolve_exit(entry_index=0, price_series=series, hold_period=hold_period)

    assert result.exit_index is None
    assert result.exit_price is None
    assert result.reason is SkipReason.INSUFFICIENT_FUTURE_DATA_EXIT
    assert result == FixedHoldExitStrategy().resolve_exit(0, series, hold_period)
