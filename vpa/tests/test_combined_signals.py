"""Unit tests for the Combined_Signal (confluence) detector on MarketAnalyzer.

These map the ten Requirement 6 acceptance criteria of the
combined-signals-confluence spec. Each test builds a MarketAnalyzer with a
tailored ``combined_signals`` config block (injected through the same temp-file
fixture style the DSS Bressert tests use) and calls
``detect_combined_signals(row_index, dss_signals, price_vs_sma_signals)``
directly with crafted constituent signal-name lists.
"""

import json
import os
import tempfile

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


# The configured combined score each firing combination contributes. Mirrors the
# committed config.json starter block (bullish positive, bearish negative).
BULL_SCORE = 10
BEAR_SCORE = -10


def _combined_config() -> dict:
    """The five starter combinations (Bull + Bear mirrors) used by the tests."""
    return {
        "enabled": True,
        "combinations": [
            {
                "name": "DSS_Cross_Plus_SMA_Position_Bull",
                "score": BULL_SCORE,
                "conditions": [
                    {"signal_name": "DSS Bullish Crossover", "kind": "presence"},
                    {"signal_name": "Price above SMA", "kind": "presence"},
                ],
            },
            {
                "name": "DSS_Cross_Plus_SMA_Position_Bear",
                "score": BEAR_SCORE,
                "conditions": [
                    {"signal_name": "DSS Bearish Crossover", "kind": "presence"},
                    {"signal_name": "Price below SMA", "kind": "presence"},
                ],
            },
            {
                "name": "DSS_Zone_Plus_SMA_Cross_Bull",
                "score": BULL_SCORE,
                "conditions": [
                    {"signal_name": "DSS Oversold", "kind": "presence"},
                    {"signal_name": "Price crossed above SMA", "kind": "presence"},
                ],
            },
            {
                "name": "DSS_Cross_From_Zone_Bull",
                "score": BULL_SCORE,
                "conditions": [
                    {"signal_name": "DSS Bullish Crossover", "kind": "presence"},
                    {"signal_name": "DSS Oversold", "kind": "presence"},
                ],
            },
            {
                "name": "DSS_Cross_SMA_Not_Overbought_Bull",
                "score": BULL_SCORE,
                "conditions": [
                    {"signal_name": "DSS Bullish Crossover", "kind": "presence"},
                    {"signal_name": "Price above SMA", "kind": "presence"},
                    {"signal_name": "DSS Overbought", "kind": "absence"},
                ],
            },
        ],
    }


def _position_only_config() -> dict:
    """Only the two-condition DSS_Cross_Plus_SMA_Position_Bull combination.

    Isolating a single combination lets a test assert the exact fired list and
    the exact configured score without other starter combinations also firing on
    the same crafted input.
    """
    return {
        "enabled": True,
        "combinations": [
            {
                "name": "DSS_Cross_Plus_SMA_Position_Bull",
                "score": BULL_SCORE,
                "conditions": [
                    {"signal_name": "DSS Bullish Crossover", "kind": "presence"},
                    {"signal_name": "Price above SMA", "kind": "presence"},
                ],
            },
        ],
    }


def _negation_only_config() -> dict:
    """Only the three-way DSS_Cross_SMA_Not_Overbought_Bull combination."""
    return {
        "enabled": True,
        "combinations": [
            {
                "name": "DSS_Cross_SMA_Not_Overbought_Bull",
                "score": BULL_SCORE,
                "conditions": [
                    {"signal_name": "DSS Bullish Crossover", "kind": "presence"},
                    {"signal_name": "Price above SMA", "kind": "presence"},
                    {"signal_name": "DSS Overbought", "kind": "absence"},
                ],
            },
        ],
    }


def _make_analyzer(combined_config: dict) -> MarketAnalyzer:
    config = _base_config()
    config["combined_signals"] = combined_config
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
        return MarketAnalyzer(
            config_path=path,
            fixed_df=frame,
            log_level="ERROR",
            log_prefix="test_combined",
        )
    finally:
        os.unlink(path)


# Req 6.1 - both constituents of DSS_Cross_Plus_SMA_Position fire.
def test_both_constituents_fire_combination_and_non_zero_score():
    analyzer = _make_analyzer(_combined_config())

    result = analyzer.detect_combined_signals(
        30,
        dss_signals=["DSS Bullish Crossover"],
        price_vs_sma_signals=["Price above SMA"],
    )

    assert "DSS_Cross_Plus_SMA_Position_Bull" in result["combined_signals"]
    assert result["combined_signal_score"] != 0.0


# Req 6.2 - exactly one constituent holds -> does not fire.
def test_exactly_one_constituent_does_not_fire():
    analyzer = _make_analyzer(_combined_config())

    result = analyzer.detect_combined_signals(
        30,
        dss_signals=["DSS Bullish Crossover"],
        price_vs_sma_signals=[],
    )

    assert "DSS_Cross_Plus_SMA_Position_Bull" not in result["combined_signals"]
    assert result["combined_signal_score"] == 0.0


# Req 6.3 - neither constituent holds -> does not fire.
def test_neither_constituent_does_not_fire():
    analyzer = _make_analyzer(_combined_config())

    result = analyzer.detect_combined_signals(
        30,
        dss_signals=[],
        price_vs_sma_signals=[],
    )

    assert "DSS_Cross_Plus_SMA_Position_Bull" not in result["combined_signals"]
    assert result["combined_signal_score"] == 0.0


# Req 6.4 - a constituent disabled (empty DSS list) while the other holds.
def test_disabled_constituent_blocks_fire():
    analyzer = _make_analyzer(_combined_config())

    result = analyzer.detect_combined_signals(
        30,
        dss_signals=[],
        price_vs_sma_signals=["Price above SMA"],
    )

    assert "DSS_Cross_Plus_SMA_Position_Bull" not in result["combined_signals"]
    assert result["combined_signal_score"] == 0.0


# Req 6.5 - category off -> empty list + 0.0 even when a confluence would hold.
def test_category_disabled_yields_empty_zero():
    config = _combined_config()
    config["enabled"] = False
    analyzer = _make_analyzer(config)

    result = analyzer.detect_combined_signals(
        30,
        dss_signals=["DSS Bullish Crossover"],
        price_vs_sma_signals=["Price above SMA"],
    )

    assert result["combined_signals"] == []
    assert result["combined_signal_score"] == 0.0


# Req 6.6 - category on, confluence holds -> exact configured combined score.
# Isolated to the single position combination so the configured score is the
# only contribution.
def test_enabled_confluence_produces_configured_score():
    analyzer = _make_analyzer(_position_only_config())

    result = analyzer.detect_combined_signals(
        30,
        dss_signals=["DSS Bullish Crossover"],
        price_vs_sma_signals=["Price above SMA"],
    )

    assert result["combined_signals"] == ["DSS_Cross_Plus_SMA_Position_Bull"]
    assert result["combined_signal_score"] == BULL_SCORE


# Req 6.7 - negation blocked by presence of the negated string. Isolated to the
# single three-way combination so the presence of "DSS Overbought" fully
# suppresses any firing and the sub-score is 0.0.
def test_negation_blocked_by_presence():
    analyzer = _make_analyzer(_negation_only_config())

    result = analyzer.detect_combined_signals(
        30,
        dss_signals=["DSS Bullish Crossover", "DSS Overbought"],
        price_vs_sma_signals=["Price above SMA"],
    )

    assert "DSS_Cross_SMA_Not_Overbought_Bull" not in result["combined_signals"]
    assert result["combined_signal_score"] == 0.0


# Req 6.8 - negation satisfied by absence of the negated string.
def test_negation_satisfied_by_absence():
    analyzer = _make_analyzer(_combined_config())

    result = analyzer.detect_combined_signals(
        30,
        dss_signals=["DSS Bullish Crossover"],
        price_vs_sma_signals=["Price above SMA"],
    )

    assert "DSS_Cross_SMA_Not_Overbought_Bull" in result["combined_signals"]
    assert result["combined_signal_score"] != 0.0


# Req 6.9 - three-way confluence (two presence + one absence) all hold.
def test_three_way_confluence_fires():
    analyzer = _make_analyzer(_combined_config())

    result = analyzer.detect_combined_signals(
        30,
        dss_signals=["DSS Bullish Crossover"],
        price_vs_sma_signals=["Price above SMA"],
    )

    # Both the two-condition position combo and the three-way negation combo hold.
    assert "DSS_Cross_SMA_Not_Overbought_Bull" in result["combined_signals"]
    assert "DSS_Cross_Plus_SMA_Position_Bull" in result["combined_signals"]
    assert result["combined_signal_score"] != 0.0


# Req 6.10 - DSS-only self-confluence (both constituents from the DSS list).
def test_dss_only_self_confluence_fires():
    analyzer = _make_analyzer(_combined_config())

    result = analyzer.detect_combined_signals(
        30,
        dss_signals=["DSS Bullish Crossover", "DSS Oversold"],
        price_vs_sma_signals=[],
    )

    assert "DSS_Cross_From_Zone_Bull" in result["combined_signals"]
    assert result["combined_signal_score"] != 0.0
