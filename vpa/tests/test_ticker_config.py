import sys
from pathlib import Path

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vpa.ml_validation.daily_signal import SignalType, build_signal_records
from vpa.ml_validation.signal_analysis import SIGNAL_DIRECTIONS, SignalDirection

# scripts/ is not a package; add it to the path so the importer can be tested.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from import_ticker_signals import SIGNIFICANCE, build_ticker_config, get_rule, select_row  # noqa: E402


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


def test_build_signal_records_unknown_confidence_sorts_last():
    # A config supplying a confidence_level outside CONFIDENCE_ORDER must not
    # crash the sort; it should sort after the known-confidence record.
    config = {
        "AAPL": {
            "distribution": {"confidence_level": "Weird", "adjusted_direction": "BUY", "suggested_hold_days": 3},
            "strong_bearish": {"confidence_level": "High", "adjusted_direction": "BUY", "suggested_hold_days": 5},
        }
    }
    signal_types = {SignalType.DISTRIBUTION, SignalType.STRONG_BEARISH}
    records = build_signal_records("AAPL", "2026-09-18", signal_types, ticker_config=config)

    assert len(records) == 2
    assert records[0].confidence_level == "High"  # known value first
    assert records[1].confidence_level == "Weird"  # unknown value last


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


# ---------------------------------------------------------------------------
# SP-360 bug condition exploration tests (Property 1: Bug Condition).
#
# These assert that adjusted_direction is DERIVED from the signal's base
# direction (SIGNAL_DIRECTIONS in vpa/ml_validation/signal_analysis.py) and the
# interpretation band, rather than hardcoded to "BUY". They are expressed at the
# build_ticker_config level (which carries the signal_type string) so they run
# against both the unfixed get_rule(row) and the fixed get_rule(row, base_dir).
#
# Base directions (per SIGNAL_DIRECTIONS): distribution -> DOWN,
# strong_bearish -> DOWN, accumulation -> UP. action(UP)="BUY", action(DOWN)="SELL".
#
# EXPECTED on UNFIXED code: all three FAIL because the unfixed code emits "BUY".
# That failure confirms the bug.
# ---------------------------------------------------------------------------


def test_bug_condition_down_strong_signal_derives_sell():
    # DOWN-base strong-signal band (hit_rate >= 0.60, significant): keep DOWN -> SELL.
    # distribution has base direction DOWN. (Req 2.1)
    df = pd.DataFrame(
        {
            "signal_type": ["distribution"],
            "horizon_days": [10],
            "event_count": [20],
            "hit_rate": [0.62],
            "p_value": [0.01],
        }
    )
    config = build_ticker_config(df)
    assert config["distribution"]["adjusted_direction"] == "SELL"


def test_bug_condition_down_weak_edge_derives_sell():
    # DOWN-base weak-edge band (0.55 < hit_rate < 0.60, significant): keep DOWN -> SELL.
    # strong_bearish has base direction DOWN. (Req 2.5)
    df = pd.DataFrame(
        {
            "signal_type": ["strong_bearish"],
            "horizon_days": [5],
            "event_count": [20],
            "hit_rate": [0.57],
            "p_value": [0.02],
        }
    )
    config = build_ticker_config(df)
    assert config["strong_bearish"]["adjusted_direction"] == "SELL"


def test_bug_condition_up_contrarian_derives_sell():
    # UP-base contrarian band (hit_rate < 0.45, significant): invert UP -> DOWN -> SELL.
    # accumulation has base direction UP. (Req 2.2)
    df = pd.DataFrame(
        {
            "signal_type": ["accumulation"],
            "horizon_days": [3],
            "event_count": [20],
            "hit_rate": [0.40],
            "p_value": [0.01],
        }
    )
    config = build_ticker_config(df)
    assert config["accumulation"]["adjusted_direction"] == "SELL"


# ---------------------------------------------------------------------------
# SP-360 preservation tests (Property 2: Preservation).
#
# Observation-first: these assertions were anchored to the OBSERVED behaviour of
# the UNFIXED code and MUST PASS on it. They capture the baseline the fix must
# preserve -- the non-buggy region (isBugCondition false), where the derived
# (post-fix) action equals the old hardcoded result.
#
# Base directions (per SIGNAL_DIRECTIONS in vpa/ml_validation/signal_analysis.py):
# distribution -> DOWN, strong_bearish -> DOWN, accumulation -> UP.
# action(UP)="BUY", action(DOWN)="SELL".
#
# Non-buggy actionable bands resolve to "BUY" (DOWN contrarian inverts to UP;
# UP strong-signal/weak-edge keep UP), which equals the old hardcoded "BUY".
# Noise / not-significant / missing-field inputs resolve to NONE under both.
#
# NOTE on the unknown-type case: on the UNFIXED code an unknown signal_type does
# NOT reach the NONE path -- it still emits "BUY" (the old code never consults
# SIGNAL_DIRECTIONS). The post-fix NONE value is therefore asserted in task 1's
# sibling (fix-checking) scope, not here. The preservation-safe invariant that
# holds on BOTH old and new code is that an unknown type never RAISES, so that
# is what this task asserts (Req 2.6 / 3.6 "rather than raising an exception").
# ---------------------------------------------------------------------------


def _single_row_config(signal_type, hit_rate, p_value, horizon_days=10, event_count=20):
    """Build a one-row analysis frame and return that signal type's rule.

    Supplies every column select_row / build_ticker_config require:
    signal_type, horizon_days, event_count, hit_rate, p_value.
    """
    df = pd.DataFrame(
        {
            "signal_type": [signal_type],
            "horizon_days": [horizon_days],
            "event_count": [event_count],
            "hit_rate": [hit_rate],
            "p_value": [p_value],
        }
    )
    return build_ticker_config(df)[signal_type]


def test_preserve_down_contrarian_still_buy():
    # DOWN-base contrarian (hit_rate < 0.45, significant): invert DOWN -> UP -> BUY.
    # The AAPL case. (Req 2.4, 3.3)
    rule = _single_row_config("distribution", 0.40, 0.01)
    assert rule["adjusted_direction"] == "BUY"


def test_preserve_up_strong_signal_still_buy():
    # UP-base strong-signal (hit_rate >= 0.60, significant): keep UP -> BUY. (Req 2.3)
    rule = _single_row_config("accumulation", 0.62, 0.01)
    assert rule["adjusted_direction"] == "BUY"


def test_preserve_up_weak_edge_still_buy():
    # UP-base weak-edge (0.55 < hit_rate < 0.60, significant): keep UP -> BUY.
    rule = _single_row_config("accumulation", 0.57, 0.02)
    assert rule["adjusted_direction"] == "BUY"


def test_preserve_noise_band_still_none():
    # 0.45 <= hit_rate <= 0.55 noise band -> NONE. (Req 3.1)
    rule = _single_row_config("distribution", 0.50, 0.01)
    assert rule == {"adjusted_direction": "NONE"}


def test_preserve_not_significant_still_none():
    # p_value >= SIGNIFICANCE -> NONE. (Req 3.2)
    rule = _single_row_config("distribution", 0.40, 0.20)
    assert rule == {"adjusted_direction": "NONE"}


def test_preserve_missing_hit_rate_still_none():
    # Missing hit_rate -> NONE (select_row drops NaN hit_rate rows; the sole row
    # is dropped, so build_ticker_config assigns the NONE fallback). (Req 3.2)
    rule = _single_row_config("distribution", float("nan"), 0.01)
    assert rule == {"adjusted_direction": "NONE"}


def test_preserve_unknown_signal_type_does_not_raise():
    # Unknown signal_type must not raise under either old or new code. The NONE
    # VALUE is a post-fix behaviour (old code emits "BUY" here), so this task only
    # asserts the preservation-safe invariant: no exception. (Req 2.6, 3.6)
    df = pd.DataFrame(
        {
            "signal_type": ["mystery_signal"],
            "horizon_days": [10],
            "event_count": [20],
            "hit_rate": [0.62],
            "p_value": [0.01],
        }
    )
    config = build_ticker_config(df)  # must not raise
    assert "mystery_signal" in config


def test_preserve_contrarian_confidence_and_hold_days():
    # Contrarian band confidence thresholds and hold-days from horizon_days. (Req 3.4)
    # 0.35 <= hit_rate < 0.45 -> "Medium-High"; hold_days from horizon_days.
    rule = _single_row_config("distribution", 0.40, 0.01, horizon_days=10)
    assert rule["confidence_level"] == "Medium-High"
    assert rule["suggested_hold_days"] == 10
    # hit_rate < 0.35 -> "High".
    rule_high = _single_row_config("distribution", 0.30, 0.01, horizon_days=7)
    assert rule_high["confidence_level"] == "High"
    assert rule_high["suggested_hold_days"] == 7


def test_preserve_strong_signal_confidence_and_hold_days():
    # Strong-signal band: "High"; hold-days from horizon_days. (Req 3.4)
    rule = _single_row_config("accumulation", 0.62, 0.01, horizon_days=5)
    assert rule["confidence_level"] == "High"
    assert rule["suggested_hold_days"] == 5


def test_preserve_weak_edge_confidence_and_hold_days():
    # Weak-edge band: "Low-Medium"; hold-days from horizon_days. (Req 3.4)
    rule = _single_row_config("accumulation", 0.57, 0.02, horizon_days=3)
    assert rule["confidence_level"] == "Low-Medium"
    assert rule["suggested_hold_days"] == 3


def test_preserve_build_ticker_config_none_fallback_when_select_row_none():
    # When every row for a signal type has NaN hit_rate, select_row returns None
    # and build_ticker_config assigns the NONE fallback for that type. (Req 3.6)
    df = pd.DataFrame(
        {
            "signal_type": ["distribution", "distribution"],
            "horizon_days": [3, 10],
            "event_count": [20, 20],
            "hit_rate": [float("nan"), float("nan")],
            "p_value": [0.01, 0.02],
        }
    )
    config = build_ticker_config(df)
    assert config["distribution"] == {"adjusted_direction": "NONE"}


# ---------------------------------------------------------------------------
# SP-360 preservation property test (hypothesis) over the NON-buggy region.
#
# Generate (base_direction, hit_rate, p_value, horizon_days) closed over the
# SIGNAL_DIRECTIONS keys, restricted to the complement of the bug condition, and
# assert the derived action equals the ORIGINAL hardcoded result: "BUY" for
# non-buggy actionable bands, "NONE" otherwise. On UNFIXED code this holds
# because the old code always emits "BUY"/"NONE".
#
# The non-buggy actionable region is exactly: UP-base contrarian/strong/weak
# (all keep/invert to UP -> BUY) and DOWN-base contrarian (invert to UP -> BUY).
# Excluded (buggy): DOWN strong-signal, DOWN weak-edge, UP contrarian -> SELL.
# ---------------------------------------------------------------------------


# One signal_type per base direction, drawn from SIGNAL_DIRECTIONS.
_UP_TYPES = [t.value for t, d in SIGNAL_DIRECTIONS.items() if d == SignalDirection.UP]
_DOWN_TYPES = [t.value for t, d in SIGNAL_DIRECTIONS.items() if d == SignalDirection.DOWN]


def _expected_original_action(base_is_up, hit_rate, p_value):
    """The ORIGINAL hardcoded result for a non-buggy input.

    Old code: NONE for missing/not-significant/noise; "BUY" for every actionable
    band. Restricted to the non-buggy region this also equals the derived action.
    """
    if p_value >= SIGNIFICANCE:
        return "NONE"
    if hit_rate < 0.45 or hit_rate >= 0.60 or (0.55 < hit_rate < 0.60):
        return "BUY"
    return "NONE"  # 0.45 <= hit_rate <= 0.55 noise band


@settings(max_examples=100, deadline=None)
@given(
    base_is_up=st.booleans(),
    # Bands spanning contrarian / noise / weak-edge / strong-signal boundaries.
    hit_rate=st.sampled_from([0.20, 0.34, 0.40, 0.44, 0.45, 0.50, 0.55, 0.56, 0.57, 0.59, 0.60, 0.65, 0.80]),
    p_value=st.sampled_from([0.001, 0.01, 0.04, 0.05, 0.20]),
    horizon_days=st.integers(min_value=1, max_value=30),
)
def test_property_preservation_non_buggy_region(base_is_up, hit_rate, p_value, horizon_days):
    """Property 2: non-buggy inputs match the original hardcoded action.

    Validates: Requirements 2.3, 2.4, 3.1, 3.2, 3.3
    """
    # Restrict to the complement of the bug condition. The buggy cases are
    # DOWN strong-signal, DOWN weak-edge, and UP contrarian (all SELL).
    significant = p_value < SIGNIFICANCE
    is_contrarian = significant and hit_rate < 0.45
    is_strong = significant and hit_rate >= 0.60
    is_weak = significant and (0.55 < hit_rate < 0.60)
    if base_is_up and is_contrarian:
        return  # buggy region -> belongs to Property 1
    if (not base_is_up) and (is_strong or is_weak):
        return  # buggy region -> belongs to Property 1

    signal_type = _UP_TYPES[0] if base_is_up else _DOWN_TYPES[0]
    rule = _single_row_config(signal_type, hit_rate, p_value, horizon_days=horizon_days)
    expected = _expected_original_action(base_is_up, hit_rate, p_value)
    assert rule["adjusted_direction"] == expected
