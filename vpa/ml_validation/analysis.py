"""VPA ML Validation - AnalysisScript for baseline accuracy and feature importance."""

import logging
from pathlib import Path

import numpy as np
import pandas as pd
from xgboost import XGBClassifier

from vpa.ml_validation.conclusion import ConclusionEngine
from vpa.ml_validation.exceptions import InsufficientDataError
from vpa.ml_validation.feature_extractor import VPAFeatureExtractor
from vpa.ml_validation.walk_forward import WalkForwardResult, WalkForwardValidator

logger = logging.getLogger(__name__)


class AnalysisScript:
    """Runs the full VPA ML validation analysis pipeline."""

    def __init__(self, dataset: pd.DataFrame, ticker: str, output_dir: Path):
        """
        Args:
            dataset: DataFrame with VPAFeatureExtractor.FEATURE_COLUMNS +
                     METADATA_COLUMNS + ["next_day_direction"].
            ticker: Ticker symbol (e.g. "SPY").
            output_dir: Path to the output directory for artefacts.
        """
        self.dataset = dataset
        self.ticker = ticker
        self.output_dir = Path(output_dir)

    def compute_baseline_accuracy(self) -> float:
        """
        Compute baseline accuracy using VPA composite score sign as predictor.

        Classification rule:
        - UP (1) when composite_score > 0
        - DOWN (0) when composite_score <= 0

        Excludes rows with null/NaN composite_score.

        Returns:
            Accuracy as a float between 0 and 1.

        Raises:
            InsufficientDataError: If dataset has zero valid labelled rows
                after excluding null composite scores.
        """
        # Filter to rows with non-null composite_score
        valid_rows = self.dataset.dropna(subset=["composite_score"])

        if len(valid_rows) == 0:
            raise InsufficientDataError(
                f"Cannot compute baseline accuracy for {self.ticker}: "
                f"zero rows with valid composite_score."
            )

        # Classify: UP (1) when composite_score > 0, DOWN (0) when <= 0
        predicted = (valid_rows["composite_score"] > 0).astype(int)
        actual = valid_rows["next_day_direction"]

        # Accuracy = proportion of correct predictions
        accuracy = float((predicted == actual).sum()) / len(valid_rows)

        return accuracy

    def extract_feature_importance(self, model: XGBClassifier) -> pd.DataFrame:
        """
        Extract gain-based feature importance from trained XGBoost model.

        Normalises scores to sum to 1.0, sorts descending by importance_score,
        and rounds to 4 decimal places.

        Args:
            model: Trained XGBClassifier instance.

        Returns:
            DataFrame with columns [feature_name, importance_score],
            sorted descending by importance_score, normalised to sum 1.0.
            All scores have 4 decimal places.
        """
        feature_names = VPAFeatureExtractor.FEATURE_COLUMNS

        # Extract gain-based importance from the booster
        booster = model.get_booster()
        gain_scores = booster.get_score(importance_type="gain")

        # Build importance array in feature column order
        importance_values = []
        for name in feature_names:
            importance_values.append(gain_scores.get(name, 0.0))

        importance_array = np.array(importance_values, dtype=float)

        # Check for all-zero importance
        total = importance_array.sum()
        if total == 0.0:
            logger.warning(
                "All features have zero importance for %s. "
                "The model found no distinguishing features.",
                self.ticker,
            )
            normalised = np.zeros(len(feature_names))
        else:
            normalised = importance_array / total

        # Round to 4 decimal places, then adjust largest value to ensure
        # sum stays within floating-point tolerance of 1.0
        normalised = np.round(normalised, 4)
        if total > 0.0:
            residual = round(1.0 - normalised.sum(), 4)
            if residual != 0.0:
                max_idx = int(np.argmax(normalised))
                normalised[max_idx] = round(normalised[max_idx] + residual, 4)

        # Build DataFrame
        importance_df = pd.DataFrame(
            {
                "feature_name": feature_names,
                "importance_score": normalised,
            }
        )

        # Sort descending by importance_score
        importance_df = importance_df.sort_values(
            "importance_score", ascending=False
        ).reset_index(drop=True)

        return importance_df

    def run_walk_forward_validation(self, n_splits: int = 5) -> WalkForwardResult:
        """
        Train XGBoost with TimeSeriesSplit walk-forward validation.

        Filters the dataset to feature-only columns (excluding date, close,
        and next_day_direction), then delegates to WalkForwardValidator.

        Args:
            n_splits: Number of TimeSeriesSplit folds.

        Returns:
            WalkForwardResult containing per-fold accuracies, mean, std,
            and the final trained model.

        Raises:
            InsufficientDataError: If all splits are skipped.
        """
        # Exclude metadata and label columns — keep only the 27 feature columns
        exclude_cols = VPAFeatureExtractor.METADATA_COLUMNS + ["next_day_direction"]
        feature_cols = [
            col for col in self.dataset.columns if col not in exclude_cols
        ]

        X = self.dataset[feature_cols]
        y = self.dataset["next_day_direction"]

        validator = WalkForwardValidator(n_splits=n_splits)
        return validator.validate(X, y)

    def generate_conclusion(self, baseline_acc: float, ml_acc: float) -> str:
        """
        Apply conclusion logic per Requirement 6 thresholds.

        Converts accuracy values from [0, 1] float to percentage,
        then delegates to ConclusionEngine.

        Args:
            baseline_acc: Baseline VPA accuracy as a float between 0 and 1.
            ml_acc: ML walk-forward mean accuracy as a float between 0 and 1.

        Returns:
            One of the five defined conclusion strings.
        """
        baseline_pct = baseline_acc * 100.0
        ml_pct = ml_acc * 100.0
        return ConclusionEngine.determine_conclusion(baseline_pct, ml_pct)

    def save_outputs(
        self,
        dataset: pd.DataFrame,
        importance_df: pd.DataFrame,
        summary_text: str,
    ) -> None:
        """
        Write all output artefacts to the output directory.

        Creates the output directory if it doesn't exist. Writes:
        - {ticker}_vpa_features.csv (dataset)
        - {ticker}_feature_importance.csv (importance report)
        - {ticker}_analysis_summary.txt (summary text)

        If any write fails, logs the error and continues to the next file.

        Args:
            dataset: The full feature dataset DataFrame to save as CSV.
            importance_df: Feature importance DataFrame to save as CSV.
            summary_text: The analysis summary string to save as text.
        """
        # Create output directory if it doesn't exist
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(
                "Failed to create output directory %s: %s", self.output_dir, e
            )
            return

        # Save dataset CSV
        dataset_path = self.output_dir / f"{self.ticker}_vpa_features.csv"
        try:
            dataset.to_csv(dataset_path, index=False)
        except OSError as e:
            logger.error("Failed to write dataset CSV %s: %s", dataset_path, e)

        # Save feature importance CSV
        importance_path = (
            self.output_dir / f"{self.ticker}_feature_importance.csv"
        )
        try:
            importance_df.to_csv(importance_path, index=False)
        except OSError as e:
            logger.error(
                "Failed to write feature importance CSV %s: %s",
                importance_path,
                e,
            )

        # Save analysis summary text
        summary_path = self.output_dir / f"{self.ticker}_analysis_summary.txt"
        try:
            summary_path.write_text(summary_text, encoding="utf-8")
        except OSError as e:
            logger.error(
                "Failed to write analysis summary %s: %s", summary_path, e
            )
