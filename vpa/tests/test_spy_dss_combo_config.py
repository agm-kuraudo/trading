"""SPY DSS/combo config schema and regression tests (SP-359, task 7.2).

Validates Requirements 6.1-6.7: the SPY entry in ``vpa/config/ticker_signals.json``
contains exactly one ``dss_bullish`` rule, one ``dss_bearish`` rule, and one rule
per combo column name; every DSS/combo rule has a valid ``adjusted_direction`` and
(when not ``"NONE"``) a valid ``confidence_level`` + integer ``suggested_hold_days``
>= 1; the file parses as valid JSON; and the pre-existing SPY non-DSS/non-combo
rules and the whole AAPL entry are unchanged.
"""

import json
from pathlib import Path

import pytest

from vpa.ml_validation.signal_analysis import _COMBO_COLUMN_TO_TYPE

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "ticker_signals.json"

# Confidence levels already used by existing entries (Req 6.4).
VALID_CONFIDENCE_LEVELS = {"High", "Medium-High", "Low-Medium", "Low"}
VALID_DIRECTIONS = {"BUY", "SELL", "NONE"}

# The ten combo column names, resolved from the single source of truth so the
# test cannot drift from the column map used at runtime.
COMBO_COLUMN_NAMES = tuple(_COMBO_COLUMN_TO_TYPE.keys())

# Pre-existing SPY rules that must remain unchanged (Req 6.7). These are the
# non-DSS, non-combo rules present before SP-359 added the DSS/combo rules.
EXPECTED_SPY_BASE_RULES = {
    "distribution": {
        "confidence_level": "High",
        "adjusted_direction": "BUY",
        "suggested_hold_days": 10,
    },
    "strong_bearish": {
        "confidence_level": "Medium-High",
        "adjusted_direction": "BUY",
        "suggested_hold_days": 10,
    },
    "strong_bullish": {
        "confidence_level": "Low-Medium",
        "adjusted_direction": "BUY",
        "suggested_hold_days": 10,
    },
    "accumulation": {
        "confidence_level": "Low",
        "adjusted_direction": "BUY",
        "suggested_hold_days": 10,
    },
}

# The entire AAPL entry must remain unchanged (Req 6.7).
EXPECTED_AAPL_ENTRY = {
    "accumulation": {"adjusted_direction": "NONE"},
    "accumulation_test_pass": {"adjusted_direction": "NONE"},
    "distribution": {
        "confidence_level": "Medium-High",
        "adjusted_direction": "BUY",
        "suggested_hold_days": 3,
    },
    "dss_bearish": {
        "confidence_level": "High",
        "adjusted_direction": "BUY",
        "suggested_hold_days": 5,
    },
    "dss_bullish": {"adjusted_direction": "NONE"},
    "strong_bearish": {
        "confidence_level": "Medium-High",
        "adjusted_direction": "BUY",
        "suggested_hold_days": 3,
    },
    "strong_bullish": {"adjusted_direction": "NONE"},
}


@pytest.fixture(scope="module")
def ticker_config():
    """Load the real ticker_signals.json; also proves it is valid JSON (Req 6.6)."""
    with CONFIG_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def spy_entry(ticker_config):
    assert "SPY" in ticker_config, "ticker_signals.json must contain a SPY entry"
    return ticker_config["SPY"]


def test_config_parses_as_valid_json():
    """Req 6.6: the file parses as valid JSON without error."""
    with CONFIG_PATH.open(encoding="utf-8") as fh:
        data = json.load(fh)
    assert isinstance(data, dict)


def test_spy_has_exactly_one_dss_bullish_and_one_dss_bearish(spy_entry):
    """Req 6.1: SPY has exactly one dss_bullish and one dss_bearish rule."""
    dss_keys = [key for key in spy_entry if key in ("dss_bullish", "dss_bearish")]
    assert dss_keys.count("dss_bullish") == 1
    assert dss_keys.count("dss_bearish") == 1


def test_spy_has_exactly_one_rule_per_combo_column(spy_entry):
    """Req 6.2: SPY has exactly one rule per combo column name."""
    for combo_col in COMBO_COLUMN_NAMES:
        present = [key for key in spy_entry if key == combo_col]
        assert len(present) == 1, f"SPY must have exactly one {combo_col} rule"

    # Guard against drift: all ten combo columns are accounted for.
    assert len(COMBO_COLUMN_NAMES) == 10


@pytest.mark.parametrize(
    "rule_name",
    ("dss_bullish", "dss_bearish", *COMBO_COLUMN_NAMES),
)
def test_spy_dss_and_combo_rule_schema(spy_entry, rule_name):
    """Req 6.3-6.5: each DSS/combo rule has a valid direction and, when not
    NONE, a valid confidence_level and an integer suggested_hold_days >= 1."""
    rule = spy_entry[rule_name]
    assert isinstance(rule, dict)

    direction = rule.get("adjusted_direction")
    assert direction in VALID_DIRECTIONS, f"{rule_name} has invalid direction {direction!r}"

    if direction == "NONE":
        # Req 6.5: a disabled rule need not carry confidence/hold values.
        return

    confidence = rule.get("confidence_level")
    assert confidence in VALID_CONFIDENCE_LEVELS, f"{rule_name} has invalid confidence {confidence!r}"

    hold_days = rule.get("suggested_hold_days")
    assert isinstance(hold_days, int) and not isinstance(hold_days, bool)
    assert hold_days >= 1, f"{rule_name} suggested_hold_days must be >= 1"


def test_spy_non_dss_non_combo_rules_unchanged(spy_entry):
    """Req 6.7: pre-existing SPY non-DSS/non-combo rules are unchanged."""
    for name, expected in EXPECTED_SPY_BASE_RULES.items():
        assert spy_entry[name] == expected


def test_aapl_entry_unchanged(ticker_config):
    """Req 6.7: the entire AAPL entry is unchanged."""
    assert ticker_config["AAPL"] == EXPECTED_AAPL_ENTRY
