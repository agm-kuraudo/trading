"""Property-based and unit tests for ConclusionEngine.

# Feature: vpa-ml-validation, Property 12: Conclusion engine correctness
"""

import pytest
from hypothesis import given, settings
from hypothesis.strategies import floats

from vpa.ml_validation.conclusion import ConclusionEngine

# --- Property 12: Conclusion engine correctness ---

VALID_CONCLUSIONS = {
    "No predictive edge detected",
    "Features have signal but scoring rules are suboptimal",
    "Real edge exists and ML improves it",
    "Rule-based approach is near-optimal",
    "Rule-based approach outperforms ML on this dataset",
}


@settings(max_examples=100)
@given(
    baseline_pct=floats(min_value=0.0, max_value=100.0, allow_nan=False),
    ml_pct=floats(min_value=0.0, max_value=100.0, allow_nan=False),
)
def test_conclusion_engine_correctness(baseline_pct: float, ml_pct: float) -> None:
    """Property 12: Conclusion engine correctness.

    For any pair of (baseline_accuracy_pct, ml_accuracy_pct) values in [0, 100],
    the conclusion engine shall return exactly one of the five defined conclusion
    strings, determined by the decision tree logic.

    **Validates: Requirements 6.2, 6.3, 6.4, 6.5, 6.6**
    """
    result = ConclusionEngine.determine_conclusion(baseline_pct, ml_pct)

    # Must be one of the five valid conclusions
    assert result in VALID_CONCLUSIONS, (
        f"Unexpected conclusion: {result!r} for baseline={baseline_pct}, ml={ml_pct}"
    )

    # Verify correct branch selection based on decision tree
    edge_threshold = ConclusionEngine.EDGE_THRESHOLD  # 52.0
    improvement_threshold = ConclusionEngine.IMPROVEMENT_THRESHOLD  # 2.0

    baseline_has_edge = baseline_pct > edge_threshold
    ml_has_edge = ml_pct > edge_threshold

    if not baseline_has_edge and not ml_has_edge:
        expected = "No predictive edge detected"
    elif not baseline_has_edge and ml_has_edge:
        expected = "Features have signal but scoring rules are suboptimal"
    else:
        # baseline > 52%
        improvement = ml_pct - baseline_pct
        if improvement > improvement_threshold:
            expected = "Real edge exists and ML improves it"
        elif improvement >= -improvement_threshold:
            expected = "Rule-based approach is near-optimal"
        else:
            expected = "Rule-based approach outperforms ML on this dataset"

    assert result == expected, (
        f"Wrong branch for baseline={baseline_pct}, ml={ml_pct}: "
        f"got {result!r}, expected {expected!r}"
    )


# --- Unit tests for boundary cases (Task 2.3) ---


class TestConclusionEngineBoundaries:
    """Test exact boundary values for the five-branch decision tree."""

    def test_both_at_threshold_52_percent(self):
        """Both baseline and ML at exactly 52% (threshold) -> no edge detected.

        52.0% is NOT greater than the 52% threshold, so neither has edge.
        Requirements: 6.2
        """
        result = ConclusionEngine.determine_conclusion(52.0, 52.0)
        assert result == "No predictive edge detected"

    def test_baseline_just_above_threshold(self):
        """Baseline at 52.01% (just above threshold) -> baseline has edge.

        With ML also just above threshold and within 2pp, should be near-optimal.
        Requirements: 6.5
        """
        result = ConclusionEngine.determine_conclusion(52.01, 52.01)
        assert result == "Rule-based approach is near-optimal"

    def test_improvement_exactly_2pp_is_near_optimal(self):
        """ML exactly 2pp above baseline -> near-optimal (within 2pp inclusive).

        baseline=55%, ml=57.0%, improvement=2.0 which is NOT > 2.0.
        Requirements: 6.5
        """
        result = ConclusionEngine.determine_conclusion(55.0, 57.0)
        assert result == "Rule-based approach is near-optimal"

    def test_improvement_just_over_2pp_is_real_edge(self):
        """ML just over 2pp above baseline -> real edge exists.

        baseline=55%, ml=57.01%, improvement=2.01 which IS > 2.0.
        Requirements: 6.4
        """
        result = ConclusionEngine.determine_conclusion(55.0, 57.01)
        assert result == "Real edge exists and ML improves it"

    def test_decline_exactly_2pp_is_near_optimal(self):
        """ML exactly 2pp below baseline -> near-optimal (within 2pp inclusive).

        baseline=55%, ml=53.0%, improvement=-2.0 which IS >= -2.0.
        Requirements: 6.5
        """
        result = ConclusionEngine.determine_conclusion(55.0, 53.0)
        assert result == "Rule-based approach is near-optimal"

    def test_decline_just_under_2pp_is_rule_based_outperforms(self):
        """ML just under 2pp below baseline -> rule-based outperforms.

        baseline=55%, ml=52.99%, improvement=-2.01 which is NOT >= -2.0.
        Requirements: 6.6
        """
        result = ConclusionEngine.determine_conclusion(55.0, 52.99)
        assert result == "Rule-based approach outperforms ML on this dataset"

    def test_extreme_low_both_zero(self):
        """Both at 0% -> no predictive edge detected.

        Requirements: 6.2
        """
        result = ConclusionEngine.determine_conclusion(0.0, 0.0)
        assert result == "No predictive edge detected"

    def test_extreme_high_both_100(self):
        """Both at 100% -> near-optimal (both have edge, within 2pp).

        Requirements: 6.5
        """
        result = ConclusionEngine.determine_conclusion(100.0, 100.0)
        assert result == "Rule-based approach is near-optimal"
