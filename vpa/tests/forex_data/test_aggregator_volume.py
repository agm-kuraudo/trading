"""Property test for volume preservation in the daily aggregator (SP-309).

Covers task 3.4 / design Property 5: aggregation must not create or destroy
volume. Each daily bar's ``Volume`` must equal the arithmetic sum of the
volumes of the source records that fall on that bar's UTC calendar day, and the
grand total of the output ``Volume`` column must equal the sum of all
source-record volumes. Volume is an integer field, so equality is exact.

Pure and network-free: builds :class:`~vpa.forex_data.decoder.Record` objects
directly and calls :func:`~vpa.forex_data.aggregator.aggregate_to_daily`.
"""

from datetime import datetime, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from vpa.forex_data.aggregator import aggregate_to_daily
from vpa.forex_data.decoder import Record

# One 30-minute (M30) bar in milliseconds; source records are M30 intraday bars.
_M30_MS = 30 * 60 * 1000
# Anchor timestamps at 2020-01-01T00:00:00Z so generated records span a small,
# deterministic window of one or more UTC days.
_BASE_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


@st.composite
def _records(draw: st.DrawFn) -> list[Record]:
    """Generate a non-empty list of records spanning one or more UTC days.

    Timestamps are drawn as arbitrary M30-slot offsets from a fixed UTC base so
    the set spans one or more calendar days, and the records are returned in
    arbitrary (unsorted) order. Volumes are arbitrary non-negative integers.
    """
    count = draw(st.integers(min_value=1, max_value=40))
    # Slot offsets can land on the same day or across several days; 0..480
    # M30 slots covers up to ~10 UTC days.
    slots = draw(
        st.lists(
            st.integers(min_value=0, max_value=480),
            min_size=count,
            max_size=count,
        )
    )
    volumes = draw(
        st.lists(
            st.integers(min_value=0, max_value=10_000_000),
            min_size=count,
            max_size=count,
        )
    )
    records = [
        Record(
            timestamp_ms=_BASE_MS + slot * _M30_MS,
            open=1.0,
            high=1.0,
            low=1.0,
            close=1.0,
            volume=vol,
        )
        for slot, vol in zip(slots, volumes)
    ]
    # Arbitrary timestamp order: shuffle the generated records.
    return draw(st.permutations(records))


def _utc_date(timestamp_ms: int):
    """Return the UTC calendar date for a millisecond epoch timestamp.

    Equivalent to ``datetime.utcfromtimestamp(timestamp_ms / 1000).date()`` but
    using the timezone-aware form to avoid the deprecated naive-UTC helper.
    """
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).date()


# Feature: replace-selenium-forex-scraping, Property 5: Volume is preserved under aggregation
@settings(max_examples=100)
@given(records=_records())
def test_volume_is_preserved_under_aggregation(records: list[Record]) -> None:
    """Validates: Requirements 3.2, 9.4.

    Per-day output Volume equals the exact integer sum of source volumes for
    that UTC day, and the grand total is conserved.
    """
    result = aggregate_to_daily(records)

    # Expected per-UTC-day volume sums from the source records.
    expected_by_day: dict[object, int] = {}
    for record in records:
        day = _utc_date(record.timestamp_ms)
        expected_by_day[day] = expected_by_day.get(day, 0) + record.volume

    # Assertion 1: each daily bar's Volume equals the sum of its day's sources.
    assert len(result) == len(expected_by_day)
    for _, row in result.iterrows():
        bar_day = row["Date"].date() if hasattr(row["Date"], "date") else row["Date"]
        assert bar_day in expected_by_day
        assert int(row["Volume"]) == expected_by_day[bar_day]

    # Assertion 2: grand total of the output Volume column is conserved.
    assert int(result["Volume"].sum()) == sum(r.volume for r in records)
