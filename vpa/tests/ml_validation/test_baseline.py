"""Property-based tests for AnalysisScript baseline accuracy and feature importance.

Contains:
- Property 6: Baseline classification rule
- Property 7: Baseline accuracy computation
- Property 8: Model receives only feature columns
- Property 11: Feature importance report validity
"""

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from xgboost import XGBClassifier

from vpa.ml_validation.analysis import AnalysisScript
from vpa.ml_validation.feature_extractor import VPAFeatureExtractor


# --- Helpers ---


def _make_analysis_dataset(
    composite_scores: list[float],
    next_day_directions: list[int],
) -> pd.DataFrame:
    """Build a minimal dataset suitable for AnalysisScript with given scores and labels.

    Includes all 27 feature columns (zeroed except composite_score) plus metadata
    and the label column.
    """
    n = len(composite_scores)
    data = {col: [0.0] * n for col in VPAFeatureExtractor.FEATURE_COLUMNS}
    data["composite_score"] = composite_scores
    data["date"] = [f"2020-01-{i + 1:02d}" for i in range(n)]
    data["close"] = [100.0 + i for i in range(n)]
    data["next_day_direction"] = next_day_directions
    return pd.DataFrame(data)


def _make_full_feature_dataset(n_rows: int, seed: int = 42) -> pd.DataFrame:
    """Create a dataset with all 27 feature columns + metadata + label.

    Feature columns have random values; metadata has date strings and close prices.
    """
    rng = np.random.default_rng(seed)
    data = {}
    for col in VPAFeatureExtractor.FEATURE_COLUMNS:
        data[col] = rng.standard_normal(n_rows)
    data["date"] = [f"2020-01-{(i % 28) + 1:02d}" for i in range(n_rows)]
    data["close"] = rng.uniform(100, 200, n_rows)
    data["next_day_direction"] = rng.integers(0, 2, size=n_rows)
    return pd.DataFrame(data)


# =============================================================================
# Property-Based Tests
# =============================================================================


# Feature: vpa-ml-validation, Property 6: Baseline classification rule
@settings(max_examples=100)
@given(
    composite_scores=st.lists(
        st.floats(min_value=-1000, max_value=1000, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=50,
    ),
)
def test_property_baseline_classification_rule(composite_scores: list[float]) -> None:
    """Property 6: Baseline classification rule.

    For any composite score value, the baseline predictor shall classify the
    direction as UP (1) when composite_score > 0, and DOWN (0) when
    composite_score <= 0.

    We verify by building a dataset, computing baseline accuracy manually using
    the classification rule, and confirming it matches compute_baseline_accuracy().

    **Validates: Requirements 3.1, 3.2**
    """
    n = len(composite_scores)
    # Generate arbitrary labels (the classification rule is independent of labels)
    labels = [1 if i % 2 == 0 else 0 for i in range(n)]

    dataset = _make_analysis_dataset(composite_scores, labels)
    script = AnalysisScript(dataset=dataset, ticker="TEST", output_dir=Path("/tmp"))

    accuracy = script.compute_baseline_accuracy()

    # Manually compute expected accuracy using the classification rule
    correct = 0
    for i, score in enumerate(composite_scores):
        predicted = 1 if score > 0 else 0
        if predicted == labels[i]:
            correct += 1
    expected_accuracy = correct / n

    assert abs(accuracy - expected_accuracy) < 1e-10, (
        f"Baseline accuracy mismatch: got {accuracy}, expected {expected_accuracy} "
        f"for composite_scores={composite_scores[:5]}..."
    )


# Feature: vpa-ml-validation, Property 7: Baseline accuracy computation
@settings(max_examples=100)
@given(
    predictions_match=st.lists(
        st.booleans(),
        min_size=1,
        max_size=100,
    ),
)
def test_property_baseline_accuracy_computation(predictions_match: list[bool]) -> None:
    """Property 7: Baseline accuracy computation.

    For any dataset of predictions and actual labels (excluding null composite rows),
    the computed baseline accuracy shall equal the count of rows where predicted
    direction matches actual direction, divided by the total count of non-null rows.

    We construct scores and labels such that we control exactly which predictions
    match, then verify the accuracy formula.

    **Validates: Requirements 3.2, 3.4**
    """
    n = len(predictions_match)

    # Construct composite_scores and labels so that match/mismatch is controlled
    composite_scores = []
    labels = []
    for match in predictions_match:
        if match:
            # Score > 0 predicts UP (1), label = 1 -> match
            composite_scores.append(5.0)
            labels.append(1)
        else:
            # Score > 0 predicts UP (1), label = 0 -> mismatch
            composite_scores.append(5.0)
            labels.append(0)

    dataset = _make_analysis_dataset(composite_scores, labels)
    script = AnalysisScript(dataset=dataset, ticker="TEST", output_dir=Path("/tmp"))

    accuracy = script.compute_baseline_accuracy()

    # Expected: count of matches / total
    expected = sum(predictions_match) / n

    assert abs(accuracy - expected) < 1e-10, (
        f"Accuracy formula mismatch: got {accuracy}, expected {expected}"
    )


# Feature: vpa-ml-validation, Property 8: Model receives only feature columns
@settings(max_examples=30, deadline=None)
@given(
    n_rows=st.integers(min_value=200, max_value=400),
    seed=st.integers(min_value=0, max_value=10000),
)
def test_property_model_receives_only_feature_columns(n_rows: int, seed: int) -> None:
    """Property 8: Model receives only feature columns.

    For any dataset passed to the walk-forward validator, the feature matrix X
    shall contain only the 27 feature columns and shall NOT contain the date,
    close, or next_day_direction columns.

    We patch WalkForwardValidator.validate to capture the X DataFrame that
    run_walk_forward_validation passes to it, and verify the column set.

    **Validates: Requirements 4.2**
    """
    dataset = _make_full_feature_dataset(n_rows, seed=seed)
    script = AnalysisScript(dataset=dataset, ticker="TEST", output_dir=Path("/tmp"))

    captured_X = {}

    def mock_validate(self, X, y):
        """Capture the X DataFrame passed to the validator."""
        captured_X["X"] = X.copy()
        captured_X["y"] = y.copy()
        # Return a minimal valid result
        from vpa.ml_validation.walk_forward import WalkForwardResult

        return WalkForwardResult(
            fold_accuracies=[0.5],
            mean_accuracy=0.5,
            std_accuracy=0.0,
            model=None,
            skipped_folds=[],
        )

    with patch(
        "vpa.ml_validation.walk_forward.WalkForwardValidator.validate",
        mock_validate,
    ):
        script.run_walk_forward_validation()

    X = captured_X["X"]

    # Verify that metadata and label columns are NOT present
    excluded_columns = {"date", "close", "next_day_direction"}
    present_excluded = set(X.columns) & excluded_columns
    assert present_excluded == set(), (
        f"Feature matrix X should not contain metadata/label columns, "
        f"but found: {present_excluded}"
    )

    # Verify that all 27 feature columns ARE present
    expected_feature_cols = set(VPAFeatureExtractor.FEATURE_COLUMNS)
    actual_cols = set(X.columns)
    assert actual_cols == expected_feature_cols, (
        f"Feature matrix X should contain exactly the 27 feature columns.\n"
        f"Missing: {expected_feature_cols - actual_cols}\n"
        f"Extra: {actual_cols - expected_feature_cols}"
    )


# Feature: vpa-ml-validation, Property 11: Feature importance report validity
@settings(max_examples=30, deadline=None)
@given(
    seed=st.integers(min_value=0, max_value=10000),
)
def test_property_feature_importance_report_validity(seed: int) -> None:
    """Property 11: Feature importance report validity.

    For any set of gain-based feature importance scores extracted from a trained
    model, the Feature_Importance_Report shall be sorted in non-increasing order
    by importance score, and all normalised scores shall sum to 1.0 (within
    floating-point tolerance of 1e-6).

    We train a real XGBClassifier on random data with the 27 feature columns,
    then verify extract_feature_importance() output meets the property.

    **Validates: Requirements 5.2, 5.3**
    """
    rng = np.random.default_rng(seed)
    n_rows = 200

    # Create training data with the 27 feature columns
    X = pd.DataFrame(
        rng.standard_normal((n_rows, 27)),
        columns=VPAFeatureExtractor.FEATURE_COLUMNS,
    )
    y = pd.Series(rng.integers(0, 2, size=n_rows), name="next_day_direction")

    # Train an XGBClassifier
    model = XGBClassifier(random_state=seed, eval_metric="logloss", n_estimators=10)
    model.fit(X, y)

    # Build a dummy dataset just to instantiate AnalysisScript
    dataset = _make_full_feature_dataset(n_rows, seed=seed)
    script = AnalysisScript(dataset=dataset, ticker="TEST", output_dir=Path("/tmp"))

    importance_df = script.extract_feature_importance(model)

    # Property: DataFrame has correct columns
    assert list(importance_df.columns) == ["feature_name", "importance_score"], (
        f"Expected columns [feature_name, importance_score], got {list(importance_df.columns)}"
    )

    # Property: Sorted in non-increasing (descending) order by importance_score
    scores = importance_df["importance_score"].tolist()
    for i in range(len(scores) - 1):
        assert scores[i] >= scores[i + 1], (
            f"Importance scores not sorted descending at index {i}: "
            f"{scores[i]} < {scores[i + 1]}"
        )

    # Property: All normalised scores sum to 1.0 (within tolerance)
    total = sum(scores)
    assert abs(total - 1.0) < 1e-6, (
        f"Importance scores should sum to 1.0, got {total}"
    )

    # Property: All scores are non-negative
    for score in scores:
        assert score >= 0.0, f"Importance score should be non-negative, got {score}"

    # Property: All 27 feature names are present
    assert len(importance_df) == 27, (
        f"Expected 27 features in importance report, got {len(importance_df)}"
    )
    assert set(importance_df["feature_name"]) == set(VPAFeatureExtractor.FEATURE_COLUMNS), (
        "Importance report feature names don't match FEATURE_COLUMNS"
    )
