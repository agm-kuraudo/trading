"""Single-candle regression tests for ``MarketAnalyzer.detect_signals`` (SP-307, Area B).

These pytest-native example tests exercise the single-candle scoring branch of
``detect_signals`` in isolation. Each test builds a hermetic analyzer via the
``populated_analyzer`` fixture (neutral windows: up bars, percentile buckets at 50,
no wick patterns) so the trend, multiple-bar, and accumulation/distribution blocks
contribute nothing surprising, and asserts specifically on ``single_candle_signals``
and ``single_candle_signal_score``.

The ``this_candle`` passed to ``detect_signals`` is given spread/volume percentile
dicts for all three period keys, all set below the strict ``> 70`` boundary, so no
"Wide Spread"/"High Volume" noise is introduced for these particular tests (those
signals are covered separately by task 5.2).

Requirements: 1.1, 1.2, 1.3, 1.9, 1.10, 11.10.
"""

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from vpa.app import Candle
from vpa.tests.conftest import (
    PERIOD_NAMES,
    make_candle,
    populate_windows,
    set_percentiles,
)

# Apply the hermeticity guards to every test in this module: any accidental network
# access or log-file creation fails the test rather than escaping silently.
pytestmark = pytest.mark.usefixtures("no_network", "null_logger")

# Percentile buckets that sit safely below every single-candle boundary (strict > 70),
# so the wide-spread / high-volume branch is never entered for these tests.
_QUIET_PERCENTILES = dict.fromkeys(PERIOD_NAMES, 50)


def _neutral_candle():
    """A neutral up bar with mid-range percentiles and no wick patterns."""
    candle = make_candle(up=True, volume=1000, spread=1.0, upper_wick=0.0, lower_wick=0.0)
    set_percentiles(candle, spread=dict(_QUIET_PERCENTILES), volume=dict(_QUIET_PERCENTILES))
    return candle


def _adx_safe_candle(index: int):
    """A neutral candle whose price varies with ``index``.

    ``calculate_adx`` (invoked by the trend block of ``detect_signals``) divides by the
    smoothed true range, so a window of identical flat candles produces a
    ``ZeroDivisionError``. Giving each ``period_three`` candle a small, non-zero
    high-low range and a gently varying close keeps the true range positive so the
    trend block runs to completion. These candles are never asserted on -- they only
    exist so the single-candle branch can be reached and measured in isolation.
    """
    base = 100.0 + index
    # open=base, close=base+0.5 (up bar, spread 0.5), with small symmetric wicks so
    # high-low spread is non-zero and no pattern flag is triggered.
    candle = Candle(
        "2023-01-03T00:00:00+00:00",
        1000,
        base,
        base + 0.6,
        base - 0.1,
        base + 0.5,
    )
    set_percentiles(candle, spread=dict(_QUIET_PERCENTILES), volume=dict(_QUIET_PERCENTILES))
    return candle


@pytest.fixture
def neutral_analyzer(analyzer_factory):
    """A hermetic analyzer with neutral windows that keep the non-single-candle blocks quiet.

    ``period_one``/``period_two`` are filled with flat neutral up bars; ``period_three``
    is filled with ADX-safe candles (small non-zero ranges, gently varying closes) so
    the trend block's ``calculate_adx`` call does not divide by zero. None of these
    windows trip the wide-spread/high-volume, bull/bear, or acc/dist boundaries, so the
    single-candle assertions are unaffected by the other blocks.
    """
    analyzer = analyzer_factory()
    deque_dictionary = analyzer._MarketAnalyzer__deque_dictionary
    period_one = [_neutral_candle() for _ in range(deque_dictionary["period_one"].maxlen)]
    period_two = [_neutral_candle() for _ in range(deque_dictionary["period_two"].maxlen)]
    period_three = [_adx_safe_candle(i) for i in range(deque_dictionary["period_three"].maxlen)]
    populate_windows(analyzer, period_one, period_two, period_three)
    return analyzer


def _quiet_candle(*, up: bool, upper_wick: float = 0.0, lower_wick: float = 0.0):
    """Build a ``this_candle`` whose percentiles never trip the > 70 branch.

    Spread percentiles are assigned before volume percentiles (the ``Candle`` volume
    setter reads spread to build its anomaly map), both below the 70 boundary for all
    three periods, so only the up/down-bar and pattern parts of the single-candle
    branch contribute.
    """
    candle = make_candle(up=up, spread=1.0, upper_wick=upper_wick, lower_wick=lower_wick)
    set_percentiles(candle, spread=dict(_QUIET_PERCENTILES), volume=dict(_QUIET_PERCENTILES))
    return candle


def test_up_bar_adds_up_bar_signal_and_plus_one(neutral_analyzer):
    """Requirement 1.1, 1.2: an up bar yields "Up Bar" with a +1 contribution."""
    this_candle = _quiet_candle(up=True)

    result = neutral_analyzer.detect_signals(this_candle)

    assert "Up Bar" in result["single_candle_signals"]
    assert "Down Bar" not in result["single_candle_signals"]
    # With quiet percentiles and no wicks, the only single-candle contribution is the
    # up-bar +1.
    assert result["single_candle_signal_score"] == pytest.approx(1)


def test_down_bar_adds_down_bar_signal_and_minus_one(neutral_analyzer):
    """Requirement 1.1, 1.3: a down bar yields "Down Bar" with a -1 contribution."""
    this_candle = _quiet_candle(up=False)

    result = neutral_analyzer.detect_signals(this_candle)

    assert "Down Bar" in result["single_candle_signals"]
    assert "Up Bar" not in result["single_candle_signals"]
    # The only single-candle contribution is the down-bar -1.
    assert result["single_candle_signal_score"] == pytest.approx(-1)


def test_shooting_star_adds_shooting_star_minus_three_and_no_hammer(neutral_analyzer):
    """Requirement 1.9: a shooting-star candle yields "Shooting Star" (-3), no "Hammer".

    A large upper wick (3.0) relative to the spread (1.0) and a zero lower wick makes
    ``upper_wick > 2 * spread`` and ``upper_wick > 2 * lower_wick`` true (shooting star)
    while never satisfying the long-legged-doji clause. The candle is an up bar, so the
    single-candle score is the up-bar +1 plus the shooting-star -3 = -2, demonstrating
    the -3 shooting-star contribution.
    """
    this_candle = _quiet_candle(up=True, upper_wick=3.0, lower_wick=0.0)

    result = neutral_analyzer.detect_signals(this_candle)

    assert "Shooting Star" in result["single_candle_signals"]
    assert "Hammer" not in result["single_candle_signals"]
    # up-bar (+1) + shooting-star (-3) = -2, isolating the -3 contribution.
    assert result["single_candle_signal_score"] == pytest.approx(1 - 3)


def test_hammer_adds_hammer_plus_three_and_no_shooting_star(neutral_analyzer):
    """Requirement 1.10: a hammer candle yields "Hammer" (+3), no "Shooting Star".

    A large lower wick (3.0) relative to the spread (1.0) and a zero upper wick makes
    ``lower_wick > 2 * spread`` and ``lower_wick > 2 * upper_wick`` true (hammer) while
    never satisfying the long-legged-doji clause. The candle is an up bar, so the
    single-candle score is the up-bar +1 plus the hammer +3 = +4, demonstrating the
    +3 hammer contribution.
    """
    this_candle = _quiet_candle(up=True, upper_wick=0.0, lower_wick=3.0)

    result = neutral_analyzer.detect_signals(this_candle)

    assert "Hammer" in result["single_candle_signals"]
    assert "Shooting Star" not in result["single_candle_signals"]
    # up-bar (+1) + hammer (+3) = +4, isolating the +3 contribution.
    assert result["single_candle_signal_score"] == pytest.approx(1 + 3)


# ---------------------------------------------------------------------------
# Task 5.2 -- wide-spread / high-volume example tests
#
# These tests probe the nested wide-spread / high-volume branch of the
# single-candle block for a single period ("period_one"). ``this_candle`` is
# built with the quiet builder and then has that period's percentiles raised
# above the strict ``> 70`` boundary. The other two periods stay at the quiet 50
# bucket so exactly one "Wide Spread (period_one)" / "High Volume (period_one)"
# pair can fire, keeping the score arithmetic unambiguous.
#
# The single-candle score also carries the up/down-bar +/-1, so each assertion
# accounts for that base contribution alongside the +/-2.5 wide-spread and the
# nested +/-2.5 high-volume adjustments.
#
# Requirements: 1.4, 1.5, 1.6, 1.7, 1.8.
# ---------------------------------------------------------------------------


def _wide_spread_candle(*, up: bool, spread_pct: dict, volume_pct: dict):
    """Build a ``this_candle`` with caller-supplied per-period percentile buckets.

    Uses the same plain up/down bar geometry as ``_quiet_candle`` (spread 1.0, no
    wicks, so no pattern flag fires) but lets the caller dictate the spread and
    volume percentile dictionaries so a chosen period can cross the strict ``> 70``
    boundary. Spread percentiles are assigned before volume percentiles, as the
    ``Candle`` volume setter requires.
    """
    candle = make_candle(up=up, spread=1.0, upper_wick=0.0, lower_wick=0.0)
    set_percentiles(candle, spread=dict(spread_pct), volume=dict(volume_pct))
    return candle


def test_up_bar_wide_spread_adds_signal_and_plus_two_point_five(neutral_analyzer):
    """Requirement 1.4: up bar with spread pct > 70 (volume <= 70) -> "Wide Spread" (+2.5).

    ``period_one`` spread percentile is 71 (strictly above 70) while its volume
    percentile stays at 50, so "Wide Spread (period_one)" fires but the nested
    "High Volume (period_one)" does not. The single-candle score is the up-bar +1
    plus the wide-spread +2.5 = +3.5.
    """
    spread_pct = {**_QUIET_PERCENTILES, "period_one": 71}
    volume_pct = dict(_QUIET_PERCENTILES)
    this_candle = _wide_spread_candle(up=True, spread_pct=spread_pct, volume_pct=volume_pct)

    result = neutral_analyzer.detect_signals(this_candle)
    signals = result["single_candle_signals"]

    assert "Wide Spread (period_one)" in signals
    assert "High Volume (period_one)" not in signals
    # up-bar (+1) + wide-spread (+2.5) = +3.5, isolating the +2.5 wide-spread contribution.
    assert result["single_candle_signal_score"] == pytest.approx(1 + 2.5)


def test_down_bar_wide_spread_adds_signal_and_minus_two_point_five(neutral_analyzer):
    """Requirement 1.5: down bar with spread pct > 70 (volume <= 70) -> "Wide Spread" (-2.5).

    Mirror of the up-bar case: ``period_one`` spread percentile is 71 with volume at
    50, so only "Wide Spread (period_one)" fires. The single-candle score is the
    down-bar -1 plus the wide-spread -2.5 = -3.5.
    """
    spread_pct = {**_QUIET_PERCENTILES, "period_one": 71}
    volume_pct = dict(_QUIET_PERCENTILES)
    this_candle = _wide_spread_candle(up=False, spread_pct=spread_pct, volume_pct=volume_pct)

    result = neutral_analyzer.detect_signals(this_candle)
    signals = result["single_candle_signals"]

    assert "Wide Spread (period_one)" in signals
    assert "High Volume (period_one)" not in signals
    # down-bar (-1) + wide-spread (-2.5) = -3.5, isolating the -2.5 wide-spread contribution.
    assert result["single_candle_signal_score"] == pytest.approx(-1 - 2.5)


def test_up_bar_high_volume_adds_signal_and_plus_two_point_five(neutral_analyzer):
    """Requirement 1.6: up bar with spread AND volume pct > 70 -> "High Volume" (+2.5).

    Both ``period_one`` spread and volume percentiles are 71 (strictly above 70), so
    the nested "High Volume (period_one)" fires alongside "Wide Spread (period_one)".
    The single-candle score is the up-bar +1 plus the wide-spread +2.5 plus the
    high-volume +2.5 = +6.0, isolating the +2.5 high-volume contribution as the delta
    over the wide-spread-only case.
    """
    spread_pct = {**_QUIET_PERCENTILES, "period_one": 71}
    volume_pct = {**_QUIET_PERCENTILES, "period_one": 71}
    this_candle = _wide_spread_candle(up=True, spread_pct=spread_pct, volume_pct=volume_pct)

    result = neutral_analyzer.detect_signals(this_candle)
    signals = result["single_candle_signals"]

    assert "Wide Spread (period_one)" in signals
    assert "High Volume (period_one)" in signals
    # up-bar (+1) + wide-spread (+2.5) + high-volume (+2.5) = +6.0.
    assert result["single_candle_signal_score"] == pytest.approx(1 + 2.5 + 2.5)


def test_down_bar_high_volume_adds_signal_and_minus_two_point_five(neutral_analyzer):
    """Requirement 1.7: down bar with spread AND volume pct > 70 -> "High Volume" (-2.5).

    Mirror of the up-bar high-volume case: both ``period_one`` percentiles are 71, so
    "Wide Spread (period_one)" and the nested "High Volume (period_one)" both fire.
    The single-candle score is the down-bar -1 plus the wide-spread -2.5 plus the
    high-volume -2.5 = -6.0.
    """
    spread_pct = {**_QUIET_PERCENTILES, "period_one": 71}
    volume_pct = {**_QUIET_PERCENTILES, "period_one": 71}
    this_candle = _wide_spread_candle(up=False, spread_pct=spread_pct, volume_pct=volume_pct)

    result = neutral_analyzer.detect_signals(this_candle)
    signals = result["single_candle_signals"]

    assert "Wide Spread (period_one)" in signals
    assert "High Volume (period_one)" in signals
    # down-bar (-1) + wide-spread (-2.5) + high-volume (-2.5) = -6.0.
    assert result["single_candle_signal_score"] == pytest.approx(-1 - 2.5 - 2.5)


def test_high_volume_without_wide_spread_is_suppressed(neutral_analyzer):
    """Requirement 1.8: volume pct > 70 but spread pct == 70 -> neither signal fires.

    "High Volume" is nested inside the wide-spread branch, so a high volume percentile
    alone cannot produce it: with ``period_one`` spread percentile exactly at 70 (NOT
    strictly greater) the whole branch is skipped even though the volume percentile is
    71. Neither "Wide Spread (period_one)" nor "High Volume (period_one)" appears, and
    the up bar contributes only its +1.
    """
    spread_pct = {**_QUIET_PERCENTILES, "period_one": 70}
    volume_pct = {**_QUIET_PERCENTILES, "period_one": 71}
    this_candle = _wide_spread_candle(up=True, spread_pct=spread_pct, volume_pct=volume_pct)

    result = neutral_analyzer.detect_signals(this_candle)
    signals = result["single_candle_signals"]

    assert "Wide Spread (period_one)" not in signals
    assert "High Volume (period_one)" not in signals
    # Only the up-bar +1 contributes.
    assert result["single_candle_signal_score"] == pytest.approx(1)


def test_spread_at_boundary_excludes_wide_spread_and_high_volume(neutral_analyzer):
    """Requirement 1.8: spread pct exactly at 70 (not strictly >) -> neither signal present.

    Confirms the strict ``> 70`` boundary directly: with ``period_one`` spread
    percentile at exactly 70 and volume at the quiet 50, neither "Wide Spread
    (period_one)" nor "High Volume (period_one)" appears for that period, and the up
    bar contributes only its +1.
    """
    spread_pct = {**_QUIET_PERCENTILES, "period_one": 70}
    volume_pct = dict(_QUIET_PERCENTILES)
    this_candle = _wide_spread_candle(up=True, spread_pct=spread_pct, volume_pct=volume_pct)

    result = neutral_analyzer.detect_signals(this_candle)
    signals = result["single_candle_signals"]

    assert "Wide Spread (period_one)" not in signals
    assert "High Volume (period_one)" not in signals
    assert result["single_candle_signal_score"] == pytest.approx(1)


# ---------------------------------------------------------------------------
# Task 5.3 -- property test for the wide-spread / high-volume 70 boundary
#
# This hypothesis property generalises the task 5.2 examples across the whole
# integer percentile input space around the strict ``> 70`` boundary. For a
# randomly chosen period, a randomly chosen spread percentile and volume
# percentile (both spanning 5..95, so both sides of 70 are exercised), and a
# random bar direction, it asserts the exact iff relationship the single-candle
# block implements:
#
#   "Wide Spread (<period>)" in single_candle_signals  <==>  spread_pct > 70
#   "High Volume (<period>)" in single_candle_signals   <==>  (spread_pct > 70 and
#                                                              volume_pct > 70)
#
# The other two periods are held quiet (percentiles at 50, below 70) so exactly
# one period can fire, and the chosen period's presence/absence is unambiguous.
# The analyzer reused is the module's hermetic, ADX-safe ``neutral_analyzer``
# fixture, so no network access or log file is touched.
#
# Requirements: 1.4, 1.6, 1.8, 5.5 (Property 2).
# ---------------------------------------------------------------------------

# Percentile values spanning both sides of the strict > 70 boundary (5..95),
# so the generator covers absent (<= 70) and present (> 70) outcomes alike.
_PERCENTILE_RANGE = st.integers(min_value=5, max_value=95)


# Feature: marketanalyzer-signal-detection-tests, Property 2: Wide-spread / high-volume presence tracks the 70 boundary
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    period=st.sampled_from(PERIOD_NAMES),
    spread_pct=_PERCENTILE_RANGE,
    volume_pct=_PERCENTILE_RANGE,
    up=st.booleans(),
)
def test_wide_spread_high_volume_presence_tracks_70_boundary(
    neutral_analyzer, period, spread_pct, volume_pct, up
):
    """Property 2: "Wide Spread"/"High Volume" presence tracks the strict > 70 boundary.

    For any candle, chosen period, and up/down direction, "Wide Spread (<period>)"
    appears in ``single_candle_signals`` iff that period's spread percentile is
    strictly greater than 70, and "High Volume (<period>)" appears iff additionally
    the volume percentile is strictly greater than 70. Signal presence is therefore
    monotonic around the strict boundary 70.

    **Validates: Requirements 1.4, 1.6, 1.8, 5.5**
    """
    # Build this_candle with the chosen period raised to the generated percentiles
    # while the other two periods stay quiet (50, below the boundary), so only the
    # chosen period can fire. Spread is assigned before volume via _wide_spread_candle.
    spread = {**_QUIET_PERCENTILES, period: spread_pct}
    volume = {**_QUIET_PERCENTILES, period: volume_pct}
    this_candle = _wide_spread_candle(up=up, spread_pct=spread, volume_pct=volume)

    result = neutral_analyzer.detect_signals(this_candle)
    signals = result["single_candle_signals"]

    wide_spread_label = f"Wide Spread ({period})"
    high_volume_label = f"High Volume ({period})"

    expected_wide_spread = spread_pct > 70
    expected_high_volume = spread_pct > 70 and volume_pct > 70

    assert (wide_spread_label in signals) == expected_wide_spread, (
        f"Wide Spread presence mismatch for {period}: spread_pct={spread_pct}, "
        f"expected present={expected_wide_spread}"
    )
    assert (high_volume_label in signals) == expected_high_volume, (
        f"High Volume presence mismatch for {period}: spread_pct={spread_pct}, "
        f"volume_pct={volume_pct}, expected present={expected_high_volume}"
    )
