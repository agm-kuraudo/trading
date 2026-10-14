"""Property and oracle tests for RecentExtremeExitStrategy (SP-354, Task 6).

One Hypothesis test per Correctness Property (Properties 1-9 from design.md)
plus a hand-computed oracle unit test (Task 6.10). The construction and
conformance tests live in ``test_recent_extreme_exit_strategy.py``; this file
exercises stop/target geometry, the forward scan, the fixed-hold fallback, the
skip cases, immutability, and determinism.

``direction`` on the strategy is GEOMETRY-ONLY: these tests assert on the
returned ``ExitResult`` fields (``exit_index``, ``exit_price``, ``stop_loss``,
``profit_target``, ``exit_reason``, ``reason``) and never on P&L sign.

Code under test: ``vpa/backtesting/exit_strategy.py``
(``RecentExtremeExitStrategy``).
"""

import copy
import math

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from vpa.backtesting.exit_strategy import FixedHoldExitStrategy, RecentExtremeExitStrategy
from vpa.backtesting.models import ExitReason, PricePoint, SkipReason
from vpa.ml_validation.signal_analysis import SignalDirection

ABS_TOL = 1e-9


def _make_bar(index: int, low: float, high: float, open_: float, close: float) -> PricePoint:
    """Build a PricePoint with a sequential 8-digit date tag (ascending dates)."""
    return PricePoint(date=f"{index:08d}", open=open_, high=high, low=low, close=close)


Config = tuple[list[PricePoint], int, int, SignalDirection, int, float, float]


@st.composite
def _valid_series(draw: st.DrawFn) -> Config:
    """Generate a valid ascending-date OHLC series plus a full config.

    Each bar satisfies ``low <= open, close <= high``. ``entry_index`` is drawn
    with at least ``lookback`` prior bars so a valid recent-extreme window
    exists (the unavailable-extreme region is exercised in Property 6). Opens
    are drawn independently inside ``[low, high]`` so gap-through paths occur
    naturally. Returns ``(bars, entry_index, hold_period, direction, lookback,
    reward_risk, buffer)``.
    """
    lookback = draw(st.integers(min_value=1, max_value=5))
    direction = draw(st.sampled_from([SignalDirection.UP, SignalDirection.DOWN]))
    reward_risk = draw(st.floats(min_value=0.25, max_value=5.0, allow_nan=False, allow_infinity=False))
    buffer = draw(st.floats(min_value=0.0, max_value=5.0, allow_nan=False, allow_infinity=False))

    n = draw(st.integers(min_value=lookback + 2, max_value=lookback + 10))
    entry_index = draw(st.integers(min_value=lookback, max_value=n - 2))
    hold_period = draw(st.integers(min_value=1, max_value=n))

    price = st.floats(min_value=10.0, max_value=1_000.0, allow_nan=False, allow_infinity=False)
    bars: list[PricePoint] = []
    for i in range(n):
        a = draw(price)
        b = draw(price)
        low, high = (a, b) if a <= b else (b, a)
        open_ = draw(st.floats(min_value=low, max_value=high, allow_nan=False, allow_infinity=False))
        close = draw(st.floats(min_value=low, max_value=high, allow_nan=False, allow_infinity=False))
        bars.append(_make_bar(i, low=low, high=high, open_=open_, close=close))

    return bars, entry_index, hold_period, direction, lookback, reward_risk, buffer


def _geometry(bars: list[PricePoint], entry_index: int, lookback: int, direction: SignalDirection, buffer: float):
    """Independently compute (extreme, stop) over the strict prior-L window."""
    window = bars[entry_index - lookback : entry_index]
    if direction is SignalDirection.UP:
        extreme = min(bar.low for bar in window)
        stop = extreme - buffer
    else:
        extreme = max(bar.high for bar in window)
        stop = extreme + buffer
    return extreme, stop


# Feature: sp-354-recent-extreme-stop-target, Property 1: Recent-extreme stop geometry: UP stop = min(low) over
# price_series[entry_index-L:entry_index] minus buffer; DOWN stop = max(high) over the same window plus buffer.
@settings(max_examples=100)
@given(data=_valid_series())
def test_property_1_recent_extreme_stop_geometry(data: Config) -> None:
    """Stop equals the strict prior-L extreme offset by the buffer, per direction.

    Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 2.6.

    Over the window of the ``L`` bars strictly before entry, UP places the stop
    at ``min(low) - buffer`` and DOWN at ``max(high) + buffer`` (buffer 0 => stop
    exactly at the extreme, Req 2.6). The stop is read off the returned
    ``ExitResult.stop_loss``; skip results carry no geometry, so they are
    excluded via ``assume``.
    """
    bars, entry_index, hold_period, direction, lookback, reward_risk, buffer = data
    strategy = RecentExtremeExitStrategy(lookback=lookback, reward_risk=reward_risk, buffer=buffer, direction=direction)
    result = strategy.resolve_exit(entry_index=entry_index, price_series=bars, hold_period=hold_period)

    # Only non-skip results carry geometry; degenerate configs skip (Property 7).
    assume(result.reason is None)

    _, expected_stop = _geometry(bars, entry_index, lookback, direction, buffer)
    assert result.stop_loss is not None
    assert math.isclose(result.stop_loss, expected_stop, abs_tol=ABS_TOL)


# Feature: sp-354-recent-extreme-stop-target, Property 2: Risk distance = abs(entry_price-stop) with
# entry_price=close[entry_index]; target = entry+risk*M (UP) / entry-risk*M (DOWN).
@settings(max_examples=100)
@given(data=_valid_series())
def test_property_2_risk_distance_and_profit_target(data: Config) -> None:
    """Target is derived from risk distance by the reward-risk multiplier.

    Validates: Requirements 4.1, 4.2, 4.3.

    With ``entry_price = close[entry_index]`` and ``risk = abs(entry_price -
    stop)``, the profit target is ``entry_price + risk * M`` for UP and
    ``entry_price - risk * M`` for DOWN. Verified against the ``stop_loss`` and
    ``profit_target`` on the returned ``ExitResult`` (non-skip results only).
    """
    bars, entry_index, hold_period, direction, lookback, reward_risk, buffer = data
    strategy = RecentExtremeExitStrategy(lookback=lookback, reward_risk=reward_risk, buffer=buffer, direction=direction)
    result = strategy.resolve_exit(entry_index=entry_index, price_series=bars, hold_period=hold_period)

    assume(result.reason is None)
    assert result.stop_loss is not None
    assert result.profit_target is not None

    entry_price = bars[entry_index].close
    risk = abs(entry_price - result.stop_loss)
    if direction is SignalDirection.UP:
        expected_target = entry_price + risk * reward_risk
    else:
        expected_target = entry_price - risk * reward_risk

    assert math.isclose(result.profit_target, expected_target, abs_tol=ABS_TOL)


def _oracle_scan(
    bars: list[PricePoint],
    entry_index: int,
    hold_period: int,
    direction: SignalDirection,
    stop: float,
    target: float,
) -> tuple[int, float, ExitReason] | None:
    """Independent forward-scan oracle: first breach wins, stop-first on a tie."""
    last_index = len(bars) - 1
    horizon = min(entry_index + hold_period, last_index)
    is_long = direction is SignalDirection.UP
    for j in range(entry_index + 1, horizon + 1):
        bar = bars[j]
        if is_long:
            if bar.low <= stop:
                return j, (bar.open if bar.open <= stop else stop), ExitReason.STOP
            if bar.high >= target:
                return j, (bar.open if bar.open >= target else target), ExitReason.TARGET
        else:
            if bar.high >= stop:
                return j, (bar.open if bar.open >= stop else stop), ExitReason.STOP
            if bar.low <= target:
                return j, (bar.open if bar.open <= target else target), ExitReason.TARGET
    return None


# Feature: sp-354-recent-extreme-stop-target, Property 3: First breach wins; when one bar breaches both stop and
# target the exit resolves as a Stop_Loss breach (stop-first same-bar precedence).
@settings(max_examples=100)
@given(data=_valid_series())
def test_property_3_first_breach_wins_stop_first(data: Config) -> None:
    """Exit resolves on the earliest breaching bar; a both-breach bar is a STOP.

    Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 9.3.

    An independent oracle scans the window ``entry_index+1 ..
    min(entry_index+hold_period, last_index)`` with the same stop-first
    precedence and must agree with the strategy on ``exit_index``,
    ``exit_price``, and ``exit_reason``. When the oracle finds no breach the
    strategy must not report STOP/TARGET (it falls back; covered by Property 5).
    """
    bars, entry_index, hold_period, direction, lookback, reward_risk, buffer = data
    strategy = RecentExtremeExitStrategy(lookback=lookback, reward_risk=reward_risk, buffer=buffer, direction=direction)
    result = strategy.resolve_exit(entry_index=entry_index, price_series=bars, hold_period=hold_period)

    assume(result.reason is None and result.exit_reason is not ExitReason.FIXED_HOLD)

    _, stop = _geometry(bars, entry_index, lookback, direction, buffer)
    entry_price = bars[entry_index].close
    risk = abs(entry_price - stop)
    assume(risk != 0)
    if direction is SignalDirection.UP:
        assume(stop < entry_price)
        target = entry_price + risk * reward_risk
    else:
        assume(stop > entry_price)
        target = entry_price - risk * reward_risk

    expected = _oracle_scan(bars, entry_index, hold_period, direction, stop, target)
    assume(expected is not None)
    exp_index, exp_price, exp_reason = expected

    assert result.exit_index == exp_index
    assert result.exit_price is not None
    assert math.isclose(result.exit_price, exp_price, abs_tol=ABS_TOL)
    assert result.exit_reason is exp_reason


@st.composite
def _breach_path(draw: st.DrawFn):
    """Build a series with a known stop/target and a forced first-breach bar.

    A single prior bar (the lookback-1 window) fixes the extreme, so the stop is
    exactly known. The entry bar's close fixes the entry price and hence the
    target. Bars between entry and the breach bar are held strictly inside the
    (stop, target) band so they never breach. The breach bar is then shaped to
    breach either the stop or the target, with its open either gapping through
    the level or sitting on the non-gap side. Returns ``(bars, entry_index,
    hold_period, direction, lookback, reward_risk, buffer, which, gap)``.
    """
    direction = draw(st.sampled_from([SignalDirection.UP, SignalDirection.DOWN]))
    which = draw(st.sampled_from(["stop", "target"]))
    gap = draw(st.booleans())
    reward_risk = draw(st.floats(min_value=1.0, max_value=4.0, allow_nan=False, allow_infinity=False))
    buffer = 0.0
    lookback = 1
    is_long = direction is SignalDirection.UP

    entry_price = draw(st.floats(min_value=100.0, max_value=500.0, allow_nan=False, allow_infinity=False))
    risk = draw(st.floats(min_value=5.0, max_value=40.0, allow_nan=False, allow_infinity=False))

    if is_long:
        stop = entry_price - risk  # extreme = min(low) of prior bar = stop (buffer 0)
        target = entry_price + risk * reward_risk
        prior = _make_bar(0, low=stop, high=stop + 1.0, open_=stop + 0.5, close=stop + 0.5)
    else:
        stop = entry_price + risk  # extreme = max(high) of prior bar = stop (buffer 0)
        target = entry_price - risk * reward_risk
        prior = _make_bar(0, low=stop - 1.0, high=stop, open_=stop - 0.5, close=stop - 0.5)

    entry_bar = _make_bar(1, low=entry_price, high=entry_price, open_=entry_price, close=entry_price)

    # Quiet filler bars strictly inside the band (stop, target), no breach.
    n_quiet = draw(st.integers(min_value=0, max_value=3))
    lo_band = min(stop, target)
    hi_band = max(stop, target)
    mid = (lo_band + hi_band) / 2.0
    span = (hi_band - lo_band) / 6.0
    quiet = [_make_bar(2 + k, low=mid - span, high=mid + span, open_=mid, close=mid) for k in range(n_quiet)]

    breach_idx = 2 + n_quiet
    if which == "stop":
        if is_long:
            # low <= stop. open gaps below stop or sits above it.
            open_ = stop - 3.0 if gap else stop + 2.0
            open_ = min(open_, target - 0.5)  # keep open below target so no target first
            bar = _make_bar(breach_idx, low=stop - 5.0, high=max(open_, stop) + 0.1, open_=open_, close=stop - 1.0)
        else:
            open_ = stop + 3.0 if gap else stop - 2.0
            open_ = max(open_, target + 0.5)
            bar = _make_bar(breach_idx, low=min(open_, stop) - 0.1, high=stop + 5.0, open_=open_, close=stop + 1.0)
    else:  # target breach, and NOT a stop breach on the same bar
        if is_long:
            open_ = target + 3.0 if gap else target - 2.0
            open_ = max(open_, stop + 0.5)  # keep open above stop so stop not breached
            bar = _make_bar(
                breach_idx, low=min(open_, target) - 0.1, high=target + 5.0, open_=open_, close=target + 1.0
            )
        else:
            open_ = target - 3.0 if gap else target + 2.0
            open_ = min(open_, stop - 0.5)
            bar = _make_bar(
                breach_idx, low=target - 5.0, high=max(open_, target) + 0.1, open_=open_, close=target - 1.0
            )

    bars = [prior, entry_bar, *quiet, bar]
    entry_index = 1
    hold_period = len(bars)  # covers the breach bar
    return bars, entry_index, hold_period, direction, lookback, reward_risk, buffer, which, gap, stop, target


# Feature: sp-354-recent-extreme-stop-target, Property 4: Gap-through-at-open exit pricing: exit_price = bar.open
# when the open has gapped past the breached level, else the level itself, for BOTH stop and target breaches.
@settings(max_examples=100)
@given(data=_breach_path())
def test_property_4_gap_through_at_open_pricing(data) -> None:
    """A gapped open prices at the open; otherwise at the breached level.

    Validates: Requirements 5.7, 5.8.

    For a bar that breaches the stop (or target), the exit price is the bar's
    ``open`` when the open has already gapped through the level, and the level
    itself otherwise -- for both the stop side (5.7) and the target side (5.8),
    in both directions.
    """
    bars, entry_index, hold_period, direction, lookback, reward_risk, buffer, which, gap, stop, target = data
    strategy = RecentExtremeExitStrategy(lookback=lookback, reward_risk=reward_risk, buffer=buffer, direction=direction)
    result = strategy.resolve_exit(entry_index=entry_index, price_series=bars, hold_period=hold_period)

    assert result.reason is None
    breach_bar = bars[result.exit_index]
    level = stop if which == "stop" else target
    expected_reason = ExitReason.STOP if which == "stop" else ExitReason.TARGET
    assert result.exit_reason is expected_reason

    is_long = direction is SignalDirection.UP
    if which == "stop":
        gapped = breach_bar.open <= level if is_long else breach_bar.open >= level
    else:
        gapped = breach_bar.open >= level if is_long else breach_bar.open <= level

    expected_price = breach_bar.open if gapped else level
    assert result.exit_price is not None
    assert math.isclose(result.exit_price, expected_price, abs_tol=ABS_TOL)
    # Cross-check against the drawn ``gap`` intent.
    assert gapped == gap


@st.composite
def _no_breach_path(draw: st.DrawFn):
    """Build a series whose forward bars stay strictly inside the (stop,target) band.

    A single prior bar fixes the extreme (buffer 0) so the stop is known; the
    entry bar fixes the entry price and target. All forward bars are confined to
    a tight band strictly between stop and target, so neither level is ever
    breached and the strategy must fall back to fixed-hold. ``hold_period`` is
    drawn to both land inside the series and run past its end, exercising the
    ``INSUFFICIENT_FUTURE_DATA_EXIT`` passthrough. Returns ``(bars, entry_index,
    hold_period, direction, lookback, reward_risk, buffer)``.
    """
    direction = draw(st.sampled_from([SignalDirection.UP, SignalDirection.DOWN]))
    reward_risk = draw(st.floats(min_value=1.0, max_value=4.0, allow_nan=False, allow_infinity=False))
    buffer = 0.0
    lookback = 1
    is_long = direction is SignalDirection.UP

    entry_price = draw(st.floats(min_value=100.0, max_value=500.0, allow_nan=False, allow_infinity=False))
    risk = draw(st.floats(min_value=10.0, max_value=40.0, allow_nan=False, allow_infinity=False))

    if is_long:
        stop = entry_price - risk
        target = entry_price + risk * reward_risk
        prior = _make_bar(0, low=stop, high=stop + 1.0, open_=stop + 0.5, close=stop + 0.5)
    else:
        stop = entry_price + risk
        target = entry_price - risk * reward_risk
        prior = _make_bar(0, low=stop - 1.0, high=stop, open_=stop - 0.5, close=stop - 0.5)

    entry_bar = _make_bar(1, low=entry_price, high=entry_price, open_=entry_price, close=entry_price)

    lo_band = min(stop, target)
    hi_band = max(stop, target)
    pad = (hi_band - lo_band) * 0.2
    inner_lo = lo_band + pad
    inner_hi = hi_band - pad

    n_fwd = draw(st.integers(min_value=1, max_value=5))
    fwd: list[PricePoint] = []
    for k in range(n_fwd):
        a = draw(st.floats(min_value=inner_lo, max_value=inner_hi, allow_nan=False, allow_infinity=False))
        b = draw(st.floats(min_value=inner_lo, max_value=inner_hi, allow_nan=False, allow_infinity=False))
        low, high = (a, b) if a <= b else (b, a)
        open_ = draw(st.floats(min_value=low, max_value=high, allow_nan=False, allow_infinity=False))
        close = draw(st.floats(min_value=low, max_value=high, allow_nan=False, allow_infinity=False))
        fwd.append(_make_bar(2 + k, low=low, high=high, open_=open_, close=close))

    bars = [prior, entry_bar, *fwd]
    entry_index = 1
    # Both inside-series and past-end horizons.
    hold_period = draw(st.integers(min_value=1, max_value=len(bars) + 2))
    return bars, entry_index, hold_period, direction, lookback, reward_risk, buffer


# Feature: sp-354-recent-extreme-stop-target, Property 5: With no stop/target breach in the scan window, exit_index
# and exit_price equal FixedHoldExitStrategy.resolve_exit(same args) and exit_reason is FIXED_HOLD.
@settings(max_examples=100)
@given(data=_no_breach_path())
def test_property_5_no_breach_delegates_to_fixed_hold(data) -> None:
    """No breach delegates index/price to the fixed-hold fallback (reason FIXED_HOLD).

    Validates: Requirements 5.9.

    When neither level is breached, the strategy's ``exit_index`` and
    ``exit_price`` match ``FixedHoldExitStrategy.resolve_exit`` for the same
    arguments. For an in-series horizon ``exit_reason`` is FIXED_HOLD; for a
    horizon past the series end the fixed-hold result (an
    ``INSUFFICIENT_FUTURE_DATA_EXIT`` skip) is passed through verbatim.
    """
    bars, entry_index, hold_period, direction, lookback, reward_risk, buffer = data
    strategy = RecentExtremeExitStrategy(lookback=lookback, reward_risk=reward_risk, buffer=buffer, direction=direction)
    result = strategy.resolve_exit(entry_index=entry_index, price_series=bars, hold_period=hold_period)
    fallback = FixedHoldExitStrategy().resolve_exit(entry_index, bars, hold_period)

    assert result.exit_index == fallback.exit_index
    assert result.exit_price == fallback.exit_price

    if fallback.reason is not None:
        # Horizon past series end: passed through verbatim, no geometry extras.
        assert result == fallback
    else:
        assert result.reason is None
        assert result.exit_reason is ExitReason.FIXED_HOLD


@st.composite
def _unavailable_extreme_path(draw: st.DrawFn):
    """Generate configs where fewer than ``lookback`` bars precede the entry.

    ``entry_index < lookback`` guarantees ``entry_index - lookback < 0``.
    """
    lookback = draw(st.integers(min_value=1, max_value=6))
    entry_index = draw(st.integers(min_value=0, max_value=lookback - 1))
    direction = draw(st.sampled_from([SignalDirection.UP, SignalDirection.DOWN]))
    reward_risk = draw(st.floats(min_value=0.5, max_value=4.0, allow_nan=False, allow_infinity=False))
    buffer = draw(st.floats(min_value=0.0, max_value=3.0, allow_nan=False, allow_infinity=False))

    # Series long enough to hold the entry bar and a forward bar.
    n = draw(st.integers(min_value=entry_index + 2, max_value=entry_index + 8))
    hold_period = draw(st.integers(min_value=1, max_value=n))
    price = st.floats(min_value=10.0, max_value=1_000.0, allow_nan=False, allow_infinity=False)
    bars: list[PricePoint] = []
    for i in range(n):
        a = draw(price)
        b = draw(price)
        low, high = (a, b) if a <= b else (b, a)
        open_ = draw(st.floats(min_value=low, max_value=high, allow_nan=False, allow_infinity=False))
        close = draw(st.floats(min_value=low, max_value=high, allow_nan=False, allow_infinity=False))
        bars.append(_make_bar(i, low=low, high=high, open_=open_, close=close))
    return bars, entry_index, hold_period, direction, lookback, reward_risk, buffer


# Feature: sp-354-recent-extreme-stop-target, Property 6: entry_index - L < 0 returns ExitResult with
# SkipReason.UNAVAILABLE_RECENT_EXTREME and exit_index / exit_price unset.
@settings(max_examples=100)
@given(data=_unavailable_extreme_path())
def test_property_6_unavailable_recent_extreme_skips(data) -> None:
    """Too few prior bars yields an UNAVAILABLE_RECENT_EXTREME skip.

    Validates: Requirements 6.1.

    When ``entry_index - lookback < 0`` the recent-extreme window cannot be
    formed, so the strategy returns an ``ExitResult`` carrying
    ``SkipReason.UNAVAILABLE_RECENT_EXTREME`` with both ``exit_index`` and
    ``exit_price`` unset.
    """
    bars, entry_index, hold_period, direction, lookback, reward_risk, buffer = data
    strategy = RecentExtremeExitStrategy(lookback=lookback, reward_risk=reward_risk, buffer=buffer, direction=direction)
    result = strategy.resolve_exit(entry_index=entry_index, price_series=bars, hold_period=hold_period)

    assert result.reason is SkipReason.UNAVAILABLE_RECENT_EXTREME
    assert result.exit_index is None
    assert result.exit_price is None


@st.composite
def _degenerate_risk_path(draw: st.DrawFn):
    """Generate configs where the stop is non-adverse (zero or wrong-side risk).

    For UP the prior-window lowest low is forced to sit at or above the entry
    close (stop >= entry); for DOWN the highest high at or below it (stop <=
    entry). Buffer is 0 so the stop is exactly the extreme.
    """
    direction = draw(st.sampled_from([SignalDirection.UP, SignalDirection.DOWN]))
    reward_risk = draw(st.floats(min_value=0.5, max_value=4.0, allow_nan=False, allow_infinity=False))
    buffer = 0.0
    lookback = 1
    is_long = direction is SignalDirection.UP

    entry_price = draw(st.floats(min_value=100.0, max_value=500.0, allow_nan=False, allow_infinity=False))
    # offset >= 0: 0 => zero risk (stop == entry); > 0 => wrong-side stop.
    offset = draw(st.floats(min_value=0.0, max_value=30.0, allow_nan=False, allow_infinity=False))

    if is_long:
        extreme = entry_price + offset  # lowest low at/above entry -> stop >= entry
        prior = _make_bar(0, low=extreme, high=extreme + 1.0, open_=extreme + 0.5, close=extreme + 0.5)
    else:
        extreme = entry_price - offset  # highest high at/below entry -> stop <= entry
        prior = _make_bar(0, low=extreme - 1.0, high=extreme, open_=extreme - 0.5, close=extreme - 0.5)

    entry_bar = _make_bar(1, low=entry_price, high=entry_price, open_=entry_price, close=entry_price)
    fwd = _make_bar(2, low=entry_price - 1, high=entry_price + 1, open_=entry_price, close=entry_price)
    bars = [prior, entry_bar, fwd]
    return bars, 1, 3, direction, lookback, reward_risk, buffer


# Feature: sp-354-recent-extreme-stop-target, Property 7: risk == 0 or a non-adverse stop (>= entry for UP, <=
# entry for DOWN) returns SkipReason.DEGENERATE_RISK_DISTANCE with exit_index / exit_price unset.
@settings(max_examples=100)
@given(data=_degenerate_risk_path())
def test_property_7_degenerate_risk_distance_skips(data) -> None:
    """Zero or wrong-side risk yields a DEGENERATE_RISK_DISTANCE skip.

    Validates: Requirements 6.2, 6.3.

    When the computed risk distance is zero, or the stop sits on the non-adverse
    side of the entry price (``stop >= entry`` for UP, ``stop <= entry`` for
    DOWN), the strategy returns an ``ExitResult`` with
    ``SkipReason.DEGENERATE_RISK_DISTANCE`` and both ``exit_index`` and
    ``exit_price`` unset.
    """
    bars, entry_index, hold_period, direction, lookback, reward_risk, buffer = data
    strategy = RecentExtremeExitStrategy(lookback=lookback, reward_risk=reward_risk, buffer=buffer, direction=direction)
    result = strategy.resolve_exit(entry_index=entry_index, price_series=bars, hold_period=hold_period)

    assert result.reason is SkipReason.DEGENERATE_RISK_DISTANCE
    assert result.exit_index is None
    assert result.exit_price is None


# Feature: sp-354-recent-extreme-stop-target, Property 8: resolve_exit never mutates its inputs; the price_series
# and every PricePoint are deep-equal before and after the call.
@settings(max_examples=100)
@given(data=_valid_series())
def test_property_8_inputs_never_mutated(data: Config) -> None:
    """The price_series and its PricePoints are unchanged by resolve_exit.

    Validates: Requirements 1.5.

    A deep copy of the input series is captured before the call and compared
    element-by-element afterwards; nothing the strategy touches is mutated.
    """
    bars, entry_index, hold_period, direction, lookback, reward_risk, buffer = data
    before = copy.deepcopy(bars)
    strategy = RecentExtremeExitStrategy(lookback=lookback, reward_risk=reward_risk, buffer=buffer, direction=direction)
    strategy.resolve_exit(entry_index=entry_index, price_series=bars, hold_period=hold_period)

    assert bars == before
    for after_bar, before_bar in zip(bars, before, strict=True):
        assert after_bar == before_bar


# Feature: sp-354-recent-extreme-stop-target, Property 9: two resolve_exit calls with identical arguments and
# configuration return equal ExitResult values (determinism).
@settings(max_examples=100)
@given(data=_valid_series())
def test_property_9_determinism(data: Config) -> None:
    """Identical calls return equal ExitResults.

    Validates: Requirements 1.4, 1.6, 9.1.

    The strategy depends only on its configuration and the in-memory arguments,
    so two successive ``resolve_exit`` calls with identical inputs return equal
    ``ExitResult`` values.
    """
    bars, entry_index, hold_period, direction, lookback, reward_risk, buffer = data
    strategy = RecentExtremeExitStrategy(lookback=lookback, reward_risk=reward_risk, buffer=buffer, direction=direction)
    first = strategy.resolve_exit(entry_index=entry_index, price_series=bars, hold_period=hold_period)
    second = strategy.resolve_exit(entry_index=entry_index, price_series=bars, hold_period=hold_period)

    assert first == second


# ---------------------------------------------------------------------------
# Task 6.10: hand-computed oracle unit tests (Req 9.2, 9.3). Tiny fixed series
# with hand-computed exit_index / exit_price for stop breach, target breach, and
# fixed-hold fallback, in BOTH directions. All use lookback=2, buffer=0, M=2.
# ---------------------------------------------------------------------------


def test_oracle_long_stop_breach() -> None:
    """Long stop breach resolves at the stop on the first breaching bar.

    Validates: Requirements 9.2, 9.3.

    Prior lows 95, 97 -> extreme min 95 -> stop 95 (buffer 0). Entry close 100,
    risk 5, M 2 -> target 110. Bar 3 dips to low 94 (<= 95) while opening at 96
    (above the stop, no gap), so the exit is a STOP at 95 on index 3.
    """
    series = [
        _make_bar(0, low=95.0, high=99.0, open_=97.0, close=98.0),
        _make_bar(1, low=97.0, high=101.0, open_=99.0, close=100.0),
        _make_bar(2, low=98.0, high=102.0, open_=100.0, close=100.0),  # entry close 100
        _make_bar(3, low=94.0, high=101.0, open_=96.0, close=97.0),  # stop breach
    ]
    strategy = RecentExtremeExitStrategy(lookback=2, reward_risk=2.0, direction=SignalDirection.UP)
    result = strategy.resolve_exit(entry_index=2, price_series=series, hold_period=3)

    assert result.exit_index == 3
    assert math.isclose(result.exit_price, 95.0, abs_tol=ABS_TOL)
    assert result.exit_reason is ExitReason.STOP
    assert math.isclose(result.stop_loss, 95.0, abs_tol=ABS_TOL)
    assert math.isclose(result.profit_target, 110.0, abs_tol=ABS_TOL)
    assert result.reason is None


def test_oracle_long_target_breach() -> None:
    """Long target breach resolves at the target on the first breaching bar.

    Validates: Requirements 9.2, 9.3.

    Same geometry (stop 95, target 110). Bar 3 keeps its low at 99 (no stop
    breach) while its high reaches 112 (>= 110) and opens at 105 (below the
    target, no gap), so the exit is a TARGET at 110 on index 3.
    """
    series = [
        _make_bar(0, low=95.0, high=99.0, open_=97.0, close=98.0),
        _make_bar(1, low=97.0, high=101.0, open_=99.0, close=100.0),
        _make_bar(2, low=98.0, high=102.0, open_=100.0, close=100.0),  # entry close 100
        _make_bar(3, low=99.0, high=112.0, open_=105.0, close=111.0),  # target breach
    ]
    strategy = RecentExtremeExitStrategy(lookback=2, reward_risk=2.0, direction=SignalDirection.UP)
    result = strategy.resolve_exit(entry_index=2, price_series=series, hold_period=3)

    assert result.exit_index == 3
    assert math.isclose(result.exit_price, 110.0, abs_tol=ABS_TOL)
    assert result.exit_reason is ExitReason.TARGET
    assert math.isclose(result.stop_loss, 95.0, abs_tol=ABS_TOL)
    assert math.isclose(result.profit_target, 110.0, abs_tol=ABS_TOL)
    assert result.reason is None


def test_oracle_long_fixed_hold_fallback() -> None:
    """Long no-breach path falls back to the fixed-hold exit close.

    Validates: Requirements 9.2, 9.3.

    Same geometry (stop 95, target 110). Bars 3 and 4 stay inside (95, 110), so
    neither level breaches. With hold_period 2 from entry index 2 the fixed-hold
    exit lands on index 4 at its close (103.0), reason FIXED_HOLD.
    """
    series = [
        _make_bar(0, low=95.0, high=99.0, open_=97.0, close=98.0),
        _make_bar(1, low=97.0, high=101.0, open_=99.0, close=100.0),
        _make_bar(2, low=98.0, high=102.0, open_=100.0, close=100.0),  # entry close 100
        _make_bar(3, low=99.0, high=108.0, open_=101.0, close=102.0),  # in band
        _make_bar(4, low=100.0, high=109.0, open_=102.0, close=103.0),  # fixed-hold exit
    ]
    strategy = RecentExtremeExitStrategy(lookback=2, reward_risk=2.0, direction=SignalDirection.UP)
    result = strategy.resolve_exit(entry_index=2, price_series=series, hold_period=2)

    assert result.exit_index == 4
    assert math.isclose(result.exit_price, 103.0, abs_tol=ABS_TOL)
    assert result.exit_reason is ExitReason.FIXED_HOLD
    assert math.isclose(result.stop_loss, 95.0, abs_tol=ABS_TOL)
    assert math.isclose(result.profit_target, 110.0, abs_tol=ABS_TOL)
    assert result.reason is None


def test_oracle_short_stop_breach() -> None:
    """Short stop breach resolves at the stop on the first breaching bar.

    Validates: Requirements 9.2, 9.3.

    Prior highs 105, 103 -> extreme max 105 -> stop 105 (buffer 0). Entry close
    100, risk 5, M 2 -> target 90. Bar 3 rallies to high 106 (>= 105) while
    opening at 104 (below the stop, no gap), so the exit is a STOP at 105 on
    index 3.
    """
    series = [
        _make_bar(0, low=101.0, high=105.0, open_=103.0, close=102.0),
        _make_bar(1, low=99.0, high=103.0, open_=101.0, close=100.0),
        _make_bar(2, low=98.0, high=102.0, open_=100.0, close=100.0),  # entry close 100
        _make_bar(3, low=99.0, high=106.0, open_=104.0, close=103.0),  # stop breach
    ]
    strategy = RecentExtremeExitStrategy(lookback=2, reward_risk=2.0, direction=SignalDirection.DOWN)
    result = strategy.resolve_exit(entry_index=2, price_series=series, hold_period=3)

    assert result.exit_index == 3
    assert math.isclose(result.exit_price, 105.0, abs_tol=ABS_TOL)
    assert result.exit_reason is ExitReason.STOP
    assert math.isclose(result.stop_loss, 105.0, abs_tol=ABS_TOL)
    assert math.isclose(result.profit_target, 90.0, abs_tol=ABS_TOL)
    assert result.reason is None


def test_oracle_short_target_breach() -> None:
    """Short target breach resolves at the target on the first breaching bar.

    Validates: Requirements 9.2, 9.3.

    Same geometry (stop 105, target 90). Bar 3 keeps its high at 101 (no stop
    breach) while its low reaches 88 (<= 90) and opens at 95 (above the target,
    no gap), so the exit is a TARGET at 90 on index 3.
    """
    series = [
        _make_bar(0, low=101.0, high=105.0, open_=103.0, close=102.0),
        _make_bar(1, low=99.0, high=103.0, open_=101.0, close=100.0),
        _make_bar(2, low=98.0, high=102.0, open_=100.0, close=100.0),  # entry close 100
        _make_bar(3, low=88.0, high=101.0, open_=95.0, close=89.0),  # target breach
    ]
    strategy = RecentExtremeExitStrategy(lookback=2, reward_risk=2.0, direction=SignalDirection.DOWN)
    result = strategy.resolve_exit(entry_index=2, price_series=series, hold_period=3)

    assert result.exit_index == 3
    assert math.isclose(result.exit_price, 90.0, abs_tol=ABS_TOL)
    assert result.exit_reason is ExitReason.TARGET
    assert math.isclose(result.stop_loss, 105.0, abs_tol=ABS_TOL)
    assert math.isclose(result.profit_target, 90.0, abs_tol=ABS_TOL)
    assert result.reason is None


def test_oracle_short_fixed_hold_fallback() -> None:
    """Short no-breach path falls back to the fixed-hold exit close.

    Validates: Requirements 9.2, 9.3.

    Same geometry (stop 105, target 90). Bars 3 and 4 stay inside (90, 105), so
    neither level breaches. With hold_period 2 from entry index 2 the fixed-hold
    exit lands on index 4 at its close (97.0), reason FIXED_HOLD.
    """
    series = [
        _make_bar(0, low=101.0, high=105.0, open_=103.0, close=102.0),
        _make_bar(1, low=99.0, high=103.0, open_=101.0, close=100.0),
        _make_bar(2, low=98.0, high=102.0, open_=100.0, close=100.0),  # entry close 100
        _make_bar(3, low=92.0, high=101.0, open_=99.0, close=98.0),  # in band
        _make_bar(4, low=91.0, high=100.0, open_=98.0, close=97.0),  # fixed-hold exit
    ]
    strategy = RecentExtremeExitStrategy(lookback=2, reward_risk=2.0, direction=SignalDirection.DOWN)
    result = strategy.resolve_exit(entry_index=2, price_series=series, hold_period=2)

    assert result.exit_index == 4
    assert math.isclose(result.exit_price, 97.0, abs_tol=ABS_TOL)
    assert result.exit_reason is ExitReason.FIXED_HOLD
    assert math.isclose(result.stop_loss, 105.0, abs_tol=ABS_TOL)
    assert math.isclose(result.profit_target, 90.0, abs_tol=ABS_TOL)
    assert result.reason is None
