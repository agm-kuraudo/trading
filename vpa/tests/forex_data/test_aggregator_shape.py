"""Property test for the daily aggregator output shape invariant (SP-309).

Covers task 3.5 / design Property 6: for *any* set of decoded intraday records
-- including the empty set -- :func:`~vpa.forex_data.aggregator.aggregate_to_daily`
returns a DataFrame whose columns are exactly
``["Date", "Open", "High", "Low", "Close", "Volume"]`` in that order, with
``Date`` a tz-naive ``datetime64[ns]`` dtype and Open/High/Low/Close/Volume
numeric dtypes. This shape is the contract ``MarketAnalyzer`` consumes
(Requirements 3.4, 4.1, 4.2).

Pure and network-free: builds :class:`~vpa.forex_data.decoder.Record` objects
directly and calls the aggregator.
"""

from datetime import datetime, timezone

import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from vpa.forex_data.aggregator import DAILY_COLUMNS, aggregate_to_daily
from vpa.forex_data.decoder import Record

# One 30-minute (M30) bar in milliseconds; source records are M30 intraday bars.
_M30_MS = 30 * 60 * 1000
# Anchor timestamps at 2020-01-01T00:00:00Z so generated records span arbitrary
# UTC days from a fixed, deterministic base.
_BASE_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


@st.composite
def _records(draw: st.DrawFn) -> list[Record]:
    """Generate a list of records, *including the empty list*.

    Timestamps are drawn as arbitrary M30-slot offsets from a fixed UTC base so
    the set spans arbitrary calendar days. Prices and volumes are arbitrary.
    ``min_size=0`` ensures the empty-input case is exercised (Requirement 3.4).
    """
    count = draw(st.integers(min_value=0, max_value=40))
    slots = draw(
        st.lists(
            st.integers(min_value=0, max_value=480),
            min_size=count,
            max_size=count,
        )
    )
    prices = draw(
        st.lists(
            st.floats(
                min_value=0.0001,
                max_value=1_000_000.0,
                allow_nan=False,
                allow_infinity=False,
            ),
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
    return [
        Record(
            timestamp_ms=_BASE_MS + slot * _M30_MS,
            open=price,
            high=price,
            low=price,
            close=price,
            volume=vol,
        )
        for slot, price, vol in zip(slots, prices, volumes)
    ]


# Feature: replace-selenium-forex-scraping, Property 6: Output DataFrame shape is invariant
@settings(max_examples=100)
@given(records=_records())
def test_output_dataframe_shape_is_invariant(records: list[Record]) -> None:
    """Validates: Requirements 3.4, 4.1, 4.2.

    For any record set (including empty), the returned DataFrame has the exact
    column order, a tz-naive datetime ``Date``, and numeric OHLCV dtypes.
    """
    result = aggregate_to_daily(records)

    # Assertion 1: exact column order (Requirements 4.1).
    assert list(result.columns) == DAILY_COLUMNS
    assert DAILY_COLUMNS == ["Date", "Open", "High", "Low", "Close", "Volume"]

    # Assertion 2: Date is tz-naive datetime64[ns] (Requirement 4.2).
    assert pd.api.types.is_datetime64_dtype(result["Date"])
    assert not isinstance(result["Date"].dtype, pd.DatetimeTZDtype)

    # Assertion 3: O/H/L/C are float; Volume is numeric.
    for column in ("Open", "High", "Low", "Close"):
        assert pd.api.types.is_float_dtype(result[column])
    assert pd.api.types.is_numeric_dtype(result["Volume"])
