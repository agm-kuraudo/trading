"""Threshold edge-condition tests for ``MarketAnalyzer.detect_signals`` (SP-307, Area D).

These pytest-native example tests exercise inputs positioned exactly at, one step
below, and one step above the boundaries used by ``detect_signals``, so off-by-one
and boundary-comparison errors are detected. Each test builds a hermetic analyzer via
the ``analyzer_factory`` fixture, populates the three rolling windows with a neutral
baseline candle set, and passes a ``this_candle`` whose percentile dicts are set to
land precisely on the boundary under test.

The neutral baseline windows use a gently-varying price series for ``period_three``
so ``calculate_adx`` has a non-zero true range to work with (a perfectly flat series
divides by zero inside ADX), while keeping the ADX below the trending threshold so the
trend block contributes nothing. Every window candle carries spread/volume percentile
buckets at a quiet ``50`` for all three period keys, so the multiple-bar and
accumulation/distribution blocks introduce no noise and the assertions can focus on
the single-candle boundary under test.

This module currently implements task 9.1 -- the single-candle spread/volume
percentile ``70`` boundary (strict ``>``). Tasks 9.2 (``Signal_Bar_Count`` inclusive
boundary) and 9.3 (Acc/Dist test-pass ``65``/``50`` boundaries) are appended to this
same file later; the section layout below leaves room for them.

Requirements: 5.1, 5.3, 5.4, 5.5.
"""

import pytest

from vpa.app import Candle
from vpa.tests.conftest import PERIOD_NAMES, make_candle, populate_windows, set_percentiles

# ``_build_period_one`` / ``_build_period_three`` are reused (task 9.3) from the
# acc/dist test module to force ``identify_acc_or_dist`` -> (True, "Acc").
from vpa.tests.test_detect_signals_acc_dist import _build_period_one, _build_period_three

# Apply the hermeticity guards to every test in this module: any accidental network
# access or log-file creation fails the test rather than escaping silently.
pytestmark = pytest.mark.usefixtures("no_network", "null_logger")

# Percentile buckets that sit safely below every single-candle boundary (strict > 70),
# used as the baseline for the periods that are NOT under test so they contribute no
# "Wide Spread"/"High Volume" noise.
_QUIET_BUCKET = 50


def _quiet_window_candle(index: int) -> Candle:
    """Build a neutral baseline candle for a rolling window at position ``index``.

    Each candle's price is anchored to a base that steps up with ``index``. This gives
    ``period_three`` a non-zero true range and consistently positive directional
    movement, so ``calculate_adx`` neither divides by zero (a perfectly flat series
    would) nor produces an undefined DX. The step is mild enough that the resulting ADX
    stays below the trending threshold, so the trend block contributes nothing.

    OHLC are derived so the candle is a small up bar with negligible wicks (no pattern
    flags): ``open = base``, ``close = base + spread``, ``high = close``, ``low = open``.
    Percentile buckets are set to the quiet baseline (``50``) for all three period keys
    so the multiple-bar and acc/dist blocks stay silent.
    """
    base = 100.0 + index
    candle_open = base
    close = base + 1.0
    high = close
    low = candle_open
    candle = Candle("2023-01-03T00:00:00+00:00", 1000, candle_open, high, low, close)
    quiet = dict.fromkeys(PERIOD_NAMES, _QUIET_BUCKET)
    set_percentiles(candle, spread=dict(quiet), volume=dict(quiet))
    return candle


@pytest.fixture
def threshold_analyzer(analyzer_factory):
    """A hermetic analyzer with neutral, ADX-safe windows for boundary tests.

    Unlike the shared ``populated_analyzer`` fixture (whose flat baseline candles make
    ``calculate_adx`` divide by zero), this fixture fills each window with a
    gently-varying neutral series so ``detect_signals`` runs end to end without the
    trend block firing. Tests then pass their own boundary ``this_candle``.
    """
    analyzer = analyzer_factory()
    deque_dictionary = analyzer._MarketAnalyzer__deque_dictionary
    period_one = [_quiet_window_candle(i) for i in range(deque_dictionary["period_one"].maxlen)]
    period_two = [_quiet_window_candle(i) for i in range(deque_dictionary["period_two"].maxlen)]
    period_three = [_quiet_window_candle(i) for i in range(deque_dictionary["period_three"].maxlen)]
    populate_windows(analyzer, period_one, period_two, period_three)
    return analyzer


def _percentiles_with(period, value, *, others=_QUIET_BUCKET):
    """Return a percentile dict with ``period`` set to ``value`` and the rest quiet.

    All three period keys are always present (``detect_signals`` indexes each period's
    percentile dict, so a missing key would raise ``KeyError``). Only the period under
    test carries the boundary ``value``; the other periods sit at the quiet baseline
    (``50``), well below the strict ``> 70`` boundary.
    """
    percentiles = dict.fromkeys(PERIOD_NAMES, others)
    percentiles[period] = value
    return percentiles


# ---------------------------------------------------------------------------
# Task 9.1 -- single-candle spread/volume percentile 70 boundary (strict >)
# ---------------------------------------------------------------------------
#
# The single-candle block does, per period:
#     if this_candle.spread_percentiles[period] > 70:
#         -> "Wide Spread (<period>)"
#         if this_candle.volume_percentiles[period] > 70:
#             -> "High Volume (<period>)"
# Both comparisons are strict ``>``, so a value of exactly 70 does NOT trigger, 69 does
# not trigger, and 71 does. "High Volume" requires BOTH spread AND volume > 70 for the
# same period.


@pytest.mark.parametrize("period", PERIOD_NAMES)
@pytest.mark.parametrize(
    ("spread_value", "expected_present"),
    [
        (70, False),  # exactly at the strict boundary -> absent
        (69, False),  # one step below -> absent
        (71, True),  # one step above -> present
    ],
)
def test_wide_spread_70_boundary(threshold_analyzer, period, spread_value, expected_present):
    """Requirements 5.1, 5.3, 5.4, 5.5: "Wide Spread" tracks the strict > 70 boundary.

    With the spread percentile for ``period`` set at 70, 69, or 71 (and volumes kept
    quiet so the nested "High Volume" branch never fires), assert that
    ``"Wide Spread (<period>)"`` is absent at 70, absent at 69, and present at 71.
    """
    spread = _percentiles_with(period, spread_value)
    # Keep volume quiet for every period so only the "Wide Spread" branch is exercised.
    volume = dict.fromkeys(PERIOD_NAMES, _QUIET_BUCKET)

    this_candle = make_candle(up=True, spread=1.0, upper_wick=0.0, lower_wick=0.0)
    set_percentiles(this_candle, spread=spread, volume=volume)

    result = threshold_analyzer.detect_signals(this_candle)
    signals = result["single_candle_signals"]

    label = f"Wide Spread ({period})"
    if expected_present:
        assert label in signals
    else:
        assert label not in signals


@pytest.mark.parametrize("period", PERIOD_NAMES)
@pytest.mark.parametrize(
    ("volume_value", "expected_present"),
    [
        (70, False),  # exactly at the strict boundary -> absent
        (69, False),  # one step below -> absent
        (71, True),  # one step above -> present
    ],
)
def test_high_volume_70_boundary(threshold_analyzer, period, volume_value, expected_present):
    """Requirements 5.1, 5.3, 5.4, 5.5: "High Volume" tracks the strict > 70 boundary.

    "High Volume (<period>)" requires BOTH the spread AND the volume percentile for the
    period to be strictly greater than 70. The spread percentile for ``period`` is held
    at 71 (strictly above the boundary, so the outer "Wide Spread" branch is entered)
    while the volume percentile is set at 70, 69, or 71. Assert "High Volume" is absent
    at 70, absent at 69, and present at 71.
    """
    # Spread strictly above 70 for the period under test so the nested branch is reachable.
    spread = _percentiles_with(period, 71)
    volume = _percentiles_with(period, volume_value)

    this_candle = make_candle(up=True, spread=1.0, upper_wick=0.0, lower_wick=0.0)
    set_percentiles(this_candle, spread=spread, volume=volume)

    result = threshold_analyzer.detect_signals(this_candle)
    signals = result["single_candle_signals"]

    label = f"High Volume ({period})"
    if expected_present:
        assert label in signals
    else:
        assert label not in signals


# ---------------------------------------------------------------------------
# Task 9.2 -- Signal_Bar_Count inclusive boundary for the bull condition (>=)
# ---------------------------------------------------------------------------
#
# The multiple-bar block does, per period:
#     if up_bar_count >= Signal_Bar_Count:        # inclusive >=
#         -> "<period>_bull" -> "Bull Signal (<period>)"  (+2.5, or +5.0 volume-backed)
#     elif up_bar_count <= PERIOD_ONE_LENGTH - Signal_Bar_Count:
#         -> "<period>_bear" -> "Bear Signal (<period>)"
# The bull comparison is inclusive ``>=``, so a count of exactly Signal_Bar_Count
# triggers, one above triggers, and one below does not.
#
# period_one is the clean case: Signal_Bar_Count = 4 and its window size
# (PERIOD_ONE_LENGTH) is 5, so up counts of 3 / 4 / 5 exercise below / at / above the
# boundary. Crucially the bear threshold for period_one is 5 - 4 = 1, so counts of
# 3, 4, and 5 are all safely above it -- the "one below" case (3) lands in the neutral
# band {2, 3} and produces neither a bull nor a bear signal, so its absence assertion
# is unambiguous.
#
# Percentiles are kept LOW (below High_Spread_Threshold / High_Volume_Threshold = 55)
# so high_spread_count / high_volume_count stay 0 and the period is never
# volume-backed: presence/absence is therefore governed purely by the count boundary,
# not by volume backing.

# Percentile buckets below every multiple-bar threshold (55) so the period is never
# volume-backed and the count boundary is the only thing under test.
_LOW_BUCKET = 10

# Period window sizes (each period deque's maxlen); mirrors config PERIOD_*_LENGTH.
_PERIOD_SIZES = {"period_one": 5, "period_two": 25, "period_three": 50}

# Neutral up-bar counts that fall strictly inside each period's neutral band (above
# ``5 - Signal_Bar_Count`` and below ``Signal_Bar_Count``), so the periods NOT under
# test emit neither a bull nor a bear signal.
_NEUTRAL_UP_COUNT = {"period_one": 2, "period_two": 5, "period_three": 10}

# period_one Signal_Bar_Count (the inclusive boundary under test).
_PERIOD_ONE_SIGNAL_BAR_COUNT = 4


def _low_percentiles() -> dict:
    """Return a fresh spread/volume percentile dict with all periods at the low bucket."""
    return dict.fromkeys(PERIOD_NAMES, _LOW_BUCKET)


def _count_window(size: int, up_count: int) -> list:
    """Build a window of ``size`` candles with exactly ``up_count`` up bars.

    Each candle carries a staggered base price and a genuine high/low range so the
    ``period_three`` window handed to ``calculate_adx`` never yields an all-zero true
    range (which would divide by zero inside the trend block). Percentiles are set LOW
    (spread then volume, the order the ``Candle`` volume setter requires) so the window
    is never volume-backed. The first ``up_count`` candles are up bars, the remainder
    down bars, so the up-bar count is exactly ``up_count``.
    """
    if not 0 <= up_count <= size:
        raise ValueError("up_count must be between 0 and size inclusive")

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
        # Small symmetric wicks so no shooting-star / hammer / long-legged-doji fires.
        high = max(candle_open, close) + 0.25
        low = min(candle_open, close) - 0.25
        candle = Candle(f"2023-01-{(i % 28) + 1:02d}T00:00:00+00:00", 1000, candle_open, high, low, close)
        candle.spread_percentiles = _low_percentiles()
        candle.volume_percentiles = _low_percentiles()
        candles.append(candle)
    return candles


def _populate_counts(analyzer, *, up_counts: dict) -> None:
    """Populate all three windows from ``up_counts`` (period name -> up-bar count)."""
    populate_windows(
        analyzer,
        _count_window(_PERIOD_SIZES["period_one"], up_counts["period_one"]),
        _count_window(_PERIOD_SIZES["period_two"], up_counts["period_two"]),
        _count_window(_PERIOD_SIZES["period_three"], up_counts["period_three"]),
    )


def _count_passed_candle() -> Candle:
    """Build the ``this_candle`` argument with low percentiles and no wick pattern.

    Its single-candle contribution is only the up-bar +1 and it stays out of the
    wide-spread branch (low percentiles); it does not touch the multiple-bar block,
    which reads only the period windows.
    """
    candle = Candle("2023-02-01T00:00:00+00:00", 1000, 100.0, 101.25, 99.75, 101.0)
    candle.spread_percentiles = _low_percentiles()
    candle.volume_percentiles = _low_percentiles()
    return candle


@pytest.mark.parametrize(
    ("up_count", "expected_present"),
    [
        (_PERIOD_ONE_SIGNAL_BAR_COUNT - 1, False),  # one below (3) -> absent
        (_PERIOD_ONE_SIGNAL_BAR_COUNT, True),  # exactly at the inclusive boundary (4) -> present
        (_PERIOD_ONE_SIGNAL_BAR_COUNT + 1, True),  # one above (5) -> present
    ],
)
def test_bull_signal_count_boundary(analyzer_factory, up_count, expected_present):
    """Requirements 5.2, 5.6: "Bull Signal" tracks the inclusive >= Signal_Bar_Count boundary.

    period_one has ``Signal_Bar_Count == 4`` and a window size of 5, so up-bar counts of
    3 / 4 / 5 land one below, exactly at, and one above the inclusive boundary. The other
    periods are held in their neutral band and the windows are kept low-percentile (never
    volume-backed), so "Bull Signal (period_one)" is present iff ``up_count >= 4``.
    """
    analyzer = analyzer_factory()
    up_counts = dict(_NEUTRAL_UP_COUNT)
    up_counts["period_one"] = up_count
    _populate_counts(analyzer, up_counts=up_counts)

    result = analyzer.detect_signals(_count_passed_candle())
    signals = result["multiple_bar_signals"]

    label = "Bull Signal (period_one)"
    if expected_present:
        assert label in signals
        # Not volume-backed, so no doubling and no "Volume Backed" companion entry.
        assert "Volume Backed (period_one)" not in signals
    else:
        assert label not in signals
        # One below the bull boundary (count 3) sits in the neutral band {2, 3}: no
        # bear signal either.
        assert "Bear Signal (period_one)" not in signals


# ---------------------------------------------------------------------------
# Task 9.3 -- Acc/Dist test-pass boundaries: period_one spread 65 (strict >)
#            and period_one volume 50 (strict <)
# ---------------------------------------------------------------------------
#
# Once an Acc/Dist base condition holds, ``detect_signals`` evaluates the "Test"
# sub-condition on ``this_candle``::
#
#     if this_candle.spread_percentiles["period_one"] > 65 or this_candle.is_candle_pattern():
#         if this_candle.volume_percentiles["period_one"] < 50:
#             acc_dist_signals.append("Test Pass")
#         else:
#             acc_dist_signals.append("Test Fail")
#
# Two strict boundaries govern the outcome:
#   * The test *candidate* condition fires when period_one spread percentile is
#     strictly > 65 (OR ``is_candle_pattern()`` is True). With no wick pattern, a
#     spread percentile of exactly 65 does NOT make a candidate, 64 does not, and
#     66 does.
#   * Once the candidate fires, the Pass-vs-Fail split turns on period_one volume
#     percentile strictly < 50: exactly 50 is NOT < 50 (Test Fail), 49 is (Test
#     Pass), and 51 is (Test Fail).
#
# We fix an *Accumulation* base condition by reusing the acc_dist test module's
# ``_build_period_three`` / ``_build_period_one`` helpers (imported at module top; they
# read only ``.volume`` and ``.close`` from the windows to force
# ``identify_acc_or_dist`` -> (True, "Acc")). The Climax branch is kept OFF by pinning
# period_two spread at 50 (not < 40), and the ``this_candle`` is built with no wicks so
# ``is_candle_pattern()`` is False and the spread percentile alone governs the candidate.

# period_one close that lands below the period_three 20th price percentile, forcing
# ``identify_acc_or_dist`` to return (True, "Acc") for the reused helpers.
_ACC_LAST_CLOSE = 90.0


def _acc_windows(analyzer):
    """Populate ``analyzer`` with windows that force an Accumulation base condition.

    Reuses the acc_dist test module's constructions: 50 period_three candles (volume
    100, closes 101..150) and 5 period_one candles (volume 500) whose final close sits
    near the lows, so ``identify_acc_or_dist`` returns (True, "Acc"). period_two is set
    to the same period_three list purely to satisfy the multiple-bar block (its output
    is not asserted here).
    """
    period_three = _build_period_three()
    period_one = _build_period_one(last_close=_ACC_LAST_CLOSE)
    populate_windows(analyzer, period_one, list(period_three), period_three)


def _boundary_test_candle(*, period_one_spread, period_one_volume):
    """Build a ``this_candle`` for the Acc/Dist test-pass boundary assertions.

    ``period_one_spread`` drives the candidate boundary (strict > 65) and
    ``period_one_volume`` drives the Pass/Fail boundary (strict < 50). period_two spread
    is pinned at 50 (not < 40) so Climax never fires, and the candle has no wicks so
    ``is_candle_pattern()`` is False -- the spread percentile alone decides the
    candidate. All three period keys are present on both percentile dicts (the acc/dist
    block indexes period_one and period_two; the multiple-bar block indexes every key).
    """
    candle = make_candle(up=True, volume=1000, spread=1.0, upper_wick=0.0, lower_wick=0.0)
    spread = {"period_one": period_one_spread, "period_two": 50, "period_three": 50}
    volume = {"period_one": period_one_volume, "period_two": 50, "period_three": 50}
    set_percentiles(candle, spread=spread, volume=volume)
    return candle


@pytest.mark.parametrize(
    ("spread_value", "candidate_fires"),
    [
        (65, False),  # exactly at the strict > 65 boundary -> no candidate
        (64, False),  # one step below -> no candidate
        (66, True),  # one step above -> candidate fires -> Test Pass (volume kept < 50)
    ],
)
def test_acc_test_candidate_spread_65_boundary(populated_analyzer, spread_value, candidate_fires):
    """Requirement 5.7: the Acc/Dist test-candidate tracks the strict > 65 spread boundary.

    With an Accumulation base condition fixed, the volume percentile held at 40 (< 50)
    and no candle pattern, the "Test" branch only fires when period_one spread is
    strictly > 65. So spread 65 -> neither "Test Pass" nor "Test Fail"; spread 64 ->
    neither; spread 66 -> candidate fires and (volume < 50) -> "Test Pass".
    """
    analyzer = populated_analyzer
    _acc_windows(analyzer)

    result = analyzer.detect_signals(_boundary_test_candle(period_one_spread=spread_value, period_one_volume=40))
    signals = result["acc_dist_signals"]

    # Base Accumulation condition holds regardless of the candidate boundary.
    assert "Possible Acc" in signals
    if candidate_fires:
        # Candidate true and volume 40 < 50 -> Test Pass, no Test Fail.
        assert "Test Pass" in signals
        assert "Test Fail" not in signals
    else:
        # No candidate at/below the boundary -> neither Test outcome present.
        assert "Test Pass" not in signals
        assert "Test Fail" not in signals


@pytest.mark.parametrize(
    ("volume_value", "expected_outcome"),
    [
        (50, "Test Fail"),  # exactly at the strict < 50 boundary -> NOT < 50 -> Test Fail
        (49, "Test Pass"),  # one step below -> < 50 -> Test Pass
        (51, "Test Fail"),  # one step above -> NOT < 50 -> Test Fail
    ],
)
def test_acc_test_pass_volume_50_boundary(populated_analyzer, volume_value, expected_outcome):
    """Requirement 5.7: the Acc/Dist Test Pass/Fail split tracks the strict < 50 volume boundary.

    With an Accumulation base condition fixed and period_one spread held at 70 (> 65 so
    the candidate always fires), the Pass-vs-Fail split turns purely on period_one
    volume percentile < 50: volume 50 -> "Test Fail" (50 is not < 50), volume 49 ->
    "Test Pass", volume 51 -> "Test Fail".
    """
    analyzer = populated_analyzer
    _acc_windows(analyzer)

    result = analyzer.detect_signals(_boundary_test_candle(period_one_spread=70, period_one_volume=volume_value))
    signals = result["acc_dist_signals"]

    assert "Possible Acc" in signals
    # Candidate always fires (spread 70 > 65); exactly one of Test Pass / Test Fail present.
    if expected_outcome == "Test Pass":
        assert "Test Pass" in signals
        assert "Test Fail" not in signals
    else:
        assert "Test Fail" in signals
        assert "Test Pass" not in signals
