"""yfinance intraday period regression + source-isolation tests (SP-379, Tasks 8.2, 8.3).

- Task 8.2: assert the intraday ``1h`` backfill requests ``period="730d"`` (not
  ``"max"``, which SP-342 proved returns EMPTY for ``1h``), while the daily path is
  unchanged (still ``period="max"``). Driven by patching ``yf.download`` to record
  its ``period`` kwarg; no network, no DB.
- Task 8.3 / Property 8 (source isolation): IG rows (``source="ig"``, ticker = epic)
  and yfinance baseline rows (``source="yfinance"``, ticker = ``SPY``) never overwrite
  each other in the store.
"""

from __future__ import annotations

import pandas as pd
import pytest

import scripts.backfill_market_data as backfill_mod
from vpa.market_data.repository import IG_EPIC, MarketDataRepository
from vpa.tests.test_market_data_repository_integration import make_conn_factory

pytestmark = pytest.mark.usefixtures("no_ig_network")


def _raw_yf_single(ticker="SPY", n=3):
    """A single-ticker yfinance-style MultiIndex daily/hourly frame."""
    dates = pd.date_range("2024-01-02", periods=n, freq="D")
    data = {
        ("Open", ticker): [100.0 + i for i in range(n)],
        ("High", ticker): [110.0 + i for i in range(n)],
        ("Low", ticker): [90.0 + i for i in range(n)],
        ("Close", ticker): [105.0 + i for i in range(n)],
        ("Volume", ticker): [1_000_000 + i for i in range(n)],
    }
    df = pd.DataFrame(data, index=dates)
    df.index.name = "Date"
    df.columns = pd.MultiIndex.from_tuples(df.columns)
    return df


# ---------------------------------------------------------------------------
# Task 8.2 - intraday period regression
# ---------------------------------------------------------------------------


@pytest.fixture
def recording_backfill(monkeypatch):
    """Patch yf.download to record its period kwarg, and bind a fake repo."""
    store, conn_factory = make_conn_factory()
    recorded = {}

    def fake_download(ticker, period=None, **kwargs):
        recorded["period"] = period
        return _raw_yf_single(ticker)

    def repo_factory(*args, **kwargs):
        return MarketDataRepository(conn_factory=conn_factory)

    monkeypatch.setattr(backfill_mod.yf, "download", fake_download)
    monkeypatch.setattr(backfill_mod, "MarketDataRepository", repo_factory)
    return recorded


def test_intraday_1h_requests_730d(recording_backfill):
    backfill_mod.backfill("SPY", "1h")
    assert recording_backfill["period"] == "730d"


def test_daily_path_still_requests_max(recording_backfill):
    backfill_mod.backfill("SPY", "1d")
    assert recording_backfill["period"] == "max"


# ---------------------------------------------------------------------------
# Task 8.3 / Property 8 - source isolation
# ---------------------------------------------------------------------------


def _canonical(dates):
    n = len(dates)
    return pd.DataFrame(
        {
            "Date": [pd.Timestamp(d, tz="UTC") for d in dates],
            "Open": [100.0 + i for i in range(n)],
            "High": [110.0 + i for i in range(n)],
            "Low": [90.0 + i for i in range(n)],
            "Close": [105.0 + i for i in range(n)],
            "Volume": [1_000 + i for i in range(n)],
        }
    )


def test_source_isolation_ig_and_yfinance_coexist():
    """Property 8: IG (epic) and yfinance (SPY) rows never overwrite each other.

    Validates: Requirements 2.5, 4.2
    """
    store, conn_factory = make_conn_factory()
    repo = MarketDataRepository(conn_factory=conn_factory)

    # Same timestamps and interval, but different tickers/sources.
    dates = ["2024-01-02 14:00:00", "2024-01-02 15:00:00"]
    ig_df = _canonical(dates)
    yf_df = _canonical(dates)

    ig_result = repo.upsert_bars(ig_df, IG_EPIC, "1h", source="ig", adjusted=False)
    yf_result = repo.upsert_bars(yf_df, "SPY", "1h", source="yfinance")

    # Both are fresh inserts: the yfinance upsert did NOT overwrite the IG rows
    # (distinct (ticker, interval, ts) keys because the ticker differs).
    assert ig_result == {"inserted": 2, "updated": 0}
    assert yf_result == {"inserted": 2, "updated": 0}
    assert len(store) == 4  # 2 IG + 2 yfinance, no collision

    # Each source reads back independently.
    ig_back = repo.get_ohlcv(IG_EPIC, "1h", "2024-01-02", "2024-01-03")
    yf_back = repo.get_ohlcv("SPY", "1h", "2024-01-02", "2024-01-03")
    assert len(ig_back) == 2
    assert len(yf_back) == 2
