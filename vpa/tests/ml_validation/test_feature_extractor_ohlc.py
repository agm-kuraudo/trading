"""SP-335: raw OHLC (open/high/low) metadata enrichment for VPAFeatureExtractor.

This is the test-first (TDD) step for SP-335. It asserts the behaviour the
SP-335 change WILL introduce: ``generate_dataset`` must emit ``date``, ``open``,
``high``, ``low`` and ``close`` metadata columns, where ``open``/``high``/``low``
hold the RAW yfinance values - NOT the synthesised candle open (previous close)
and NOT the clamped high/low used internally for VPA candle logic.

Until the SP-335 production change lands, these tests are EXPECTED TO FAIL
because ``open``/``high``/``low`` are not emitted as columns.

yfinance is mocked so the tests are offline and deterministic.

Requirements: SP-335 DoD (raw OHLC in dataset); Design: Part A, SP-335 Tests.
"""

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from vpa.ml_validation.feature_extractor import VPAFeatureExtractor

CONFIG_PATH = r"d:\projects\trading\vpa\config\config.json"
TICKER = "SPY"

# PERIOD_THREE_LENGTH=50 -> warm-up skips the first 49 rows; the final row is
# excluded (no next-day label). 2050 raw rows -> 2050 - 49 - 1 = 2000 labelled
# rows, which exactly clears the >=2000 gate in generate_dataset.
N_RAW_ROWS = 2050


def _make_distinct_ohlcv_dataframe(n_rows: int, start_date: str = "2010-01-04") -> pd.DataFrame:
    """Generate a deterministic OHLCV DataFrame where the RAW open/high/low are
    intentionally distinct from the synthesised-candle values.

    The extractor synthesises the candle open as the *previous* close and clamps
    ``high = max(raw_high, synth_open)`` / ``low = min(raw_low, synth_open)``.
    To make raw-vs-synthesised assertions meaningful we construct the series so
    that, for every emitted row:

    - the raw ``Open`` differs from the previous close (synthesised open), and
    - the raw ``High`` and ``Low`` are wide enough that clamping against the
      synthesised open never alters them (so the raw values are unambiguous).

    Prices trend smoothly upward so the VPA logic produces valid features.

    Args:
        n_rows: Number of trading-day rows to generate.
        start_date: Start date for the (business-day) time series.

    Returns:
        DataFrame with columns Date, Open, High, Low, Close, Volume.
    """
    dates = pd.bdate_range(start=start_date, periods=n_rows)

    # Smooth, strictly increasing closes: previous close (the synthesised open)
    # is always different from the raw open we set below.
    idx = np.arange(n_rows, dtype=float)
    closes = 100.0 + idx * 0.5

    # Raw open deliberately offset well below the close (and therefore below the
    # previous close), guaranteeing raw_open != previous_close for every row.
    opens = closes - 3.0

    # Wide raw high/low so max(raw_high, synth_open) == raw_high and
    # min(raw_low, synth_open) == raw_low: clamping is a no-op, so the emitted
    # metadata (raw) and the synthesised-candle high/low happen to coincide only
    # because we made the raw range dominate. The assertion still distinguishes
    # raw open (which clamping never touches) from the synthesised open.
    highs = closes + 5.0
    lows = closes - 8.0

    volumes = np.full(n_rows, 5_000_000.0)

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


class TestRawOhlcMetadataColumns:
    """SP-335: generate_dataset emits raw open/high/low alongside date/close."""

    @patch("vpa.ml_validation.feature_extractor.yf.download")
    def test_dataset_includes_raw_ohlc_metadata_columns(self, mock_yf_download):
        """After SP-335 the DataFrame must include date, open, high, low, close.

        EXPECTED TO FAIL before the SP-335 change (open/high/low absent)."""
        mock_df = _make_distinct_ohlcv_dataframe(N_RAW_ROWS)
        mock_yf_download.return_value = mock_df

        extractor = VPAFeatureExtractor(
            config_path=CONFIG_PATH,
            ticker_symbol=TICKER,
            enable_extraction=True,
        )

        result = extractor.generate_dataset(days=3650)

        for col in ("date", "open", "high", "low", "close"):
            assert col in result.columns, f"expected metadata column '{col}' to be present"

    @patch("vpa.ml_validation.feature_extractor.yf.download")
    def test_emitted_open_high_low_are_raw_yfinance_values(self, mock_yf_download):
        """open/high/low must equal the RAW yfinance inputs, not the synthesised
        candle open (previous close) nor a clamped high/low.

        EXPECTED TO FAIL before the SP-335 change (open/high/low absent)."""
        mock_df = _make_distinct_ohlcv_dataframe(N_RAW_ROWS)
        mock_yf_download.return_value = mock_df

        extractor = VPAFeatureExtractor(
            config_path=CONFIG_PATH,
            ticker_symbol=TICKER,
            enable_extraction=True,
        )

        result = extractor.generate_dataset(days=3650)

        # Map each emitted row back to its source raw row by date so we compare
        # against the exact raw yfinance values regardless of warm-up offset.
        def _date_key(value) -> str:
            return value.isoformat() if hasattr(value, "isoformat") else str(value)

        raw_by_date = {}
        index_by_date = {}
        for src_idx, (d, o, h, low, c) in enumerate(
            zip(
                mock_df["Date"],
                mock_df["Open"],
                mock_df["High"],
                mock_df["Low"],
                mock_df["Close"],
                strict=False,
            )
        ):
            key = _date_key(d)
            raw_by_date[key] = (o, h, low, c)
            index_by_date[key] = src_idx

        # Check several emitted rows, including at least two where the
        # synthesised open (previous close) provably differs from the raw open.
        sample_positions = [0, 1, 2, len(result) // 2, len(result) - 1]
        checked_distinct = 0
        for pos in sample_positions:
            emitted = result.iloc[pos]
            date_key = emitted["date"]
            raw_open, raw_high, raw_low, raw_close = raw_by_date[date_key]

            assert emitted["open"] == pytest.approx(raw_open), "open must be the RAW yfinance open"
            assert emitted["high"] == pytest.approx(raw_high), "high must be the RAW yfinance high"
            assert emitted["low"] == pytest.approx(raw_low), "low must be the RAW yfinance low"
            assert emitted["close"] == pytest.approx(raw_close)

            # The synthesised candle open would be the PREVIOUS close. Confirm the
            # raw open we assert on genuinely differs from that synthesised value.
            src_idx = index_by_date[date_key]
            if src_idx > 0:
                synthesised_open = float(mock_df.iloc[src_idx - 1]["Close"])
                assert raw_open != pytest.approx(
                    synthesised_open
                ), "test fixture must make raw open differ from synthesised open"
                checked_distinct += 1

        assert checked_distinct >= 2, "expected at least two rows distinguishing raw vs synthesised open"


class TestSynthesisedFeatureComputationUnchanged:
    """SP-335 must not change the synthesised-candle feature computation."""

    @patch("vpa.ml_validation.feature_extractor.yf.download")
    def test_feature_columns_and_labels_still_present_and_populated(self, mock_yf_download):
        """The full FEATURE_COLUMNS set, close, and next_day_direction must still
        exist and be populated (no NaNs), proving feature computation is intact."""
        mock_df = _make_distinct_ohlcv_dataframe(N_RAW_ROWS)
        mock_yf_download.return_value = mock_df

        extractor = VPAFeatureExtractor(
            config_path=CONFIG_PATH,
            ticker_symbol=TICKER,
            enable_extraction=True,
        )

        result = extractor.generate_dataset(days=3650)

        for col in VPAFeatureExtractor.FEATURE_COLUMNS:
            assert col in result.columns, f"feature column '{col}' must remain present"
            assert not result[col].isna().any(), f"feature column '{col}' must be populated"

        assert "composite_score" in result.columns
        assert not result["composite_score"].isna().any()

        assert "close" in result.columns
        assert not result["close"].isna().any()

        assert "next_day_direction" in result.columns
        assert set(result["next_day_direction"].unique()).issubset({0, 1})
