"""Unit and property-based tests for the VPA threshold-tuning classifiers (SP-313).

These are FAST tests: the functions under test are pure (no model, no I/O, no
global state), so none of these carry the ``slow`` marker.

# Feature: vpa-threshold-tuning-ml-revalidation, Property 7: Classification band partition
"""

from hypothesis import given, settings
from hypothesis.strategies import floats, one_of, sampled_from

from vpa.ml_validation.tuning.classify import (
    ML_BAND_HIGH,
    ML_BAND_LOW,
    PURSUE_ML_THRESHOLD_PCT,
    SP312_BASELINE_PCT,
    SP312_ML_STD_PCT,
    PursueResult,
    classify_baseline_vs_sp312,
    classify_ml_vs_sp312,
    classify_ticker_edge,
    pursue_decision,
)

# Allowed band strings per classifier (single source of truth for the tests).
ML_BANDS = {"increased", "decreased", "within-band"}
BASELINE_BANDS = {"increased", "decreased", "unchanged"}
EDGE_BANDS = {"stronger", "weaker", "comparable"}
PURSUE_RECOMMENDATIONS = {"pursue", "do not pursue", "no recommendation"}


# --- Unit tests: classify_ml_vs_sp312 (boundaries 47.50 / 53.68) ---------


class TestClassifyMlVsSp312:
    """Boundary behaviour of the ML-vs-SP312 band classifier (Req 7.4)."""

    def test_just_below_low_band_is_decreased(self):
        assert classify_ml_vs_sp312(47.49) == "decreased"

    def test_at_low_band_is_within_band(self):
        # 47.50 is inclusive -> within-band.
        assert classify_ml_vs_sp312(47.50) == "within-band"

    def test_just_above_low_band_is_within_band(self):
        assert classify_ml_vs_sp312(47.51) == "within-band"

    def test_midpoint_is_within_band(self):
        assert classify_ml_vs_sp312(50.59) == "within-band"

    def test_just_below_high_band_is_within_band(self):
        assert classify_ml_vs_sp312(53.67) == "within-band"

    def test_at_high_band_is_within_band(self):
        # 53.68 is inclusive -> within-band.
        assert classify_ml_vs_sp312(53.68) == "within-band"

    def test_just_above_high_band_is_increased(self):
        assert classify_ml_vs_sp312(53.69) == "increased"

    def test_far_below_is_decreased(self):
        assert classify_ml_vs_sp312(0.0) == "decreased"

    def test_far_above_is_increased(self):
        assert classify_ml_vs_sp312(100.0) == "increased"


# --- Unit tests: classify_baseline_vs_sp312 (boundary 52.34) -------------


class TestClassifyBaselineVsSp312:
    """Boundary behaviour of the baseline-vs-SP312 classifier (Req 7.4)."""

    def test_exactly_at_baseline_is_unchanged(self):
        assert classify_baseline_vs_sp312(52.34) == "unchanged"

    def test_just_above_baseline_is_increased(self):
        assert classify_baseline_vs_sp312(52.35) == "increased"

    def test_just_below_baseline_is_decreased(self):
        assert classify_baseline_vs_sp312(52.33) == "decreased"

    def test_far_above_is_increased(self):
        assert classify_baseline_vs_sp312(100.0) == "increased"

    def test_far_below_is_decreased(self):
        assert classify_baseline_vs_sp312(0.0) == "decreased"


# --- Unit tests: classify_ticker_edge (band +/-3.09 from SPY) ------------


class TestClassifyTickerEdge:
    """Boundary behaviour of the ticker-edge classifier (Req 9.4)."""

    def test_exactly_plus_band_is_comparable(self):
        # Ticker exactly +3.09 from SPY -> comparable (inclusive). Anchor on the
        # exact constant with SPY=0.0 so the subtraction lands precisely on the
        # boundary (decimal literals like 53.09-50.0 drift off it in IEEE-754).
        assert classify_ticker_edge(SP312_ML_STD_PCT, 0.0) == "comparable"

    def test_exactly_minus_band_is_comparable(self):
        # Ticker exactly -3.09 from SPY -> comparable (inclusive).
        assert classify_ticker_edge(-SP312_ML_STD_PCT, 0.0) == "comparable"

    def test_equal_to_spy_is_comparable(self):
        assert classify_ticker_edge(50.0, 50.0) == "comparable"

    def test_more_than_plus_band_is_stronger(self):
        assert classify_ticker_edge(53.10, 50.0) == "stronger"

    def test_more_than_minus_band_is_weaker(self):
        assert classify_ticker_edge(46.90, 50.0) == "weaker"

    def test_far_above_is_stronger(self):
        assert classify_ticker_edge(90.0, 50.0) == "stronger"

    def test_far_below_is_weaker(self):
        assert classify_ticker_edge(10.0, 50.0) == "weaker"


# --- Unit tests: pursue_decision (threshold strictly > 54.0; None case) --


class TestPursueDecision:
    """Boundary behaviour of the pursue decision (Req 8)."""

    def test_strictly_above_threshold_is_pursue(self):
        result = pursue_decision(54.01)
        assert result.recommendation == "pursue"
        assert result.supporting_ml_accuracy_pct == 54.01
        assert result.unavailable_reason is None

    def test_exactly_at_threshold_is_do_not_pursue(self):
        result = pursue_decision(54.0)
        assert result.recommendation == "do not pursue"
        assert result.supporting_ml_accuracy_pct == 54.0
        assert result.unavailable_reason is None

    def test_below_threshold_is_do_not_pursue(self):
        result = pursue_decision(50.59)
        assert result.recommendation == "do not pursue"
        assert result.supporting_ml_accuracy_pct == 50.59
        assert result.unavailable_reason is None

    def test_none_is_no_recommendation(self):
        result = pursue_decision(None)
        assert isinstance(result, PursueResult)
        assert result.recommendation == "no recommendation"
        assert result.supporting_ml_accuracy_pct is None
        assert result.unavailable_reason is not None

    def test_supporting_value_echoes_input(self):
        # When a value is given, the supporting value must equal it exactly.
        for value in (0.0, 54.0, 54.01, 100.0):
            assert pursue_decision(value).supporting_ml_accuracy_pct == value


# --- Property 7: Classification band partition ---------------------------

# A float strategy that oversamples the exact band boundaries so Hypothesis
# routinely exercises the inclusive/strict comparisons, plus the full real line.
_boundary_values = sampled_from(
    [
        ML_BAND_LOW,
        ML_BAND_HIGH,
        SP312_BASELINE_PCT,
        PURSUE_ML_THRESHOLD_PCT,
        SP312_ML_STD_PCT,
        -SP312_ML_STD_PCT,
        0.0,
        100.0,
    ]
)
_accuracy_floats = one_of(
    floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
    _boundary_values,
)


@settings(max_examples=200)
@given(ml_pct=_accuracy_floats)
def test_property7_classify_ml_vs_sp312_partition(ml_pct: float) -> None:
    """Property 7: ML-vs-SP312 band partition.

    For any float input, classify_ml_vs_sp312 returns exactly one allowed band,
    and the band matches the mathematical definition (increased iff >53.68,
    decreased iff <47.50, within-band otherwise, inclusive of both boundaries).

    **Validates: Requirements 7.4; Property 7**
    """
    result = classify_ml_vs_sp312(ml_pct)
    assert result in ML_BANDS, f"Unexpected band {result!r} for ml_pct={ml_pct}"

    is_increased = ml_pct > ML_BAND_HIGH
    is_decreased = ml_pct < ML_BAND_LOW
    is_within = (not is_increased) and (not is_decreased)

    # Mutual exclusivity: exactly one band holds.
    assert (is_increased + is_decreased + is_within) == 1

    expected = "increased" if is_increased else "decreased" if is_decreased else "within-band"
    assert result == expected, f"ml_pct={ml_pct}: got {result!r}, expected {expected!r}"


@settings(max_examples=200)
@given(base_pct=_accuracy_floats)
def test_property7_classify_baseline_vs_sp312_partition(base_pct: float) -> None:
    """Property 7: baseline-vs-SP312 band partition.

    For any float input, classify_baseline_vs_sp312 returns exactly one allowed
    band, matching the definition (increased iff >52.34, decreased iff <52.34,
    unchanged iff exactly equal).

    **Validates: Requirements 7.4; Property 7**
    """
    result = classify_baseline_vs_sp312(base_pct)
    assert result in BASELINE_BANDS, f"Unexpected band {result!r} for base_pct={base_pct}"

    is_increased = base_pct > SP312_BASELINE_PCT
    is_decreased = base_pct < SP312_BASELINE_PCT
    is_unchanged = base_pct == SP312_BASELINE_PCT

    assert (is_increased + is_decreased + is_unchanged) == 1

    expected = "increased" if is_increased else "decreased" if is_decreased else "unchanged"
    assert result == expected, f"base_pct={base_pct}: got {result!r}, expected {expected!r}"


@settings(max_examples=200)
@given(ticker_base_pct=_accuracy_floats, spy_base_pct=_accuracy_floats)
def test_property7_classify_ticker_edge_partition(ticker_base_pct: float, spy_base_pct: float) -> None:
    """Property 7: ticker-edge band partition.

    For any pair of float inputs, classify_ticker_edge returns exactly one
    allowed band, matching the definition (stronger iff delta > +3.09, weaker
    iff delta < -3.09, comparable within +/-3.09 inclusive).

    **Validates: Requirements 9.4; Property 7**
    """
    result = classify_ticker_edge(ticker_base_pct, spy_base_pct)
    assert result in EDGE_BANDS, f"Unexpected band {result!r} for delta"

    delta_pp = ticker_base_pct - spy_base_pct
    is_stronger = delta_pp > SP312_ML_STD_PCT
    is_weaker = delta_pp < -SP312_ML_STD_PCT
    is_comparable = (not is_stronger) and (not is_weaker)

    assert (is_stronger + is_weaker + is_comparable) == 1

    expected = "stronger" if is_stronger else "weaker" if is_weaker else "comparable"
    assert (
        result == expected
    ), f"ticker={ticker_base_pct}, spy={spy_base_pct} (delta={delta_pp}): got {result!r}, expected {expected!r}"


@settings(max_examples=200)
@given(
    spy_ml_pct=one_of(floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False), _boundary_values)
)
def test_property7_pursue_decision_float_partition(spy_ml_pct: float) -> None:
    """Property 7: pursue decision for any float input.

    For any float x, pursue iff x > 54.0 (strict); otherwise do not pursue.
    A value is always echoed as the supporting value and the reason is None.

    **Validates: Requirements 8; Property 7**
    """
    result = pursue_decision(spy_ml_pct)
    assert result.recommendation in {"pursue", "do not pursue"}
    assert result.supporting_ml_accuracy_pct == spy_ml_pct
    assert result.unavailable_reason is None

    expected = "pursue" if spy_ml_pct > PURSUE_ML_THRESHOLD_PCT else "do not pursue"
    assert result.recommendation == expected, f"spy_ml_pct={spy_ml_pct}: got {result.recommendation!r}"


def test_property7_pursue_decision_none_is_no_recommendation() -> None:
    """Property 7: None input yields the only 'no recommendation' outcome.

    None iff 'no recommendation': supporting value is None and a reason is set.

    **Validates: Requirements 8; Property 7**
    """
    result = pursue_decision(None)
    assert result.recommendation == "no recommendation"
    assert result.recommendation in PURSUE_RECOMMENDATIONS
    assert result.supporting_ml_accuracy_pct is None
    assert result.unavailable_reason is not None
