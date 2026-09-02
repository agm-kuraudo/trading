"""Tests for the Signal_Log and Price_Series builders (SP-317).

Task 7.2 covers Property 12 (Signal-Log construction from dataset) via Hypothesis,
using SignalConditionalAnalyzer.classify_signals as the oracle since the builder is a
thin adapter over it. Task 7.3 covers the price-series builder unit tests, including
the SP-335-not-applied guard that raises when an OHLC column is missing.
"""

import math

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vpa.backtesting.models import PricePoint, SignalEntry
from vpa.backtesting.signal_log_builder import (
    build_price_series_from_dataset,
    build_signal_log_from_dataset,
)
from vpa.ml_validation.signal_analysis import (
    SIGNAL_DIRECTIONS,
    SignalConditionalAnalyzer,
    SignalType,
)

# ---------------------------------------------------------------------------
# Task 7.2 - Property test for signal-log construction
# ---------------------------------------------------------------------------

# Hypothesis strategy for a single dataset row. Ranges are chosen so every signal
# threshold in classify_signals can fire: composite_score spans both strong bands,
# acc_dist_flag/type drive accumulation/distribution, and acc_dist_score spans the
# accumulation-test-pass threshold. NaN is injected into driving fields so the
# NaN-exclusion behaviour (Req 2.5) is exercised too.
_signal_floats = st.one_of(
    st.floats(min_value=-30.0, max_value=30.0, allow_nan=False, allow_infinity=False),
    st.just(float("nan")),
)
_score_floats = st.one_of(
    st.floats(min_value=0.0, max_value=30.0, allow_nan=False, allow_infinity=False),
    st.just(float("nan")),
)
_flag_values = st.sampled_from([0, 1])
_type_values = st.sampled_from([-1, 0, 1])
_price_floats = st.floats(min_value=0.01, max_value=10000.0, allow_nan=False, allow_infinity=False)


@st.composite
def _feature_datasets(draw: st.DrawFn) -> pd.DataFrame:
    """Build a random Feature_Dataset with unique ascending ISO dates and signal fields."""
    n_rows = draw(st.integers(min_value=1, max_value=12))

    base = pd.Timestamp("2020-01-01")
    dates = [(base + pd.Timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n_rows)]

    rows = []
    for _ in range(n_rows):
        rows.append(
            {
                "composite_score": draw(_signal_floats),
                "acc_dist_flag": draw(_flag_values),
                "acc_dist_type": draw(_type_values),
                "acc_dist_score": draw(_score_floats),
                "open": draw(_price_floats),
                "high": draw(_price_floats),
                "low": draw(_price_floats),
                "close": draw(_price_floats),
            }
        )

    df = pd.DataFrame(rows)
    df.insert(0, "date", dates)
    return df


# Feature: vpa-backtesting-engine, Property 12: Signal-Log construction from dataset
@settings(max_examples=100)
@given(df=_feature_datasets())
def test_signal_log_matches_classify_signals_oracle(df: pd.DataFrame) -> None:
    """Every (row, matched SignalType) yields exactly one SignalEntry with correct date/direction.

    Uses classify_signals as the oracle: the builder is a thin adapter over it, so the
    property under test is adapter faithfulness - one entry per (row, matched type) with
    the row date and SIGNAL_DIRECTIONS[signal_type].

    **Validates: Requirements 2.1, 2.2, 2.5**
    """
    oracle = SignalConditionalAnalyzer(output_dir=".").classify_signals(df)

    # Expected: one entry per (row_index, matched signal_type).
    expected: list[SignalEntry] = []
    total_matches = 0
    for signal_type in SignalType:
        for row_index in oracle[signal_type]:
            total_matches += 1
            expected.append(
                SignalEntry(
                    date=df.loc[row_index, "date"],
                    signal_type=signal_type,
                    direction=SIGNAL_DIRECTIONS[signal_type],
                )
            )

    actual = build_signal_log_from_dataset(df)

    # One entry per (row_index, signal_type) match.
    assert len(actual) == total_matches

    # Each emitted entry carries the correct direction for its type.
    for entry in actual:
        assert entry.direction == SIGNAL_DIRECTIONS[entry.signal_type]

    # The multiset of emitted entries equals the oracle-derived multiset.
    def _key(entries: list[SignalEntry]) -> list[tuple[str, str, str]]:
        return sorted((e.date, e.signal_type.value, e.direction.value) for e in entries)

    assert _key(actual) == _key(expected)


# ---------------------------------------------------------------------------
# Task 7.3 - Unit tests for the price-series builder
# _Requirements: 2.3; Design: Error Handling (Missing OHLC columns)_
# ---------------------------------------------------------------------------


def _row(date: str, open_: float, high: float, low: float, close: float) -> dict[str, object]:
    return {"date": date, "open": open_, "high": high, "low": low, "close": close}


def test_unsorted_rows_returned_date_ascending() -> None:
    """Unsorted date rows are returned as PricePoints sorted date-ascending (Req 2.3)."""
    df = pd.DataFrame(
        [
            _row("2020-01-03", 3.0, 3.5, 2.5, 3.2),
            _row("2020-01-01", 1.0, 1.5, 0.5, 1.2),
            _row("2020-01-02", 2.0, 2.5, 1.5, 2.2),
        ]
    )

    series = build_price_series_from_dataset(df)

    assert [p.date for p in series] == ["2020-01-01", "2020-01-02", "2020-01-03"]


def test_pricepoint_values_match_source_row() -> None:
    """Each PricePoint's OHLC values match the source row as floats (Req 2.3)."""
    df = pd.DataFrame(
        [
            _row("2020-01-01", 1.0, 1.5, 0.5, 1.2),
            _row("2020-01-02", 2.0, 2.5, 1.5, 2.2),
        ]
    )

    series = build_price_series_from_dataset(df)

    assert series[0] == PricePoint(date="2020-01-01", open=1.0, high=1.5, low=0.5, close=1.2)
    assert series[1] == PricePoint(date="2020-01-02", open=2.0, high=2.5, low=1.5, close=2.2)
    for point in series:
        assert isinstance(point.open, float)
        assert isinstance(point.high, float)
        assert isinstance(point.low, float)
        assert isinstance(point.close, float)


def test_missing_open_column_raises_keyerror_naming_column() -> None:
    """A dataset missing the 'open' column raises KeyError naming it (SP-335-not-applied guard)."""
    df = pd.DataFrame(
        [
            {"date": "2020-01-01", "high": 1.5, "low": 0.5, "close": 1.2},
        ]
    )

    with pytest.raises(KeyError, match="open"):
        build_price_series_from_dataset(df)


def test_missing_close_column_raises_keyerror_naming_column() -> None:
    """A dataset missing the 'close' column raises KeyError naming it (SP-335-not-applied guard)."""
    df = pd.DataFrame(
        [
            {"date": "2020-01-01", "open": 1.0, "high": 1.5, "low": 0.5},
        ]
    )

    with pytest.raises(KeyError, match="close"):
        build_price_series_from_dataset(df)


def test_missing_multiple_ohlc_columns_names_them() -> None:
    """When several OHLC columns are missing, the error names each of them."""
    df = pd.DataFrame(
        [
            {"date": "2020-01-01", "close": 1.2},
        ]
    )

    with pytest.raises(KeyError) as exc_info:
        build_price_series_from_dataset(df)

    message = str(exc_info.value)
    assert "open" in message
    assert "high" in message
    assert "low" in message


def test_single_row_price_series_has_no_nan() -> None:
    """A well-formed single-row dataset produces one finite PricePoint."""
    df = pd.DataFrame([_row("2020-01-01", 1.0, 1.5, 0.5, 1.2)])

    series = build_price_series_from_dataset(df)

    assert len(series) == 1
    point = series[0]
    assert not math.isnan(point.open)
    assert not math.isnan(point.close)
