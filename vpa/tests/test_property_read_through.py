"""Property-based test for read-through completeness (SP-349, Task 10.4).

**Property 4: Read-through completeness.**
``load_ohlcv(ticker, interval, start, end)`` returns a contiguous set of
trading-day bars for the requested range — no missing days the source could
provide — AND fetches only the missing tail (no full re-download when the store
already covers a prefix). Daily contiguity is checked against
``utils.utils.trading_days_between(start, end)`` / ``pd.date_range(freq="B")``.

**Validates: Requirements 11.4, 3.2, 3.3**

Design mechanics being exercised (see ``vpa/market_data/repository.py``):

- ``load_ohlcv`` reads the store offline first (``get_ohlcv``), computes the
  ``expected_last`` business day on/before ``end``, and compares it against the
  newest stored bar. When the store is empty or stale it fetches **only the
  missing tail**: from ``start`` when nothing is stored, otherwise from the day
  **after** the newest stored bar. It then upserts the tail idempotently and
  re-reads the merged range.

Test doubles:

- The **store** is the in-memory ``FakeConnection`` / ``make_conn_factory`` from
  ``test_market_data_repository_integration`` — no real DB.
- The **source** (yfinance) is a fake that patches
  ``vpa.market_data.repository.fetch_yf`` (the name imported into the repository).
  The fake returns a canonical frame of the business days in ``[tail_start, end]``
  with deterministic values, and **records** the ``tail_start`` it was called with
  so the test can assert only the missing tail was requested. The patch is applied
  **inside the test body** with ``mock.patch`` so it is hypothesis-safe (no
  per-example function-scoped fixture resets).
"""

from __future__ import annotations

import math
from unittest import mock

import pandas as pd
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from utils.utils import trading_days_between
from vpa.market_data.repository import MarketDataRepository

from .test_market_data_repository_integration import make_canonical_df, make_conn_factory

# A fixed, timezone-naive anchor so generated ranges are deterministic and land on
# real weekday business days. We pick a start business-day offset within a window and
# a length in trading days.
_ANCHOR = pd.Timestamp("2020-01-01")


def _business_days(start, end) -> list[pd.Timestamp]:
    """All business days in the inclusive ``[start, end]`` range (tz-naive)."""
    return [pd.Timestamp(d) for d in pd.date_range(start=start, end=end, freq="B")]


def _norm_naive(value) -> pd.Timestamp:
    """Normalise a (possibly tz-aware) timestamp to a tz-naive midnight."""
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts.normalize()


def _make_fake_fetch(calls: list):
    """Build a fake ``fetch_yf`` that records ``tail_start`` and returns a canonical
    frame of business days in ``[tail_start, end]`` with deterministic values.

    ``calls`` accumulates each ``tail_start`` (normalised, tz-naive) so the test can
    assert exactly which tail was requested.
    """

    def _fake_fetch(ticker, interval, start, end):  # noqa: ARG001 - signature mirrors fetch_yf
        calls.append(_norm_naive(start))
        tail_days = _business_days(start, end)
        return make_canonical_df(tail_days)

    return _fake_fetch


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    # Offset (in calendar days) of the range start from the fixed anchor; snapped to a
    # business day below. Range length in trading days. Prefix fraction p in [0, 1].
    start_offset=st.integers(min_value=0, max_value=400),
    n_trading_days=st.integers(min_value=1, max_value=20),
    prefix_fraction=st.floats(min_value=0.0, max_value=1.0),
)
def test_load_ohlcv_read_through_completeness(start_offset, n_trading_days, prefix_fraction):
    ticker, interval = "SPY", "1d"

    # --- Build the requested [start, end] range over business days. -------------
    # Snap the start to the first business day on/after the offset anchor so the
    # generated range always begins on a trading day.
    raw_start = _ANCHOR + pd.Timedelta(days=start_offset)
    business_from_start = pd.date_range(start=raw_start, periods=n_trading_days, freq="B")
    full_days = [pd.Timestamp(d) for d in business_from_start]
    start = full_days[0]
    end = full_days[-1]
    n = len(full_days)

    # Sanity: the range's trading-day count matches the codebase helper.
    assert trading_days_between(start, end) == n

    # --- Model the "prefix already stored" fraction. ---------------------------
    prefix_count = math.floor(prefix_fraction * n)
    prefix_days = full_days[:prefix_count]

    store, conn_factory = make_conn_factory()
    repo = MarketDataRepository(conn_factory=conn_factory)

    if prefix_days:
        repo.upsert_bars(make_canonical_df(prefix_days), ticker, interval)

    # --- Patch the source (fetch_yf) inside the test body (hypothesis-safe). ----
    fetch_calls: list[pd.Timestamp] = []
    fake_fetch = _make_fake_fetch(fetch_calls)

    with mock.patch("vpa.market_data.repository.fetch_yf", side_effect=fake_fetch):
        out = repo.load_ohlcv(ticker, interval, start, end)

    # --- Assertion 1: contiguous, complete trading-day coverage. ----------------
    result_dates = sorted(_norm_naive(d) for d in out["Date"])
    expected_dates = sorted(_norm_naive(d) for d in full_days)
    assert result_dates == expected_dates, "returned bars must cover every business day in [start, end]"

    # --- Assertion 2: no duplicate dates in the result. -------------------------
    assert len(result_dates) == len(set(result_dates)), "no duplicate dates in the read-through result"

    # --- Assertion 3: only the missing tail was fetched. ------------------------
    if prefix_count == 0:
        # Empty store => fetch the whole range, starting at `start`.
        assert len(fetch_calls) == 1
        assert fetch_calls[0] == _norm_naive(start)
    elif prefix_count == n:
        # Fully warm store => the newest stored bar == expected_last, so either no
        # fetch happens, or if one did it must not have re-downloaded the prefix.
        for called_start in fetch_calls:
            assert called_start > _norm_naive(prefix_days[-1])
    else:
        # Partial prefix => fetch only the tail, starting the day AFTER the last
        # stored bar (never from `start`, i.e. never a full re-download).
        last_stored = _norm_naive(prefix_days[-1])
        expected_tail_start = last_stored + pd.Timedelta(days=1)
        assert len(fetch_calls) == 1
        assert fetch_calls[0] == expected_tail_start
        assert fetch_calls[0] != _norm_naive(start)
