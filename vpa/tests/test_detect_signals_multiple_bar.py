"""Multiple-bar regression tests for ``MarketAnalyzer.detect_signals`` (SP-307, Area B).

These pytest-native example tests exercise the *multiple-bar* scoring branch of
``detect_signals`` in isolation. Task 7.1 covers the per-period bull, bear, and
neutral-band outcomes when the period is **not** volume-backed; task 7.2 (appended
below) covers the volume-backed doubling (+/-5.0 with "Volume Backed (<period>)")
and the sub-condition-failure cases where a volume-backed sub-condition fails and
the contribution stays undoubled (+/-2.5).

Design recap (from ``detect_signals`` in ``vpa/app_runner.py`` and
``vpa/config/config.json`` ``trading_parameters``):

- For each period key, ``up_bar_count`` is the number of up bars in that period's
  window. A **bull** signal is set when ``up_bar_count >= Signal_Bar_Count``; an
  **elif bear** signal when ``up_bar_count <= PERIOD_ONE_LENGTH - Signal_Bar_Count``.
  Note the bear threshold always uses ``PERIOD_ONE_LENGTH`` (``5``) regardless of the
  period, exactly as written in the code under test.
- ``Signal_Bar_Count`` is ``4`` (period_one), ``13`` (period_two), ``26``
  (period_three). So the bear threshold ``5 - Signal_Bar_Count`` is ``1`` for
  period_one and negative (unreachable) for the longer periods -- a bear signal is
  therefore only realistically achievable for period_one.
- A period is **volume-backed** only when ``high_spread_count >= High_Spread_Count``
  AND ``high_volume_count >= High_Volume_Count`` AND ``anomaly_count <=
  Anomaly_Threshold``. ``high_spread_count`` / ``high_volume_count`` count candles
  whose spread / volume percentile for that period exceeds ``High_Spread_Threshold`` /
  ``High_Volume_Threshold`` (both ``55``). By setting every candle's spread and volume
  percentiles LOW (below ``55``), those counts are ``0``, so the period is never
  volume-backed and the bull/bear contribution stays *undoubled* (``+/-2.5``).

To isolate a single period's contribution, the other two periods are kept in their
neutral band (neither bull nor bear -> ``0`` contribution). The ``period_three``
window is always built as a staggered price walk so ``calculate_adx`` (invoked by
``detect_signals`` before the multiple-bar block) has non-degenerate ranges to work
with; the trend result itself is not asserted here.

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7.
"""

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from vpa.app import Candle
from vpa.tests.conftest import PERIOD_NAMES, populate_windows

# Apply the hermeticity guards to every test in this module: any accidental network
# access or log-file creation fails the test rather than escaping silently.
pytestmark = pytest.mark.usefixtures("no_network", "null_logger")

# Percentile buckets that sit below every relevant threshold. Spread/volume both at
# 10 keeps high_spread_count / high_volume_count at 0 (< High_Spread_Count /
# High_Volume_Count), so no period is ever volume-backed and the anomaly count stays
# 0 (|10 - 10| = 0 <= Anomaly_Threshold). This is also below the single-candle > 70
# boundary, so the passed candle introduces no wide-spread / high-volume noise.
_LOW_BUCKET = 10

# Period window sizes (each period deque's maxlen); mirrors config PERIOD_*_LENGTH.
_PERIOD_SIZES = {"period_one": 5, "period_two": 25, "period_three": 50}

# Neutral up-bar counts that fall strictly inside each period's neutral band, i.e.
# above ``5 - Signal_Bar_Count`` and below ``Signal_Bar_Count`` -> neither bull nor
# bear. period_one neutral band is {2, 3}; the longer periods only need to stay below
# their (large) Signal_Bar_Count while above the (negative) bear threshold.
_NEUTRAL_UP_COUNT = {"period_one": 2, "period_two": 5, "period_three": 10}


def _low_percentiles() -> dict:
    """Return a fresh spread/volume percentile dict with all periods at the low bucket."""
    return dict.fromkeys(PERIOD_NAMES, _LOW_BUCKET)


def _build_window(size: int, up_count: int) -> list:
    """Build a window of ``size`` candles with exactly ``up_count`` up bars.

    Every candle is given a staggered base price and a genuine high/low range so the
    ``period_three`` window fed to ``calculate_adx`` never produces an all-zero True
    Range (which would divide by zero). Percentiles are set LOW (spread then volume,
    the order the ``Candle`` volume setter requires) so the window is never
    volume-backed. The up/down direction is chosen per index to hit ``up_count``
    exactly.
    """
    if not 0 <= up_count <= size:
        raise ValueError("up_count must be between 0 and size inclusive")

    candles = []
    for i in range(size):
        is_up = i < up_count
        # Staggered base so consecutive candles differ (non-degenerate TR / DM values).
        base = 100.0 + i
        if is_up:
            candle_open = base
            close = base + 1.0
        else:
            candle_open = base + 1.0
            close = base
        # Real high/low range beyond the body, kept symmetric and small so no wick
        # pattern (shooting star / hammer / LLD) is triggered.
        high = max(candle_open, close) + 0.25
        low = min(candle_open, close) - 0.25

        candle = Candle(f"2023-01-{(i % 28) + 1:02d}T00:00:00+00:00", 1000, candle_open, high, low, close)
        candle.spread_percentiles = _low_percentiles()
        candle.volume_percentiles = _low_percentiles()
        candles.append(candle)
    return candles


def _passed_candle(*, up: bool) -> Candle:
    """Build the ``this_candle`` argument with low percentiles and no wick pattern.

    Its single-candle contribution is only the up/down-bar +/-1, and its low
    percentiles keep it out of the wide-spread branch; it does not affect the
    multiple-bar block (which reads only the period windows).
    """
    if up:
        candle = Candle("2023-02-01T00:00:00+00:00", 1000, 100.0, 101.25, 99.75, 101.0)
    else:
        candle = Candle("2023-02-01T00:00:00+00:00", 1000, 101.0, 101.25, 99.75, 100.0)
    candle.spread_percentiles = _low_percentiles()
    candle.volume_percentiles = _low_percentiles()
    return candle


def _populate(analyzer, *, up_counts: dict) -> None:
    """Populate all three windows from ``up_counts`` (period name -> up-bar count)."""
    populate_windows(
        analyzer,
        _build_window(_PERIOD_SIZES["period_one"], up_counts["period_one"]),
        _build_window(_PERIOD_SIZES["period_two"], up_counts["period_two"]),
        _build_window(_PERIOD_SIZES["period_three"], up_counts["period_three"]),
    )


# ---------------------------------------------------------------------------
# Bull signal (up_bar_count >= Signal_Bar_Count), not volume-backed -> +2.5
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("period", "up_count"),
    [
        ("period_one", 4),  # Signal_Bar_Count = 4
        ("period_two", 13),  # Signal_Bar_Count = 13
        ("period_three", 26),  # Signal_Bar_Count = 26
    ],
)
def test_bull_signal_undoubled_plus_two_point_five(analyzer_factory, period, up_count):
    """Requirement 3.1, 3.2: a period at/above its Signal_Bar_Count, not volume-backed.

    The tested period's up-bar count is set to exactly its ``Signal_Bar_Count`` so the
    bull condition (``>=``) holds; the other two periods stay in their neutral band and
    contribute nothing. Low percentiles keep the period from being volume-backed, so
    the contribution is the undoubled +2.5 and "Volume Backed" is absent.
    """
    analyzer = analyzer_factory()
    up_counts = dict(_NEUTRAL_UP_COUNT)
    up_counts[period] = up_count
    _populate(analyzer, up_counts=up_counts)

    result = analyzer.detect_signals(_passed_candle(up=True))

    assert f"Bull Signal ({period})" in result["multiple_bar_signals"]
    assert f"Bear Signal ({period})" not in result["multiple_bar_signals"]
    assert f"Volume Backed ({period})" not in result["multiple_bar_signals"]
    assert result["multiple_bar_signal_score"] == pytest.approx(2.5)


# ---------------------------------------------------------------------------
# Bear signal (up_bar_count <= PERIOD_ONE_LENGTH - Signal_Bar_Count) -> -2.5
# Only period_one has a reachable bear threshold (5 - 4 = 1).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("up_count", [0, 1])
def test_bear_signal_undoubled_minus_two_point_five(analyzer_factory, up_count):
    """Requirement 3.1, 3.3: period_one at/below its bear threshold, not volume-backed.

    period_one's bear threshold is ``PERIOD_ONE_LENGTH - Signal_Bar_Count = 5 - 4 = 1``,
    so an up-bar count of 0 or 1 triggers the bear condition (``<=``). period_two and
    period_three stay neutral. Low percentiles keep it un-volume-backed, so the
    contribution is the undoubled -2.5 and "Volume Backed" is absent.
    """
    analyzer = analyzer_factory()
    up_counts = dict(_NEUTRAL_UP_COUNT)
    up_counts["period_one"] = up_count
    _populate(analyzer, up_counts=up_counts)

    result = analyzer.detect_signals(_passed_candle(up=False))

    assert "Bear Signal (period_one)" in result["multiple_bar_signals"]
    assert "Bull Signal (period_one)" not in result["multiple_bar_signals"]
    assert "Volume Backed (period_one)" not in result["multiple_bar_signals"]
    assert result["multiple_bar_signal_score"] == pytest.approx(-2.5)


# ---------------------------------------------------------------------------
# Neutral band (bear threshold < up_bar_count < Signal_Bar_Count) -> 0
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("period", "up_count"),
    [
        ("period_one", 2),  # neutral band {2, 3}: above 1, below 4
        ("period_one", 3),
        ("period_two", 5),  # below Signal_Bar_Count 13, above (negative) bear threshold
        ("period_three", 10),  # below Signal_Bar_Count 26, above (negative) bear threshold
    ],
)
def test_neutral_band_contributes_zero(analyzer_factory, period, up_count):
    """Requirement 3.6: an up-bar count inside the neutral band emits no bull/bear.

    All three periods are held in their neutral band (the tested period at ``up_count``,
    the others at their default neutral counts), so no bull or bear signal appears for
    any period and the multiple-bar contribution is exactly 0.
    """
    analyzer = analyzer_factory()
    up_counts = dict(_NEUTRAL_UP_COUNT)
    up_counts[period] = up_count
    _populate(analyzer, up_counts=up_counts)

    result = analyzer.detect_signals(_passed_candle(up=True))

    for candidate in PERIOD_NAMES:
        assert f"Bull Signal ({candidate})" not in result["multiple_bar_signals"]
        assert f"Bear Signal ({candidate})" not in result["multiple_bar_signals"]
    assert result["multiple_bar_signals"] == []
    assert result["multiple_bar_signal_score"] == pytest.approx(0)


# ---------------------------------------------------------------------------
# Task 7.2: volume-backed and sub-condition-failure tests.
#
# A period is *volume-backed* only when all three sub-conditions hold together
# (see the multiple-bar block of ``detect_signals`` in ``vpa/app_runner.py`` and
# ``trading_parameters`` in ``vpa/config/config.json``):
#
#   high_spread_count >= High_Spread_Count   (candles with spread pct > 55)
#   high_volume_count >= High_Volume_Count   (candles with volume pct > 55)
#   anomaly_count     <= Anomaly_Threshold   (candles with |spread - volume| > 20)
#
# High_Spread_Count / High_Volume_Count per period are 3/3 (period_one),
# 6/6 (period_two), 12/12 (period_three). To volume-back a period we therefore
# need at least that many candles whose spread AND volume percentiles both exceed
# 55, while keeping the per-candle |spread - volume| gap at/under 20 so those same
# candles never count as anomalies. Setting both percentiles equal and HIGH (the
# ``_HIGH_BUCKET`` below) satisfies "> 55" and yields a zero anomaly gap.
#
# ``_build_high_window`` is the volume-backing variant of ``_build_window``: it
# builds a window whose FIRST ``high_count`` candles carry high (equal) spread and
# volume percentiles, with the remaining candles left at the low bucket. The
# up/down direction is still chosen per index to hit ``up_count`` exactly, so a
# window can be simultaneously bull-or-bear AND volume-backed (or deliberately
# fall short on one sub-condition).
#
# Requirements: 3.4, 3.5, 3.7.
# ---------------------------------------------------------------------------


# Percentile bucket comfortably above High_Spread_Threshold / High_Volume_Threshold
# (both 55). Used for the spread AND volume percentile of a "high" candle; because
# both are set to the same value the per-candle anomaly gap is 0 (<= Anomaly_Threshold
# 20), so high candles never inflate anomaly_count.
_HIGH_BUCKET = 80

# The number of high-percentile candles each period needs to satisfy BOTH
# High_Spread_Count and High_Volume_Count (they are equal per period): period_one 3,
# period_two 6, period_three 12. Mirrors config trading_parameters.
_VOLUME_BACKED_COUNT = {"period_one": 3, "period_two": 6, "period_three": 12}


def _high_percentiles() -> dict:
    """Return a spread/volume percentile dict with all periods at the high bucket."""
    return dict.fromkeys(PERIOD_NAMES, _HIGH_BUCKET)


def _build_high_window(size: int, up_count: int, high_count: int) -> list:
    """Build a window of ``size`` candles, the first ``high_count`` volume-backing.

    Like :func:`_build_window` (same staggered, ADX-safe price walk and exact
    ``up_count`` up bars), but the first ``high_count`` candles are given HIGH,
    equal spread and volume percentiles (``_HIGH_BUCKET``) so they count toward
    ``high_spread_count`` and ``high_volume_count`` while contributing nothing to
    ``anomaly_count`` (their |spread - volume| gap is 0). The remaining candles keep
    the low bucket. Independent of direction: an up or a down candle can carry high
    percentiles, so a window can be bull/bear AND volume-backed at the same time.
    """
    if not 0 <= up_count <= size:
        raise ValueError("up_count must be between 0 and size inclusive")
    if not 0 <= high_count <= size:
        raise ValueError("high_count must be between 0 and size inclusive")

    candles = []
    for i in range(size):
        is_up = i < up_count
        base = 100.0 + i
        if is_up:
            candle_open = base
            close = base + 1.0
        else:
            candle_open = base + 1.0
            close = base
        high = max(candle_open, close) + 0.25
        low = min(candle_open, close) - 0.25

        candle = Candle(f"2023-01-{(i % 28) + 1:02d}T00:00:00+00:00", 1000, candle_open, high, low, close)
        if i < high_count:
            candle.spread_percentiles = _high_percentiles()
            candle.volume_percentiles = _high_percentiles()
        else:
            candle.spread_percentiles = _low_percentiles()
            candle.volume_percentiles = _low_percentiles()
        candles.append(candle)
    return candles


def _populate_with_target(analyzer, *, period: str, up_count: int, high_count: int) -> None:
    """Populate all three windows, giving ``period`` the target window, others neutral.

    The target period gets a :func:`_build_high_window` window (so it can be both
    bull/bear and volume-backed), while the other two periods stay in their neutral
    band via :func:`_build_window` and contribute 0.
    """
    windows = {}
    for name in PERIOD_NAMES:
        if name == period:
            windows[name] = _build_high_window(_PERIOD_SIZES[name], up_count, high_count)
        else:
            windows[name] = _build_window(_PERIOD_SIZES[name], _NEUTRAL_UP_COUNT[name])
    populate_windows(analyzer, windows["period_one"], windows["period_two"], windows["period_three"])


# ---------------------------------------------------------------------------
# Volume-backed bull -> "Bull Signal" + "Volume Backed", doubled +5.0
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("period", "up_count"),
    [
        ("period_one", 4),  # Signal_Bar_Count = 4, High_Spread/Volume_Count = 3
        ("period_two", 13),  # Signal_Bar_Count = 13, High_Spread/Volume_Count = 6
        ("period_three", 26),  # Signal_Bar_Count = 26, High_Spread/Volume_Count = 12
    ],
)
def test_volume_backed_bull_doubles_to_plus_five(analyzer_factory, period, up_count):
    """Requirement 3.4: a bull period that is volume-backed doubles to +5.0.

    The tested period's up-bar count is at its ``Signal_Bar_Count`` (bull holds) and
    it carries exactly ``High_Spread_Count`` (== ``High_Volume_Count``) candles with
    high, equal spread+volume percentiles, so ``high_spread_count`` and
    ``high_volume_count`` both meet their thresholds while ``anomaly_count`` stays 0.
    All three volume sub-conditions hold, so "Volume Backed" is emitted and the bull
    contribution is doubled from +2.5 to +5.0. The other periods stay neutral.
    """
    analyzer = analyzer_factory()
    _populate_with_target(analyzer, period=period, up_count=up_count, high_count=_VOLUME_BACKED_COUNT[period])

    result = analyzer.detect_signals(_passed_candle(up=True))

    assert f"Bull Signal ({period})" in result["multiple_bar_signals"]
    assert f"Volume Backed ({period})" in result["multiple_bar_signals"]
    assert f"Bear Signal ({period})" not in result["multiple_bar_signals"]
    assert result["multiple_bar_signal_score"] == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# Volume-backed bear -> "Bear Signal" + "Volume Backed", doubled -5.0
# Only period_one has a reachable bear threshold (5 - 4 = 1).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("up_count", [0, 1])
def test_volume_backed_bear_doubles_to_minus_five(analyzer_factory, up_count):
    """Requirement 3.5: a bear period that is volume-backed doubles to -5.0.

    period_one's bear threshold is ``PERIOD_ONE_LENGTH - Signal_Bar_Count = 1``, so an
    up-bar count of 0 or 1 triggers bear. All five candles carry high, equal
    spread+volume percentiles (direction-independent), so ``high_spread_count`` and
    ``high_volume_count`` are 5 (>= 3) and ``anomaly_count`` is 0 (<= 20): the period
    is volume-backed and the bear contribution doubles from -2.5 to -5.0. period_two
    and period_three stay neutral.
    """
    analyzer = analyzer_factory()
    # All five period_one candles high so the count is met regardless of how few are up.
    _populate_with_target(analyzer, period="period_one", up_count=up_count, high_count=_PERIOD_SIZES["period_one"])

    result = analyzer.detect_signals(_passed_candle(up=False))

    assert "Bear Signal (period_one)" in result["multiple_bar_signals"]
    assert "Volume Backed (period_one)" in result["multiple_bar_signals"]
    assert "Bull Signal (period_one)" not in result["multiple_bar_signals"]
    assert result["multiple_bar_signal_score"] == pytest.approx(-5.0)


# ---------------------------------------------------------------------------
# Sub-condition failure -> "Volume Backed" absent, contribution undoubled
# ---------------------------------------------------------------------------


def test_bull_high_spread_count_below_threshold_not_volume_backed(analyzer_factory):
    """Requirement 3.7: bull met but too few high candles -> undoubled +2.5.

    period_one is bull (4 up bars) but only 2 candles carry high spread+volume
    percentiles, so ``high_spread_count`` and ``high_volume_count`` are 2, below the
    ``High_Spread_Count`` / ``High_Volume_Count`` threshold of 3. The volume-backed
    condition fails, "Volume Backed" is absent, and the bull contribution stays the
    undoubled +2.5.
    """
    analyzer = analyzer_factory()
    _populate_with_target(analyzer, period="period_one", up_count=4, high_count=2)

    result = analyzer.detect_signals(_passed_candle(up=True))

    assert "Bull Signal (period_one)" in result["multiple_bar_signals"]
    assert "Volume Backed (period_one)" not in result["multiple_bar_signals"]
    assert result["multiple_bar_signal_score"] == pytest.approx(2.5)


def test_bull_high_volume_count_below_threshold_not_volume_backed(analyzer_factory):
    """Requirement 3.7: bull met, spread count OK but volume count short -> +2.5.

    period_one is bull (4 up bars). Three candles have high SPREAD percentiles (so
    ``high_spread_count`` = 3, meeting its threshold) but each of those candles has a
    LOW volume percentile, so ``high_volume_count`` = 0 (< 3). Because the high-spread
    candles now have a |spread - volume| gap of |80 - 10| = 70 (> 20) they also make
    ``anomaly_count`` = 3, but the volume sub-condition alone already fails the
    volume-backed AND. "Volume Backed" is absent and the contribution is the undoubled
    +2.5.
    """
    analyzer = analyzer_factory()

    # Build period_one by hand: 4 up bars, first 3 candles high-spread / low-volume.
    period_one = []
    for i in range(_PERIOD_SIZES["period_one"]):
        is_up = i < 4
        base = 100.0 + i
        candle_open = base if is_up else base + 1.0
        close = base + 1.0 if is_up else base
        high = max(candle_open, close) + 0.25
        low = min(candle_open, close) - 0.25
        candle = Candle(f"2023-01-{i + 1:02d}T00:00:00+00:00", 1000, candle_open, high, low, close)
        if i < 3:
            # High spread, low volume: high_spread_count counts it, high_volume_count does not.
            candle.spread_percentiles = _high_percentiles()
            candle.volume_percentiles = _low_percentiles()
        else:
            candle.spread_percentiles = _low_percentiles()
            candle.volume_percentiles = _low_percentiles()
        period_one.append(candle)

    populate_windows(
        analyzer,
        period_one,
        _build_window(_PERIOD_SIZES["period_two"], _NEUTRAL_UP_COUNT["period_two"]),
        _build_window(_PERIOD_SIZES["period_three"], _NEUTRAL_UP_COUNT["period_three"]),
    )

    result = analyzer.detect_signals(_passed_candle(up=True))

    assert "Bull Signal (period_one)" in result["multiple_bar_signals"]
    assert "Volume Backed (period_one)" not in result["multiple_bar_signals"]
    assert result["multiple_bar_signal_score"] == pytest.approx(2.5)


def test_bull_anomaly_count_above_threshold_not_volume_backed(analyzer_factory):
    """Requirement 3.7: bull met, spread & volume counts OK but anomaly too high -> +2.5.

    period_one is bull (4 up bars) with all five candles having high spread AND high
    volume percentiles, so ``high_spread_count`` and ``high_volume_count`` are 5
    (>= 3). But each candle's spread (95) and volume (60) percentiles differ by
    |95 - 60| = 35 (> Anomaly_Threshold 20), so ``anomaly_count`` = 5 (> 20 is false,
    but the sub-condition is ``anomaly_count <= 20`` and 5 <= 20 would pass...).

    To actually breach the anomaly sub-condition we need MORE than 20 anomalous
    candles, which period_one (size 5) cannot provide. So this scenario is only
    reachable on the longer periods. This test therefore uses period_three: 26 up
    bars (bull), 12 candles high-spread/high-volume enough for the counts, but with a
    wide spread/volume gap on 21 candles so ``anomaly_count`` = 21 (> 20). "Volume
    Backed" is absent and the contribution is the undoubled +2.5.
    """
    analyzer = analyzer_factory()

    size = _PERIOD_SIZES["period_three"]
    period_three = []
    for i in range(size):
        is_up = i < 26
        base = 100.0 + i
        candle_open = base if is_up else base + 1.0
        close = base + 1.0 if is_up else base
        high = max(candle_open, close) + 0.25
        low = min(candle_open, close) - 0.25
        candle = Candle(f"2023-01-{(i % 28) + 1:02d}T00:00:00+00:00", 1000, candle_open, high, low, close)
        if i < 12:
            # High spread AND high volume, equal -> counts toward both, zero anomaly.
            candle.spread_percentiles = _high_percentiles()
            candle.volume_percentiles = _high_percentiles()
        elif i < 12 + 21:
            # Wide spread/volume gap: spread 95, volume 60 -> |95 - 60| = 35 (> 20)
            # anomalous, and volume 60 > 55 also keeps high_volume_count comfortably
            # above its threshold; spread 95 > 55 keeps high_spread_count high too.
            candle.spread_percentiles = dict.fromkeys(PERIOD_NAMES, 95)
            candle.volume_percentiles = dict.fromkeys(PERIOD_NAMES, 60)
        else:
            candle.spread_percentiles = _low_percentiles()
            candle.volume_percentiles = _low_percentiles()
        period_three.append(candle)

    populate_windows(
        analyzer,
        _build_window(_PERIOD_SIZES["period_one"], _NEUTRAL_UP_COUNT["period_one"]),
        _build_window(_PERIOD_SIZES["period_two"], _NEUTRAL_UP_COUNT["period_two"]),
        period_three,
    )

    result = analyzer.detect_signals(_passed_candle(up=True))

    assert "Bull Signal (period_three)" in result["multiple_bar_signals"]
    assert "Volume Backed (period_three)" not in result["multiple_bar_signals"]
    assert result["multiple_bar_signal_score"] == pytest.approx(2.5)


# ---------------------------------------------------------------------------
# Task 7.3 (optional property test): bull-signal presence tracks the
# Signal_Bar_Count boundary.
#
# Property 3 (from design.md, Correctness Properties):
#   For any period and any up-bar count ``c`` in that period's window,
#   "Bull Signal (<period>)" appears in ``multiple_bar_signals`` if and only if
#   ``c >= Signal_Bar_Count`` for that period (holding volume-backing constant/off).
#   Presence is monotonic in ``c`` at the inclusive boundary.
#
# We validate the property on ``period_one`` for a clean, small, fully-bounded input
# space: ``Signal_Bar_Count == 4`` and the window size (``PERIOD_ONE_LENGTH``) is 5,
# so ``up_count`` ranges over ``0..5`` inclusive. Percentiles are held LOW (the shared
# ``_build_window`` / ``_LOW_BUCKET`` machinery keeps every window candle below the
# volume-backing thresholds of 55), so ``high_spread_count`` / ``high_volume_count``
# stay 0 and the period is never volume-backed: bull presence is governed purely by
# the count boundary. The other two periods are held in their neutral band via
# ``_NEUTRAL_UP_COUNT`` so only period_one can produce a bull signal.
#
# Note on the period_one decision bands (all with the multiple-bar block as written):
#   * up_count <= 5 - 4 = 1   -> BEAR   (0, 1)
#   * 2 <= up_count <= 3      -> NEUTRAL
#   * up_count >= 4           -> BULL   (4, 5)
# so the iff for the BULL signal on period_one is exactly ``up_count >= 4``.
# ---------------------------------------------------------------------------

# period_one Signal_Bar_Count (the inclusive bull boundary under test).
_PERIOD_ONE_SIGNAL_BAR_COUNT = 4


# Feature: marketanalyzer-signal-detection-tests, Property 3: Bull-signal presence tracks the `Signal_Bar_Count` boundary  # noqa: E501
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(up_count=st.integers(min_value=0, max_value=_PERIOD_SIZES["period_one"]))
def test_bull_signal_presence_tracks_signal_bar_count_boundary(analyzer_factory, up_count):
    """Property 3: "Bull Signal (period_one)" appears iff up_count >= Signal_Bar_Count.

    **Validates: Requirements 3.2, 5.6**

    For every up-bar count ``0..5`` in the period_one window, hold the other periods in
    their neutral band and keep all percentiles LOW (so period_one is never
    volume-backed), then assert that ``"Bull Signal (period_one)"`` is in
    ``multiple_bar_signals`` if and only if ``up_count >= 4``. This is the monotonic,
    inclusive-boundary behaviour of Property 3 realised on the clean period_one space.
    """
    analyzer = analyzer_factory()
    up_counts = dict(_NEUTRAL_UP_COUNT)
    up_counts["period_one"] = up_count
    _populate(analyzer, up_counts=up_counts)

    result = analyzer.detect_signals(_passed_candle(up=True))
    signals = result["multiple_bar_signals"]

    bull_present = "Bull Signal (period_one)" in signals
    assert bull_present == (up_count >= _PERIOD_ONE_SIGNAL_BAR_COUNT)

    # Since period_one is never volume-backed here, a present bull signal is the
    # undoubled variant with no "Volume Backed" companion entry.
    if bull_present:
        assert "Volume Backed (period_one)" not in signals
