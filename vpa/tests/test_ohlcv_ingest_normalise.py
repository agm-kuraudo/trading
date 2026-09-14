"""Unit tests for ``vpa.market_data.ohlcv_ingest.normalise_yf_download`` (SP-349, Task 3.4).

These are pure-logic tests: they exercise ``normalise_yf_download`` only, feeding it
hand-built DataFrames that mimic the shapes ``yf.download`` produces. There is
deliberately NO network I/O here (Requirement 4.3) -- every input is constructed in
memory.

Covers Requirements:
- 4.1: flatten a MultiIndex download, case-insensitively rename to the canonical
  names, drop rows with missing OHLCV values, and sort ascending by ``Date``.
- 4.2: the returned DataFrame contains exactly the columns
  ``Date, Open, High, Low, Close, Volume``.
"""

import numpy as np
import pandas as pd

from vpa.market_data.ohlcv_ingest import CANONICAL_COLUMNS, normalise_yf_download

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _multiindex_download(dates, opens, highs, lows, closes, volumes, ticker="SPY"):
    """Build a DataFrame shaped like a single-ticker ``yf.download`` result.

    yfinance returns a DatetimeIndex plus a MultiIndex column axis whose first level
    is the field name (``Open``/``High``/...) and whose second level is the ticker.
    """
    index = pd.DatetimeIndex(dates, name="Date")
    columns = pd.MultiIndex.from_tuples(
        [
            ("Open", ticker),
            ("High", ticker),
            ("Low", ticker),
            ("Close", ticker),
            ("Volume", ticker),
        ],
        names=["Price", "Ticker"],
    )
    data = np.column_stack([opens, highs, lows, closes, volumes])
    return pd.DataFrame(data, index=index, columns=columns)


# ---------------------------------------------------------------------------
# MultiIndex-column input is flattened correctly (Req 4.1, 4.2)
# ---------------------------------------------------------------------------


def test_multiindex_input_is_flattened_to_canonical_columns():
    raw = _multiindex_download(
        dates=["2023-01-03", "2023-01-04"],
        opens=[100.0, 101.0],
        highs=[102.0, 103.0],
        lows=[99.0, 100.5],
        closes=[101.0, 102.5],
        volumes=[1_000_000, 1_100_000],
    )

    result = normalise_yf_download(raw)

    assert list(result.columns) == CANONICAL_COLUMNS
    assert len(result) == 2
    # Values survive the flatten unchanged.
    assert result.loc[0, "Open"] == 100.0
    assert result.loc[0, "Close"] == 101.0
    assert result.loc[1, "High"] == 103.0
    assert result.loc[1, "Volume"] == 1_100_000


# ---------------------------------------------------------------------------
# Flat-column input with lower/mixed case is renamed case-insensitively (Req 4.1)
# ---------------------------------------------------------------------------


def test_flat_lowercase_columns_are_renamed_case_insensitively():
    raw = pd.DataFrame(
        {
            "date": pd.to_datetime(["2023-01-03", "2023-01-04"]),
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.5],
            "close": [101.0, 102.5],
            "volume": [1_000_000, 1_100_000],
        }
    )

    result = normalise_yf_download(raw)

    assert list(result.columns) == CANONICAL_COLUMNS
    assert result.loc[0, "Open"] == 100.0
    assert result.loc[1, "Close"] == 102.5


def test_flat_mixedcase_columns_are_renamed_case_insensitively():
    raw = pd.DataFrame(
        {
            "DATE": pd.to_datetime(["2023-01-03", "2023-01-04"]),
            "OpEn": [100.0, 101.0],
            "HIGH": [102.0, 103.0],
            "Low": [99.0, 100.5],
            "cLoSe": [101.0, 102.5],
            "VOLUME": [1_000_000, 1_100_000],
        }
    )

    result = normalise_yf_download(raw)

    assert list(result.columns) == CANONICAL_COLUMNS
    assert result.loc[0, "High"] == 102.0
    assert result.loc[1, "Low"] == 100.5


# ---------------------------------------------------------------------------
# Rows with NaN in any OHLCV column are dropped (Req 4.1)
# ---------------------------------------------------------------------------


def test_rows_with_nan_in_any_ohlcv_column_are_dropped():
    raw = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2023-01-03", "2023-01-04", "2023-01-05", "2023-01-06", "2023-01-07"]),
            "Open": [100.0, np.nan, 102.0, 103.0, 104.0],
            "High": [101.0, 102.0, np.nan, 104.0, 105.0],
            "Low": [99.0, 100.0, 101.0, np.nan, 103.0],
            "Close": [100.5, 101.5, 102.5, 103.5, np.nan],
            "Volume": [1_000_000, 1_100_000, 1_200_000, 1_300_000, 1_400_000],
        }
    )

    result = normalise_yf_download(raw)

    # Only the first row has no NaN across any OHLCV column.
    assert len(result) == 1
    assert result.loc[0, "Date"] == pd.Timestamp("2023-01-03")
    assert result.loc[0, "Open"] == 100.0


def test_row_with_nan_volume_is_dropped():
    raw = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2023-01-03", "2023-01-04"]),
            "Open": [100.0, 101.0],
            "High": [102.0, 103.0],
            "Low": [99.0, 100.5],
            "Close": [101.0, 102.5],
            "Volume": [np.nan, 1_100_000],
        }
    )

    result = normalise_yf_download(raw)

    assert len(result) == 1
    assert result.loc[0, "Date"] == pd.Timestamp("2023-01-04")


# ---------------------------------------------------------------------------
# Output is sorted ascending by Date (Req 4.1)
# ---------------------------------------------------------------------------


def test_output_is_sorted_ascending_by_date():
    raw = pd.DataFrame(
        {
            # Deliberately out of order.
            "Date": pd.to_datetime(["2023-01-05", "2023-01-03", "2023-01-04"]),
            "Open": [105.0, 103.0, 104.0],
            "High": [106.0, 104.0, 105.0],
            "Low": [104.0, 102.0, 103.0],
            "Close": [105.5, 103.5, 104.5],
            "Volume": [1_500_000, 1_300_000, 1_400_000],
        }
    )

    result = normalise_yf_download(raw)

    dates = list(result["Date"])
    assert dates == [
        pd.Timestamp("2023-01-03"),
        pd.Timestamp("2023-01-04"),
        pd.Timestamp("2023-01-05"),
    ]
    # The Date column is monotonically increasing.
    assert result["Date"].is_monotonic_increasing


# ---------------------------------------------------------------------------
# Output has EXACTLY the canonical columns in order with a reset RangeIndex (Req 4.2)
# ---------------------------------------------------------------------------


def test_output_has_exactly_canonical_columns_in_order():
    raw = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2023-01-03", "2023-01-04"]),
            "Open": [100.0, 101.0],
            "High": [102.0, 103.0],
            "Low": [99.0, 100.5],
            "Close": [101.0, 102.5],
            "Volume": [1_000_000, 1_100_000],
            # Extra columns that must NOT appear in the canonical output.
            "Adj Close": [101.0, 102.5],
            "Dividends": [0.0, 0.0],
        }
    )

    result = normalise_yf_download(raw)

    assert list(result.columns) == CANONICAL_COLUMNS
    assert list(result.columns) == ["Date", "Open", "High", "Low", "Close", "Volume"]


def test_output_has_reset_rangeindex():
    # Feed out-of-order rows so a naive sort would leave a shuffled index.
    raw = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2023-01-05", "2023-01-03", "2023-01-04"]),
            "Open": [105.0, 103.0, 104.0],
            "High": [106.0, 104.0, 105.0],
            "Low": [104.0, 102.0, 103.0],
            "Close": [105.5, 103.5, 104.5],
            "Volume": [1_500_000, 1_300_000, 1_400_000],
        }
    )

    result = normalise_yf_download(raw)

    assert isinstance(result.index, pd.RangeIndex)
    assert list(result.index) == [0, 1, 2]
