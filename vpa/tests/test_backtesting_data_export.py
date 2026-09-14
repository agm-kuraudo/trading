"""Smoke test for the backtesting scoped-export helper (SP-349, Task 8.5).

Verifies :func:`vpa.backtesting.data_export.export_ohlcv_for_backtest` writes a
**scoped** OHLCV CSV with no DB and no network, by injecting the same in-memory
psycopg2-like fake connection used by the repository integration tests. The
export path is offline (``get_ohlcv``) and scoped to the requested range only —
never a standing full-history copy (Req 5.4, 3.5, 3.6).
"""

from __future__ import annotations

import pandas as pd

from vpa.backtesting.data_export import export_ohlcv_for_backtest
from vpa.market_data.repository import MarketDataRepository
from vpa.tests.test_market_data_repository_integration import make_canonical_df, make_conn_factory


def test_export_helper_writes_scoped_csv_no_network(tmp_path):
    store, conn_factory = make_conn_factory()
    repo = MarketDataRepository(conn_factory=conn_factory)

    # Warm the store with five daily bars.
    df = make_canonical_df(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"])
    repo.upsert_bars(df, "SPY", "1d")

    # Export a scoped sub-range (excludes the first and last stored bars).
    out_path = export_ohlcv_for_backtest("SPY", "1d", "2024-01-03", "2024-01-05", out_dir=str(tmp_path), repo=repo)

    assert out_path.endswith("SPY_ohlcv.csv")
    read_back = pd.read_csv(out_path)
    assert list(read_back.columns) == ["Date", "Open", "High", "Low", "Close", "Volume"]
    # Scoped to the requested range only: three of the five bars.
    assert len(read_back) == 3


def test_export_helper_default_layout_nested_ticker(tmp_path):
    store, conn_factory = make_conn_factory()
    repo = MarketDataRepository(conn_factory=conn_factory)
    repo.upsert_bars(make_canonical_df(["2024-02-01", "2024-02-02"]), "AAPL", "1d")

    out_path = export_ohlcv_for_backtest(
        "AAPL", "1d", "2024-02-01", "2024-02-02", out_dir=str(tmp_path / "root"), repo=repo
    )

    assert out_path.endswith("AAPL_ohlcv.csv")
    assert pd.read_csv(out_path).shape[0] == 2
