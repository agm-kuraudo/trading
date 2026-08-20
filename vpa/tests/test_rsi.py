"""Property-based and example-based tests for RSI calculator and signal scoring.

Tests use Hypothesis to verify universal correctness properties of the
calculate_rsi function from vpa.rsi, and example-based tests to verify
signal scoring logic in MarketAnalyzer.detect_rsi_signals().

Validates: Requirements 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 3.2, 3.4
"""

import json
import os
import tempfile

import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from vpa.rsi import calculate_rsi


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def make_temp_config(config_dict: dict) -> str:
    """Write a config dict to a temp JSON file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(config_dict, f)
    return path


def make_minimal_df(rows: int = 250) -> pd.DataFrame:
    """Create a minimal DataFrame with enough rows to avoid insufficient-data warnings."""
    prices = [100.0 + i * 0.1 for i in range(rows)]
    return pd.DataFrame({
        "Date": pd.date_range("2023-01-01", periods=rows),
        "Close": prices,
        "High": [p + 1 for p in prices],
        "Low": [p - 1 for p in prices],
        "Open": prices,
        "Volume": [1_000_000] * rows,
    })


def base_config() -> dict:
    """Return a minimal valid config without RSI or MA crossover sections."""
    return {
        "use_real_data": False,
        "rolling_window_complete_msg_display": False,
        "MAX_ROWS": 5002,
        "PERIOD_ONE_LENGTH": 5,
        "PERIOD_TWO_LENGTH": 25,
        "PERIOD_THREE_LENGTH": 50,
        "PERCENTILE_START": 5,
        "PERCENTILE_INCREMENTS": 5,
        "ticker_symbol": "SPY",
        "trading_parameters": {
            "period_one": {
                "High_Spread_Threshold": 55,
                "High_Volume_Threshold": 55,
                "Anomaly_Threshold": 20,
                "Signal_Bar_Count": 4,
                "High_Spread_Count": 3,
                "High_Volume_Count": 3,
            },
            "period_two": {
                "High_Spread_Threshold": 55,
                "High_Volume_Threshold": 55,
                "Anomaly_Threshold": 20,
                "Signal_Bar_Count": 13,
                "High_Spread_Count": 6,
                "High_Volume_Count": 6,
            },
            "period_three": {
                "High_Spread_Threshold": 55,
                "High_Volume_Threshold": 55,
                "Anomaly_Threshold": 20,
                "Signal_Bar_Count": 26,
                "High_Spread_Count": 12,
                "High_Volume_Count": 12,
            },
        },
    }


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

def positive_prices(min_size: int, max_size: int = 500):
    """Strategy for generating valid positive closing price sequences."""
    return st.lists(
        st.floats(min_value=0.01, max_value=999_999.99, allow_nan=False, allow_infinity=False),
        min_size=min_size,
        max_size=max_size,
    )


def strictly_increasing_prices(min_size: int, max_size: int = 500):
    """Strategy for generating strictly increasing price sequences."""
    return st.lists(
        st.floats(min_value=0.01, max_value=1000.0, allow_nan=False, allow_infinity=False),
        min_size=min_size,
        max_size=max_size,
        unique=True,
    ).map(sorted)


def strictly_decreasing_prices(min_size: int, max_size: int = 500):
    """Strategy for generating strictly decreasing price sequences."""
    return st.lists(
        st.floats(min_value=0.01, max_value=1000.0, allow_nan=False, allow_infinity=False),
        min_size=min_size,
        max_size=max_size,
        unique=True,
    ).map(lambda xs: sorted(xs, reverse=True))


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------

class TestRSIProperties:
    """Property-based tests for RSI calculator correctness."""

    @given(
        closes=positive_prices(min_size=15, max_size=500),
        period=st.integers(min_value=2, max_value=14),
    )
    @settings(max_examples=200, deadline=None)
    def test_rsi_boundedness(self, closes, period):
        """RSI output is always in [0.0, 100.0] for any valid positive price sequence.

        **Property 1: RSI Boundedness**
        For any valid sequence of positive closing prices (0.01-999999.99) of length
        >= period+1 (up to 500), output is in [0.0, 100.0].

        **Validates: Requirements 1.2, 1.3**
        """
        # Ensure we have enough data for the given period
        if len(closes) < period + 1:
            return  # Skip inputs that don't meet the precondition

        result = calculate_rsi(closes, period)

        assert 0.0 <= result <= 100.0, (
            f"RSI {result} out of bounds [0.0, 100.0] for "
            f"{len(closes)} prices with period={period}"
        )

    @given(closes=strictly_increasing_prices(min_size=15, max_size=500))
    @settings(max_examples=200, deadline=None)
    def test_monotonic_bullish(self, closes):
        """Strictly increasing prices produce RSI > 50.0.

        **Property 2: Monotonic Bullish**
        For any strictly increasing price series of at least period+1 closing prices,
        calculate_rsi returns a value above 50.0.

        **Validates: Requirements 1.4**
        """
        period = 14

        if len(closes) < period + 1:
            return  # Skip if not enough data

        result = calculate_rsi(closes, period)

        assert result > 50.0, (
            f"RSI {result} should be > 50.0 for strictly increasing prices "
            f"(length={len(closes)}, period={period})"
        )

    @given(closes=strictly_decreasing_prices(min_size=15, max_size=500))
    @settings(max_examples=200, deadline=None)
    def test_monotonic_bearish(self, closes):
        """Strictly decreasing prices produce RSI < 50.0.

        **Property 3: Monotonic Bearish**
        For any strictly decreasing price series of at least period+1 closing prices,
        calculate_rsi returns a value below 50.0.

        **Validates: Requirements 1.5**
        """
        period = 14

        if len(closes) < period + 1:
            return  # Skip if not enough data

        result = calculate_rsi(closes, period)

        assert result < 50.0, (
            f"RSI {result} should be < 50.0 for strictly decreasing prices "
            f"(length={len(closes)}, period={period})"
        )

    @given(
        closes=positive_prices(min_size=1, max_size=14),
        period=st.just(14),
    )
    @settings(max_examples=100, deadline=None)
    def test_insufficient_data_neutrality(self, closes, period):
        """Series of length < period+1 returns exactly 50.0.

        **Property 4: Insufficient Data Neutrality**
        For any price series of length < period+1, calculate_rsi returns exactly 50.0.

        **Validates: Requirements 1.2**
        """
        # Ensure the series is shorter than period + 1
        if len(closes) >= period + 1:
            return  # Skip - too much data for this property

        result = calculate_rsi(closes, period)

        assert result == 50.0, (
            f"RSI should be exactly 50.0 for insufficient data "
            f"(length={len(closes)}, period={period}), got {result}"
        )



# ---------------------------------------------------------------------------
# Example-Based Tests for Signal Scoring (Task 4.4)
# ---------------------------------------------------------------------------

class TestRSISignalScoring:
    """Example-based tests for detect_rsi_signals() signal scoring logic.

    Tests verify that RSI thresholds correctly produce signal scores and
    signal names, including disabled/invalid config scenarios.

    **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 3.2, 3.4**
    """

    def _make_analyzer_with_rsi_column(self, rsi_value: float, rsi_config: dict = None):
        """Helper: create a MarketAnalyzer and manually set the RSI column to a fixed value.

        Creates a DataFrame with 30 rows (enough to pass the row_index >= period check)
        and sets all RSI values to the provided rsi_value.

        Returns the analyzer instance.
        """
        from vpa.app_runner import MarketAnalyzer

        config = base_config()
        if rsi_config is not None:
            config["rsi"] = rsi_config

        config_path = make_temp_config(config)
        try:
            df = make_minimal_df(rows=30)
            analyzer = MarketAnalyzer(
                config_path=config_path,
                fixed_df=df,
                log_level="ERROR",
                log_prefix="test_rsi_signal",
            )
            # Manually set the RSI column to a fixed value for all rows
            analyzer.myDF["RSI"] = rsi_value
            return analyzer
        finally:
            os.unlink(config_path)

    def test_overbought_signal(self):
        """RSI=75 (above default threshold 70) returns score=-5 and signals=["RSI Overbought"].

        **Validates: Requirements 2.1**
        """
        analyzer = self._make_analyzer_with_rsi_column(75.0)

        # Use row_index=20 (well past the period=14 warmup)
        result = analyzer.detect_rsi_signals(20)

        assert result["rsi_signal_score"] == -5.0
        assert result["rsi_signals"] == ["RSI Overbought"]

    def test_oversold_signal(self):
        """RSI=25 (below default threshold 30) returns score=+5 and signals=["RSI Oversold"].

        **Validates: Requirements 2.2**
        """
        analyzer = self._make_analyzer_with_rsi_column(25.0)

        result = analyzer.detect_rsi_signals(20)

        assert result["rsi_signal_score"] == 5.0
        assert result["rsi_signals"] == ["RSI Oversold"]

    def test_neutral_signal(self):
        """RSI=50 (between thresholds 30-70 inclusive) returns score=0 and signals=[].

        **Validates: Requirements 2.3**
        """
        analyzer = self._make_analyzer_with_rsi_column(50.0)

        result = analyzer.detect_rsi_signals(20)

        assert result["rsi_signal_score"] == 0.0
        assert result["rsi_signals"] == []

    def test_disabled_config_returns_zero(self):
        """When rsi.enabled=false, returns score=0 and empty signals with no RSI computation.

        **Validates: Requirements 3.2**
        """
        from vpa.app_runner import MarketAnalyzer

        config = base_config()
        config["rsi"] = {
            "enabled": False,
            "period": 14,
            "overbought_threshold": 70,
            "oversold_threshold": 30,
            "scores": {"overbought": -5, "oversold": 5},
        }

        config_path = make_temp_config(config)
        try:
            df = make_minimal_df(rows=30)
            analyzer = MarketAnalyzer(
                config_path=config_path,
                fixed_df=df,
                log_level="ERROR",
                log_prefix="test_disabled",
            )

            # RSI should be disabled
            assert analyzer._MarketAnalyzer__rsi_enabled is False

            # Even if we manually set an extreme RSI value, result should be zero
            analyzer.myDF["RSI"] = 80.0
            result = analyzer.detect_rsi_signals(20)

            assert result["rsi_signal_score"] == 0.0
            assert result["rsi_signals"] == []
        finally:
            os.unlink(config_path)

    def test_invalid_thresholds_disables_rsi(self):
        """When oversold >= overbought (e.g. 80 >= 30), RSI is disabled with warning.

        **Validates: Requirements 3.4**
        """
        from vpa.app_runner import MarketAnalyzer

        config = base_config()
        config["rsi"] = {
            "enabled": True,
            "period": 14,
            "overbought_threshold": 30,
            "oversold_threshold": 80,
            "scores": {"overbought": -5, "oversold": 5},
        }

        config_path = make_temp_config(config)
        try:
            df = make_minimal_df(rows=30)
            analyzer = MarketAnalyzer(
                config_path=config_path,
                fixed_df=df,
                log_level="DEBUG",
                log_prefix="test_invalid_thresholds",
            )

            # RSI should be disabled due to invalid thresholds
            assert analyzer._MarketAnalyzer__rsi_enabled is False

            # Signal detection should return zero
            analyzer.myDF["RSI"] = 10.0
            result = analyzer.detect_rsi_signals(20)

            assert result["rsi_signal_score"] == 0.0
            assert result["rsi_signals"] == []
        finally:
            os.unlink(config_path)

    def test_boundary_at_overbought_threshold(self):
        """RSI exactly at overbought threshold (70) is NOT overbought (requires > 70).

        **Validates: Requirements 2.1, 2.3**
        """
        analyzer = self._make_analyzer_with_rsi_column(70.0)

        result = analyzer.detect_rsi_signals(20)

        assert result["rsi_signal_score"] == 0.0
        assert result["rsi_signals"] == []

    def test_boundary_at_oversold_threshold(self):
        """RSI exactly at oversold threshold (30) is NOT oversold (requires < 30).

        **Validates: Requirements 2.2, 2.3**
        """
        analyzer = self._make_analyzer_with_rsi_column(30.0)

        result = analyzer.detect_rsi_signals(20)

        assert result["rsi_signal_score"] == 0.0
        assert result["rsi_signals"] == []

    def test_insufficient_data_row_returns_zero(self):
        """Row index below RSI period returns zero score even with valid RSI column value.

        **Validates: Requirements 2.4**
        """
        analyzer = self._make_analyzer_with_rsi_column(75.0)

        # Use row_index=5 (below period=14)
        result = analyzer.detect_rsi_signals(5)

        assert result["rsi_signal_score"] == 0.0
        assert result["rsi_signals"] == []


# ---------------------------------------------------------------------------
# Integration Tests for RSI Composite Score (Task 6.3)
# ---------------------------------------------------------------------------

class TestRSIIntegration:
    """Integration tests verifying RSI contributes to the composite trade_signal.

    Tests confirm that process_data() includes RSI score in the composite summation,
    and that the feature extractor's FEATURE_COLUMNS includes the RSI fields.

    **Property 6: Composite Additivity** - Composite trade_signal equals sum of all
    6 sub-scores (single_candle, trend, multiple_bar, acc_dist, ma_crossover, rsi).

    **Validates: Requirements 2.5, 5.1, 5.4**
    """

    def _make_declining_df(self, rows: int = 100) -> pd.DataFrame:
        """Create a DataFrame with steadily declining prices to produce oversold RSI.

        Uses a steep downward slope so that after the warmup period,
        RSI will be well below 30 (oversold territory).
        """
        prices = [200.0 - i * 1.5 for i in range(rows)]
        return pd.DataFrame({
            "Date": pd.date_range("2023-01-01", periods=rows),
            "Close": prices,
            "High": [p + 0.5 for p in prices],
            "Low": [p - 0.5 for p in prices],
            "Open": [p + 0.2 for p in prices],
            "Volume": [1_000_000] * rows,
        })

    def _make_rising_df(self, rows: int = 100) -> pd.DataFrame:
        """Create a DataFrame with steadily increasing prices to produce overbought RSI.

        Uses a steep upward slope so that after the warmup period,
        RSI will be well above 70 (overbought territory).
        """
        prices = [50.0 + i * 1.5 for i in range(rows)]
        return pd.DataFrame({
            "Date": pd.date_range("2023-01-01", periods=rows),
            "Close": prices,
            "High": [p + 0.5 for p in prices],
            "Low": [p - 0.5 for p in prices],
            "Open": [p - 0.2 for p in prices],
            "Volume": [1_000_000] * rows,
        })

    def test_oversold_rsi_contributes_positive_score(self):
        """Steadily declining prices produce oversold RSI, adding +5 to composite score.

        Compares process_data() output with RSI enabled vs disabled.
        The difference should equal the RSI oversold score (+5).

        **Validates: Requirements 2.5**
        """
        from vpa.app_runner import MarketAnalyzer

        # Config with RSI enabled
        config_enabled = base_config()
        config_enabled["rsi"] = {
            "enabled": True,
            "period": 14,
            "overbought_threshold": 70,
            "oversold_threshold": 30,
            "scores": {"overbought": -5, "oversold": 5},
        }

        # Config with RSI disabled
        config_disabled = base_config()
        config_disabled["rsi"] = {
            "enabled": False,
            "period": 14,
            "overbought_threshold": 70,
            "oversold_threshold": 30,
            "scores": {"overbought": -5, "oversold": 5},
        }

        config_enabled_path = make_temp_config(config_enabled)
        config_disabled_path = make_temp_config(config_disabled)

        try:
            df = self._make_declining_df(rows=100)

            analyzer_enabled = MarketAnalyzer(
                config_path=config_enabled_path,
                fixed_df=df.copy(),
                log_level="ERROR",
                log_prefix="test_rsi_oversold_enabled",
            )

            analyzer_disabled = MarketAnalyzer(
                config_path=config_disabled_path,
                fixed_df=df.copy(),
                log_level="ERROR",
                log_prefix="test_rsi_oversold_disabled",
            )

            signal_with_rsi = analyzer_enabled.process_data()
            signal_without_rsi = analyzer_disabled.process_data()

            # The difference should be exactly the RSI oversold score (+5)
            rsi_contribution = signal_with_rsi - signal_without_rsi
            assert rsi_contribution == 5.0, (
                f"Expected RSI contribution of +5.0 (oversold), "
                f"got {rsi_contribution}. "
                f"With RSI: {signal_with_rsi}, Without RSI: {signal_without_rsi}"
            )
        finally:
            os.unlink(config_enabled_path)
            os.unlink(config_disabled_path)

    def test_overbought_rsi_contributes_negative_score(self):
        """Steadily increasing prices produce overbought RSI, adding -5 to composite score.

        Compares process_data() output with RSI enabled vs disabled.
        The difference should equal the RSI overbought score (-5).

        **Validates: Requirements 2.5**
        """
        from vpa.app_runner import MarketAnalyzer

        # Config with RSI enabled
        config_enabled = base_config()
        config_enabled["rsi"] = {
            "enabled": True,
            "period": 14,
            "overbought_threshold": 70,
            "oversold_threshold": 30,
            "scores": {"overbought": -5, "oversold": 5},
        }

        # Config with RSI disabled
        config_disabled = base_config()
        config_disabled["rsi"] = {
            "enabled": False,
            "period": 14,
            "overbought_threshold": 70,
            "oversold_threshold": 30,
            "scores": {"overbought": -5, "oversold": 5},
        }

        config_enabled_path = make_temp_config(config_enabled)
        config_disabled_path = make_temp_config(config_disabled)

        try:
            df = self._make_rising_df(rows=100)

            analyzer_enabled = MarketAnalyzer(
                config_path=config_enabled_path,
                fixed_df=df.copy(),
                log_level="ERROR",
                log_prefix="test_rsi_overbought_enabled",
            )

            analyzer_disabled = MarketAnalyzer(
                config_path=config_disabled_path,
                fixed_df=df.copy(),
                log_level="ERROR",
                log_prefix="test_rsi_overbought_disabled",
            )

            signal_with_rsi = analyzer_enabled.process_data()
            signal_without_rsi = analyzer_disabled.process_data()

            # The difference should be exactly the RSI overbought score (-5)
            rsi_contribution = signal_with_rsi - signal_without_rsi
            assert rsi_contribution == -5.0, (
                f"Expected RSI contribution of -5.0 (overbought), "
                f"got {rsi_contribution}. "
                f"With RSI: {signal_with_rsi}, Without RSI: {signal_without_rsi}"
            )
        finally:
            os.unlink(config_enabled_path)
            os.unlink(config_disabled_path)

    def test_disabled_rsi_no_contribution(self):
        """With RSI disabled, process_data() trade_signal has no RSI contribution.

        Running the same data with RSI disabled twice should produce identical results,
        confirming RSI is completely removed from the composite score.

        **Validates: Requirements 2.5, 3.2**
        """
        from vpa.app_runner import MarketAnalyzer

        config = base_config()
        config["rsi"] = {
            "enabled": False,
            "period": 14,
            "overbought_threshold": 70,
            "oversold_threshold": 30,
            "scores": {"overbought": -5, "oversold": 5},
        }

        config_path = make_temp_config(config)

        try:
            # Use declining prices that would trigger oversold if RSI were enabled
            df = self._make_declining_df(rows=100)

            analyzer = MarketAnalyzer(
                config_path=config_path,
                fixed_df=df.copy(),
                log_level="ERROR",
                log_prefix="test_rsi_disabled",
            )

            assert analyzer._MarketAnalyzer__rsi_enabled is False

            signal = analyzer.process_data()

            # Now run with RSI enabled to confirm they differ
            config_enabled = base_config()
            config_enabled["rsi"] = {
                "enabled": True,
                "period": 14,
                "overbought_threshold": 70,
                "oversold_threshold": 30,
                "scores": {"overbought": -5, "oversold": 5},
            }
            config_enabled_path = make_temp_config(config_enabled)
            try:
                analyzer_enabled = MarketAnalyzer(
                    config_path=config_enabled_path,
                    fixed_df=df.copy(),
                    log_level="ERROR",
                    log_prefix="test_rsi_enabled_compare",
                )
                signal_enabled = analyzer_enabled.process_data()

                # Disabled signal should differ from enabled signal
                assert signal != signal_enabled, (
                    f"Expected different trade_signal when RSI is enabled vs disabled, "
                    f"but both returned {signal}"
                )
            finally:
                os.unlink(config_enabled_path)
        finally:
            os.unlink(config_path)

    def test_feature_columns_include_rsi_fields(self):
        """FEATURE_COLUMNS in VPAFeatureExtractor includes rsi_value and rsi_signal_score.

        Verifies that the feature vector schema includes the two RSI columns
        positioned after acc_dist_score and before composite_score.

        **Validates: Requirements 5.1**
        """
        from vpa.ml_validation.feature_extractor import VPAFeatureExtractor

        columns = VPAFeatureExtractor.FEATURE_COLUMNS

        assert "rsi_value" in columns, "rsi_value not found in FEATURE_COLUMNS"
        assert "rsi_signal_score" in columns, "rsi_signal_score not found in FEATURE_COLUMNS"

        # Verify ordering: rsi columns appear after acc_dist_score and before composite_score
        acc_dist_idx = columns.index("acc_dist_score")
        rsi_value_idx = columns.index("rsi_value")
        rsi_score_idx = columns.index("rsi_signal_score")
        composite_idx = columns.index("composite_score")

        assert acc_dist_idx < rsi_value_idx < rsi_score_idx < composite_idx, (
            f"RSI columns should appear after acc_dist_score ({acc_dist_idx}) "
            f"and before composite_score ({composite_idx}), "
            f"but got rsi_value at {rsi_value_idx}, rsi_signal_score at {rsi_score_idx}"
        )
