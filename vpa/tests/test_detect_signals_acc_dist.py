"""Accumulation/Distribution regression tests for ``MarketAnalyzer.detect_signals`` (SP-307).

Task 8.1 -- BASE Acc/Dist condition only:

- Accumulation: force ``identify_acc_or_dist(period_three, period_one)`` to return
  ``(True, "Acc")`` and assert ``acc_dist_signals`` contains ``"Possible Acc"`` with a
  ``+10`` contribution to ``acc_dist_signal_score``.
- Distribution: force ``(True, "Dist")`` and assert ``acc_dist_signals`` contains
  ``"Possible Dist"`` with a ``-10`` contribution.

The tests deliberately keep ``this_candle`` neutral so that the *sub*-conditions of the
acc/dist block do NOT fire, isolating the base +10 / -10 outcome:

- Test Pass / Test Fail requires ``this_candle.spread_percentiles["period_one"] > 65``
  OR ``this_candle.is_candle_pattern()``. We set period_one spread to ``50`` (<= 65)
  and build ``this_candle`` with no wicks (no pattern), so this branch is skipped.
- Climax requires ``this_candle.spread_percentiles["period_two"] < 40`` AND
  ``this_candle.volume_percentiles["period_two"] > 60``. We set period_two spread to
  ``50`` (not < 40), so this branch is skipped.

Requirements: 4.1, 4.2, 4.3.

How ``identify_acc_or_dist`` is forced (it reads only ``.volume`` and ``.close``):

- ``period_three`` (50 candles): all volume ``100`` and closes spread across ``101..150``.
  ``np.percentile(volumes, 65) == 100`` so any period_one candle with volume ``> 100``
  counts toward ``high_volume_count``. ``np.percentile(closes, [10, 20, 80])`` yields a
  20th percentile around ``111`` and an 80th percentile around ``140``.
- ``period_one`` (5 candles): all volume ``500`` (> 100) so ``high_volume_count == 5 >= 3``.
  The last candle's close decides direction:
    * Acc  -> ``period_one[-1].close = 90`` which is ``< p3_price_20`` (near lows).
    * Dist -> ``period_one[-1].close = 200`` which is ``> p3_price_80`` (near highs).
"""

import numpy as np
import pytest

from vpa.tests.conftest import (
    PERIOD_NAMES,
    make_candle,
    populate_windows,
    set_percentiles,
)

# Neutral percentile buckets that keep every boundary-sensitive branch quiet:
# - period_one spread 50 (<= 65) and no candle pattern -> Test Pass/Fail skipped.
# - period_two spread 50 (not < 40) -> Climax skipped.
NEUTRAL_PERCENTILES = dict.fromkeys(PERIOD_NAMES, 50)


def _neutral_this_candle():
    """A plain up bar with neutral percentiles and no pattern flags.

    Used as the ``this_candle`` argument so the acc/dist sub-conditions (Test
    Pass/Fail, Climax) never fire and only the base +10 / -10 outcome is asserted.
    """
    candle = make_candle(up=True, volume=1000, spread=1.0, upper_wick=0.0, lower_wick=0.0)
    set_percentiles(candle, spread=dict(NEUTRAL_PERCENTILES), volume=dict(NEUTRAL_PERCENTILES))
    return candle


def _build_period_three():
    """50 candles, all volume 100, closes spread across 101..150.

    Only ``.volume`` and ``.close`` are read by ``identify_acc_or_dist``; percentile
    dicts are set neutrally so the (unasserted) multiple-bar block does not KeyError.
    An up bar with ``spread=i`` has ``close = 100 + i`` (see ``make_candle``), giving
    closes 101..150 for i in 1..50.
    """
    candles = []
    for i in range(1, 51):
        candle = make_candle(up=True, volume=100, spread=float(i), upper_wick=0.0, lower_wick=0.0)
        set_percentiles(candle, spread=dict(NEUTRAL_PERCENTILES), volume=dict(NEUTRAL_PERCENTILES))
        candles.append(candle)
    return candles


def _build_period_one(last_close):
    """5 candles, all volume 500 (> p3 65th percentile of 100), so high_volume_count == 5.

    The last candle's close is set precisely to ``last_close`` to place it below the
    period_three 20th price percentile (Acc) or above the 80th (Dist).
    """
    candles = []
    for _ in range(4):
        candle = make_candle(up=True, volume=500, spread=1.0, upper_wick=0.0, lower_wick=0.0)
        set_percentiles(candle, spread=dict(NEUTRAL_PERCENTILES), volume=dict(NEUTRAL_PERCENTILES))
        candles.append(candle)

    # Build the final candle with the exact requested close. make_candle anchors the
    # open at 100.0, so for an up bar close = 100 + spread and for a down bar
    # close = 100 - spread. Pick direction/spread to hit last_close exactly.
    if last_close >= 100.0:
        last_candle = make_candle(up=True, volume=500, spread=last_close - 100.0)
    else:
        last_candle = make_candle(up=False, volume=500, spread=100.0 - last_close)
    set_percentiles(last_candle, spread=dict(NEUTRAL_PERCENTILES), volume=dict(NEUTRAL_PERCENTILES))
    candles.append(last_candle)
    return candles


def test_period_three_percentile_assumptions_hold():
    """Guard: confirm the constructed period_three yields the percentiles we rely on.

    Documents (and asserts) the data-construction reasoning so a future change to
    ``make_candle`` that breaks the volume/close distribution fails here loudly rather
    than silently weakening the Acc/Dist tests below.
    """
    period_three = _build_period_three()
    volumes = [c.volume for c in period_three]
    closes = [c.close for c in period_three]

    vol_65 = np.percentile(volumes, [65, 90])[0]
    price_10, price_20, price_80 = np.percentile(closes, [10, 20, 80])

    # period_one volume 500 must exceed the 65th volume percentile.
    assert 500 > vol_65
    # Acc target close 90 must be below the 20th price percentile.
    assert 90 < price_20
    # Dist target close 200 must be above the 80th price percentile.
    assert 200 > price_80


def test_base_accumulation_possible_acc_plus_ten(populated_analyzer):
    """(True, "Acc") -> "Possible Acc" present and +10 base contribution.

    Validates: Requirements 4.1, 4.2
    """
    analyzer = populated_analyzer

    period_three = _build_period_three()
    # Acc: last period_one close below the 20th price percentile (near lows).
    period_one = _build_period_one(last_close=90.0)
    populate_windows(analyzer, period_one, list(period_three), period_three)

    result = analyzer.detect_signals(_neutral_this_candle())

    assert "Possible Acc" in result["acc_dist_signals"]
    assert "Possible Dist" not in result["acc_dist_signals"]
    # Base condition only: no Test Pass/Fail, no Climax -> score is exactly +10.
    assert "Test Pass" not in result["acc_dist_signals"]
    assert "Test Fail" not in result["acc_dist_signals"]
    assert "Climax" not in result["acc_dist_signals"]
    assert result["acc_dist_signal_score"] == pytest.approx(10)


def test_base_distribution_possible_dist_minus_ten(populated_analyzer):
    """(True, "Dist") -> "Possible Dist" present and -10 base contribution.

    Validates: Requirements 4.1, 4.3
    """
    analyzer = populated_analyzer

    period_three = _build_period_three()
    # Dist: last period_one close above the 80th price percentile (near highs).
    period_one = _build_period_one(last_close=200.0)
    populate_windows(analyzer, period_one, list(period_three), period_three)

    result = analyzer.detect_signals(_neutral_this_candle())

    assert "Possible Dist" in result["acc_dist_signals"]
    assert "Possible Acc" not in result["acc_dist_signals"]
    # Base condition only: no Test Pass/Fail, no Climax -> score is exactly -10.
    assert "Test Pass" not in result["acc_dist_signals"]
    assert "Test Fail" not in result["acc_dist_signals"]
    assert "Climax" not in result["acc_dist_signals"]
    assert result["acc_dist_signal_score"] == pytest.approx(-10)


# ---------------------------------------------------------------------------
# Task 8.2 -- Test Pass / Test Fail sub-condition (Requirements 4.4, 4.5, 4.6, 4.7)
# ---------------------------------------------------------------------------
#
# Once an Acc/Dist base condition holds, ``detect_signals`` evaluates the "Test"
# sub-condition on ``this_candle``::
#
#     if this_candle.spread_percentiles["period_one"] > 65 or this_candle.is_candle_pattern():
#         if this_candle.volume_percentiles["period_one"] < 50:
#             acc_dist_signals.append("Test Pass")
#             acc_dist_signal_score += 5 if acc == "Acc" else -5
#         else:
#             acc_dist_signals.append("Test Fail")
#             acc_dist_signal_score -= 2 if acc == "Acc" else 2   # i.e. -2 (Acc) / +2 (Dist)
#
# The Climax sub-condition (period_two spread < 40 AND period_two volume > 60) is
# kept OFF by leaving period_two spread at 50 (not < 40), so only the base +10 / -10
# and the Test Pass / Test Fail adjustment contribute to ``acc_dist_signal_score``.
#
# ``this_candle`` is built with the needed period_one / period_two percentiles via
# ``set_percentiles`` (spread then volume, all three keys), reusing the existing
# ``_build_period_three`` / ``_build_period_one`` helpers to force Acc vs Dist.


def _test_candle(*, period_one_spread, period_one_volume):
    """Build a ``this_candle`` that drives the Test Pass / Test Fail branch.

    The Test *candidate* condition fires when period_one spread percentile > 65 (we
    supply that via ``period_one_spread``); the Pass vs Fail outcome is then decided
    by whether period_one volume percentile < 50 (``period_one_volume``). period_two
    spread is pinned at 50 (not < 40) so the Climax branch stays silent, and the
    candle itself has no wicks so ``is_candle_pattern()`` is False -- the spread
    percentile alone governs the candidate condition.
    """
    candle = make_candle(up=True, volume=1000, spread=1.0, upper_wick=0.0, lower_wick=0.0)
    spread = {"period_one": period_one_spread, "period_two": 50, "period_three": 50}
    volume = {"period_one": period_one_volume, "period_two": 50, "period_three": 50}
    set_percentiles(candle, spread=spread, volume=volume)
    return candle


def test_accumulation_test_pass_plus_five(populated_analyzer):
    """Acc + Test Pass: period_one spread > 65 AND volume < 50 -> "Test Pass", +5.

    Base +10 plus the +5 test-pass adjustment gives a total score of +15.

    Validates: Requirements 4.4
    """
    analyzer = populated_analyzer

    period_three = _build_period_three()
    period_one = _build_period_one(last_close=90.0)  # Acc (near lows)
    populate_windows(analyzer, period_one, list(period_three), period_three)

    # Candidate true (spread 70 > 65) and volume 40 < 50 -> Test Pass.
    result = analyzer.detect_signals(_test_candle(period_one_spread=70, period_one_volume=40))

    assert "Possible Acc" in result["acc_dist_signals"]
    assert "Test Pass" in result["acc_dist_signals"]
    assert "Test Fail" not in result["acc_dist_signals"]
    assert "Climax" not in result["acc_dist_signals"]
    # Base +10 + Test Pass +5 = +15.
    assert result["acc_dist_signal_score"] == pytest.approx(15)


def test_distribution_test_pass_minus_five(populated_analyzer):
    """Dist + Test Pass: period_one spread > 65 AND volume < 50 -> "Test Pass", -5.

    Base -10 plus the -5 test-pass adjustment gives a total score of -15.

    Validates: Requirements 4.5
    """
    analyzer = populated_analyzer

    period_three = _build_period_three()
    period_one = _build_period_one(last_close=200.0)  # Dist (near highs)
    populate_windows(analyzer, period_one, list(period_three), period_three)

    # Candidate true (spread 70 > 65) and volume 40 < 50 -> Test Pass.
    result = analyzer.detect_signals(_test_candle(period_one_spread=70, period_one_volume=40))

    assert "Possible Dist" in result["acc_dist_signals"]
    assert "Test Pass" in result["acc_dist_signals"]
    assert "Test Fail" not in result["acc_dist_signals"]
    assert "Climax" not in result["acc_dist_signals"]
    # Base -10 + Test Pass -5 = -15.
    assert result["acc_dist_signal_score"] == pytest.approx(-15)


def test_accumulation_test_fail_minus_two(populated_analyzer):
    """Acc + Test Fail: candidate true (spread > 65) but volume NOT < 50 -> "Test Fail", -2.

    Base +10 minus the 2-point test-fail penalty gives a total score of +8.

    Validates: Requirements 4.6
    """
    analyzer = populated_analyzer

    period_three = _build_period_three()
    period_one = _build_period_one(last_close=90.0)  # Acc (near lows)
    populate_windows(analyzer, period_one, list(period_three), period_three)

    # Candidate true (spread 70 > 65) but volume 60 NOT < 50 -> Test Fail.
    result = analyzer.detect_signals(_test_candle(period_one_spread=70, period_one_volume=60))

    assert "Possible Acc" in result["acc_dist_signals"]
    assert "Test Fail" in result["acc_dist_signals"]
    assert "Test Pass" not in result["acc_dist_signals"]
    assert "Climax" not in result["acc_dist_signals"]
    # Base +10 + Test Fail -2 = +8.
    assert result["acc_dist_signal_score"] == pytest.approx(8)


def test_distribution_test_fail_plus_two(populated_analyzer):
    """Dist + Test Fail: candidate true (spread > 65) but volume NOT < 50 -> "Test Fail", +2.

    Base -10 plus the +2 test-fail adjustment gives a total score of -8.

    Validates: Requirements 4.7
    """
    analyzer = populated_analyzer

    period_three = _build_period_three()
    period_one = _build_period_one(last_close=200.0)  # Dist (near highs)
    populate_windows(analyzer, period_one, list(period_three), period_three)

    # Candidate true (spread 70 > 65) but volume 60 NOT < 50 -> Test Fail.
    result = analyzer.detect_signals(_test_candle(period_one_spread=70, period_one_volume=60))

    assert "Possible Dist" in result["acc_dist_signals"]
    assert "Test Fail" in result["acc_dist_signals"]
    assert "Test Pass" not in result["acc_dist_signals"]
    assert "Climax" not in result["acc_dist_signals"]
    # Base -10 + Test Fail +2 = -8.
    assert result["acc_dist_signal_score"] == pytest.approx(-8)


# ---------------------------------------------------------------------------
# Task 8.3 -- Climax sub-condition (Requirements 4.8, 4.9)
# ---------------------------------------------------------------------------
#
# The Climax sub-condition is evaluated independently of Test Pass / Test Fail
# whenever an Acc/Dist base condition holds::
#
#     if this_candle.spread_percentiles["period_two"] < 40 and this_candle.volume_percentiles["period_two"] > 60:
#         acc_dist_signals.append("Climax")
#         acc_dist_signal_score += 10 if acc_or_dist == "Acc" else -10
#
# To isolate the Climax +10 / -10 contribution cleanly, ``this_candle`` is built so
# the Test Pass / Test Fail *candidate* condition is FALSE:
#
# - period_one spread percentile 50 (<= 65), so the spread half of the candidate is off.
# - no wicks, so ``is_candle_pattern()`` is False (the other half of the candidate).
#
# With the Test branch skipped, only the base (+10 / -10) and Climax (+10 / -10)
# contribute, giving a total of +20 (Acc) or -20 (Dist).


def _climax_candle():
    """Build a ``this_candle`` that drives the Climax branch and nothing else.

    period_two spread percentile 30 (< 40) AND period_two volume percentile 70 (> 60)
    satisfy the Climax condition. period_one spread percentile 50 (<= 65) plus no wicks
    (``is_candle_pattern()`` False) keep the Test Pass / Test Fail candidate condition
    FALSE, so only the base +10 / -10 and Climax +10 / -10 contribute.
    """
    candle = make_candle(up=True, volume=1000, spread=1.0, upper_wick=0.0, lower_wick=0.0)
    spread = {"period_one": 50, "period_two": 30, "period_three": 50}
    volume = {"period_one": 50, "period_two": 70, "period_three": 50}
    set_percentiles(candle, spread=spread, volume=volume)
    return candle


def test_accumulation_climax_plus_ten(populated_analyzer):
    """Acc + Climax: period_two spread < 40 AND volume > 60 -> "Climax", +10.

    Base +10 plus the +10 climax contribution gives a total score of +20, with the
    Test Pass / Test Fail candidate condition held false so it does not perturb it.

    Validates: Requirements 4.8
    """
    analyzer = populated_analyzer

    period_three = _build_period_three()
    period_one = _build_period_one(last_close=90.0)  # Acc (near lows)
    populate_windows(analyzer, period_one, list(period_three), period_three)

    result = analyzer.detect_signals(_climax_candle())

    assert "Possible Acc" in result["acc_dist_signals"]
    assert "Climax" in result["acc_dist_signals"]
    # Test branch held off so only base +10 and Climax +10 contribute.
    assert "Test Pass" not in result["acc_dist_signals"]
    assert "Test Fail" not in result["acc_dist_signals"]
    # Base +10 + Climax +10 = +20.
    assert result["acc_dist_signal_score"] == pytest.approx(20)


def test_distribution_climax_minus_ten(populated_analyzer):
    """Dist + Climax: period_two spread < 40 AND volume > 60 -> "Climax", -10.

    Base -10 plus the -10 climax contribution gives a total score of -20, with the
    Test Pass / Test Fail candidate condition held false so it does not perturb it.

    Validates: Requirements 4.9
    """
    analyzer = populated_analyzer

    period_three = _build_period_three()
    period_one = _build_period_one(last_close=200.0)  # Dist (near highs)
    populate_windows(analyzer, period_one, list(period_three), period_three)

    result = analyzer.detect_signals(_climax_candle())

    assert "Possible Dist" in result["acc_dist_signals"]
    assert "Climax" in result["acc_dist_signals"]
    # Test branch held off so only base -10 and Climax -10 contribute.
    assert "Test Pass" not in result["acc_dist_signals"]
    assert "Test Fail" not in result["acc_dist_signals"]
    # Base -10 + Climax -10 = -20.
    assert result["acc_dist_signal_score"] == pytest.approx(-20)


# ---------------------------------------------------------------------------
# Task 8.4 -- Property 4: Acc/Dist "Test Pass" presence tracks the 65 and 50 boundaries
# ---------------------------------------------------------------------------
#
# Reuses the base-condition and candle helpers above (``_build_period_three`` /
# ``_build_period_one`` force ``identify_acc_or_dist`` -> (True, "Acc"); ``_test_candle``
# builds a wick-free ``this_candle`` so ``is_candle_pattern()`` is False and the Test
# *candidate* condition is governed purely by ``spread_percentiles["period_one"] > 65``).
#
# The property samples the period_one spread percentile across both sides of 65 and the
# period_one volume percentile across both sides of 50, and asserts the exact Test
# Pass / Test Fail iff-relationship from the code under test (Climax stays OFF because
# ``_test_candle`` pins period_two spread at 50, not < 40).

from hypothesis import HealthCheck, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402


# Feature: marketanalyzer-signal-detection-tests, Property 4: Acc/Dist "Test Pass" presence tracks the 65 and 50 boundaries  # noqa: E501
# The function-scoped ``populated_analyzer`` fixture is intentionally reused across
# generated inputs: each example fully overwrites the analyzer's three rolling windows
# via ``populate_windows`` before invoking ``detect_signals``, and the result depends
# only on that freshly-set window state plus ``this_candle`` (no residual state leaks),
# so suppressing the function-scoped-fixture health check is safe here.
@settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    # period_one spread percentile spanning both sides of the strict 65 candidate boundary.
    period_one_spread=st.integers(min_value=55, max_value=75),
    # period_one volume percentile spanning both sides of the strict 50 pass boundary.
    period_one_volume=st.integers(min_value=40, max_value=60),
)
def test_acc_dist_test_pass_tracks_65_and_50_boundaries(
    populated_analyzer, period_one_spread, period_one_volume
):
    """"Test Pass" presence tracks the 65 (candidate) and 50 (pass) boundaries.

    Under an established Accumulation condition, and with a wick-free ``this_candle``
    (so ``is_candle_pattern()`` is False), the Test candidate is governed purely by
    ``spread_percentiles["period_one"] > 65``. The property asserts, for any sampled
    spread/volume percentiles:

    - "Test Pass" appears iff (candidate AND volume < 50);
    - "Test Fail" appears iff (candidate AND NOT volume < 50);
    - when the candidate is false, neither "Test Pass" nor "Test Fail" appears.

    Validates: Requirements 4.4, 4.5, 4.6, 4.7, 5.7
    """
    analyzer = populated_analyzer

    period_three = _build_period_three()
    period_one = _build_period_one(last_close=90.0)  # Acc (near lows)
    populate_windows(analyzer, period_one, list(period_three), period_three)

    result = analyzer.detect_signals(
        _test_candle(period_one_spread=period_one_spread, period_one_volume=period_one_volume)
    )
    signals = result["acc_dist_signals"]

    # The Accumulation base condition holds regardless of the sampled boundaries.
    assert "Possible Acc" in signals

    candidate = period_one_spread > 65
    pass_expected = candidate and period_one_volume < 50
    fail_expected = candidate and not (period_one_volume < 50)

    assert ("Test Pass" in signals) == pass_expected
    assert ("Test Fail" in signals) == fail_expected

    if not candidate:
        assert "Test Pass" not in signals
        assert "Test Fail" not in signals
