"""Property test for reproducibility (Property 13): deterministic output.

Runs the AnalysisScript pipeline twice on the same synthetic dataset and verifies
that all outputs are identical — baseline accuracy, walk-forward fold accuracies,
and feature importance rankings.

# Feature: vpa-ml-validation, Property 13: Reproducibility — deterministic output

**Validates: Requirements 8.5**
"""

import numpy as np
import pandas as pd
import pytest

from vpa.ml_validation.analysis import AnalysisScript
from vpa.ml_validation.feature_extractor import VPAFeatureExtractor


def _make_synthetic_dataset(n_rows: int = 300, seed: int = 42) -> pd.DataFrame:
    """Create a fixed synthetic dataset suitable for walk-forward validation.

    Produces a DataFrame with all 27 feature columns, metadata (date, close),
    and the next_day_direction label. Uses a fixed seed so the dataset is
    identical across invocations.
    """
    rng = np.random.default_rng(seed)

    data = {}
    for col in VPAFeatureExtractor.FEATURE_COLUMNS:
        data[col] = rng.standard_normal(n_rows)

    data["date"] = pd.date_range("2015-01-02", periods=n_rows, freq="B").strftime(
        "%Y-%m-%d"
    )
    data["close"] = rng.uniform(100, 500, size=n_rows)
    data["next_day_direction"] = rng.integers(0, 2, size=n_rows)

    return pd.DataFrame(data)


class TestReproducibility:
    """Property 13: Reproducibility — deterministic output.

    The pipeline must produce identical results when run twice on the same data
    with the same random seeds. This verifies that numpy and XGBoost seeding
    is applied correctly throughout.
    """

    @pytest.fixture
    def dataset(self) -> pd.DataFrame:
        """Fixed synthetic dataset used for both pipeline runs."""
        return _make_synthetic_dataset(n_rows=300, seed=42)

    def _run_pipeline(self, dataset: pd.DataFrame, output_dir):
        """Run the full analysis pipeline and return key metrics.

        Sets numpy seed to 42 before each run (matching run_analysis.py behaviour).
        """
        np.random.seed(42)

        script = AnalysisScript(
            dataset=dataset.copy(), ticker="TEST", output_dir=output_dir
        )

        baseline_acc = script.compute_baseline_accuracy()
        wf_result = script.run_walk_forward_validation(n_splits=5)
        importance_df = script.extract_feature_importance(wf_result.model)

        return {
            "baseline_accuracy": baseline_acc,
            "fold_accuracies": wf_result.fold_accuracies,
            "mean_accuracy": wf_result.mean_accuracy,
            "std_accuracy": wf_result.std_accuracy,
            "importance_df": importance_df,
            "skipped_folds": wf_result.skipped_folds,
        }

    def test_baseline_accuracy_is_identical_across_runs(self, dataset, tmp_path):
        """Baseline accuracy must be exactly the same on repeated runs.

        The baseline uses a deterministic rule (composite_score > 0 → UP),
        so given the same data it must always produce the same number.
        """
        run1 = self._run_pipeline(dataset, tmp_path / "run1")
        run2 = self._run_pipeline(dataset, tmp_path / "run2")

        assert run1["baseline_accuracy"] == run2["baseline_accuracy"], (
            f"Baseline accuracy differs: {run1['baseline_accuracy']} vs {run2['baseline_accuracy']}"
        )

    def test_walk_forward_fold_accuracies_are_identical_across_runs(
        self, dataset, tmp_path
    ):
        """Walk-forward fold accuracies must be identical on repeated runs.

        XGBoost uses random_state=42, so given the same splits and same data
        the trained models and their predictions must be deterministic.
        """
        run1 = self._run_pipeline(dataset, tmp_path / "run1")
        run2 = self._run_pipeline(dataset, tmp_path / "run2")

        assert run1["fold_accuracies"] == run2["fold_accuracies"], (
            f"Fold accuracies differ:\n  Run 1: {run1['fold_accuracies']}\n  Run 2: {run2['fold_accuracies']}"
        )
        assert run1["mean_accuracy"] == run2["mean_accuracy"], (
            f"Mean accuracy differs: {run1['mean_accuracy']} vs {run2['mean_accuracy']}"
        )
        assert run1["std_accuracy"] == run2["std_accuracy"], (
            f"Std accuracy differs: {run1['std_accuracy']} vs {run2['std_accuracy']}"
        )

    def test_feature_importance_rankings_are_identical_across_runs(
        self, dataset, tmp_path
    ):
        """Feature importance order and scores must be identical on repeated runs.

        Since the model is deterministic (same data + same seed), the gain-based
        importances must produce the same ranking and normalised scores.
        """
        run1 = self._run_pipeline(dataset, tmp_path / "run1")
        run2 = self._run_pipeline(dataset, tmp_path / "run2")

        imp1 = run1["importance_df"].reset_index(drop=True)
        imp2 = run2["importance_df"].reset_index(drop=True)

        # Feature names in same order
        assert imp1["feature_name"].tolist() == imp2["feature_name"].tolist(), (
            f"Feature name order differs:\n  Run 1: {imp1['feature_name'].tolist()}\n  Run 2: {imp2['feature_name'].tolist()}"
        )

        # Importance scores identical
        assert imp1["importance_score"].tolist() == imp2["importance_score"].tolist(), (
            f"Importance scores differ:\n  Run 1: {imp1['importance_score'].tolist()}\n  Run 2: {imp2['importance_score'].tolist()}"
        )

    def test_skipped_folds_are_identical_across_runs(self, dataset, tmp_path):
        """The set of skipped folds must be identical on repeated runs.

        Since the dataset size and TimeSeriesSplit are deterministic, the same
        folds must be skipped (or not skipped) each time.
        """
        run1 = self._run_pipeline(dataset, tmp_path / "run1")
        run2 = self._run_pipeline(dataset, tmp_path / "run2")

        assert run1["skipped_folds"] == run2["skipped_folds"], (
            f"Skipped folds differ: {run1['skipped_folds']} vs {run2['skipped_folds']}"
        )
