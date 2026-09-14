"""Property test for ascending chronological ordering of daily bars (SP-309).

Covers task 3.3 / design Property 4: the ``Date`` column of the aggregated
DataFrame must be strictly increasing. Because ``aggregate_to_daily`` groups by
UTC calendar day, "strictly increasing" means the dates are both monotonically
increasing AND unique (no two bars share a date), so no matter what order the
source records arrive in, the output is sorted ascending with one bar per day.

Pure and network-free: builds :class:`~vpa.forex_data.decoder.Record` objects
directly with UNORDERED timestamps spanning multiple UTC days and calls
:func:`~vpa.forex_data.aggregator.aggregate_to_daily`.
"""

from datetime import UTC, datetime

from hypothesis import given, settings
from hypothesis import strategies as st

from vpa.forex_data.aggregator import aggregate_to_daily
from vpa.forex_data.decoder import Record

# One UTC calendar day in milliseconds.
_MS_PER_DAY = 86_400_000
# One minute in milliseconds (intraday bars sit on minute boundaries).
_MS_PER_MINUTE = 60_000
# Anchor at 2015-01-01T00:00:00Z: within the era of the real Dukascopy feed and
# comfortably timezone-representable.
_BASE_MIDNIGHT_MS = int(datetime(2015, 1, 1, tzinfo=UTC).timestamp() * 1000)

# Arbitrary small forex-like prices, rounded to 5-digit feed precision.
_prices = st.floats(
    min_value=0.5,
    max_value=2.5,
    allow_nan=False,
    allow_infinity=False,
).map(lambda p: round(p, 5))

# Arbitrary non-negative integer volume.
_volumes = st.integers(min_value=0, max_value=1_000_000)


@st.composite
def _records_unordered_multiple_days(draw: st.DrawFn) -> list[Record]:
    """Build records across several distinct UTC days, returned unordered.

    Draws a set of distinct day offsets and, for each, one or more intraday
    minute offsets. Timestamps are assembled as
    ``base_midnight + day_offset*day + minute_offset*minute``. The complete list
    is shuffled so the aggregator receives an arbitrary, unordered input.
    Always yields at least one record so the output frame is non-empty and
    spans multiple UTC days when more than one day offset is drawn.
    """
    day_offsets = draw(
        st.lists(
            st.integers(min_value=0, max_value=60),
            min_size=1,
            max_size=8,
            unique=True,
        )
    )

    records: list[Record] = []
    for day_offset in day_offsets:
        day_midnight_ms = _BASE_MIDNIGHT_MS + day_offset * _MS_PER_DAY
        minute_offsets = draw(
            st.lists(
                st.integers(min_value=0, max_value=1439),
                min_size=1,
                max_size=6,
                unique=True,
            )
        )
        for minute_offset in minute_offsets:
            records.append(
                Record(
                    timestamp_ms=day_midnight_ms + minute_offset * _MS_PER_MINUTE,
                    open=draw(_prices),
                    high=draw(_prices),
                    low=draw(_prices),
                    close=draw(_prices),
                    volume=draw(_volumes),
                )
            )

    # Present the records in arbitrary (unordered) timestamp order.
    return draw(st.permutations(records))


# Feature: replace-selenium-forex-scraping, Property 4: Daily bars are in ascending chronological order
@settings(max_examples=100)
@given(records=_records_unordered_multiple_days())
def test_daily_bars_ascending(records: list[Record]) -> None:
    """The ``Date`` column is strictly increasing regardless of input order.

    Validates: Requirements 3.3

    Strictly increasing = monotonic increasing AND all dates unique, which
    together guarantee each value is strictly greater than the previous one.
    """
    result = aggregate_to_daily(records)

    date_col = result["Date"]

    # Monotonic non-decreasing ordering of the Date column.
    assert date_col.is_monotonic_increasing
    # No duplicate dates: combined with monotonicity this gives strictly
    # increasing (each value strictly greater than the previous).
    assert date_col.is_unique
