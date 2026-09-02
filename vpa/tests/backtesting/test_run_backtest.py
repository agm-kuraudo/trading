"""Light smoke test for the optional CLI runner (SP-317).

_Design: Optional Runner run_backtest.py_

Proves ``main()`` executes end-to-end against an in-memory dataset (no network,
no real CSV) and prints a counts-only summary. Reporting/metrics are out of
scope (SP-333); this test only asserts the count lines are present.
"""

import pandas as pd

from vpa.backtesting import run_backtest


def _make_feature_df() -> pd.DataFrame:
    """Build a tiny feature dataset with at least one signal-firing row.

    A composite_score of 20.0 (>= COMPOSITE_THRESHOLD of 15.0) fires
    STRONG_BULLISH on the first row, so the builder emits a signal that the
    engine can turn into a trade given enough forward price data.
    """
    return pd.DataFrame(
        {
            "date": ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-06"],
            "open": [100.0, 101.0, 102.0, 103.0, 104.0],
            "high": [101.0, 102.0, 103.0, 104.0, 105.0],
            "low": [99.0, 100.0, 101.0, 102.0, 103.0],
            "close": [100.5, 101.5, 102.5, 103.5, 104.5],
            "composite_score": [20.0, 0.0, 0.0, 0.0, 0.0],
            "acc_dist_flag": [0.0, 0.0, 0.0, 0.0, 0.0],
            "acc_dist_type": [0.0, 0.0, 0.0, 0.0, 0.0],
            "acc_dist_score": [0.0, 0.0, 0.0, 0.0, 0.0],
        }
    )


def test_main_runs_and_reports_counts(monkeypatch, capsys):
    """main() runs end-to-end and prints a counts-only summary."""
    monkeypatch.setattr(run_backtest.pd, "read_csv", lambda *_args, **_kwargs: _make_feature_df())

    run_backtest.main(ticker="SPY", hold_period=2)

    out = capsys.readouterr().out
    assert "Signals:" in out
    assert "Price points:" in out
    assert "Trades:" in out
    assert "Skipped:" in out
    assert "Skipped by reason:" in out
    # A firing signal on the first row with a 2-day hold has enough forward
    # data, so at least one trade is opened.
    assert "Trades: 1" in out
