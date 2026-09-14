"""Property-based test for the market-data store (SP-349, Task 10.2).

**Property 2: Round-trip.** Bars upserted then read back via ``get_ohlcv`` equal
the normalised input (within float tolerance) for the same ticker/interval/range.
Formally (design §Correctness Properties, Property 2)::

    ∀ df: get_ohlcv(ticker, interval, min(df.Date), max(df.Date))
          ≈ normalise_yf_download(df)   (OHLCV within ε)

**Validates: Requirements 11.2, 3.1**

This runs with **no database and no network**: it reuses the in-memory,
psycopg2-like fake connection from ``test_market_data_repository_integration``
(``make_conn_factory`` + ``make_canonical_df``). The fake stores whatever
``upsert_bars`` writes and returns it from ``get_ohlcv`` verbatim, so the
round-trip is meaningful for the mapping / ordering / typing logic under test —
``to_store_rows`` (``Date -> ts`` UTC bar-open) → store → ``get_ohlcv`` canonical
frame — without any real Postgres.

Generator (hypothesis strategy):
    - A set of 1..12 DISTINCT dates (drawn as ``datetime.date``, deduped, so the
      resulting ``ts`` values after ``to_store_rows`` are distinct and the read-back
      row count matches the input row count).
    - Finite, non-NaN OHLCV floats per row (built by ``make_canonical_df``; each row
      gets deterministic distinct values so a transposed/reordered mapping is
      caught).
    - A ticker/interval drawn from a small fixed set.

Comparison detail — the ``ts`` UTC bar-open mapping:
    ``make_canonical_df`` produces tz-naive ``Date`` values; after ``to_store_rows``
    each ``Date`` becomes a UTC tz-aware bar-open ``ts`` (daily = midnight UTC), and
    ``get_ohlcv`` returns those as ``Date``. So the read-back ``Date`` column is
    UTC-aware. Dates are therefore compared on their normalised calendar day
    (``_as_naive_days``) rather than raw dtype, matching the design's "compare on
    date/normalised timestamps" note. OHLCV values are compared with
    ``numpy.allclose`` (float tolerance).
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from vpa.market_data.ohlcv_ingest import CANONICAL_COLUMNS
from vpa.market_data.repository import MarketDataRepository
from vpa.tests.test_market_data_repository_integration import (
    make_canonical_df,
    make_conn_factory,
)

# Small fixed pools for the instrument key; the property holds for any of them.
_TICKERS = ["SPY", "AAPL", "MSFT", "QQQ"]
_INTERVALS = ["1d", "1h"]

# OHLCV float comparison tolerance.
_RTOL = 1e-9
_ATOL = 1e-6


def _as_naive_days(dates) -> list[pd.Timestamp]:
    """Normalise a Date series to tz-naive, midnight-normalised calendar days.

    Both the original input (tz-naive) and the read-back frame (UTC tz-aware, per
    the ``ts`` bar-open mapping) reduce to the same list here, so date ordering /
    identity can be compared irrespective of tz-awareness.
    """
    out: list[pd.Timestamp] = []
    for value in dates:
        ts = pd.Timestamp(value)
        if ts.tzinfo is not None:
            ts = ts.tz_convert("UTC").tz_localize(None)
        out.append(ts.normalize())
    return out


@st.composite
def _bar_sets(draw):
    """Draw ``(df, ticker, interval)`` for a set of bars over DISTINCT dates.

    Dates are drawn as a hypothesis ``set`` of ``datetime.date`` (guaranteeing
    distinctness) and sorted, then handed to ``make_canonical_df`` which fills in
    finite, non-NaN OHLCV floats. Distinct dates + one ``(ticker, interval)`` mean
    every row lands on a distinct ``(ticker, interval, ts)`` key, so the read-back
    row count equals the input row count. Between 1 and 12 dates keeps examples fast.
    """
    dates = draw(
        st.sets(
            st.dates(min_value=dt.date(2000, 1, 1), max_value=dt.date(2035, 12, 31)),
            min_size=1,
            max_size=12,
        )
    )
    ticker = draw(st.sampled_from(_TICKERS))
    interval = draw(st.sampled_from(_INTERVALS))
    df = make_canonical_df(sorted(dates))
    return df, ticker, interval


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(bars=_bar_sets())
def test_upsert_then_get_ohlcv_round_trips(bars):
    """get_ohlcv(min..max) ≈ the upserted input: same rows, order, columns, values.

    Validates: Requirements 11.2, 3.1
    """
    df, ticker, interval = bars
    store, conn_factory = make_conn_factory()
    repo = MarketDataRepository(conn_factory=conn_factory)

    # Upsert the bars, then read back over exactly [min(Date), max(Date)].
    repo.upsert_bars(df, ticker, interval)
    start = df["Date"].min()
    end = df["Date"].max()
    out = repo.get_ohlcv(ticker, interval, start, end)

    # Canonical column set and order, exactly.
    assert list(out.columns) == CANONICAL_COLUMNS

    # Same row count as the (distinct-dated) input — nothing dropped or duplicated.
    assert len(out) == len(df)

    # Input is already sorted ascending by Date; the read-back must be too, and the
    # two date sequences must match day-for-day (accounting for the ts UTC bar-open
    # mapping by comparing on normalised calendar days).
    expected_days = _as_naive_days(df["Date"])
    actual_days = _as_naive_days(out["Date"])
    assert actual_days == sorted(actual_days)  # ORDER BY ts => ascending Date
    assert actual_days == expected_days

    # OHLCV values round-trip within float tolerance, row-for-row (ordering already
    # confirmed identical above).
    for column in ("Open", "High", "Low", "Close", "Volume"):
        expected_values = df[column].to_numpy(dtype=float)
        actual_values = out[column].to_numpy(dtype=float)
        assert np.allclose(
            actual_values, expected_values, rtol=_RTOL, atol=_ATOL
        ), f"{column} mismatch: {actual_values!r} != {expected_values!r}"
