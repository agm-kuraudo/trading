"""Repository intraday read-through tests (SP-379, Tasks 6.3, 6.4, 6.5).

Hermetic tests (no DB, no network) for the session-aware intraday behaviour added to
``MarketDataRepository``: ``_expected_last`` for ``15m``/``1h``, the IG-backed tail
fetcher routing in ``load_ohlcv`` (asserted with a fake fetcher that records calls),
the incomplete-final-bar drop, and idempotent ingestion. Reuses the in-memory store
fake from ``test_market_data_repository_integration``.

Properties validated:
- Property 6 (session-aware expectation) - Task 6.4
- Property 4 (idempotent ingestion)      - Task 6.5
"""

from __future__ import annotations

import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from vpa.market_data.repository import IG_EPIC, MarketDataRepository

from .test_market_data_repository_integration import make_conn_factory

pytestmark = pytest.mark.usefixtures("no_ig_network")

_EXPECTED_LAST = MarketDataRepository._expected_last


def _canonical_1h(start, n):
    """Build a contiguous hourly canonical frame of n bars from start (UTC)."""
    dates = pd.date_range(start=pd.Timestamp(start, tz="UTC"), periods=n, freq="1h")
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": [100.0 + i for i in range(n)],
            "High": [110.0 + i for i in range(n)],
            "Low": [90.0 + i for i in range(n)],
            "Close": [105.0 + i for i in range(n)],
            "Volume": [1_000 + i for i in range(n)],
        }
    )


# ---------------------------------------------------------------------------
# Task 6.3 - _expected_last for intraday
# ---------------------------------------------------------------------------


def test_expected_last_returns_last_completed_bar_not_end():
    # Tuesday mid-session: end 15:30 -> last completed 1h bar opens at 14:00.
    result = _EXPECTED_LAST("1h", "2024-01-02 00:00", "2024-01-02 15:30")
    assert result == pd.Timestamp("2024-01-02 14:00:00")


def test_expected_last_none_for_weekend_range():
    result = _EXPECTED_LAST("1h", "2024-01-06 00:00", "2024-01-07 23:00")
    assert result is None


def test_expected_last_15m_grid():
    result = _EXPECTED_LAST("15m", "2024-01-02 00:00", "2024-01-02 15:37")
    assert result == pd.Timestamp("2024-01-02 15:15:00")


# ---------------------------------------------------------------------------
# Task 6.3 - read-through fetches only the missing tail and drops partial bar
# ---------------------------------------------------------------------------


class _RecordingFetcher:
    """Fake IG tail fetcher returning a canonical frame and recording its args."""

    def __init__(self, frame):
        self._frame = frame
        self.calls = []

    def __call__(self, ticker, interval, start, end):
        self.calls.append({"ticker": ticker, "interval": interval, "start": start, "end": end})
        return self._frame.copy()


def test_read_through_fetches_only_missing_tail_via_injected_fetcher():
    store, conn_factory = make_conn_factory()

    # Pre-store two 1h bars (12:00, 13:00) for the IG epic.
    seed = _canonical_1h("2024-01-02 12:00:00", 2)
    seed_repo = MarketDataRepository(conn_factory=conn_factory)
    seed_repo.upsert_bars(seed, IG_EPIC, "1h", source="ig", adjusted=False)

    # The fetcher returns the tail 14:00..16:00 (16:00 is the in-progress bar).
    tail = _canonical_1h("2024-01-02 14:00:00", 3)
    fetcher = _RecordingFetcher(tail)
    repo = MarketDataRepository(conn_factory=conn_factory, ig_tail_fetcher=fetcher)

    out = repo.load_ohlcv(IG_EPIC, "1h", "2024-01-02 12:00:00", "2024-01-02 16:30:00")

    # Exactly one tail fetch, starting AFTER the newest stored bar (13:00 -> 14:00).
    assert len(fetcher.calls) == 1
    # tail_start is tz-naive UTC (repository normalises via _to_naive_utc).
    assert pd.Timestamp(fetcher.calls[0]["start"]) == pd.Timestamp("2024-01-02 14:00:00")

    # The incomplete final bar (16:00) was dropped before persisting; the merged
    # result therefore spans 12:00..15:00 (16:00 absent).
    dates = list(pd.to_datetime(out["Date"], utc=True))
    assert pd.Timestamp("2024-01-02 15:00:00", tz="UTC") in dates
    assert pd.Timestamp("2024-01-02 16:00:00", tz="UTC") not in dates


def test_drop_incomplete_final_bar_intraday_vs_daily():
    df = _canonical_1h("2024-01-02 12:00:00", 3)
    dropped = MarketDataRepository._drop_incomplete_final_bar(df, "1h")
    assert len(dropped) == 2  # last bar removed

    # Daily is a no-op.
    kept = MarketDataRepository._drop_incomplete_final_bar(df, "1d")
    assert len(kept) == 3


# ---------------------------------------------------------------------------
# Task 6.4 / Property 6 - session-aware expectation
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    interval=st.sampled_from(["15m", "1h"]),
    end_offset=st.integers(min_value=0, max_value=14 * 24 * 60),  # minutes past anchor
    span_minutes=st.integers(min_value=1, max_value=10 * 24 * 60),
)
def test_property_session_aware_expectation(interval, end_offset, span_minutes):
    """Property 6: last completed session bar on/before end, None off-session, monotonic.

    Validates: Requirements 5.1
    """
    anchor = pd.Timestamp("2024-01-01 00:00:00")  # a Monday
    end = anchor + pd.Timedelta(minutes=end_offset)
    start = end - pd.Timedelta(minutes=span_minutes)

    result = _EXPECTED_LAST(interval, start, end)

    if result is not None:
        # Never beyond end, and never mid-bar (floored to the grid).
        # end is tz-naive by construction (anchor + Timedelta).`n        assert result <= end
        minutes = 15 if interval == "15m" else 60
        assert result == result.floor(f"{minutes}min")

    # Monotonic non-decreasing in end: pushing end forward never moves it back.
    later = _EXPECTED_LAST(interval, start, end + pd.Timedelta(minutes=30))
    if result is not None and later is not None:
        assert later >= result


# ---------------------------------------------------------------------------
# Task 6.5 / Property 4 - idempotent ingestion
# ---------------------------------------------------------------------------


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(n=st.integers(min_value=1, max_value=24))
def test_property_idempotent_ig_ingestion(n):
    """Property 4: upserting the same IG bars twice adds zero rows; overlap inserts none.

    Validates: Requirements 3.4, 5.2
    """
    store, conn_factory = make_conn_factory()
    repo = MarketDataRepository(conn_factory=conn_factory)
    df = _canonical_1h("2024-01-02 12:00:00", n)

    first = repo.upsert_bars(df, IG_EPIC, "1h", source="ig", adjusted=False)
    assert first == {"inserted": n, "updated": 0}
    assert len(store) == n

    second = repo.upsert_bars(df, IG_EPIC, "1h", source="ig", adjusted=False)
    assert second == {"inserted": 0, "updated": n}
    assert len(store) == n  # no duplicates on (ticker, interval, ts)

    # Overlapping window (shift by half) inserts only the genuinely new bars.
    overlap = _canonical_1h("2024-01-02 12:00:00", n + 3)
    third = repo.upsert_bars(overlap, IG_EPIC, "1h", source="ig", adjusted=False)
    assert third["inserted"] == 3
    assert len(store) == n + 3
