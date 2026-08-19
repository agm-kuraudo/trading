import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score
from sklearn.model_selection import TimeSeriesSplit
from xgboost import XGBClassifier

from vpa.ml_validation.exceptions import InsufficientDataError

logger = logging.getLogger(__name__)


@dataclass
class WalkForwardResult:
    """Result of walk-forward cross-validation."""

    fold_accuracies: list[float]
    mean_accuracy: float
    std_accuracy: float
    model: Any  # XGBClassifier instance from last valid fold
    skipped_folds: list[int] = field(default_factory=list)


class WalkForwardValidator:
    """Walk-forward cross-validation with minimum sample enforcement."""

    def __init__(
        self,
        n_splits: int = 5,
        min_train_samples: int = 30,
        min_test_samples: int = 10,
        random_state: int = 42,
    ):
        """
        Args:
            n_splits: Number of TimeSeriesSplit folds.
            min_train_samples: Minimum training samples per fold; folds below this are skipped.
            min_test_samples: Minimum test samples per fold; folds below this are skipped.
            random_state: Random state seed for XGBClassifier reproducibility.
        """
        self.n_splits = n_splits
        self.min_train_samples = min_train_samples
        self.min_test_samples = min_test_samples
        self.random_state = random_state

    def validate(self, X: pd.DataFrame, y: pd.Series) -> WalkForwardResult:
        """
        Run walk-forward validation using TimeSeriesSplit.

        Skips folds with insufficient samples, logs warnings.
        Raises InsufficientDataError if all folds are skipped.

        Args:
            X: Feature DataFrame (only feature columns, no metadata or labels).
            y: Target Series with binary labels (0/1).

        Returns:
            WalkForwardResult with fold accuracies, mean, std, trained model,
            and list of skipped fold indices.
        """
        tscv = TimeSeriesSplit(n_splits=self.n_splits)

        fold_accuracies: list[float] = []
        skipped_folds: list[int] = []
        last_model: XGBClassifier | None = None

        for fold_idx, (train_index, test_index) in enumerate(tscv.split(X)):
            X_train, X_test = X.iloc[train_index], X.iloc[test_index]
            y_train, y_test = y.iloc[train_index], y.iloc[test_index]

            if len(X_train) < self.min_train_samples:
                logger.warning(
                    "Fold %d skipped: training set has %d samples (minimum %d required)",
                    fold_idx,
                    len(X_train),
                    self.min_train_samples,
                )
                skipped_folds.append(fold_idx)
                continue

            if len(X_test) < self.min_test_samples:
                logger.warning(
                    "Fold %d skipped: test set has %d samples (minimum %d required)",
                    fold_idx,
                    len(X_test),
                    self.min_test_samples,
                )
                skipped_folds.append(fold_idx)
                continue

            model = XGBClassifier(
                random_state=self.random_state,
                eval_metric="logloss",
            )
            model.fit(X_train, y_train)

            y_pred = model.predict(X_test)
            accuracy = accuracy_score(y_test, y_pred)
            fold_accuracies.append(accuracy)
            last_model = model

        if not fold_accuracies:
            raise InsufficientDataError(
                f"All {self.n_splits} walk-forward folds were skipped due to "
                f"insufficient data (min_train={self.min_train_samples}, "
                f"min_test={self.min_test_samples}). "
                f"Dataset has {len(X)} total samples."
            )

        mean_accuracy = float(np.mean(fold_accuracies))
        std_accuracy = float(np.std(fold_accuracies))

        return WalkForwardResult(
            fold_accuracies=fold_accuracies,
            mean_accuracy=mean_accuracy,
            std_accuracy=std_accuracy,
            model=last_model,
            skipped_folds=skipped_folds,
        )
