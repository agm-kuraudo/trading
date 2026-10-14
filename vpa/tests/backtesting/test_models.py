"""Unit tests for the SP-354 additions to the backtesting data models.

Covers the new ``ExitReason`` enum, the two new ``SkipReason`` members, and the
additive, defaulted ``stop_loss``/``profit_target``/``exit_reason`` fields on
``ExitResult`` and ``TradeRecord`` (backward compatibility).

Code under test: ``vpa/backtesting/models.py``.

Requirements: 6.5, 7.1, 7.2
"""

from vpa.backtesting.models import (
    ExitReason,
    ExitResult,
    SkipReason,
    TradeRecord,
)
from vpa.ml_validation.signal_analysis import SignalType


def test_exit_reason_has_exactly_stop_target_fixed_hold() -> None:
    """ExitReason exposes exactly STOP, TARGET, FIXED_HOLD (Req 7.1)."""
    assert {member.name for member in ExitReason} == {"STOP", "TARGET", "FIXED_HOLD"}
    assert ExitReason.STOP.value == "stop"
    assert ExitReason.TARGET.value == "target"
    assert ExitReason.FIXED_HOLD.value == "fixed_hold"


def test_skip_reason_adds_two_new_members() -> None:
    """The two SP-354 SkipReason members exist with the expected values (Req 6.5)."""
    assert SkipReason.UNAVAILABLE_RECENT_EXTREME.value == "unavailable_recent_extreme"
    assert SkipReason.DEGENERATE_RISK_DISTANCE.value == "degenerate_risk_distance"


def test_skip_reason_preserves_pre_existing_members() -> None:
    """The pre-SP-354 SkipReason members are unchanged and still present (Req 6.5)."""
    existing = {
        "MISSING_PRICE_DATE": "missing_price_date",
        "OVERLAPPING_POSITION": "overlapping_position",
        "INSUFFICIENT_FUTURE_DATA_ENTRY": "insufficient_future_data_entry",
        "INSUFFICIENT_FUTURE_DATA_EXIT": "insufficient_future_data_exit",
        "INVALID_ENTRY_PRICE": "invalid_entry_price",
        "INVALID_EXIT_PRICE": "invalid_exit_price",
    }
    for name, value in existing.items():
        assert SkipReason[name].value == value


def test_exit_result_defaults_new_fields_to_none() -> None:
    """A default-constructed ExitResult leaves the three new fields at None (Req 7.2)."""
    result = ExitResult(exit_index=3, exit_price=10.0, reason=None)
    assert result.stop_loss is None
    assert result.profit_target is None
    assert result.exit_reason is None


def test_trade_record_defaults_new_fields_to_none() -> None:
    """A TradeRecord built with only the original six fields defaults extras to None (Req 7.2)."""
    trade = TradeRecord(
        entry_date="2024-01-01",
        exit_date="2024-01-05",
        entry_price=100.0,
        exit_price=110.0,
        return_pct=0.1,
        signal_type=SignalType.STRONG_BULLISH,
    )
    assert trade.stop_loss is None
    assert trade.profit_target is None
    assert trade.exit_reason is None
