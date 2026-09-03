"""Trend-branch regression tests for ``MarketAnalyzer.detect_signals`` (SP-307, task 6.1).

These example tests exercise the trend block of ``detect_signals`` (see
``vpa/app_runner.py``)::

    adx_values   = calculate_adx(self.__deque_dictionary["period_three"])
    trending     = adx_values[0] > 25
    trending_up  = adx_values[2] > adx_values[3]   # mean DM+ vs mean DM-
    trending_down= adx_values[3] > adx_values[2]

Only when ``trending`` are ``"Market is trending"`` plus ``"Trending Up"`` (+5) /
``"Trending Down"`` (-5) appended, so the three branches asserted here are:

- **trending up** — ``adx_values[0] > 25`` with DM+ (``[2]``) > DM- (``[3]``)
  -> ``trend_signals`` contains "Market is trending" and "Trending Up",
  ``trend_signal_score == +5``.
- **trending down** — ``adx_values[0] > 25`` with DM- (``[3]``) > DM+ (``[2]``)
  -> "Market is trending" and "Trending Down", ``trend_signal_score == -5``.
- **not trending** — ``adx_values[0] <= 25`` -> ``trend_signals`` empty,
  ``trend_signal_score == 0``.

The ``period_three`` window is populated with synthetic candle sequences engineered
to force each branch (verified empirically): a steadily-rising sequence yields a high
ADX with DM+ dominant, a steadily-falling sequence yields a high ADX with DM- dominant,
and a balanced zig-zag sequence keeps the ADX at/below 25. ``calculate_adx`` requires
at least 15 candles; each sequence supplies 20 (``period_three`` ``maxlen`` is 50).

Hermeticity (no network, no log file) comes from the ``analyzer_factory`` fixture in
``conftest.py``. Requirements: 2.1, 2.2, 2.3, 2.4.
"""

import pytest

from vpa.app import Candle

from .conftest import (
    PERIOD_NAMES,
    make_candle,
    populate_windows,
    set_percentiles,
)

# A neutral percentile map used for every trend-sequence candle: mid-range buckets
# for all three periods so the single-candle and multiple-bar blocks that index the
# percentile dicts do not raise and do not fire any boundary-sensitive signal.
_NEUTRAL = dict.fromkeys(PERIOD_NAMES, 50)


def _trend_candle(candle_open: float, high: float, low: float, close: float) -> Candle:
    """Build a Candle with explicit OHLC and neutral percentiles for the ADX path."""
    candle = Candle("2023-01-01T00:00:00+00:00", 1000, candle_open, high, low, close)
    set_percentiles(candle, spread=dict(_NEUTRAL), volume=dict(_NEUTRAL))
    return candle


def _trending_up_sequence(n: int = 20) -> list[Candle]:
    """Steadily-rising candles: highs and lows climb each step.

    Each step raises the high (DM+ positive) while the low never falls (DM- zero), so
    the smoothed DM+ dominates and the directional index is saturated, driving
    ``adx_values[0]`` well above 25 with ``adx_values[2] > adx_values[3]``.
    """
    candles = []
    base = 100.0
    for i in range(n):
        candle_open = base + i
        close = candle_open + 1.0
        high = close + 0.2
        low = candle_open - 0.2
        candles.append(_trend_candle(candle_open, high, low, close))
    return candles


def _trending_down_sequence(n: int = 20) -> list[Candle]:
    """Steadily-falling candles: highs and lows drop each step.

    Each step lowers the low (DM- positive) while the high never rises (DM+ zero), so
    the smoothed DM- dominates, driving ``adx_values[0]`` above 25 with
    ``adx_values[3] > adx_values[2]``.
    """
    candles = []
    base = 100.0
    for i in range(n):
        candle_open = base - i
        close = candle_open - 1.0
        high = candle_open + 0.2
        low = close - 0.2
        candles.append(_trend_candle(candle_open, high, low, close))
    return candles


def _not_trending_sequence(n: int = 20, amplitude: float = 2.0) -> list[Candle]:
    """Balanced zig-zag candles: the whole range steps up then down alternately.

    Highs and lows move together up on even steps and down on odd steps, so DM+ and
    DM- roughly cancel across the window and the directional index stays low, keeping
    ``adx_values[0]`` at/below 25 (empirically ~1.5). Both wicks/legs are always
    non-zero so no true-range collapses to a divide-by-zero.
    """
    candles = []
    prev_high = 101.0
    prev_low = 99.0
    for i in range(n):
        if i % 2 == 0:
            high = prev_high + amplitude
            low = prev_low + amplitude
        else:
            high = prev_high - amplitude
            low = prev_low - amplitude
        mid = (high + low) / 2
        candle_open = mid - 0.1
        close = mid + 0.1
        candles.append(_trend_candle(candle_open, high, low, close))
        prev_high = high
        prev_low = low
    return candles


def _neutral_window(length: int) -> list[Candle]:
    """A window of neutral up bars with mid-range percentiles (no signals fire)."""
    window = []
    for _ in range(length):
        candle = make_candle(up=True, volume=1000, spread=1.0, upper_wick=0.0, lower_wick=0.0)
        set_percentiles(candle, spread=dict(_NEUTRAL), volume=dict(_NEUTRAL))
        window.append(candle)
    return window


def _build_analyzer(analyzer_factory, period_three: list[Candle]):
    """Construct a hermetic analyzer with neutral p1/p2 windows and the given p3."""
    analyzer = analyzer_factory()
    deque_dictionary = analyzer._MarketAnalyzer__deque_dictionary
    period_one = _neutral_window(deque_dictionary["period_one"].maxlen)
    period_two = _neutral_window(deque_dictionary["period_two"].maxlen)
    populate_windows(analyzer, period_one, period_two, period_three)
    return analyzer, period_one[0]


def test_trend_up_appends_trending_up_and_scores_plus_five(analyzer_factory):
    """A rising period_three yields ADX > 25 with DM+ dominant -> Trending Up, +5.

    Requirements: 2.1, 2.2.
    """
    analyzer, this_candle = _build_analyzer(analyzer_factory, _trending_up_sequence())

    result = analyzer.detect_signals(this_candle)

    assert "Market is trending" in result["trend_signals"]
    assert "Trending Up" in result["trend_signals"]
    assert "Trending Down" not in result["trend_signals"]
    assert result["trend_signal_score"] == 5


def test_trend_down_appends_trending_down_and_scores_minus_five(analyzer_factory):
    """A falling period_three yields ADX > 25 with DM- dominant -> Trending Down, -5.

    Requirements: 2.1, 2.3.
    """
    analyzer, this_candle = _build_analyzer(analyzer_factory, _trending_down_sequence())

    result = analyzer.detect_signals(this_candle)

    assert "Market is trending" in result["trend_signals"]
    assert "Trending Down" in result["trend_signals"]
    assert "Trending Up" not in result["trend_signals"]
    assert result["trend_signal_score"] == -5


def test_not_trending_leaves_trend_signals_empty_and_score_zero(analyzer_factory):
    """A balanced zig-zag period_three yields ADX <= 25 -> no trend signals, 0.

    Requirements: 2.1, 2.4.
    """
    analyzer, this_candle = _build_analyzer(analyzer_factory, _not_trending_sequence())

    result = analyzer.detect_signals(this_candle)

    assert result["trend_signals"] == []
    assert result["trend_signal_score"] == 0


def test_short_period_three_raises_value_error_for_insufficient_adx(analyzer_factory):
    """Fewer than 15 period_three candles -> detect_signals raises the ADX ValueError.

    ``calculate_adx`` (in ``vpa/app.py``) raises
    ``ValueError("Not enough data to calculate ADX. At least 15 periods are required.")``
    when ``len(candles) < period + 1`` (default ``period=14`` -> needs >= 15). The trend
    block of ``detect_signals`` calls ``calculate_adx(period_three)`` directly, so a
    period_three window holding only 10 candles must surface that ValueError.

    Note the single-candle block runs *before* the trend block and indexes
    ``this_candle.spread_percentiles``/``volume_percentiles`` for every period, so
    ``this_candle`` (and the short period_three candles) must carry valid percentile
    dicts for all three keys -- otherwise a ``KeyError`` would fire first. The
    period_one / period_two contents are irrelevant here because the ValueError is
    raised in the trend block, ahead of the multiple-bar block.

    Requirements: 2.5.
    """
    analyzer = analyzer_factory()
    deque_dictionary = analyzer._MarketAnalyzer__deque_dictionary

    # A short period_three window: 10 candles is fewer than the 15 ADX requires.
    short_period_three = _not_trending_sequence(n=10)
    assert len(short_period_three) < 15

    period_one = _neutral_window(deque_dictionary["period_one"].maxlen)
    period_two = _neutral_window(deque_dictionary["period_two"].maxlen)
    populate_windows(analyzer, period_one, period_two, short_period_three)

    # this_candle needs valid percentiles for all three period keys because the
    # single-candle block (which indexes them) runs before the trend block.
    this_candle = make_candle(up=True, volume=1000, spread=1.0, upper_wick=0.0, lower_wick=0.0)
    set_percentiles(this_candle, spread=dict(_NEUTRAL), volume=dict(_NEUTRAL))

    with pytest.raises(ValueError, match="Not enough data to calculate ADX"):
        analyzer.detect_signals(this_candle)
