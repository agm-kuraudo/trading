"""Determinism regression test for ``MarketAnalyzer.detect_signals`` (SP-307, Area E).

This pytest-native example test exercises the determinism / idempotence guarantee of
``detect_signals``: invoking the method repeatedly with the *same* populated analyzer
and the *same* ``this_candle`` must yield identical signal lists and identical scores
on every call. ``detect_signals`` reads the rolling-window deques and ``this_candle``
but rebuilds all of its result lists/dicts on each call and never mutates that input
state, so repeated invocations are expected to be pure over their inputs.

To make the check meaningful (rather than comparing four empty lists), the fixed
inputs are chosen to light up several signal categories at once:

- **Single-candle:** ``this_candle`` is an up bar whose ``period_one`` spread AND
  volume percentiles are strictly above the ``> 70`` boundary (so "Wide Spread" and
  the nested "High Volume" fire) and which also exhibits a hammer wick pattern (so
  "Hammer" fires).
- **Multiple-bar:** the ``populated_analyzer`` baseline fills every window with up
  bars, so each period's up-bar count reaches its ``Signal_Bar_Count`` threshold and
  "Bull Signal (<period>)" entries are produced.
- **Trend:** the ADX-safe baseline lets the trend block run to completion (no
  ``ZeroDivisionError``) without crossing the trending threshold.

Percentiles are assigned for all three period keys (spread then volume, per the
``Candle`` setter ordering) so ``detect_signals`` can index every period without a
``KeyError``.

Requirements: 1.11, 6.3.
"""

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from vpa.tests.conftest import (
    PERIOD_NAMES,
    make_candle,
    make_neutral_window_candle,
    populate_windows,
    set_percentiles,
)

# Apply the hermeticity guards to every test in this module: any accidental network
# access or log-file creation fails the test rather than escaping silently.
pytestmark = pytest.mark.usefixtures("no_network", "null_logger")

# Number of successive invocations to compare (Requirement 6.3: "executed ten times").
_INVOCATION_COUNT = 10

# The four signal-list keys and the four score keys of the detect_signals contract.
_SIGNAL_LIST_KEYS = (
    "single_candle_signals",
    "trend_signals",
    "multiple_bar_signals",
    "acc_dist_signals",
)
_SCORE_KEYS = (
    "single_candle_signal_score",
    "trend_signal_score",
    "multiple_bar_signal_score",
    "acc_dist_signal_score",
)


def _multi_signal_candle():
    """Build a fixed ``this_candle`` that trips several single-candle signals.

    The candle is an up bar with:

    - a hammer wick pattern (``lower_wick`` 3.0 vs ``spread`` 1.0, zero upper wick, so
      ``lower_wick > 2 * spread`` and ``lower_wick > 2 * upper_wick`` -> hammer, with no
      accidental long-legged doji), and
    - ``period_one`` spread AND volume percentiles at 71 (strictly above the ``> 70``
      boundary) so both "Wide Spread (period_one)" and the nested "High Volume
      (period_one)" fire, while the other two periods stay at the quiet 50 bucket.

    Percentiles are set for all three period keys (spread then volume) so every period
    in the deque dictionary can be indexed by ``detect_signals``.
    """
    candle = make_candle(up=True, volume=1000, spread=1.0, upper_wick=0.0, lower_wick=3.0)
    spread_pct = {**dict.fromkeys(PERIOD_NAMES, 50), "period_one": 71}
    volume_pct = {**dict.fromkeys(PERIOD_NAMES, 50), "period_one": 71}
    set_percentiles(candle, spread=spread_pct, volume=volume_pct)
    return candle


def test_detect_signals_repeated_invocation_is_deterministic(populated_analyzer):
    """Requirements 1.11, 6.3: ten identical invocations produce identical results.

    Calls ``detect_signals`` ten times in succession on the same populated analyzer
    with the same ``this_candle`` and asserts that all four signal lists and all four
    scores are equal to the first invocation's results every time. The fixed inputs
    exercise the single-candle (up bar, wide spread, high volume, hammer) and
    multiple-bar (baseline up-bar bull signals) categories, so the determinism check
    compares populated, non-trivial results rather than empty lists.
    """
    this_candle = _multi_signal_candle()

    results = [populated_analyzer.detect_signals(this_candle) for _ in range(_INVOCATION_COUNT)]

    first = results[0]

    # Sanity: the fixed inputs must exercise more than just empty lists, otherwise the
    # determinism assertion would be vacuous.
    assert "Up Bar" in first["single_candle_signals"]
    assert "Wide Spread (period_one)" in first["single_candle_signals"]
    assert "High Volume (period_one)" in first["single_candle_signals"]
    assert "Hammer" in first["single_candle_signals"]
    assert first["multiple_bar_signals"], "expected the baseline windows to produce multiple-bar signals"

    # Every subsequent invocation must reproduce the first invocation's lists exactly.
    for invocation_index, result in enumerate(results):
        for list_key in _SIGNAL_LIST_KEYS:
            assert result[list_key] == first[list_key], (
                f"invocation {invocation_index} differs from invocation 0 for {list_key}"
            )
        for score_key in _SCORE_KEYS:
            assert result[score_key] == pytest.approx(first[score_key]), (
                f"invocation {invocation_index} differs from invocation 0 for {score_key}"
            )


# ---------------------------------------------------------------------------
# Property-based determinism / idempotence test (task 10.2, Area E).
#
# Property 1 is the universal form of the example test above: rather than one
# fixed input exercised ten times, hypothesis generates a varied-but-valid input
# space (up/down this_candle, a couple of period_one spread/volume percentile
# values spanning the strict > 70 boundary, and a wick pattern choice), builds a
# fresh hermetic analyzer per example, and asserts that two successive
# invocations on the SAME generated inputs return byte-for-byte-equal results
# (all four signal lists equal and all four scores equal).
#
# Note on scope: the property is same-input-repeated-call equality, NOT
# cross-example equality -- each hypothesis example constructs its own
# this_candle and its own analyzer, calls detect_signals twice with those exact
# inputs, and compares the two results. The generators only vary inputs to widen
# the space over which repeated-call determinism is demonstrated.
#
# Hermeticity: the module-level ``pytestmark`` already applies ``no_network`` and
# ``null_logger`` to every test here, and the analyzer is built through the
# hermetic ``analyzer_factory`` (which depends on both), so no network access or
# log file is touched. The windows are filled with the ADX-safe neutral baseline
# candle so the trend block runs to completion without a ZeroDivisionError.
#
# Requirements: 1.11, 6.3 (Property 1).
# ---------------------------------------------------------------------------

# Percentile values spanning both sides of the strict > 70 boundary (5..95), so
# the generated this_candle sometimes fires the wide-spread / high-volume branch
# and sometimes does not -- widening the input space over which repeated-call
# determinism is asserted.
_PERCENTILE_RANGE = st.integers(min_value=5, max_value=95)

# Wick pattern choices: a plain bar (no pattern), a shooting star (large upper
# wick), or a hammer (large lower wick). Each is expressed as an
# ``(upper_wick, lower_wick)`` pair relative to the fixed spread of 1.0.
_WICK_CHOICES = st.sampled_from(
    [
        (0.0, 0.0),  # plain bar, no pattern flag
        (3.0, 0.0),  # shooting star: upper_wick > 2 * spread and > 2 * lower_wick
        (0.0, 3.0),  # hammer: lower_wick > 2 * spread and > 2 * upper_wick
    ]
)


def _build_populated_analyzer(analyzer_factory):
    """Build a fresh hermetic analyzer with ADX-safe neutral rolling windows.

    Mirrors the ``populated_analyzer`` fixture but is callable inside a hypothesis
    example so each generated case gets its own untouched analyzer (the property is
    repeated-call equality per example, so a fresh analyzer per example keeps
    examples independent).
    """
    analyzer = analyzer_factory()
    deque_dictionary = analyzer._MarketAnalyzer__deque_dictionary
    period_one = [make_neutral_window_candle(i) for i in range(deque_dictionary["period_one"].maxlen)]
    period_two = [make_neutral_window_candle(i) for i in range(deque_dictionary["period_two"].maxlen)]
    period_three = [make_neutral_window_candle(i) for i in range(deque_dictionary["period_three"].maxlen)]
    populate_windows(analyzer, period_one, period_two, period_three)
    return analyzer


# Feature: marketanalyzer-signal-detection-tests, Property 1: `detect_signals` is deterministic and idempotent
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    up=st.booleans(),
    spread_pct=_PERCENTILE_RANGE,
    volume_pct=_PERCENTILE_RANGE,
    wicks=_WICK_CHOICES,
)
def test_detect_signals_is_deterministic_and_idempotent(
    analyzer_factory, up, spread_pct, volume_pct, wicks
):
    """Property 1: repeated ``detect_signals`` calls on identical inputs are identical.

    For any generated ``this_candle`` (up/down direction, a ``period_one`` spread and
    volume percentile spanning the strict ``> 70`` boundary, and a wick pattern choice)
    over a fresh analyzer whose rolling windows hold the fixed ADX-safe neutral candle
    set, invoking ``detect_signals(this_candle)`` twice with the SAME inputs yields
    identical ``single_candle_signals``, ``trend_signals``, ``multiple_bar_signals``,
    ``acc_dist_signals`` and all four score values on every invocation.

    The generators vary the inputs only to widen the space over which repeated-call
    equality is demonstrated; each example builds its own ``this_candle`` and analyzer
    and compares that example's two invocations, never comparing across examples.

    **Validates: Requirements 1.11, 6.3**
    """
    upper_wick, lower_wick = wicks
    analyzer = _build_populated_analyzer(analyzer_factory)

    this_candle = make_candle(
        up=up, volume=1000, spread=1.0, upper_wick=upper_wick, lower_wick=lower_wick
    )
    # Raise only period_one to the generated buckets; the other periods stay quiet at
    # 50 (below the strict boundaries). Spread is set before volume per the setter.
    spread = {**dict.fromkeys(PERIOD_NAMES, 50), "period_one": spread_pct}
    volume = {**dict.fromkeys(PERIOD_NAMES, 50), "period_one": volume_pct}
    set_percentiles(this_candle, spread=spread, volume=volume)

    first = analyzer.detect_signals(this_candle)
    second = analyzer.detect_signals(this_candle)

    for list_key in _SIGNAL_LIST_KEYS:
        assert first[list_key] == second[list_key], (
            f"repeated invocation differs for {list_key} "
            f"(up={up}, spread_pct={spread_pct}, volume_pct={volume_pct}, wicks={wicks})"
        )
    for score_key in _SCORE_KEYS:
        assert first[score_key] == pytest.approx(second[score_key]), (
            f"repeated invocation differs for {score_key} "
            f"(up={up}, spread_pct={spread_pct}, volume_pct={volume_pct}, wicks={wicks})"
        )
