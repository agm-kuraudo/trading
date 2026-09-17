"""Tests for DSS Bressert MarketAnalyzer integration."""

import json
import os
import tempfile

import numpy as np
import pandas as pd

from vpa.app_runner import MarketAnalyzer


def _base_config() -> dict:
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


def _make_analyzer(dss_config: dict) -> MarketAnalyzer:
    config = _base_config()
    config["dss_bressert"] = dss_config
    prices = [100.0 + i * 0.1 for i in range(40)]
    frame = pd.DataFrame(
        {
            "Date": pd.date_range("2024-01-01", periods=len(prices)),
            "Open": prices,
            "High": [price + 1 for price in prices],
            "Low": [price - 1 for price in prices],
            "Close": prices,
            "Volume": [1_000_000] * len(prices),
        }
    )
    fd, path = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(config, handle)
        return MarketAnalyzer(config_path=path, fixed_df=frame, log_level="ERROR", log_prefix="test_dss")
    finally:
        os.unlink(path)


def _enabled_config() -> dict:
    return {
        "enabled": True,
        "stochastic_period": 10,
        "smoothing_period": 9,
        "trigger_period": 5,
        "overbought_threshold": 80,
        "oversold_threshold": 20,
        "scores": {
            "bullish_crossover": 3,
            "bearish_crossover": 4,
            "oversold": 2,
            "overbought": -2,
        },
    }


def test_bullish_crossover_and_oversold_scores_are_combined():
    analyzer = _make_analyzer(_enabled_config())
    analyzer.myDF["DSS"] = [50.0] * 40
    analyzer.myDF["DSS_Trigger"] = [50.0] * 40
    analyzer.myDF.loc[29, "DSS"] = 10.0
    analyzer.myDF.loc[29, "DSS_Trigger"] = 20.0
    analyzer.myDF.loc[30, "DSS"] = 15.0
    analyzer.myDF.loc[30, "DSS_Trigger"] = 12.0

    result = analyzer.detect_dss_bressert_signals(30)

    assert result["dss_bressert_signals"] == ["DSS Bullish Crossover", "DSS Oversold"]
    assert result["dss_bressert_signal_score"] == 5


def test_bearish_crossover_and_overbought_scores_are_combined():
    analyzer = _make_analyzer(_enabled_config())
    analyzer.myDF["DSS"] = [50.0] * 40
    analyzer.myDF["DSS_Trigger"] = [50.0] * 40
    analyzer.myDF.loc[29, "DSS"] = 85.0
    analyzer.myDF.loc[29, "DSS_Trigger"] = 80.0
    analyzer.myDF.loc[30, "DSS"] = 90.0
    analyzer.myDF.loc[30, "DSS_Trigger"] = 95.0

    result = analyzer.detect_dss_bressert_signals(30)

    assert result["dss_bressert_signals"] == ["DSS Bearish Crossover", "DSS Overbought"]
    assert result["dss_bressert_signal_score"] == -6


def test_nan_values_degrade_to_empty_zero_result():
    analyzer = _make_analyzer(_enabled_config())
    analyzer.myDF["DSS"] = [50.0] * 40
    analyzer.myDF["DSS_Trigger"] = [50.0] * 40
    analyzer.myDF.loc[30, "DSS"] = np.nan

    assert analyzer.detect_dss_bressert_signals(30) == {
        "dss_bressert_signals": [],
        "dss_bressert_signal_score": 0.0,
    }


def test_disabled_config_degrades_to_empty_zero_result():
    config = _enabled_config()
    config["enabled"] = False
    analyzer = _make_analyzer(config)

    assert analyzer.detect_dss_bressert_signals(30) == {
        "dss_bressert_signals": [],
        "dss_bressert_signal_score": 0.0,
    }


def test_invalid_period_disables_dss_signal():
    config = _enabled_config()
    config["stochastic_period"] = 0
    analyzer = _make_analyzer(config)

    assert analyzer.detect_dss_bressert_signals(30)["dss_bressert_signal_score"] == 0.0


def test_invalid_thresholds_disable_dss_signal():
    config = _enabled_config()
    config["oversold_threshold"] = 80
    config["overbought_threshold"] = 80
    analyzer = _make_analyzer(config)

    assert analyzer.detect_dss_bressert_signals(30)["dss_bressert_signal_score"] == 0.0
