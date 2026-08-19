"""Tests for WalkForwardValidator.

Contains:
- Property-based test for chronological ordering (Property 9)
- Property-based test for fold skip threshold (Property 10)
- Unit tests for edge cases (Requirements 4.4, 4.7, 4.8)
"""

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sklearn.model_selection import TimeSeriesSplit

from vpa.ml_validation.exceptions import InsufficientDataError
from vpa.ml_validation.walk_forward import WalkForwardResult, WalkForwardValidator


# --- Helpers ---


def _make_dataset(n_rows: int, n_features: int = 5, seed: int = 42) -> tuple[pd.DataFrame, pd.Series]:
    """Create a synthetic dataset with random features and binary labels.

    Args:
        n_rows: Number of rows in the dataset.
        n_features: Number of feature columns.
        seed: Random seed for reproducibility.

    Returns:
        Tuple of (X features DataFrame, y labels Series).
    """
    rng = np.random.default_rng(seed)
    X = pd.DataFrame(
        rng.standard_normal((n_rows, n_features)),
        columns=[f"feature_{i}" for i in range(n_features)],
    )
    y = pd.Series(rng.integers(0, 2, size=n_rows), name="next_day_direction")
    return X, y


def _compute_expected_skipped_folds(
    n_rows: int, n_splits: int, min_train: int, min_test: int
) -> list[int]:
    """Independently calculate which folds should be skipped using TimeSeriesSplit."""
    tscv = TimeSeriesSplit(n_splits=n_splits)
    indices = np.arange(n_rows)
    skipped = []
    for fold_idx, (train_idx, test_idx) in enumerate(tscv.split(indices)):
        if len(train_idx) < min_train or len(test_idx) < min_test:
            skipped.append(fold_idx)
    return skipped


# =============================================================================
# Property-Based Tests
# =============================================================================


@st.composite
def time_indexed_dataset(draw):
    """Generate a time-indexed DataFrame with random numeric features and binary labels.

    Produces datasets of 100-300 rows with 2-5 feature columns, suitable for
    walk-forward validation with default settings (min_train=30, min_test=10).
    """
    n_rows = draw(st.integers(min_value=100, max_value=300))
    n_features = draw(st.integers(min_value=2, max_value=5))

    # Generate sequential date index
    dates = pd.date_range(start="2020-01-01", periods=n_rows, freq="B")

    # Generate random numeric features
    feature_data = {}
    for i in range(n_features):
        feature_data[f"feature_{i}"] = draw(
            st.lists(
                st.floats(min_value=-100, max_value=100, allow_nan=False, allow_infinity=False),
                min_size=n_rows,
                max_size=n_rows,
            )
        )

    X = pd.DataFrame(feature_data, index=dates)

    # Generate binary labels
    labels = draw(
        st.lists(
            st.integers(min_value=0, max_value=1),
            min_size=n_rows,
            max_size=n_rows,
        )
    )
    y = pd.Series(labels, index=dates, name="label")

    return X, y


# Feature: vpa-ml-validation, Property 9: Walk-forward chronological ordering
@given(data=time_indexed_dataset())
@settings(max_examples=50, deadline=None)
def test_property_walk_forward_chronological_ordering(data):
    """Property 9: For each non-skipped fold, the max index in training is strictly
    less than the min index in testing.

    We verify this by using the same TimeSeriesSplit configuration as WalkForwardValidator
    and confirming all training indices precede test indices. Then we verify the validator
    produces the expected number of valid folds given the data size.

    **Validates: Requirements 4.3**
    """
    X, y = data
    n_splits = 5

    # Part 1: Verify TimeSeriesSplit maintains chronological ordering directly
    tscv = TimeSeriesSplit(n_splits=n_splits)
    for fold_idx, (train_index, test_index) in enumerate(tscv.split(X)):
        # All training indices must come before all test indices
        max_train_idx = train_index.max()
        min_test_idx = test_index.min()
        assert max_train_idx < min_test_idx, (
            f"Fold {fold_idx}: max train positional index ({max_train_idx}) "
            f"is not strictly less than min test positional index ({min_test_idx})"
        )

        # Verify using the actual datetime index
        train_dates = X.index[train_index]
        test_dates = X.index[test_index]
        assert train_dates.max() < test_dates.min(), (
            f"Fold {fold_idx}: max train date ({train_dates.max()}) "
            f"is not strictly earlier than min test date ({test_dates.min()})"
        )

    # Part 2: Verify WalkForwardValidator produces consistent fold counts
    validator = WalkForwardValidator(n_splits=n_splits)
    result = validator.validate(X, y)

    # The number of completed folds + skipped folds must equal n_splits
    assert len(result.fold_accuracies) + len(result.skipped_folds) == n_splits, (
        f"Expected {n_splits} total folds, got "
        f"{len(result.fold_accuracies)} completed + {len(result.skipped_folds)} skipped = "
        f"{len(result.fold_accuracies) + len(result.skipped_folds)}"
    )

    # All fold accuracies must be valid proportions
    for acc in result.fold_accuracies:
        assert 0.0 <= acc <= 1.0, f"Fold accuracy {acc} is not in [0, 1]"


# Feature: vpa-ml-validation, Property 10: Fold skip on insufficient samples
@settings(max_examples=50, deadline=None)
@given(
    n_rows=st.integers(min_value=12, max_value=200),
    seed=st.integers(min_value=0, max_value=10000),
)
def test_property_fold_skip_on_insufficient_samples(n_rows: int, seed: int) -> None:
    """Property 10: Fold skip on insufficient samples.

    For any dataset of varying sizes (12 to 200 rows), run WalkForwardValidator
    with min_train_samples=30 and min_test_samples=10. Independently calculate
    which folds should be skipped using sklearn TimeSeriesSplit, then verify
    the validator's skipped_folds matches.

    Uses n_rows >= 12 because TimeSeriesSplit requires n_samples >= n_splits + 1 (6).
    We use 12 as the minimum to ensure at least 2 samples per fold segment.

    **Validates: Requirements 4.7**
    """
    X, y = _make_dataset(n_rows, n_features=5, seed=seed)

    expected_skipped = _compute_expected_skipped_folds(
        n_rows, 5, 30, 10
    )

    validator = WalkForwardValidator(
        n_splits=5,
        min_train_samples=30,
        min_test_samples=10,
        random_state=42,
    )

    # If all folds would be skipped, the validator should raise InsufficientDataError
    if len(expected_skipped) == 5:
        with pytest.raises(InsufficientDataError):
            validator.validate(X, y)
        return

    result = validator.validate(X, y)

    # Verify that the skipped folds match our independent calculation
    assert sorted(result.skipped_folds) == sorted(expected_skipped), (
        f"Skipped folds mismatch for n_rows={n_rows}: "
        f"got {sorted(result.skipped_folds)}, expected {sorted(expected_skipped)}"
    )

    # Verify that the number of fold accuracies equals non-skipped folds
    expected_valid_folds = 5 - len(expected_skipped)
    assert len(result.fold_accuracies) == expected_valid_folds, (
        f"Expected {expected_valid_folds} fold accuracies for n_rows={n_rows}, "
        f"got {len(result.fold_accuracies)}"
    )


# =============================================================================
# Unit Tests
# =============================================================================


class TestWalkForwardValidatorEdgeCases:
    """Edge case tests for WalkForwardValidator."""

    def test_all_folds_skipped_raises_insufficient_data_error(self):
        """A dataset with 30 rows should cause all folds to be skipped.

        With n_splits=5 and 30 rows, TimeSeriesSplit produces test folds of
        size 5 (30 // 6 = 5), all below min_test=10. Every fold is skipped
        and InsufficientDataError must be raised.
        Requirements: 4.7, 4.8
        """
        X, y = _make_dataset(n_rows=30)
        validator = WalkForwardValidator(n_splits=5, min_train_samples=30, min_test_samples=10)

        with pytest.raises(InsufficientDataError):
            validator.validate(X, y)

    def test_minimum_viable_dataset_at_least_one_fold_runs(self):
        """A dataset of ~60 rows should allow at least one fold to run.

        TimeSeriesSplit with n_splits=5 gives the last fold the largest train set.
        With 60 rows, the last fold should have ~50 train and ~10 test samples,
        meeting both min_train=30 and min_test=10.
        Requirements: 4.7
        """
        X, y = _make_dataset(n_rows=60)
        validator = WalkForwardValidator(n_splits=5, min_train_samples=30, min_test_samples=10)

        result = validator.validate(X, y)

        assert isinstance(result, WalkForwardResult)
        assert len(result.fold_accuracies) >= 1
        assert result.mean_accuracy >= 0.0
        assert result.mean_accuracy <= 1.0

    def test_xgboost_random_state_produces_deterministic_results(self):
        """Running validation twice with same data must produce identical results.

        This verifies XGBoost random_state=42 ensures reproducibility.
        Requirements: 4.4
        """
        X, y = _make_dataset(n_rows=200)
        validator = WalkForwardValidator(n_splits=5, random_state=42)

        result1 = validator.validate(X, y)
        result2 = validator.validate(X, y)

        assert result1.fold_accuracies == result2.fold_accuracies
        assert result1.mean_accuracy == result2.mean_accuracy
        assert result1.std_accuracy == result2.std_accuracy

    def test_result_model_is_not_none(self):
        """The returned model must be from the last valid fold and not None.

        Requirements: 4.4
        """
        X, y = _make_dataset(n_rows=200)
        validator = WalkForwardValidator(n_splits=5)

        result = validator.validate(X, y)

        assert result.model is not None
        # Verify it's a trained model that can make predictions
        predictions = result.model.predict(X.iloc[:5])
        assert len(predictions) == 5
        assert all(p in (0, 1) for p in predictions)

    def test_large_dataset_all_folds_run_no_skips(self):
        """A dataset of 200+ rows should allow all 5 folds to run with no skips.

        TimeSeriesSplit with n_splits=5 on 200 rows gives ~33 test samples per fold
        and growing training sets (33, 66, 99, ...), all exceeding minimums.
        Requirements: 4.7
        """
        X, y = _make_dataset(n_rows=250)
        validator = WalkForwardValidator(n_splits=5, min_train_samples=30, min_test_samples=10)

        result = validator.validate(X, y)

        assert len(result.fold_accuracies) == 5
        assert result.skipped_folds == []
        assert result.mean_accuracy > 0.0
        assert result.std_accuracy >= 0.0
