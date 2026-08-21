"""Conclusion engine for VPA ML validation analysis."""


class ConclusionEngine:
    """Determines the go/no-go conclusion based on accuracy thresholds."""

    EDGE_THRESHOLD = 52.0  # percentage
    IMPROVEMENT_THRESHOLD = 2.0  # percentage points

    @staticmethod
    def determine_conclusion(baseline_accuracy_pct: float, ml_accuracy_pct: float) -> str:
        """
        Apply the five-branch decision tree to determine the conclusion.

        Args:
            baseline_accuracy_pct: Baseline VPA accuracy as a percentage (0-100).
            ml_accuracy_pct: ML walk-forward mean accuracy as a percentage (0-100).

        Returns:
            One of five defined conclusion strings.
        """
        baseline_has_edge = baseline_accuracy_pct > ConclusionEngine.EDGE_THRESHOLD
        ml_has_edge = ml_accuracy_pct > ConclusionEngine.EDGE_THRESHOLD

        if not baseline_has_edge and not ml_has_edge:
            return "No predictive edge detected"

        if not baseline_has_edge and ml_has_edge:
            return "Features have signal but scoring rules are suboptimal"

        # From here, baseline > 52%
        improvement = ml_accuracy_pct - baseline_accuracy_pct

        if improvement > ConclusionEngine.IMPROVEMENT_THRESHOLD:
            return "Real edge exists and ML improves it"

        if improvement >= -ConclusionEngine.IMPROVEMENT_THRESHOLD:
            return "Rule-based approach is near-optimal"

        return "Rule-based approach outperforms ML on this dataset"
