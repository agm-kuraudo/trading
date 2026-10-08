import sys
from pathlib import Path

import pandas as pd
import pytest

from vpa.ml_validation.daily_signal import SignalType, build_signal_records

# scripts/ is not a package; add it to the path so the importer can be tested.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from import_ticker_signals import build_ticker_config, get_rule, select_row  # noqa: E402


@pytest.fixture
def mock_ticker_config():
    return {
        "AAPL": {
            "distribution": {
                "confidence_level": "Low",
                "adjusted_direction": "SELL",
                "suggested_hold_days": 5,
            },
            "strong_bearish": {"adjusted_direction": "NONE"},
        }
    }


def test_build_signal_records_override(mock_ticker_config):
    signal_types = {SignalType.DISTRIBUTION, SignalType.STRONG_BEARISH}
    records = build_signal_records("AAPL", "2026-09-18", signal_types, ticker_config=mock_ticker_config)

    # Should contain only DISTRIBUTION (STRONG_BEARISH was NONE)
    assert len(records) == 1
    assert records[0].signal_type == "distribution"
    assert records[0].adjusted_direction == "SELL"
    assert records[0].confidence_level == "Low"
    assert records[0].suggested_hold_days == 5


def test_build_signal_records_fallback():
    signal_types = {SignalType.DISTRIBUTION}
    # Using empty config
    records = build_signal_records("SPY", "2026-09-18", signal_types, ticker_config={})

    assert len(records) == 1
    assert records[0].adjusted_direction == "BUY"  # Default
    assert records[0].confidence_level == "High"  # Default for Distribution


def test_select_row_prefers_lowest_significant_pvalue():
    # Three horizons for one signal type; only two are significant.
    rows = pd.DataFrame(
        {
            "signal_type": ["distribution"] * 3,
            "horizon_days": [3, 5, 10],
            "event_count": [20, 20, 20],
            "hit_rate": [0.62, 0.65, 0.40],
            "p_value": [0.04, 0.20, 0.01],
        }
    )
    chosen = select_row(rows)
    # p=0.01 at horizon 10 is the lowest significant p-value.
    assert chosen["horizon_days"] == 10


def test_select_row_tie_breaks_on_event_count():
    rows = pd.DataFrame(
        {
            "signal_type": ["accumulation"] * 2,
            "horizon_days": [3, 5],
            "event_count": [10, 40],
            "hit_rate": [0.62, 0.63],
            "p_value": [0.02, 0.02],
        }
    )
    chosen = select_row(rows)
    assert chosen["horizon_days"] == 5  # larger event_count wins the tie


def test_select_row_falls_back_when_none_significant():
    rows = pd.DataFrame(
        {
            "signal_type": ["strong_bullish"] * 2,
            "horizon_days": [3, 5],
            "event_count": [12, 30],
            "hit_rate": [0.52, 0.53],
            "p_value": [0.40, 0.30],
        }
    )
    chosen = select_row(rows)
    assert chosen["horizon_days"] == 5  # most events among non-significant rows


def test_get_rule_hold_days_from_horizon():
    row = pd.Series({"hit_rate": 0.40, "p_value": 0.01, "horizon_days": 10})
    rule = get_rule(row)
    assert rule["adjusted_direction"] == "BUY"
    assert rule["confidence_level"] == "Medium-High"  # 0.35 <= hr < 0.45
    assert rule["suggested_hold_days"] == 10


def test_get_rule_noise_band_is_none():
    row = pd.Series({"hit_rate": 0.50, "p_value": 0.01, "horizon_days": 5})
    assert get_rule(row) == {"adjusted_direction": "NONE"}


def test_build_ticker_config_collapses_horizons():
    # Two signal types, each with multiple horizons -> one rule per type.
    df = pd.DataFrame(
        {
            "signal_type": ["distribution", "distribution", "accumulation", "accumulation"],
            "horizon_days": [3, 10, 3, 5],
            "event_count": [20, 20, 15, 15],
            "hit_rate": [0.62, 0.40, 0.50, 0.50],
            "p_value": [0.30, 0.01, 0.80, 0.90],
        }
    )
    config = build_ticker_config(df)

    assert set(config.keys()) == {"distribution", "accumulation"}
    # distribution: only horizon 10 is significant -> contrarian, hold 10
    assert config["distribution"]["adjusted_direction"] == "BUY"
    assert config["distribution"]["suggested_hold_days"] == 10
    # accumulation: nothing significant and noise-band hit_rate -> NONE
    assert config["accumulation"] == {"adjusted_direction": "NONE"}
