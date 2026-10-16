"""Property and example tests for build_signal_records with DSS/combo types (SP-359).

Covers spec tasks 6.3-6.6:

- **Property 8** (6.3): for a DSS/combo type with no matching config rule,
  build_signal_records uses the CONFIDENCE_MAP confidence, direction "BUY",
  and hold 10.
- **Property 9** (6.4): a matching rule overrides direction/confidence/hold,
  and a "NONE" rule omits the signal.
- **Property 10** (6.5): records are ordered by CONFIDENCE_ORDER (High first),
  with unknown confidence levels sorted last.
- Example tests (6.6) for Req 7.7 / 7.8.

FAST: build_signal_records is pure (no I/O, no model).

# Feature: dss-daily-signal-classification, Properties 8, 9, 10
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from vpa.ml_validation.daily_signal import (
    CONFIDENCE_MAP,
    CONFIDENCE_ORDER,
    build_signal_records,
)
from vpa.ml_validation.signal_analysis import _COMBO_COLUMN_TO_TYPE, SignalType

# The DSS + combo SignalTypes this ticket governs.
_DSS_TYPES = [SignalType.DSS_BULLISH, SignalType.DSS_BEARISH]
_COMBO_TYPES = list(_COMBO_COLUMN_TO_TYPE.values())
_DSS_COMBO_TYPES = _DSS_TYPES + _COMBO_TYPES

_TICKER = "SPY"
_DATE = "2026-01-02"


# ---------------------------------------------------------------------------
# Property 8 (task 6.3): default-path records use mapped confidence, BUY, hold 10
# ---------------------------------------------------------------------------


class TestProperty8DefaultPath:
    # Feature: dss-daily-signal-classification, Property 8: Default-path DSS and combo records use the mapped confidence, BUY, hold 10  # noqa: E501
    # Validates: Requirement 5.5
    @settings(max_examples=100, deadline=None)
    @given(sig_type=st.sampled_from(_DSS_COMBO_TYPES))
    def test_no_matching_rule_uses_defaults(self, sig_type):
        # No ticker_config at all -> default path.
        records = build_signal_records(_TICKER, _DATE, {sig_type}, ticker_config=None)
        assert len(records) == 1
        record = records[0]
        assert record.confidence_level == CONFIDENCE_MAP[sig_type]
        assert record.adjusted_direction == "BUY"
        assert record.suggested_hold_days == 10
        assert record.signal_type == sig_type.value


# ---------------------------------------------------------------------------
# Property 9 (task 6.4): matching rule overrides, NONE omits
# ---------------------------------------------------------------------------


class TestProperty9RuleOverrides:
    # Feature: dss-daily-signal-classification, Property 9: A matching rule overrides direction, confidence, and hold days (and NONE omits)  # noqa: E501
    # Validates: Requirements 5.6, 5.7
    @settings(max_examples=200, deadline=None)
    @given(
        sig_type=st.sampled_from(_DSS_COMBO_TYPES),
        direction=st.sampled_from(["BUY", "SELL", "NONE"]),
        confidence=st.sampled_from(CONFIDENCE_ORDER),
        hold=st.integers(min_value=1, max_value=30),
    )
    def test_matching_rule_applied_or_omitted(self, sig_type, direction, confidence, hold):
        rule = {"adjusted_direction": direction}
        if direction != "NONE":
            rule["confidence_level"] = confidence
            rule["suggested_hold_days"] = hold
        config = {_TICKER: {sig_type.value: rule}}

        records = build_signal_records(_TICKER, _DATE, {sig_type}, ticker_config=config)

        if direction == "NONE":
            # Req 5.7: a NONE rule omits the signal entirely.
            assert records == []
        else:
            # Req 5.6: the rule's direction/confidence/hold are applied.
            assert len(records) == 1
            record = records[0]
            assert record.adjusted_direction == direction
            assert record.confidence_level == confidence
            assert record.suggested_hold_days == hold


# ---------------------------------------------------------------------------
# Property 10 (task 6.5): records ordered by confidence, High first, unknown last
# ---------------------------------------------------------------------------


class TestProperty10Ordering:
    # Feature: dss-daily-signal-classification, Property 10: Records are ordered by confidence, High first, unknown last
    # Validates: Requirement 5.8
    @settings(max_examples=100, deadline=None)
    @given(
        confidences=st.lists(
            st.sampled_from([*CONFIDENCE_ORDER, "Mystery", "Unranked"]),
            min_size=1,
            max_size=len(_DSS_COMBO_TYPES),
            unique=True,
        )
    )
    def test_records_sorted_by_confidence_rank(self, confidences):
        # Assign each generated confidence to a distinct DSS/combo type via a
        # ticker_config rule so build_signal_records produces one record each.
        types = _DSS_COMBO_TYPES[: len(confidences)]
        rules = {
            t.value: {
                "adjusted_direction": "BUY",
                "confidence_level": c,
                "suggested_hold_days": 10,
            }
            for t, c in zip(types, confidences, strict=False)
        }
        config = {_TICKER: rules}

        records = build_signal_records(_TICKER, _DATE, set(types), ticker_config=config)

        def rank(level: str) -> int:
            return CONFIDENCE_ORDER.index(level) if level in CONFIDENCE_ORDER else len(CONFIDENCE_ORDER)

        ranks = [rank(r.confidence_level) for r in records]
        assert ranks == sorted(ranks), f"records not ordered by confidence: {ranks}"
        # Every unknown-confidence record must sit at the end.
        known = [r for r in records if r.confidence_level in CONFIDENCE_ORDER]
        unknown = [r for r in records if r.confidence_level not in CONFIDENCE_ORDER]
        assert [r.confidence_level for r in records[: len(known)]] == [r.confidence_level for r in known]
        assert all(r.confidence_level not in CONFIDENCE_ORDER for r in records[len(known) :]) or not unknown


# ---------------------------------------------------------------------------
# Example tests (task 6.6): Req 7.7, 7.8
# ---------------------------------------------------------------------------


class TestBuildSignalRecordsExamples:
    def test_no_matching_rule_uses_confidence_map(self):
        # Req 7.7
        sig = SignalType.DSS_BULLISH
        records = build_signal_records(_TICKER, _DATE, {sig}, ticker_config={})
        assert len(records) == 1
        assert records[0].confidence_level == CONFIDENCE_MAP[sig]
        assert records[0].adjusted_direction == "BUY"
        assert records[0].suggested_hold_days == 10

    def test_matching_rule_direction_applied(self):
        # Req 7.8 (override)
        sig = SignalType.COMBO_DSS_CROSS_SMA_POS_BULL
        config = {
            _TICKER: {
                sig.value: {
                    "adjusted_direction": "SELL",
                    "confidence_level": "High",
                    "suggested_hold_days": 7,
                }
            }
        }
        records = build_signal_records(_TICKER, _DATE, {sig}, ticker_config=config)
        assert len(records) == 1
        assert records[0].adjusted_direction == "SELL"
        assert records[0].confidence_level == "High"
        assert records[0].suggested_hold_days == 7

    def test_none_rule_omits_record(self):
        # Req 7.8 (NONE omits)
        sig = SignalType.DSS_BEARISH
        config = {_TICKER: {sig.value: {"adjusted_direction": "NONE"}}}
        records = build_signal_records(_TICKER, _DATE, {sig}, ticker_config=config)
        assert records == []
