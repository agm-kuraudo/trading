"""Property-based test for the market-data store (SP-349, Task 10.1).

**Property 1: Idempotency (PK invariant).** For any set of bars ``B``,
``upsert_bars(B)`` followed by ``upsert_bars(B)`` again yields the same stored
rows as a single ``upsert_bars(B)`` — identical count, no duplicate
``(ticker, interval, ts)``. Formally (design §Correctness Properties, Property 1)::

    ∀ B: rows_after(upsert(upsert(∅, B)), B) == rows_after(upsert(∅, B))
         ∧ no_duplicates(ticker, interval, ts)

**Validates: Requirements 11.1, 2.2, 2.3**

This runs with **no database and no network**: it reuses the in-memory,
psycopg2-like fake connection from
``test_market_data_repository_integration`` (``make_conn_factory`` +
``make_canonical_df``). The fake keys rows by ``(ticker, interval, ts)`` — exactly
the store's PK — so duplicate-suppression is exercised faithfully offline.

Generator (hypothesis strategy):
    - A set of 1..12 DISTINCT dates (drawn as ``datetime.date`` values, deduped,
      so the resulting ``ts`` values after ``to_store_rows`` are distinct).
    - Finite, non-NaN OHLCV floats per row (built by ``make_canonical_df`` with the
      drawn dates; each row gets deterministic distinct values).
    - A ticker/interval drawn from a small fixed set.
"""

from __future__ import annotations

import datetime as dt

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from vpa.market_data.repository import MarketDataRepository
from vpa.tests.test_market_data_repository_integration import (
    make_canonical_df,
    make_conn_factory,
)

# Small fixed pools for the instrument key; the property holds for any of them.
_TICKERS = ["SPY", "AAPL", "MSFT", "QQQ"]
_INTERVALS = ["1d", "1h"]


@st.composite
def _bar_sets(draw):
    """Draw ``(df, ticker, interval)`` for a set of bars over DISTINCT dates.

    Dates are drawn as a hypothesis ``set`` of ``datetime.date`` (guaranteeing
    distinctness) and sorted, then handed to ``make_canonical_df`` which fills in
    finite, non-NaN OHLCV floats. Because each date is distinct and daily bars map
    to midnight-UTC ``ts``, every row lands on a distinct ``(ticker, interval, ts)``
    key. Between 1 and 12 dates keeps examples fast.
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
def test_upsert_is_idempotent_on_pk(bars):
    """upsert∘upsert == upsert: no new rows, no duplicate (ticker, interval, ts).

    Validates: Requirements 11.1, 2.2, 2.3
    """
    df, ticker, interval = bars
    store, conn_factory = make_conn_factory()
    repo = MarketDataRepository(conn_factory=conn_factory)

    # The number of distinct PK keys this bar set should occupy. Dates are already
    # distinct (drawn as a set) and share one (ticker, interval), so it equals the
    # row count.
    expected = len(df)

    # First upsert: everything is a fresh insert, nothing updated.
    first = repo.upsert_bars(df, ticker, interval)
    assert first == {"inserted": expected, "updated": 0}
    assert len(store) == expected  # distinct (ticker, interval, ts) keys

    # Second upsert of the SAME bars: no inserts, every row updated in place.
    second = repo.upsert_bars(df, ticker, interval)
    assert second == {"inserted": 0, "updated": expected}

    # PK invariant: the distinct-key count is unchanged — no duplicates crept in.
    assert len(store) == expected

    # And every key is a genuine (ticker, interval, ts) triple with no repeats.
    assert len(set(store.keys())) == expected
    assert all(k[0] == ticker and k[1] == interval for k in store)
