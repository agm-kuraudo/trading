"""Unit and property-based tests for data window coordination in MarketAnalyzer.

Tests cover: _get_data_days() logic when both features enabled, only one enabled,
both disabled, and insufficient data disabling a feature for a ticker.

Property tests validate correctness Property 10 from the design document.

Requirements: 7.1, 7.2, 7.3, 7.4
"""

import json
import os
import tempfile

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def make_temp_config(config_dict: dict) -> str:
    """Write a config dict to a temp JSON file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(config_dict, f)
    return path


def make_large_df(rows: int = 400) -> pd.DataFrame:
    """Create a DataFrame large enough for both MA and drawdown features."""
    prices = [100.0 + i * 0.1 for i in range(rows)]
    return pd.DataFrame({
        "Date": pd.date_range("2022-01-01", periods=rows),
        "Close": prices,
        "High": [p + 1 for p in prices],
        "Low": [p - 1 for p in prices],
        "Open": prices,
        "Volume": [1_000_000] * rows,
    })


def base_config() -> dict:
    """Return a minimal valid config without feature sections."""
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
# Tests: Data Window Coordination
# ---------------------------------------------------------------------------


class TestDataWindowCoordination:
    """Tests for _get_data_days() returning the correct max across enabled features.

    Validates: Requirements 7.1, 7.2, 7.3, 7.4
    """

    def test_both_enabled_drawdown_larger(self):
        """MA data_days=300, drawdown data_days=365 => returns 365.

        Validates: Requirement 7.1
        """
        from vpa.app_runner import MarketAnalyzer

        config = base_config()
        config["ma_crossover"] = {
            "enabled": True,
            "ma_periods": {"short": 10, "medium": 50, "long": 200},
            "ma_data_days": 300,
            "crossover_scores": {"short_medium": 5, "short_long": 8, "medium_long": 10},
            "position_scores": {"above_all": 5, "below_all": 5, "above_two": 2, "below_two": 2},
        }
        config["drawdown_filter"] = {
            "enabled": True,
            "drawdown_threshold": 20,
            "momentum_period": 20,
            "data_days": 365,
        }

        config_path = make_temp_config(config)
        try:
            analyzer = MarketAnalyzer(
                config_path=config_path,
                fixed_df=make_large_df(rows=400),
                log_level="ERROR",
                log_prefix="test_both_drawdown_larger",
            )
            assert analyzer._get_data_days() == 365
        finally:
            os.unlink(config_path)

    def test_both_enabled_ma_larger(self):
        """MA data_days=500, drawdown data_days=365 => returns 500.

        Validates: Requirement 7.1
        """
        from vpa.app_runner import MarketAnalyzer

        config = base_config()
        config["ma_crossover"] = {
            "enabled": True,
            "ma_periods": {"short": 10, "medium": 50, "long": 200},
            "ma_data_days": 500,
            "crossover_scores": {"short_medium": 5, "short_long": 8, "medium_long": 10},
            "position_scores": {"above_all": 5, "below_all": 5, "above_two": 2, "below_two": 2},
        }
        config["drawdown_filter"] = {
            "enabled": True,
            "drawdown_threshold": 20,
            "momentum_period": 20,
            "data_days": 365,
        }

        config_path = make_temp_config(config)
        try:
            analyzer = MarketAnalyzer(
                config_path=config_path,
                fixed_df=make_large_df(rows=400),
                log_level="ERROR",
                log_prefix="test_both_ma_larger",
            )
            assert analyzer._get_data_days() == 500
        finally:
            os.unlink(config_path)

    def test_only_drawdown_enabled(self):
        """MA disabled, drawdown data_days=365 => returns 365.

        Validates: Requirement 7.2
        """
        from vpa.app_runner import MarketAnalyzer

        config = base_config()
        config["ma_crossover"] = {
            "enabled": False,
            "ma_periods": {"short": 10, "medium": 50, "long": 200},
            "ma_data_days": 300,
            "crossover_scores": {"short_medium": 5, "short_long": 8, "medium_long": 10},
            "position_scores": {"above_all": 5, "below_all": 5, "above_two": 2, "below_two": 2},
        }
        config["drawdown_filter"] = {
            "enabled": True,
            "drawdown_threshold": 20,
            "momentum_period": 20,
            "data_days": 365,
        }

        config_path = make_temp_config(config)
        try:
            analyzer = MarketAnalyzer(
                config_path=config_path,
                fixed_df=make_large_df(rows=400),
                log_level="ERROR",
                log_prefix="test_only_drawdown",
            )
            assert analyzer._get_data_days() == 365
        finally:
            os.unlink(config_path)

    def test_only_ma_enabled(self):
        """Drawdown disabled, MA data_days=300 => returns 300.

        Validates: Requirement 7.3
        """
        from vpa.app_runner import MarketAnalyzer

        config = base_config()
        config["ma_crossover"] = {
            "enabled": True,
            "ma_periods": {"short": 10, "medium": 50, "long": 200},
            "ma_data_days": 300,
            "crossover_scores": {"short_medium": 5, "short_long": 8, "medium_long": 10},
            "position_scores": {"above_all": 5, "below_all": 5, "above_two": 2, "below_two": 2},
        }
        config["drawdown_filter"] = {
            "enabled": False,
            "drawdown_threshold": 20,
            "momentum_period": 20,
            "data_days": 365,
        }

        config_path = make_temp_config(config)
        try:
            analyzer = MarketAnalyzer(
                config_path=config_path,
                fixed_df=make_large_df(rows=400),
                log_level="ERROR",
                log_prefix="test_only_ma",
            )
            assert analyzer._get_data_days() == 300
        finally:
            os.unlink(config_path)

    def test_both_disabled_returns_100(self):
        """Both features disabled => falls back to base default of 100.

        Validates: Requirements 7.1, 7.2, 7.3 (implied fallback)
        """
        from vpa.app_runner import MarketAnalyzer

        config = base_config()
        config["ma_crossover"] = {
            "enabled": False,
            "ma_periods": {"short": 10, "medium": 50, "long": 200},
            "ma_data_days": 300,
            "crossover_scores": {"short_medium": 5, "short_long": 8, "medium_long": 10},
            "position_scores": {"above_all": 5, "below_all": 5, "above_two": 2, "below_two": 2},
        }
        config["drawdown_filter"] = {
            "enabled": False,
            "drawdown_threshold": 20,
            "momentum_period": 20,
            "data_days": 365,
        }

        config_path = make_temp_config(config)
        try:
            analyzer = MarketAnalyzer(
                config_path=config_path,
                fixed_df=make_large_df(rows=400),
                log_level="ERROR",
                log_prefix="test_both_disabled",
            )
            assert analyzer._get_data_days() == 100
        finally:
            os.unlink(config_path)

    def test_insufficient_data_disables_ma_for_ticker(self):
        """When DataFrame has fewer rows than MA long period, MA is disabled for that ticker.

        With a small fixed_df (150 rows) and MA long period=200, the MarketAnalyzer
        should disable MA. This means _get_data_days() no longer includes MA's value
        and uses drawdown's data_days instead.

        Validates: Requirement 7.4
        """
        from vpa.app_runner import MarketAnalyzer

        config = base_config()
        config["ma_crossover"] = {
            "enabled": True,
            "ma_periods": {"short": 10, "medium": 50, "long": 200},
            "ma_data_days": 500,
            "crossover_scores": {"short_medium": 5, "short_long": 8, "medium_long": 10},
            "position_scores": {"above_all": 5, "below_all": 5, "above_two": 2, "below_two": 2},
        }
        config["drawdown_filter"] = {
            "enabled": True,
            "drawdown_threshold": 20,
            "momentum_period": 20,
            "data_days": 365,
        }

        config_path = make_temp_config(config)
        try:
            # Only 150 rows — below MA long period of 200
            small_df = make_large_df(rows=150)
            analyzer = MarketAnalyzer(
                config_path=config_path,
                fixed_df=small_df,
                log_level="DEBUG",
                log_prefix="test_insufficient_data",
            )

            # MA should have been disabled due to insufficient data
            assert analyzer._MarketAnalyzer__ma_enabled is False

            # _get_data_days() should now only consider drawdown (365), not MA (500)
            assert analyzer._get_data_days() == 365
        finally:
            os.unlink(config_path)

    def test_no_drawdown_section_uses_defaults(self):
        """When drawdown_filter section is absent, defaults are applied (enabled=True, data_days=400).

        Validates: Requirements 7.1, 7.2
        """
        from vpa.app_runner import MarketAnalyzer

        config = base_config()
        config["ma_crossover"] = {
            "enabled": True,
            "ma_periods": {"short": 10, "medium": 50, "long": 200},
            "ma_data_days": 300,
            "crossover_scores": {"short_medium": 5, "short_long": 8, "medium_long": 10},
            "position_scores": {"above_all": 5, "below_all": 5, "above_two": 2, "below_two": 2},
        }
        # No drawdown_filter section at all

        config_path = make_temp_config(config)
        try:
            analyzer = MarketAnalyzer(
                config_path=config_path,
                fixed_df=make_large_df(rows=400),
                log_level="ERROR",
                log_prefix="test_no_drawdown_section",
            )

            # Drawdown should be enabled by default
            assert analyzer._MarketAnalyzer__drawdown_enabled is True
            # data_days default is 400, which is > MA's 300
            assert analyzer._get_data_days() == 400
        finally:
            os.unlink(config_path)

    def test_equal_data_days_returns_that_value(self):
        """When both features have the same data_days, returns that value.

        Validates: Requirement 7.1
        """
        from vpa.app_runner import MarketAnalyzer

        config = base_config()
        config["ma_crossover"] = {
            "enabled": True,
            "ma_periods": {"short": 10, "medium": 50, "long": 200},
            "ma_data_days": 365,
            "crossover_scores": {"short_medium": 5, "short_long": 8, "medium_long": 10},
            "position_scores": {"above_all": 5, "below_all": 5, "above_two": 2, "below_two": 2},
        }
        config["drawdown_filter"] = {
            "enabled": True,
            "drawdown_threshold": 20,
            "momentum_period": 20,
            "data_days": 365,
        }

        config_path = make_temp_config(config)
        try:
            analyzer = MarketAnalyzer(
                config_path=config_path,
                fixed_df=make_large_df(rows=400),
                log_level="ERROR",
                log_prefix="test_equal_days",
            )
            assert analyzer._get_data_days() == 365
        finally:
            os.unlink(config_path)


# ---------------------------------------------------------------------------
# Property-Based Tests: Data Window Coordination
# ---------------------------------------------------------------------------


class TestDataWindowProperty:
    """Property-based test for data window coordination.

    Feature: momentum-drawdown-filter, Property 10: Data window coordination returns max

    Validates: Requirements 7.1
    """

    @given(
        ma_days=st.integers(min_value=201, max_value=600),  # Must be > long period (200)
        drawdown_days=st.integers(min_value=200, max_value=600),
    )
    @settings(max_examples=100, deadline=None)
    def test_property_data_window_returns_max_of_both(self, ma_days, drawdown_days):
        """For any pair of (ma_data_days, drawdown_data_days) with both enabled,
        _get_data_days() returns max(ma_data_days, drawdown_data_days).

        **Validates: Requirements 7.1**
        """
        from vpa.app_runner import MarketAnalyzer

        config = base_config()
        config["ma_crossover"] = {
            "enabled": True,
            "ma_periods": {"short": 10, "medium": 50, "long": 200},
            "ma_data_days": ma_days,
            "crossover_scores": {"short_medium": 5, "short_long": 8, "medium_long": 10},
            "position_scores": {"above_all": 5, "below_all": 5, "above_two": 2, "below_two": 2},
        }
        config["drawdown_filter"] = {
            "enabled": True,
            "drawdown_threshold": 20,
            "momentum_period": 20,
            "data_days": drawdown_days,
        }

        config_path = make_temp_config(config)
        try:
            analyzer = MarketAnalyzer(
                config_path=config_path,
                fixed_df=make_large_df(rows=400),
                log_level="ERROR",
                log_prefix="prop_test_max",
            )
            result = analyzer._get_data_days()
            expected = max(ma_days, drawdown_days)
            assert result == expected, (
                f"_get_data_days() returned {result}, expected max({ma_days}, {drawdown_days}) = {expected}"
            )
        finally:
            os.unlink(config_path)
