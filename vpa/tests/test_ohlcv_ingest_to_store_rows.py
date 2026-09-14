"""Unit tests for ``vpa.market_data.ohlcv_ingest.to_store_rows`` (SP-349, Task 3.5).

These are pure-logic tests: they exercise ``to_store_rows`` (and, indirectly, the
private ``_to_utc_bar_open`` helper it delegates to) with hand-built canonical
DataFrames. There is deliberately NO network I/O and NO database connection here.

Covers Requirements:
- 1.4 — ``ts`` is stored as the bar-open time in UTC, using midnight UTC of the
  trading day for daily bars.
- 4.5 — mapping canonical rows to store rows maps ``Date`` to ``ts`` as a UTC
  bar-open timestamp; the tuple carries ticker/interval/OHLCV/adjusted/source.
"""

import datetime

import pandas as pd

from vpa.market_data.ohlcv_ingest import CANONICAL_COLUMNS, to_store_rows

# The exact positional order produced by ``to_store_rows`` per row.
STORE_ROW_FIELDS = (
    "ticker",
    "interval",
    "ts",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "adjusted",
    "source",
)


def make_canonical_df(dates) -> pd.DataFrame:
    """Build a canonical OHLCV DataFrame over ``dates`` with distinct per-row values.

    Each row ``i`` gets deterministic, mutually-distinct O/H/L/C/V values so tests can
    assert the values are threaded into the correct tuple positions (and rows aren't
    transposed or reordered). Columns are exactly ``CANONICAL_COLUMNS``.
    """
    n = len(dates)
    frame = pd.DataFrame(
        {
            "Date": list(dates),
            "Open": [100.0 + i for i in range(n)],
            "High": [110.0 + i for i in range(n)],
            "Low": [90.0 + i for i in range(n)],
            "Close": [105.0 + i for i in range(n)],
            "Volume": [1_000_000 + i for i in range(n)],
        }
    )
    # Sanity: the helper must feed the function exactly the canonical columns.
    assert list(frame.columns) == CANONICAL_COLUMNS
    return frame


# ---------------------------------------------------------------------------
# Tuple shape / order (Req 4.5)
# ---------------------------------------------------------------------------


def test_to_store_rows_tuple_shape_and_order():
    df = make_canonical_df([pd.Timestamp("2024-01-02")])

    rows = to_store_rows(df, ticker="SPY", interval="1d", source="yfinance", adjusted=True)

    assert len(rows) == 1
    row = rows[0]
    # Exactly ten positional fields, in the documented order.
    assert isinstance(row, tuple)
    assert len(row) == len(STORE_ROW_FIELDS)

    ticker, interval, ts, open_, high, low, close, volume, adjusted, source = row
    assert ticker == "SPY"
    assert interval == "1d"
    assert open_ == 100.0
    assert high == 110.0
    assert low == 90.0
    assert close == 105.0
    assert volume == 1_000_000.0
    assert adjusted is True
    assert source == "yfinance"
    # ts is the bar-open timestamp (asserted in detail below).
    assert isinstance(ts, pd.Timestamp)


def test_to_store_rows_passes_through_ticker_interval_source_adjusted():
    df = make_canonical_df([pd.Timestamp("2024-03-15")])

    rows = to_store_rows(df, ticker="AAPL", interval="15m", source="custom", adjusted=False)

    ticker, interval, _ts, *_rest, adjusted, source = rows[0]
    assert ticker == "AAPL"
    assert interval == "15m"
    assert source == "custom"
    assert adjusted is False


# ---------------------------------------------------------------------------
# Numeric typing (Req 4.5)
# ---------------------------------------------------------------------------


def test_to_store_rows_ohlc_and_volume_are_floats():
    # Feed integer-typed OHLCV to prove they are coerced to float on output.
    df = pd.DataFrame(
        {
            "Date": [pd.Timestamp("2024-01-02")],
            "Open": [100],
            "High": [110],
            "Low": [90],
            "Close": [105],
            "Volume": [1_000_000],
        }
    )

    (row,) = to_store_rows(df, ticker="SPY", interval="1d", source="yfinance", adjusted=True)
    _t, _i, _ts, open_, high, low, close, volume, _adj, _src = row

    for value in (open_, high, low, close, volume):
        assert isinstance(value, float)


# ---------------------------------------------------------------------------
# Date -> ts UTC bar-open mapping (Req 1.4, 4.5)
# ---------------------------------------------------------------------------


def test_naive_daily_date_maps_to_midnight_utc():
    # A naive (tz-less) daily Date should localise to midnight UTC of that day.
    df = make_canonical_df([pd.Timestamp("2024-01-02")])

    (row,) = to_store_rows(df, ticker="SPY", interval="1d", source="yfinance", adjusted=True)
    ts = row[2]

    assert isinstance(ts, pd.Timestamp)
    # Timezone-aware and specifically UTC.
    assert ts.tzinfo is not None
    assert ts.utcoffset() == datetime.timedelta(0)
    # Daily bar-open == midnight UTC of the date.
    assert (ts.hour, ts.minute, ts.second, ts.microsecond) == (0, 0, 0, 0)
    assert (ts.year, ts.month, ts.day) == (2024, 1, 2)


def test_naive_python_date_maps_to_midnight_utc():
    # A plain datetime.date (no time component) is also a valid daily Date.
    df = make_canonical_df([datetime.date(2024, 1, 2)])

    (row,) = to_store_rows(df, ticker="SPY", interval="1d", source="yfinance", adjusted=True)
    ts = row[2]

    assert ts.utcoffset() == datetime.timedelta(0)
    assert (ts.hour, ts.minute, ts.second) == (0, 0, 0)
    assert (ts.year, ts.month, ts.day) == (2024, 1, 2)


def test_tz_aware_date_is_converted_to_utc():
    # An already tz-aware Date (US/Eastern) must be CONVERTED to UTC, not relocalised.
    # 2024-01-02 09:30 America/New_York == 2024-01-02 14:30 UTC.
    eastern_ts = pd.Timestamp("2024-01-02 09:30", tz="America/New_York")
    df = make_canonical_df([eastern_ts])

    (row,) = to_store_rows(df, ticker="SPY", interval="1h", source="yfinance", adjusted=True)
    ts = row[2]

    assert ts.utcoffset() == datetime.timedelta(0)
    assert (ts.year, ts.month, ts.day) == (2024, 1, 2)
    assert (ts.hour, ts.minute) == (14, 30)
    # Same instant as the original, just expressed in UTC.
    assert ts == eastern_ts


# ---------------------------------------------------------------------------
# Row count and ordering (Req 4.5)
# ---------------------------------------------------------------------------


def test_row_count_equals_input_and_order_preserved():
    dates = [
        pd.Timestamp("2024-01-02"),
        pd.Timestamp("2024-01-03"),
        pd.Timestamp("2024-01-04"),
    ]
    df = make_canonical_df(dates)

    rows = to_store_rows(df, ticker="SPY", interval="1d", source="yfinance", adjusted=True)

    assert len(rows) == len(df)
    # ts values appear in the same order as the input rows.
    result_dates = [(r[2].year, r[2].month, r[2].day) for r in rows]
    assert result_dates == [(2024, 1, 2), (2024, 1, 3), (2024, 1, 4)]
    # Close values (distinct per row) confirm no transposition/reordering.
    result_closes = [r[6] for r in rows]
    assert result_closes == [105.0, 106.0, 107.0]


def test_empty_dataframe_yields_no_rows():
    df = make_canonical_df([])

    rows = to_store_rows(df, ticker="SPY", interval="1d", source="yfinance", adjusted=True)

    assert rows == []
