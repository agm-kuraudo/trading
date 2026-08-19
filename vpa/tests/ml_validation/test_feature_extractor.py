"""Unit tests for VPAFeatureExtractor.

Tests:
- enable_feature_extraction=False flag storage
- Dataset with exactly 2000 rows (boundary pass)
- Dataset with 1999 rows (raises InsufficientDataError)
- Warm-up period skipping (no features before period_three is full)

Requirements: 1.2, 1.3, 2.4
"""

import datetime
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from vpa.ml_validation.exceptions import InsufficientDataError
from vpa.ml_validation.feature_extractor import VPAFeatureExtractor

CONFIG_PATH = r"d:\projects\trading\vpa\config\config.json"
TICKER = "SPY"


# --- Helper to generate synthetic OHLCV data ---


def _make_ohlcv_dataframe(n_rows: int, start_date: str = "2010-01-04") -> pd.DataFrame:
    """Generate a synthetic OHLCV DataFrame mimicking yfinance output.

    Produces steadily trending price data so VPA logic can produce
    valid features without crashing on degenerate data.

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

    return pd.DataFrame({
        "Date": dates,
        "Open": opens,
        "High": highs,
        "Low": lows,
        "Close": closes,
        "Volume": volumes,
    })


# --- Test 1: enable_feature_extraction=False flag storage ---


class TestEnableExtractionFlag:
    """Test that enable_extraction=False is stored correctly."""

    def test_flag_stored_when_false(self):
        """When enable_extraction=False, the internal flag should be False."""
        extractor = VPAFeatureExtractor(
            config_path=CONFIG_PATH,
            ticker_symbol=TICKER,
            enable_extraction=False,
        )
        assert extractor._enable_extraction is False

    def test_flag_stored_when_true(self):
        """When enable_extraction=True (default), the internal flag should be True."""
        extractor = VPAFeatureExtractor(
            config_path=CONFIG_PATH,
            ticker_symbol=TICKER,
            enable_extraction=True,
        )
        assert extractor._enable_extraction is True

    def test_flag_defaults_to_true(self):
        """Default value for enable_extraction should be True."""
        extractor = VPAFeatureExtractor(
            config_path=CONFIG_PATH,
            ticker_symbol=TICKER,
        )
        assert extractor._enable_extraction is True


# --- Test 2: Dataset with exactly 2000 rows (boundary pass) ---


class TestMinimumRowBoundary:
    """Test the 2000-row minimum check boundary."""

    @patch("vpa.ml_validation.feature_extractor.yf.download")
    def test_exactly_2000_rows_passes(self, mock_yf_download):
        """A dataset producing exactly 2000 labelled rows after processing should pass.

        With PERIOD_THREE_LENGTH=50, warm-up skips 49 rows. After warm-up we get
        N-49 feature rows, then N-50 after final-row exclusion.
        So we need N=2050 raw rows -> 2050-49-1 = 2000 labelled rows.
        """
        n_raw = 2050
        mock_df = _make_ohlcv_dataframe(n_raw)
        mock_yf_download.return_value = mock_df

        extractor = VPAFeatureExtractor(
            config_path=CONFIG_PATH,
            ticker_symbol=TICKER,
            enable_extraction=True,
        )

        result = extractor.generate_dataset(days=3650)

        # Should not raise and should have >= 2000 rows
        assert len(result) >= 2000
        # Verify the DataFrame has expected columns
        for col in VPAFeatureExtractor.FEATURE_COLUMNS:
            assert col in result.columns
        assert "next_day_direction" in result.columns
        assert "date" in result.columns
        assert "close" in result.columns


# --- Test 3: Dataset with 1999 rows (raises InsufficientDataError) ---


class TestInsufficientDataError:
    """Test that fewer than 2000 labelled rows raises InsufficientDataError."""

    @patch("vpa.ml_validation.feature_extractor.yf.download")
    def test_1999_rows_raises_error(self, mock_yf_download):
        """A dataset producing fewer than 2000 labelled rows should raise InsufficientDataError.

        With PERIOD_THREE_LENGTH=50, warm-up skips 49 rows (deque needs 50 items
        before the condition len < 50 is false). After warm-up we get N-49 feature
        rows, then N-50 after final-row exclusion.
        So N=2049 -> 2049-49-1 = 1999 labelled rows -> triggers error.
        """
        n_raw = 2049
        mock_df = _make_ohlcv_dataframe(n_raw)
        mock_yf_download.return_value = mock_df

        extractor = VPAFeatureExtractor(
            config_path=CONFIG_PATH,
            ticker_symbol=TICKER,
            enable_extraction=True,
        )

        with pytest.raises(InsufficientDataError) as exc_info:
            extractor.generate_dataset(days=3650)

        assert "1999" in str(exc_info.value) or "Insufficient" in str(exc_info.value)

    @patch("vpa.ml_validation.feature_extractor.yf.download")
    def test_empty_download_raises_error(self, mock_yf_download):
        """An empty yfinance download should raise InsufficientDataError."""
        # Return a DataFrame with very few rows (less than period_three_length)
        mock_df = _make_ohlcv_dataframe(10)
        mock_yf_download.return_value = mock_df

        extractor = VPAFeatureExtractor(
            config_path=CONFIG_PATH,
            ticker_symbol=TICKER,
            enable_extraction=True,
        )

        with pytest.raises(InsufficientDataError):
            extractor.generate_dataset(days=3650)


# --- Test 4: Warm-up period skipping ---


class TestWarmUpPeriodSkipping:
    """Test that rows before period_three is full produce no features."""

    @patch("vpa.ml_validation.feature_extractor.yf.download")
    def test_warmup_rows_excluded(self, mock_yf_download):
        """Features should only be produced once period_three deque is full.

        With PERIOD_THREE_LENGTH=50, the condition `len < 50` skips the first
        49 rows (indices 0-48). Row index 49 is the first where len==50.
        So for N total rows: N-49 feature rows, then N-50 after final-row exclusion.
        """
        # Use enough rows to pass the 2000 minimum
        n_raw = 2100
        mock_df = _make_ohlcv_dataframe(n_raw)
        mock_yf_download.return_value = mock_df

        extractor = VPAFeatureExtractor(
            config_path=CONFIG_PATH,
            ticker_symbol=TICKER,
            enable_extraction=True,
        )

        result = extractor.generate_dataset(days=3650)

        # With 2100 raw rows: 2100 - 49 (warm-up) - 1 (final row) = 2050 labelled rows
        expected_rows = n_raw - 49 - 1
        assert len(result) == expected_rows

    @patch("vpa.ml_validation.feature_extractor.yf.download")
    def test_first_feature_date_is_after_warmup(self, mock_yf_download):
        """The first feature row's date should correspond to the row where
        period_three deque first becomes full (row index 49, the 50th row).
        """
        n_raw = 2100
        mock_df = _make_ohlcv_dataframe(n_raw)
        mock_yf_download.return_value = mock_df

        extractor = VPAFeatureExtractor(
            config_path=CONFIG_PATH,
            ticker_symbol=TICKER,
            enable_extraction=True,
        )

        result = extractor.generate_dataset(days=3650)

        # The first feature should be from row index 49 in mock_df
        # (period_three deque has maxlen=50, first full after 50 appends)
        first_feature_date = result.iloc[0]["date"]
        expected_date = mock_df.iloc[49]["Date"]
        if hasattr(expected_date, "isoformat"):
            expected_date_str = expected_date.isoformat()
        else:
            expected_date_str = str(expected_date)

        assert first_feature_date == expected_date_str

    @patch("vpa.ml_validation.feature_extractor.yf.download")
    def test_no_features_with_only_warmup_rows(self, mock_yf_download):
        """If data has fewer rows than PERIOD_THREE_LENGTH, no features are produced."""
        # Only 49 rows - not enough to fill period_three (50)
        mock_df = _make_ohlcv_dataframe(49)
        mock_yf_download.return_value = mock_df

        extractor = VPAFeatureExtractor(
            config_path=CONFIG_PATH,
            ticker_symbol=TICKER,
            enable_extraction=True,
        )

        with pytest.raises(InsufficientDataError):
            extractor.generate_dataset(days=3650)
