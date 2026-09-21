import pytest
import json
from pathlib import Path
from unittest.mock import patch, mock_open
from vpa.ml_validation.daily_signal import build_signal_records, SignalRecord, SignalType

@pytest.fixture
def mock_ticker_config():
    return {
        "AAPL": {
            "distribution": {
                "confidence_level": "Low",
                "adjusted_direction": "SELL",
                "suggested_hold_days": 5
            },
            "strong_bearish": {
                "adjusted_direction": "NONE"
            }
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
    assert records[0].adjusted_direction == "BUY" # Default
    assert records[0].confidence_level == "High" # Default for Distribution
