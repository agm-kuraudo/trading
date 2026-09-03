"""Unit tests for the price vs SMA signal (SP-326).

Covers the position-based signal (close above/below the SMA), optional
crossover event detection, config-driven enable/weight, and graceful
degradation on disabled config or insufficient data.

Tests instantiate MarketAnalyzer with a fixed DataFrame, call
compute_price_vs_sma_column() to populate the SMA column, then assert on
the dict returned by detect_price_vs_sma_signals(row_index).
"""

import json
import os
import tempfile

import pandas as pd

from vpa.app_runner import MarketAnalyzer

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def make_temp_config(config_dict: dict) -> str:
    """Write a config dict to a temp JSON file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(config_dict, f)
    return path


def make_df(closes: list[float]) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame from a list of closing prices."""
    n = len(closes)
    return pd.DataFrame(
        {
            "Date": pd.date_range("2024-01-01", periods=n),
            "Close": closes,
            "High": [c + 1 for c in closes],
            "Low": [c - 1 for c in closes],
            "Open": closes,
            "Volume": [1_000_000] * n,
        }
    )


def base_config() -> dict:
    """Return a minimal valid config with no price_vs_sma/rsi/ma sections."""
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


def make_analyzer(config: dict, closes: list[float]) -> MarketAnalyzer:
    """Instantiate a MarketAnalyzer with the given config and closes.

    Computes the price_vs_sma SMA column so detect_price_vs_sma_signals can
    be called directly. The temp config file is cleaned up before returning.
    """
    config_path = make_temp_config(config)
    try:
        analyzer = MarketAnalyzer(
            config_path=config_path,
            fixed_df=make_df(closes),
            log_level="ERROR",
            log_prefix="test_price_vs_sma",
        )
    finally:
        os.unlink(config_path)
    analyzer.compute_price_vs_sma_column()
    return analyzer


# ---------------------------------------------------------------------------
# Position-based signal
# ---------------------------------------------------------------------------


class TestPriceVsSMAPosition:
    """Above/below/equal position logic for the price vs SMA signal."""

    def test_close_above_sma_bullish(self):
        """A close above the SMA contributes a positive (bullish) score."""
        config = base_config()
        config["price_vs_sma"] = {
            "enabled": True,
            "period": 5,
            "scores": {"above": 5, "below": 5},
        }
        # Flat at 100 for 5 bars (SMA=100) then a jump to 110 (close > SMA).
        closes = [100.0, 100.0, 100.0, 100.0, 100.0, 110.0]
        analyzer = make_analyzer(config, closes)

        result = analyzer.detect_price_vs_sma_signals(5)

        assert result["price_vs_sma_signal_score"] == 5
        assert result["price_vs_sma_signals"] == ["Price above SMA"]

    def test_close_below_sma_bearish(self):
        """A close below the SMA contributes a negative (bearish) score."""
        config = base_config()
        config["price_vs_sma"] = {
            "enabled": True,
            "period": 5,
            "scores": {"above": 5, "below": 5},
        }
        # Flat at 100 for 5 bars (SMA=100) then a drop to 90 (close < SMA).
        closes = [100.0, 100.0, 100.0, 100.0, 100.0, 90.0]
        analyzer = make_analyzer(config, closes)

        result = analyzer.detect_price_vs_sma_signals(5)

        assert result["price_vs_sma_signal_score"] == -5
        assert result["price_vs_sma_signals"] == ["Price below SMA"]

    def test_close_equal_sma_no_signal(self):
        """A close exactly equal to the SMA produces no signal and zero score."""
        config = base_config()
        config["price_vs_sma"] = {
            "enabled": True,
            "period": 5,
            "scores": {"above": 5, "below": 5},
        }
        # Perfectly flat: SMA == close everywhere.
        closes = [100.0, 100.0, 100.0, 100.0, 100.0, 100.0]
        analyzer = make_analyzer(config, closes)

        result = analyzer.detect_price_vs_sma_signals(5)

        assert result["price_vs_sma_signal_score"] == 0.0
        assert result["price_vs_sma_signals"] == []

    def test_custom_weights_respected(self):
        """Configured above/below weights are applied to the score."""
        config = base_config()
        config["price_vs_sma"] = {
            "enabled": True,
            "period": 5,
            "scores": {"above": 8, "below": 3},
        }
        closes = [100.0, 100.0, 100.0, 100.0, 100.0, 110.0]
        analyzer = make_analyzer(config, closes)

        result = analyzer.detect_price_vs_sma_signals(5)

        assert result["price_vs_sma_signal_score"] == 8


# ---------------------------------------------------------------------------
# Crossover event detection (optional)
# ---------------------------------------------------------------------------


class TestPriceVsSMACrossover:
    """Optional crossover event detection when detect_crossover is enabled."""

    def test_cross_above_event(self):
        """Price moving from below to above the SMA fires a cross-above event."""
        config = base_config()
        config["price_vs_sma"] = {
            "enabled": True,
            "period": 3,
            "scores": {"above": 5, "below": 5},
            "detect_crossover": True,
            "crossover_scores": {"cross_above": 3, "cross_below": 3},
        }
        # Falling then a sharp reversal so the last close crosses above its SMA.
        closes = [110.0, 100.0, 90.0, 80.0, 130.0]
        analyzer = make_analyzer(config, closes)

        # Confirm the previous row was below and the last row is above.
        df = analyzer.get_dataframe()
        assert df.iloc[3]["Close"] < df.iloc[3]["SMA_price_vs"]
        assert df.iloc[4]["Close"] > df.iloc[4]["SMA_price_vs"]

        result = analyzer.detect_price_vs_sma_signals(4)

        # Position (+5 above) plus crossover (+3 cross_above)
        assert "Price above SMA" in result["price_vs_sma_signals"]
        assert "Price crossed above SMA" in result["price_vs_sma_signals"]
        assert result["price_vs_sma_signal_score"] == 8

    def test_cross_below_event(self):
        """Price moving from above to below the SMA fires a cross-below event."""
        config = base_config()
        config["price_vs_sma"] = {
            "enabled": True,
            "period": 3,
            "scores": {"above": 5, "below": 5},
            "detect_crossover": True,
            "crossover_scores": {"cross_above": 3, "cross_below": 3},
        }
        # Rising then a sharp reversal so the last close crosses below its SMA.
        closes = [90.0, 100.0, 110.0, 120.0, 70.0]
        analyzer = make_analyzer(config, closes)

        df = analyzer.get_dataframe()
        assert df.iloc[3]["Close"] > df.iloc[3]["SMA_price_vs"]
        assert df.iloc[4]["Close"] < df.iloc[4]["SMA_price_vs"]

        result = analyzer.detect_price_vs_sma_signals(4)

        assert "Price below SMA" in result["price_vs_sma_signals"]
        assert "Price crossed below SMA" in result["price_vs_sma_signals"]
        assert result["price_vs_sma_signal_score"] == -8

    def test_crossover_disabled_by_default(self):
        """With detect_crossover off, only the position signal is produced."""
        config = base_config()
        config["price_vs_sma"] = {
            "enabled": True,
            "period": 3,
            "scores": {"above": 5, "below": 5},
            "detect_crossover": False,
        }
        closes = [110.0, 100.0, 90.0, 80.0, 130.0]
        analyzer = make_analyzer(config, closes)

        result = analyzer.detect_price_vs_sma_signals(4)

        assert result["price_vs_sma_signals"] == ["Price above SMA"]
        assert result["price_vs_sma_signal_score"] == 5


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


class TestPriceVsSMADegradation:
    """Disabled config, missing column, and insufficient-data handling."""

    def test_disabled_returns_zero(self):
        """When disabled, the detector returns an empty list and zero score."""
        config = base_config()
        config["price_vs_sma"] = {"enabled": False, "period": 5}
        closes = [100.0, 100.0, 100.0, 100.0, 100.0, 110.0]
        analyzer = make_analyzer(config, closes)

        result = analyzer.detect_price_vs_sma_signals(5)

        assert result["price_vs_sma_signal_score"] == 0.0
        assert result["price_vs_sma_signals"] == []

    def test_insufficient_data_returns_zero(self):
        """Rows before the SMA warmup period yield NaN SMA and zero score."""
        config = base_config()
        config["price_vs_sma"] = {
            "enabled": True,
            "period": 5,
            "scores": {"above": 5, "below": 5},
        }
        closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
        analyzer = make_analyzer(config, closes)

        # Row 2 is within the 5-bar warmup, so SMA is NaN.
        assert pd.isna(analyzer.get_dataframe().iloc[2]["SMA_price_vs"])

        result = analyzer.detect_price_vs_sma_signals(2)

        assert result["price_vs_sma_signal_score"] == 0.0
        assert result["price_vs_sma_signals"] == []

    def test_missing_column_returns_zero(self):
        """If the SMA column was never computed, the detector degrades safely."""
        config = base_config()
        config["price_vs_sma"] = {
            "enabled": True,
            "period": 5,
            "scores": {"above": 5, "below": 5},
        }
        # Build analyzer WITHOUT calling compute_price_vs_sma_column().
        config_path = make_temp_config(config)
        try:
            analyzer = MarketAnalyzer(
                config_path=config_path,
                fixed_df=make_df([100.0] * 5 + [110.0]),
                log_level="ERROR",
                log_prefix="test_price_vs_sma",
            )
        finally:
            os.unlink(config_path)

        assert "SMA_price_vs" not in analyzer.get_dataframe().columns

        result = analyzer.detect_price_vs_sma_signals(5)

        assert result["price_vs_sma_signal_score"] == 0.0
        assert result["price_vs_sma_signals"] == []

    def test_invalid_period_disables_signal(self):
        """A non-positive period disables the signal via config validation."""
        config = base_config()
        config["price_vs_sma"] = {
            "enabled": True,
            "period": 0,
            "scores": {"above": 5, "below": 5},
        }
        closes = [100.0, 100.0, 100.0, 100.0, 100.0, 110.0]
        analyzer = make_analyzer(config, closes)

        # Disabled config means no SMA column is computed and no signal fires.
        assert "SMA_price_vs" not in analyzer.get_dataframe().columns

        result = analyzer.detect_price_vs_sma_signals(5)

        assert result["price_vs_sma_signal_score"] == 0.0
        assert result["price_vs_sma_signals"] == []


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------


class TestPriceVsSMAConfigDefaults:
    """Behaviour when the price_vs_sma section is absent from config."""

    def test_defaults_enable_signal_with_period_10(self):
        """No price_vs_sma section uses defaults (enabled, period 10)."""
        config = base_config()  # deliberately omit price_vs_sma
        assert "price_vs_sma" not in config

        # 10 flat bars (SMA=100) then a jump above.
        closes = [100.0] * 10 + [120.0]
        analyzer = make_analyzer(config, closes)

        assert "SMA_price_vs" in analyzer.get_dataframe().columns

        result = analyzer.detect_price_vs_sma_signals(10)

        assert result["price_vs_sma_signals"] == ["Price above SMA"]
        assert result["price_vs_sma_signal_score"] == 5
