"""Property-based test for Correctness Property 3 — Offline read (SP-349, Task 10.3).

**Property 3: Offline read.** ``get_ohlcv`` and ``export_ohlcv`` never perform
network I/O — a patched ``yf.download`` / ``fetch_yf`` is never called.

**Validates: Requirements 11.3, 3.1, 3.6**

Strategy
--------
Hypothesis generates, for each example:

- an arbitrary ticker (short upper-case symbol) and interval,
- an arbitrary set of *distinct* stored bar dates (a canonical
  ``Date, Open, High, Low, Close, Volume`` frame built from those dates), and
- an arbitrary query range ``[start, end]`` that is deliberately allowed to fall
  partly or wholly **outside** the stored data (the range endpoints are drawn from a
  window that extends well before and after the stored dates), so ranges that select
  all / some / none of the stored bars are all exercised.

For every generated example the store is warmed with the bars via ``upsert_bars``
(the write path — not under test here; it uses the injected fake connection, never
the network), then ``get_ohlcv`` and ``export_ohlcv`` are invoked **with both network
entry points patched to raise**. If either read path touched the network the patched
callable would raise ``AssertionError`` and the property would fail.

Hermeticity notes
-----------------
Hypothesis warns when a test relies on function-scoped fixtures (``tmp_path``,
``monkeypatch``) that are set up once but re-used across every generated example. To
keep each generated example fully self-contained this test uses
:func:`unittest.mock.patch` as context managers and :class:`tempfile.TemporaryDirectory`
*inside* the test body — no per-example fixtures — so there are no hypothesis
fixture-scope warnings. The store uses ``make_conn_factory`` (an in-memory fake
connection): no database and no network are involved.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import mock

import pandas as pd
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from vpa.market_data.repository import MarketDataRepository
from vpa.tests.test_market_data_repository_integration import (
    make_canonical_df,
    make_conn_factory,
)

# The dates the store can be warmed with are drawn from a bounded window so query
# ranges (below) can be positioned before / within / after them deterministically.
_STORE_WINDOW_START = pd.Timestamp("2020-06-01")
_STORE_WINDOW_END = pd.Timestamp("2020-08-31")

# Query-range endpoints are drawn from a *wider* window that brackets the store
# window on both sides, so generated ranges routinely fall partly or wholly outside
# the stored data (selecting all, some, or none of the bars).
_QUERY_WINDOW_START = pd.Timestamp("2020-01-01")
_QUERY_WINDOW_END = pd.Timestamp("2020-12-31")


@st.composite
def _stored_bars(draw):
    """Generate ``(ticker, interval, df)`` with distinct dates in the store window.

    Dates are unique (``pd.Timestamp`` per day) so each maps to a distinct
    ``(ticker, interval, ts)`` key; the canonical frame is built by the shared
    :func:`make_canonical_df` helper so OHLCV values are deterministic per row.
    """
    ticker = draw(st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ", min_size=1, max_size=5))
    interval = draw(st.sampled_from(["1d", "1h", "1wk"]))

    span_days = (_STORE_WINDOW_END - _STORE_WINDOW_START).days
    day_offsets = draw(
        st.lists(
            st.integers(min_value=0, max_value=span_days),
            min_size=1,
            max_size=12,
            unique=True,
        )
    )
    dates = sorted(_STORE_WINDOW_START + pd.Timedelta(days=off) for off in day_offsets)
    return ticker, interval, make_canonical_df(dates)


@st.composite
def _query_range(draw):
    """Generate an inclusive ``(start, end)`` range, possibly outside the store window."""
    span_days = (_QUERY_WINDOW_END - _QUERY_WINDOW_START).days
    a = draw(st.integers(min_value=0, max_value=span_days))
    b = draw(st.integers(min_value=0, max_value=span_days))
    lo, hi = sorted((a, b))
    start = _QUERY_WINDOW_START + pd.Timedelta(days=lo)
    end = _QUERY_WINDOW_START + pd.Timedelta(days=hi)
    return start, end


def _raise_on_network(*args, **kwargs):  # noqa: ARG001 - signature-agnostic guard
    raise AssertionError("network access attempted during an offline read")


@settings(max_examples=40, suppress_health_check=[HealthCheck.too_slow])
@given(bars=_stored_bars(), query=_query_range())
def test_offline_read_never_touches_network(bars, query):
    """get_ohlcv and export_ohlcv are offline for any bars / any query range.

    **Validates: Requirements 11.3, 3.1, 3.6**
    """
    ticker, interval, df = bars
    start, end = query

    # Warm the store via the write path (fake connection — no DB, no network). This
    # is intentionally OUTSIDE the network patch: upsert_bars is not under test here.
    _store, conn_factory = make_conn_factory()
    repo = MarketDataRepository(conn_factory=conn_factory)
    repo.upsert_bars(df, ticker, interval)

    # Patch every network entry point the read/export paths could conceivably reach:
    # the raw yfinance API, the ingestion wrapper, and the wrapper's yf use-site.
    # Any call raises AssertionError, failing the property immediately.
    with (
        mock.patch("yfinance.download", _raise_on_network),
        mock.patch("vpa.market_data.ohlcv_ingest.fetch_yf", _raise_on_network),
        mock.patch("vpa.market_data.ohlcv_ingest.yf.download", _raise_on_network),
    ):
        # --- get_ohlcv: strictly offline, returns the canonical read shape. ---
        out = repo.get_ohlcv(ticker, interval, start, end)
        assert list(out.columns) == ["Date", "Open", "High", "Low", "Close", "Volume"]
        # Returned rows are exactly those stored dates that fall within [start, end].
        stored_dates = {pd.Timestamp(d).normalize() for d in df["Date"]}
        expected = {d for d in stored_dates if start.normalize() <= d <= end.normalize()}
        got = {pd.Timestamp(d).tz_localize(None).normalize() for d in out["Date"]}
        assert got == expected
        # Ordered by Date ascending.
        assert list(out["Date"]) == sorted(out["Date"])

        # --- export_ohlcv: writes a scoped file, also strictly offline. ---
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_path = str(Path(tmp_dir) / "export.csv")
            returned = repo.export_ohlcv(ticker, interval, start, end, out_path)
            assert returned == out_path
            assert Path(out_path).exists()
            read_back = pd.read_csv(out_path)
            assert list(read_back.columns) == ["Date", "Open", "High", "Low", "Close", "Volume"]
            assert len(read_back) == len(expected)
