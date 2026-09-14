"""Pure daily aggregation for the browserless forex retriever.

Resamples decoded intraday (M30) :class:`~vpa.forex_data.decoder.Record`
objects into daily (D1) bars grouped by UTC calendar day, producing the exact
``["Date", "Open", "High", "Low", "Close", "Volume"]`` DataFrame that
``MarketAnalyzer`` consumes. This module performs no network I/O and reads no
globals, so it is deterministic and property-testable (Requirement 9).
"""

import pandas as pd

from vpa.forex_data.decoder import Record

DAILY_COLUMNS = ["Date", "Open", "High", "Low", "Close", "Volume"]

# Aggregation rule per daily bar (Requirement 3.2).
_AGG_RULES = {
    "Open": "first",
    "High": "max",
    "Low": "min",
    "Close": "last",
    "Volume": "sum",
}


def _empty_daily_frame() -> pd.DataFrame:
    """Return an empty Analysis_DataFrame with the correct columns and dtypes.

    Empty input must not raise (Requirement 3.4). ``Date`` is tz-naive
    ``datetime64[ns]``; O/H/L/C are float and Volume is integer.
    """
    return pd.DataFrame(
        {
            "Date": pd.Series([], dtype="datetime64[ns]"),
            "Open": pd.Series([], dtype="float64"),
            "High": pd.Series([], dtype="float64"),
            "Low": pd.Series([], dtype="float64"),
            "Close": pd.Series([], dtype="float64"),
            "Volume": pd.Series([], dtype="int64"),
        }
    )


def aggregate_to_daily(records: list[Record]) -> pd.DataFrame:
    """Aggregate intraday records into daily (D1) bars grouped by UTC day.

    Args:
        records: Decoded intraday records (any iterable of objects exposing
            ``timestamp_ms``, ``open``, ``high``, ``low``, ``close``, and
            ``volume`` attributes).

    Returns:
        A DataFrame with columns exactly :data:`DAILY_COLUMNS`, sorted ascending
        by ``Date``. ``Date`` is tz-naive ``datetime64[ns]``; O/H/L/C are float
        and Volume is numeric. Days with no records are dropped
        (Requirements 3.1, 3.2, 3.3, 4.1, 4.2). Empty input returns an empty
        frame with the correct columns/dtypes and raises no error
        (Requirement 3.4).
    """
    if not records:
        return _empty_daily_frame()

    frame = pd.DataFrame(
        {
            "Open": [r.open for r in records],
            "High": [r.high for r in records],
            "Low": [r.low for r in records],
            "Close": [r.close for r in records],
            "Volume": [r.volume for r in records],
        },
        index=pd.to_datetime(
            [r.timestamp_ms for r in records], unit="ms", utc=True
        ),
    )

    # Resample by calendar day (UTC) and apply per-field aggregation, then drop
    # days that had no records (weekends/holidays) (Requirements 3.1, 3.2).
    daily = frame.resample("1D").agg(_AGG_RULES).dropna()

    # Move the datetime index into a tz-naive ``Date`` column (Requirement 4.2).
    daily = daily.reset_index()
    date_col = daily.columns[0]
    daily[date_col] = daily[date_col].dt.tz_localize(None)
    daily = daily.rename(columns={date_col: "Date"})

    # Exact column order, ascending by Date (Requirements 3.3, 4.1).
    daily = daily.sort_values("Date").reset_index(drop=True)
    return daily[DAILY_COLUMNS]
