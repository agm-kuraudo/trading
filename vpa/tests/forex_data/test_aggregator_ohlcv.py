"""Property test for per-day OHLCV aggregation (SP-309, task 3.2).

Exercises :func:`vpa.forex_data.aggregator.aggregate_to_daily` against a set of
decoded intraday records spanning multiple UTC calendar days, verifying that
each daily bar's Open/High/Low/Close is computed correctly from the source
records grouped by their UTC calendar date, that there is exactly one bar per
distinct UTC day present in the input, and that the most recent UTC day appears
as the last bar. This module owns only Property 3; the other aggregator
properties live in their own test files (order/volume/shape/units).
"""

from datetime import UTC, datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vpa.forex_data.aggregator import DAILY_COLUMNS, aggregate_to_daily
from vpa.forex_data.decoder import Record

# One UTC calendar day in milliseconds.
_MS_PER_DAY = 86_400_000
# One minute in milliseconds (intraday bars sit on minute boundaries).
_MS_PER_MINUTE = 60_000
# Base UTC midnight to offset day generation from: 2010-01-01T00:00:00Z, which
# matches the era of the real Dukascopy feed and is comfortably tz-representable.
_BASE_MIDNIGHT_MS = int(datetime(2010, 1, 1, tzinfo=UTC).timestamp() * 1000)


# A realistic small forex price, e.g. GBPUSD around 0.5 - 2.5, rounded to the
# 5-digit precision the feed carries so float comparisons stay clean.
_prices = st.floats(
    min_value=0.5,
    max_value=2.5,
    allow_nan=False,
    allow_infinity=False,
).map(lambda p: round(p, 5))

# Non-negative integer volume.
_volumes = st.integers(min_value=0, max_value=1_000_000)


@st.composite
def _records_spanning_multiple_days(draw) -> list[Record]:
    """Build records across several distinct UTC days, unordered.

    Picks a set of distinct day offsets, then for each day generates one or more
    intraday minute offsets. Timestamps are assembled as
    ``base_midnight + day_offset*day + minute_offset*minute`` and the full list
    is shuffled so the aggregator sees an arbitrary (unordered) input order.
    Always yields at least one record so the frame is non-empty.
    """
    day_offsets = draw(st.lists(st.integers(min_value=0, max_value=40), min_size=1, max_size=6, unique=True))

    records: list[Record] = []
    for day_offset in day_offsets:
        day_midnight_ms = _BASE_MIDNIGHT_MS + day_offset * _MS_PER_DAY
        # Distinct minute offsets within the day so earliest/latest are unambiguous.
        minute_offsets = draw(
            st.lists(
                st.integers(min_value=0, max_value=1439),
                min_size=1,
                max_size=8,
                unique=True,
            )
        )
        for minute_offset in minute_offsets:
            timestamp_ms = day_midnight_ms + minute_offset * _MS_PER_MINUTE
            records.append(
                Record(
                    timestamp_ms=timestamp_ms,
                    open=draw(_prices),
                    high=draw(_prices),
                    low=draw(_prices),
                    close=draw(_prices),
                    volume=draw(_volumes),
                )
            )

    # Present the records in arbitrary (possibly unordered) timestamp order.
    return draw(st.permutations(records))


def _utc_date(timestamp_ms: int):
    """Return the UTC calendar date for a millisecond timestamp."""
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).date()


def _expected_daily_ohlcv(records: list[Record]) -> dict:
    """Compute expected per-UTC-day OHLCV independently of the aggregator.

    Open is the open of the earliest-timestamp record that day, Close is the
    close of the latest-timestamp record that day, High is the max high, Low is
    the min low. Only days that actually have records are included.
    """
    by_day: dict = {}
    for record in records:
        by_day.setdefault(_utc_date(record.timestamp_ms), []).append(record)

    expected = {}
    for day, day_records in by_day.items():
        earliest = min(day_records, key=lambda r: r.timestamp_ms)
        latest = max(day_records, key=lambda r: r.timestamp_ms)
        expected[day] = {
            "Open": earliest.open,
            "High": max(r.high for r in day_records),
            "Low": min(r.low for r in day_records),
            "Close": latest.close,
        }
    return expected


# Feature: replace-selenium-forex-scraping, Property 3: Daily aggregation computes correct per-day OHLCV
@settings(max_examples=100)
@given(records=_records_spanning_multiple_days())
def test_aggregation_ohlcv(records: list[Record]) -> None:
    """Each daily bar has correct per-day OHLCV; most-recent day is last.

    Validates: Requirements 3.1, 3.2, 3.5
    """
    expected = _expected_daily_ohlcv(records)

    result = aggregate_to_daily(records)

    # Exactly one bar per distinct UTC day present in the input (Req 3.1).
    assert list(result.columns) == DAILY_COLUMNS
    assert len(result) == len(expected)

    result_days = [d.date() for d in result["Date"]]
    assert set(result_days) == set(expected)
    # No duplicate days.
    assert len(result_days) == len(set(result_days))

    # Correct O/H/L/C per day (Req 3.2).
    for _, row in result.iterrows():
        day = row["Date"].date()
        want = expected[day]
        assert row["Open"] == pytest.approx(want["Open"])
        assert row["High"] == pytest.approx(want["High"])
        assert row["Low"] == pytest.approx(want["Low"])
        assert row["Close"] == pytest.approx(want["Close"])

    # The most recent UTC day in the input is present as the LAST bar (Req 3.5).
    most_recent_day = max(expected)
    assert result_days[-1] == most_recent_day
