"""Integration tests for the full VPA ML validation pipeline.

Tests:
1. End-to-end pipeline with mocked yfinance (300+ rows) completes without error
2. Output files exist with correct names and headers after pipeline run
3. Summary file contains all required sections (baseline, ML accuracy, top 5 features,
   conclusion, date range)

Requirements: 7.1, 7.2, 7.3, 8.3, 8.4

SP-349 (Task 8.3/8.6): the feature extractor now sources bars from
``MarketDataRepository.load_ohlcv`` rather than ``yf.download``. ``run_analysis.main``
builds its own extractor and calls ``generate_dataset`` with no injected repo, so these
tests patch ``vpa.ml_validation.feature_extractor.MarketDataRepository`` with a stub
whose ``load_ohlcv`` returns the same synthetic OHLCV frame the tests previously fed
through the mocked ``yf.download``. The pipeline stays offline and deterministic and all
assertions are unchanged.
"""

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from vpa.ml_validation.run_analysis import main

CONFIG_PATH = r"d:\projects\trading\vpa\config\config.json"


class _FakeRepo:
    """Stub ``MarketDataRepository`` returning a fixed canonical OHLCV frame.

    Instantiated with no args (matching ``MarketDataRepository()`` inside
    ``generate_dataset``) but reads the module-level ``_FAKE_REPO_DF`` set by each test
    via ``_patch_repo``. Performs no network I/O.
    """

    def load_ohlcv(self, ticker, interval, start, end) -> pd.DataFrame:
        return _FAKE_REPO_DF.copy()


# Module-level frame the patched repository serves; set by _patch_repo() per test.
_FAKE_REPO_DF: pd.DataFrame | None = None


def _patch_repo(df: pd.DataFrame):
    """Return a patch context that makes the feature extractor's repository seam
    serve ``df`` offline (no network). Use as ``with _patch_repo(df):``."""
    global _FAKE_REPO_DF
    _FAKE_REPO_DF = df
    return patch("vpa.ml_validation.feature_extractor.MarketDataRepository", _FakeRepo)


# --- Helper to generate synthetic OHLCV data ---


def _make_ohlcv_dataframe(n_rows: int, start_date: str = "2010-01-04") -> pd.DataFrame:
    """Generate a synthetic OHLCV DataFrame mimicking yfinance output.

    Produces steadily trending price data with enough variance for VPA logic
    to produce valid features without crashing on degenerate data.

    Args:
        n_rows: Number of trading day rows to generate.
        start_date: Start date for the time series.

    Returns:
        DataFrame with columns Date, Open, High, Low, Close, Volume.
    """
    rng = np.random.default_rng(42)
    dates = pd.bdate_range(start=start_date, periods=n_rows)

    # Start with a base price and random walk
    base_price = 100.0
    returns = rng.normal(0.0005, 0.01, size=n_rows)
    closes = base_price * np.cumprod(1 + returns)

    # Generate OHLC from close
    opens = closes * (1 + rng.normal(0, 0.002, size=n_rows))
    highs = np.maximum(opens, closes) * (1 + rng.uniform(0.001, 0.01, size=n_rows))
    lows = np.minimum(opens, closes) * (1 - rng.uniform(0.001, 0.01, size=n_rows))
    volumes = rng.integers(1_000_000, 100_000_000, size=n_rows).astype(float)

    return pd.DataFrame(
        {
            "Date": dates,
            "Open": opens,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": volumes,
        }
    )


# --- Test 1: End-to-end pipeline completes without error ---


class TestEndToEndPipeline:
    """Test that the full pipeline runs end-to-end with mocked data."""

    def test_pipeline_completes_without_error(self, tmp_path):
        """Run main() with store-sourced data and verify it completes.

        Uses 2100+ rows to ensure the dataset exceeds the 2000-row minimum
        after warm-up (PERIOD_THREE_LENGTH=50 skips 49 rows, then final row
        excluded: 2100 - 49 - 1 = 2050 labelled rows).
        """
        mock_df = _make_ohlcv_dataframe(2150)

        # Should not raise any exception
        with _patch_repo(mock_df):
            main(
                ticker="SPY",
                output_dir=str(tmp_path),
                config_path=CONFIG_PATH,
            )

    def test_pipeline_prints_summary_to_stdout(self, tmp_path, capsys):
        """Pipeline should print summary information to stdout."""
        mock_df = _make_ohlcv_dataframe(2150)

        with _patch_repo(mock_df):
            main(
                ticker="SPY",
                output_dir=str(tmp_path),
                config_path=CONFIG_PATH,
            )

        captured = capsys.readouterr()
        # Key output lines should be present
        assert "Baseline VPA Accuracy" in captured.out
        assert "ML Walk-Forward Accuracy" in captured.out
        assert "Conclusion:" in captured.out
        assert "Pipeline complete!" in captured.out


# --- Test 2: Output files exist with correct names and headers ---


class TestOutputFileCreation:
    """Test that output files are created with correct names and structure."""

    def test_dataset_csv_exists(self, tmp_path):
        """The pipeline should create {ticker}_vpa_features.csv."""
        mock_df = _make_ohlcv_dataframe(2150)

        with _patch_repo(mock_df):
            main(
                ticker="SPY",
                output_dir=str(tmp_path),
                config_path=CONFIG_PATH,
            )

        dataset_path = tmp_path / "SPY_vpa_features.csv"
        assert dataset_path.exists(), "Dataset CSV file was not created"

    def test_feature_importance_csv_exists(self, tmp_path):
        """The pipeline should create {ticker}_feature_importance.csv."""
        mock_df = _make_ohlcv_dataframe(2150)

        with _patch_repo(mock_df):
            main(
                ticker="SPY",
                output_dir=str(tmp_path),
                config_path=CONFIG_PATH,
            )

        importance_path = tmp_path / "SPY_feature_importance.csv"
        assert importance_path.exists(), "Feature importance CSV file was not created"

    def test_summary_txt_exists(self, tmp_path):
        """The pipeline should create {ticker}_analysis_summary.txt."""
        mock_df = _make_ohlcv_dataframe(2150)

        with _patch_repo(mock_df):
            main(
                ticker="SPY",
                output_dir=str(tmp_path),
                config_path=CONFIG_PATH,
            )

        summary_path = tmp_path / "SPY_analysis_summary.txt"
        assert summary_path.exists(), "Analysis summary text file was not created"

    def test_dataset_csv_headers(self, tmp_path):
        """Dataset CSV should have all 27 feature columns plus metadata and label."""
        mock_df = _make_ohlcv_dataframe(2150)

        with _patch_repo(mock_df):
            main(
                ticker="SPY",
                output_dir=str(tmp_path),
                config_path=CONFIG_PATH,
            )

        dataset_path = tmp_path / "SPY_vpa_features.csv"
        df = pd.read_csv(dataset_path)

        from vpa.ml_validation.feature_extractor import VPAFeatureExtractor

        # All 27 feature columns must be present
        for col in VPAFeatureExtractor.FEATURE_COLUMNS:
            assert col in df.columns, f"Missing feature column: {col}"

        # Metadata columns
        assert "date" in df.columns
        assert "close" in df.columns

        # Label column
        assert "next_day_direction" in df.columns

    def test_feature_importance_csv_headers(self, tmp_path):
        """Feature importance CSV should have feature_name and importance_score columns."""
        mock_df = _make_ohlcv_dataframe(2150)

        with _patch_repo(mock_df):
            main(
                ticker="SPY",
                output_dir=str(tmp_path),
                config_path=CONFIG_PATH,
            )

        importance_path = tmp_path / "SPY_feature_importance.csv"
        df = pd.read_csv(importance_path)

        assert "feature_name" in df.columns
        assert "importance_score" in df.columns
        # DSS adds bullish/bearish crossover features to the existing feature set.
        assert len(df) == 31
        assert {"dss_bullish_cross", "dss_bearish_cross"} <= set(df["feature_name"])

    def test_feature_importance_scores_sum_to_one(self, tmp_path):
        """Feature importance scores should sum to approximately 1.0."""
        mock_df = _make_ohlcv_dataframe(2150)

        with _patch_repo(mock_df):
            main(
                ticker="SPY",
                output_dir=str(tmp_path),
                config_path=CONFIG_PATH,
            )

        importance_path = tmp_path / "SPY_feature_importance.csv"
        df = pd.read_csv(importance_path)

        total = df["importance_score"].sum()
        assert abs(total - 1.0) < 1e-4, f"Importance scores sum to {total}, expected ~1.0"


# --- Test 3: Summary file contains all required sections ---


class TestSummaryFileContent:
    """Test that the analysis summary contains all required sections."""

    @pytest.fixture
    def summary_content(self, tmp_path):
        """Run the pipeline and return the summary file content."""
        mock_df = _make_ohlcv_dataframe(2150)
        with _patch_repo(mock_df):
            main(
                ticker="SPY",
                output_dir=str(tmp_path),
                config_path=CONFIG_PATH,
            )

        summary_path = tmp_path / "SPY_analysis_summary.txt"
        return summary_path.read_text(encoding="utf-8")

    def test_summary_contains_ticker(self, summary_content):
        """Summary should contain the ticker symbol."""
        assert "Ticker: SPY" in summary_content

    def test_summary_contains_baseline_accuracy(self, summary_content):
        """Summary should contain baseline VPA accuracy as a percentage."""
        assert "Baseline VPA Accuracy:" in summary_content
        # Should have a percentage value
        assert "%" in summary_content

    def test_summary_contains_ml_accuracy(self, summary_content):
        """Summary should contain ML walk-forward accuracy with std dev."""
        assert "ML Walk-Forward Accuracy:" in summary_content
        # Should contain +/- notation for standard deviation
        assert "+/-" in summary_content

    def test_summary_contains_top_5_features(self, summary_content):
        """Summary should list top 5 features by importance."""
        assert "Top 5 Features by Importance:" in summary_content
        # Check that numbered entries 1-5 are present
        assert "  1." in summary_content
        assert "  2." in summary_content
        assert "  3." in summary_content
        assert "  4." in summary_content
        assert "  5." in summary_content

    def test_summary_contains_conclusion(self, summary_content):
        """Summary should contain a conclusion string."""
        assert "Conclusion:" in summary_content
        # The conclusion must be one of the five defined strings
        valid_conclusions = [
            "No predictive edge detected",
            "Features have signal but scoring rules are suboptimal",
            "Real edge exists and ML improves it",
            "Rule-based approach is near-optimal",
            "Rule-based approach outperforms ML on this dataset",
        ]
        assert any(
            conclusion in summary_content for conclusion in valid_conclusions
        ), "Summary does not contain a valid conclusion string"

    def test_summary_contains_date_range(self, summary_content):
        """Summary should contain the data date range."""
        assert "Data Range:" in summary_content

    def test_summary_contains_valid_rows_count(self, summary_content):
        """Summary should contain the number of valid feature rows."""
        assert "Valid Feature Rows:" in summary_content
