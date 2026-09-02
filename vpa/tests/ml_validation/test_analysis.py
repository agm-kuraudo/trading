"""Unit tests for AnalysisScript.

Contains:
- Test all composite scores null raises InsufficientDataError
- Test zero labelled rows raises error (empty dataset after filtering)
- Test all-zero importances produces warning and 0.0000 scores
- Test output file creation and overwrite behaviour
- Test summary text file format matches expected structure

Requirements: 3.4, 3.5, 5.4, 7.1, 7.2, 7.3, 7.5, 7.6
"""

import logging

import numpy as np
import pandas as pd
import pytest
from xgboost import XGBClassifier

from vpa.ml_validation.analysis import AnalysisScript
from vpa.ml_validation.exceptions import InsufficientDataError
from vpa.ml_validation.feature_extractor import VPAFeatureExtractor

# --- Helpers ---


def _make_valid_dataset(n_rows: int = 100, seed: int = 42) -> pd.DataFrame:
    """Create a synthetic dataset with valid feature columns, metadata, and labels.

    Produces a DataFrame matching the schema expected by AnalysisScript:
    27 feature columns + date + open + high + low + close + next_day_direction.
    """
    rng = np.random.default_rng(seed)

    data = {}
    for col in VPAFeatureExtractor.FEATURE_COLUMNS:
        data[col] = rng.standard_normal(n_rows)

    data["date"] = pd.date_range("2020-01-01", periods=n_rows, freq="B").strftime("%Y-%m-%d")
    # SP-335: raw OHLC metadata columns emitted alongside close
    data["open"] = rng.uniform(100, 500, size=n_rows)
    data["high"] = rng.uniform(100, 500, size=n_rows)
    data["low"] = rng.uniform(100, 500, size=n_rows)
    data["close"] = rng.uniform(100, 500, size=n_rows)
    data["next_day_direction"] = rng.integers(0, 2, size=n_rows)

    return pd.DataFrame(data)


def _train_constant_feature_model(n_rows: int = 200) -> XGBClassifier:
    """Train an XGBClassifier on a dataset where all features are constant.

    When all feature values are identical, the model cannot learn meaningful
    splits, resulting in all-zero gain-based feature importances.
    """
    # All features are constant (same value for every row)
    X = pd.DataFrame(
        np.ones((n_rows, len(VPAFeatureExtractor.FEATURE_COLUMNS))),
        columns=VPAFeatureExtractor.FEATURE_COLUMNS,
    )
    # Labels have some variance so XGBoost doesn't degenerate completely
    rng = np.random.default_rng(42)
    y = pd.Series(rng.integers(0, 2, size=n_rows))

    model = XGBClassifier(random_state=42, eval_metric="logloss", n_estimators=10)
    model.fit(X, y)
    return model


# =============================================================================
# Unit Tests - Baseline Accuracy Error Handling
# =============================================================================


class TestBaselineAccuracyErrors:
    """Tests for error conditions in compute_baseline_accuracy()."""

    def test_all_composite_scores_null_raises_insufficient_data_error(self, tmp_path):
        """When all composite_score values are NaN, zero valid rows remain.

        The method must raise InsufficientDataError since no rows have a
        valid composite score to classify with.
        Requirements: 3.4, 3.5
        """
        dataset = _make_valid_dataset(n_rows=50)
        dataset["composite_score"] = np.nan

        script = AnalysisScript(dataset=dataset, ticker="TEST", output_dir=tmp_path)

        with pytest.raises(InsufficientDataError):
            script.compute_baseline_accuracy()

    def test_empty_dataset_raises_insufficient_data_error(self, tmp_path):
        """An empty DataFrame (zero rows) raises InsufficientDataError.

        Requirements: 3.5
        """
        dataset = _make_valid_dataset(n_rows=10)
        # Filter to an empty dataset
        empty_dataset = dataset[dataset["composite_score"] > 9999.0].copy()

        script = AnalysisScript(dataset=empty_dataset, ticker="TEST", output_dir=tmp_path)

        with pytest.raises(InsufficientDataError):
            script.compute_baseline_accuracy()

    def test_partial_null_composite_scores_excludes_only_null_rows(self, tmp_path):
        """When some composite_score values are null, those rows are excluded
        but remaining valid rows are used for calculation.

        Requirements: 3.4
        """
        dataset = _make_valid_dataset(n_rows=50)
        # Set first 25 rows to NaN, leave last 25 valid
        dataset.loc[:24, "composite_score"] = np.nan
        # Set known values for verifiable result
        dataset.loc[25:, "composite_score"] = 5.0  # All positive → predict UP (1)
        dataset.loc[25:, "next_day_direction"] = 1  # All actually UP

        script = AnalysisScript(dataset=dataset, ticker="TEST", output_dir=tmp_path)
        accuracy = script.compute_baseline_accuracy()

        # All predictions should match actual (all UP = 1)
        assert accuracy == 1.0


# =============================================================================
# Unit Tests - Feature Importance
# =============================================================================


class TestFeatureImportance:
    """Tests for extract_feature_importance() method."""

    def test_all_zero_importances_produces_warning_and_zero_scores(self, tmp_path, caplog):
        """When all features have zero importance, a warning is logged
        and all scores are set to 0.0000.

        Requirements: 5.4
        """
        model = _train_constant_feature_model()
        dataset = _make_valid_dataset()
        script = AnalysisScript(dataset=dataset, ticker="TEST", output_dir=tmp_path)

        with caplog.at_level(logging.WARNING):
            importance_df = script.extract_feature_importance(model)

        # All scores should be 0.0000
        assert (
            importance_df["importance_score"] == 0.0
        ).all(), f"Expected all zeros, got: {importance_df['importance_score'].tolist()}"

        # A warning should have been logged
        assert any(
            "zero importance" in record.message.lower() or "no distinguishing features" in record.message.lower()
            for record in caplog.records
        ), f"Expected warning about zero importance, got: {[r.message for r in caplog.records]}"

    def test_importance_sorted_descending(self, tmp_path):
        """Feature importance must be sorted in descending order by score.

        Requirements: 5.2
        """
        # Train on a dataset with actual variance so we get non-zero importances
        rng = np.random.default_rng(42)
        n_rows = 200
        X = pd.DataFrame(
            rng.standard_normal((n_rows, len(VPAFeatureExtractor.FEATURE_COLUMNS))),
            columns=VPAFeatureExtractor.FEATURE_COLUMNS,
        )
        y = pd.Series(rng.integers(0, 2, size=n_rows))

        model = XGBClassifier(random_state=42, eval_metric="logloss")
        model.fit(X, y)

        dataset = _make_valid_dataset()
        script = AnalysisScript(dataset=dataset, ticker="TEST", output_dir=tmp_path)
        importance_df = script.extract_feature_importance(model)

        scores = importance_df["importance_score"].tolist()
        assert scores == sorted(scores, reverse=True), "Importance scores are not sorted in descending order"

    def test_importance_normalised_to_one(self, tmp_path):
        """Normalised importance scores must sum to 1.0 (within tolerance).

        Requirements: 5.3
        """
        rng = np.random.default_rng(123)
        n_rows = 200
        X = pd.DataFrame(
            rng.standard_normal((n_rows, len(VPAFeatureExtractor.FEATURE_COLUMNS))),
            columns=VPAFeatureExtractor.FEATURE_COLUMNS,
        )
        y = pd.Series(rng.integers(0, 2, size=n_rows))

        model = XGBClassifier(random_state=42, eval_metric="logloss")
        model.fit(X, y)

        dataset = _make_valid_dataset()
        script = AnalysisScript(dataset=dataset, ticker="TEST", output_dir=tmp_path)
        importance_df = script.extract_feature_importance(model)

        total = importance_df["importance_score"].sum()
        assert abs(total - 1.0) < 1e-4, f"Importance scores sum to {total}, expected ~1.0"


# =============================================================================
# Unit Tests - Output File Creation
# =============================================================================


class TestSaveOutputs:
    """Tests for save_outputs() method using tmp_path fixture."""

    def test_output_files_created_at_correct_paths(self, tmp_path):
        """save_outputs() creates all three output files at the expected paths.

        Requirements: 7.1, 7.2, 7.3
        """
        dataset = _make_valid_dataset()
        ticker = "SPY"
        script = AnalysisScript(dataset=dataset, ticker=ticker, output_dir=tmp_path)

        importance_df = pd.DataFrame(
            {
                "feature_name": ["adx", "spread_pct_p1"],
                "importance_score": [0.6000, 0.4000],
            }
        )
        summary_text = "VPA ML Validation Summary\n=========================\nTest summary"

        script.save_outputs(
            dataset=dataset,
            importance_df=importance_df,
            summary_text=summary_text,
        )

        # Verify all three files exist
        assert (tmp_path / f"{ticker}_vpa_features.csv").exists()
        assert (tmp_path / f"{ticker}_feature_importance.csv").exists()
        assert (tmp_path / f"{ticker}_analysis_summary.txt").exists()

    def test_output_directory_created_if_not_exists(self, tmp_path):
        """save_outputs() creates nested output directories that don't exist yet.

        Requirements: 7.4
        """
        nested_dir = tmp_path / "nested" / "output" / "dir"
        dataset = _make_valid_dataset()
        script = AnalysisScript(dataset=dataset, ticker="TEST", output_dir=nested_dir)

        importance_df = pd.DataFrame(
            {
                "feature_name": ["adx"],
                "importance_score": [1.0],
            }
        )

        script.save_outputs(
            dataset=dataset,
            importance_df=importance_df,
            summary_text="test summary",
        )

        assert nested_dir.exists()
        assert (nested_dir / "TEST_vpa_features.csv").exists()

    def test_output_files_overwrite_existing(self, tmp_path):
        """save_outputs() overwrites existing output files without error.

        Requirements: 7.5
        """
        ticker = "SPY"
        dataset = _make_valid_dataset()
        script = AnalysisScript(dataset=dataset, ticker=ticker, output_dir=tmp_path)

        importance_df = pd.DataFrame(
            {
                "feature_name": ["adx"],
                "importance_score": [1.0],
            }
        )

        # Write initial files
        script.save_outputs(
            dataset=dataset,
            importance_df=importance_df,
            summary_text="first version",
        )

        # Overwrite with new content
        script.save_outputs(
            dataset=dataset,
            importance_df=importance_df,
            summary_text="second version",
        )

        # Verify the file contains the latest content
        summary_path = tmp_path / f"{ticker}_analysis_summary.txt"
        content = summary_path.read_text(encoding="utf-8")
        assert "second version" in content
        assert "first version" not in content

    def test_filesystem_error_logged_and_continues(self, tmp_path, caplog, monkeypatch):
        """If writing one file fails, the error is logged and remaining files
        are still written.

        Requirements: 7.6
        """
        ticker = "SPY"
        dataset = _make_valid_dataset()
        script = AnalysisScript(dataset=dataset, ticker=ticker, output_dir=tmp_path)

        importance_df = pd.DataFrame(
            {
                "feature_name": ["adx"],
                "importance_score": [1.0],
            }
        )

        # Make the dataset CSV write fail by patching DataFrame.to_csv
        original_to_csv = pd.DataFrame.to_csv
        call_count = [0]

        def failing_to_csv(self_df, path_or_buf, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call (dataset CSV) fails
                raise OSError("Disk full")
            return original_to_csv(self_df, path_or_buf, **kwargs)

        monkeypatch.setattr(pd.DataFrame, "to_csv", failing_to_csv)

        with caplog.at_level(logging.ERROR):
            script.save_outputs(
                dataset=dataset,
                importance_df=importance_df,
                summary_text="test summary",
            )

        # The error should be logged
        assert any(
            "failed" in record.message.lower() or "disk full" in record.message.lower() for record in caplog.records
        ), f"Expected error log, got: {[r.message for r in caplog.records]}"

        # The importance CSV should still be written (second to_csv call succeeds)
        assert (tmp_path / f"{ticker}_feature_importance.csv").exists()

        # The summary text file should still be written
        assert (tmp_path / f"{ticker}_analysis_summary.txt").exists()

    def test_dataset_csv_has_correct_headers(self, tmp_path):
        """The saved dataset CSV has the expected column headers.

        Requirements: 7.1
        """
        dataset = _make_valid_dataset(n_rows=5)
        ticker = "TEST"
        script = AnalysisScript(dataset=dataset, ticker=ticker, output_dir=tmp_path)

        importance_df = pd.DataFrame({"feature_name": ["adx"], "importance_score": [1.0]})

        script.save_outputs(
            dataset=dataset,
            importance_df=importance_df,
            summary_text="test",
        )

        csv_path = tmp_path / f"{ticker}_vpa_features.csv"
        loaded = pd.read_csv(csv_path)

        # Should contain all feature columns + metadata + label
        expected_cols = (
            VPAFeatureExtractor.FEATURE_COLUMNS + VPAFeatureExtractor.METADATA_COLUMNS + ["next_day_direction"]
        )
        for col in expected_cols:
            assert col in loaded.columns, f"Missing column: {col}"


# =============================================================================
# Unit Tests - Summary Text Format
# =============================================================================


class TestSummaryTextFormat:
    """Tests for the summary text file structure and content."""

    def test_summary_text_contains_expected_sections(self, tmp_path):
        """The analysis summary text file contains baseline accuracy,
        ML accuracy, top features, and conclusion sections.

        Requirements: 7.3
        """
        dataset = _make_valid_dataset()
        ticker = "SPY"
        script = AnalysisScript(dataset=dataset, ticker=ticker, output_dir=tmp_path)

        # Build a representative summary text (as run_analysis.py would produce)
        summary_text = (
            "VPA ML Validation Summary\n"
            "=========================\n"
            "Ticker: SPY\n"
            "Data Range: 2020-01-01 to 2024-01-01\n"
            "Valid Feature Rows: 2500\n"
            "\n"
            "Baseline VPA Accuracy: 51.37%\n"
            "ML Walk-Forward Accuracy: 54.12% (+/- 2.85%)\n"
            "\n"
            "Top 5 Features by Importance:\n"
            "  1. adx (0.1523)\n"
            "  2. spread_pct_p3 (0.1201)\n"
            "  3. volume_pct_p1 (0.0987)\n"
            "  4. trend_score (0.0876)\n"
            "  5. up_bar_ratio_p2 (0.0754)\n"
            "\n"
            "Conclusion: Features have signal but scoring rules are suboptimal\n"
        )

        script.save_outputs(
            dataset=dataset,
            importance_df=pd.DataFrame({"feature_name": ["adx"], "importance_score": [1.0]}),
            summary_text=summary_text,
        )

        summary_path = tmp_path / f"{ticker}_analysis_summary.txt"
        content = summary_path.read_text(encoding="utf-8")

        # Verify required sections are present
        assert "Baseline VPA Accuracy:" in content
        assert "ML Walk-Forward Accuracy:" in content
        assert "Top 5 Features by Importance:" in content
        assert "Conclusion:" in content
        assert "Data Range:" in content
        assert "Valid Feature Rows:" in content

    def test_summary_saved_as_utf8_text(self, tmp_path):
        """The summary file is written with UTF-8 encoding.

        Requirements: 7.3
        """
        dataset = _make_valid_dataset()
        ticker = "TEST"
        script = AnalysisScript(dataset=dataset, ticker=ticker, output_dir=tmp_path)

        summary_text = "Summary with special chars: ±2.85%"

        script.save_outputs(
            dataset=dataset,
            importance_df=pd.DataFrame({"feature_name": ["adx"], "importance_score": [1.0]}),
            summary_text=summary_text,
        )

        summary_path = tmp_path / f"{ticker}_analysis_summary.txt"
        content = summary_path.read_text(encoding="utf-8")
        assert "±" in content
