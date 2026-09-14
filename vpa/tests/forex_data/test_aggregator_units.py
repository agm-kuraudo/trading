"""Unit test for the empty aggregation case (task 3.6).

``aggregate_to_daily`` must treat an empty record list as "no data" and return
an empty Analysis_DataFrame with the exact
``["Date", "Open", "High", "Low", "Close", "Volume"]`` column set and correct
dtypes, raising no error (Requirement 3.4). This module lives alongside, but
distinct from, the aggregator property tests (``test_aggregator_ohlcv.py``,
``test_aggregator_volume.py``, ``test_aggregator_shape.py``,
``test_aggregator_order.py``).

Requirements: 3.4.
"""

import pandas as pd
from pandas.api import types as ptypes

from vpa.forex_data.aggregator import aggregate_to_daily


def test_empty_records_return_empty_frame_with_correct_schema():
    """``aggregate_to_daily([])`` returns an empty, correctly-typed frame.

    No exception may be raised; the frame must have exactly the daily columns
    in order, zero rows, a tz-naive ``datetime64[ns]`` ``Date`` column, float
    O/H/L/C columns, and a numeric ``Volume`` column.

    Requirements: 3.4.
    """
    df = aggregate_to_daily([])

    # Exact column order and no rows.
    assert list(df.columns) == ["Date", "Open", "High", "Low", "Close", "Volume"]
    assert len(df) == 0

    # Date is tz-naive datetime64[ns].
    assert ptypes.is_datetime64_ns_dtype(df["Date"].dtype)
    assert not isinstance(df["Date"].dtype, pd.DatetimeTZDtype)

    # O/H/L/C are float; Volume is numeric.
    for col in ("Open", "High", "Low", "Close"):
        assert ptypes.is_float_dtype(df[col].dtype)
    assert ptypes.is_numeric_dtype(df["Volume"].dtype)
