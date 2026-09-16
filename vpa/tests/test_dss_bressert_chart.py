"""Smoke tests for MarketAnalyzer.graph_dss_bressert (SP-325).

Covers Req 10.5 (a PNG is produced under log/ when the signal is enabled and
the DSS/DSS_Trigger columns are present) and Req 10.6 (a price-only chart is
produced without error when the signal is disabled or the columns are absent).

Tests are hermetic: a fixed_df is passed so no network/yfinance access occurs,
and the working directory is switched to a tmp_path so the relative ``log/``
output lands somewhere cleanup-safe. A non-interactive matplotlib backend is
used so no window pops up (show_chart is left False regardless).
"""

import json
import os
import tempfile

import matplotlib
import pandas as pd

matplotlib.use("Agg")

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


def make_rising_df(rows: int = 60) -> pd.DataFrame:
    """Build a rising OHLCV DataFrame long enough to exceed the DSS warmup.

    The default DSS warmup is stochastic_period + smoothing_period +
    trigger_period - 2 = 10 + 9 + 5 - 2 = 22 rows, so 60 rows is comfortably
    beyond it.
    """
    prices = [100.0 + i * 0.5 for i in range(rows)]
    return pd.DataFrame(
        {
            "Date": pd.date_range("2024-01-01", periods=rows),
            "Close": prices,
            "High": [p + 1 for p in prices],
            "Low": [p - 1 for p in prices],
            "Open": prices,
            "Volume": [1_000_000] * rows,
        }
    )


def base_config() -> dict:
    """Return a minimal valid config with no feature sections."""
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


def make_analyzer(config: dict, df: pd.DataFrame) -> MarketAnalyzer:
    """Instantiate a MarketAnalyzer with the given config and fixed DataFrame."""
    config_path = make_temp_config(config)
    try:
        analyzer = MarketAnalyzer(
            config_path=config_path,
            ticker_symbol="SPY",
            fixed_df=df,
            log_level="ERROR",
            log_prefix="test_dss_chart",
        )
    finally:
        os.unlink(config_path)
    return analyzer


# ---------------------------------------------------------------------------
# Smoke tests
# ---------------------------------------------------------------------------


def test_enabled_produces_png(tmp_path, monkeypatch):
    """Enabled DSS with DSS/DSS_Trigger columns present -> PNG under log/ (Req 10.5)."""
    monkeypatch.chdir(tmp_path)

    config = base_config()
    config["dss_bressert"] = {
        "enabled": True,
        "stochastic_period": 10,
        "smoothing_period": 9,
        "trigger_period": 5,
        "overbought_threshold": 80,
        "oversold_threshold": 20,
        "scores": {
            "bullish_crossover": 0,
            "bearish_crossover": 0,
            "oversold": 0,
            "overbought": 0,
        },
    }

    analyzer = make_analyzer(config, make_rising_df(60))
    # process_data populates the DSS / DSS_Trigger columns via
    # compute_dss_bressert_columns().
    analyzer.process_data()

    df = analyzer.get_dataframe()
    assert "DSS" in df.columns and "DSS_Trigger" in df.columns

    # Should not raise.
    analyzer.graph_dss_bressert()

    expected_png = tmp_path / "log" / "SPY_dss_bressert.png"
    assert expected_png.exists()


def test_disabled_produces_price_only_png(tmp_path, monkeypatch):
    """Disabled DSS -> price-only chart written without error (Req 10.6)."""
    monkeypatch.chdir(tmp_path)

    config = base_config()
    config["dss_bressert"] = {"enabled": False}

    analyzer = make_analyzer(config, make_rising_df(60))
    analyzer.process_data()

    # Disabled -> columns are not computed.
    assert "DSS" not in analyzer.get_dataframe().columns

    # Should not raise and should still write a price-only PNG.
    analyzer.graph_dss_bressert()

    expected_png = tmp_path / "log" / "SPY_dss_bressert.png"
    assert expected_png.exists()


def test_missing_columns_produce_price_only_png(tmp_path, monkeypatch):
    """Enabled DSS but columns absent (process_data not run) -> price-only chart (Req 10.6)."""
    monkeypatch.chdir(tmp_path)

    config = base_config()
    config["dss_bressert"] = {
        "enabled": True,
        "stochastic_period": 10,
        "smoothing_period": 9,
        "trigger_period": 5,
        "overbought_threshold": 80,
        "oversold_threshold": 20,
        "scores": {
            "bullish_crossover": 0,
            "bearish_crossover": 0,
            "oversold": 0,
            "overbought": 0,
        },
    }

    # Build the analyzer but do NOT call process_data / compute, so the DSS
    # columns never get added.
    analyzer = make_analyzer(config, make_rising_df(60))
    assert "DSS" not in analyzer.get_dataframe().columns

    # Should not raise despite the guard falling back to a price-only chart.
    analyzer.graph_dss_bressert()

    expected_png = tmp_path / "log" / "SPY_dss_bressert.png"
    assert expected_png.exists()
