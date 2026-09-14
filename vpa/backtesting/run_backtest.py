"""Optional CLI runner for the VPA backtesting engine (SP-317).

A thin command-line wrapper that loads a ticker's feature dataset CSV, builds
the Signal_Log and Price_Series, runs :class:`BacktestEngine`, and prints a
short trade-count summary only. Metrics, equity curves, P&L, and reporting are
out of scope (SP-333); this runner prints COUNTS ONLY.

No network / ``yfinance`` usage (Req 8.3): the runner only reads a local CSV.
"""

import argparse

import pandas as pd

from vpa.backtesting.config import BacktestConfig
from vpa.backtesting.data_export import export_ohlcv_for_backtest
from vpa.backtesting.engine import BacktestEngine
from vpa.backtesting.models import SkipReason
from vpa.backtesting.signal_log_builder import (
    build_price_series_from_dataset,
    build_signal_log_from_dataset,
)


def _dataset_path(ticker: str, output_dir: str) -> str:
    """Resolve the feature dataset CSV path following the SP-314 convention.

    SPY lives at ``{output_dir}/SPY_vpa_features.csv``; every other ticker is
    nested under ``{output_dir}/{ticker}/{ticker}_vpa_features.csv``.
    """
    if ticker == "SPY":
        return f"{output_dir}/SPY_vpa_features.csv"
    return f"{output_dir}/{ticker}/{ticker}_vpa_features.csv"


def main(
    ticker: str = "SPY",
    hold_period: int = 10,
    output_dir: str = "ml_validation_output",
    export_range: tuple | None = None,
) -> None:
    """Load a dataset, run the backtest, and print a trade-count summary only.

    Prints the number of signals, price points, and trades, plus a breakdown of
    skipped signals by :class:`SkipReason`. No metrics or P&L (SP-333).

    By default the runner reads an already-present local feature CSV — existing
    behaviour is unchanged. When ``export_range`` is provided as ``(start, end)``,
    the runner first materialises a **scoped** OHLCV file from the store on demand
    via :func:`export_ohlcv_for_backtest` (offline, no standing full-history copy;
    SP-349 Task 8.5, Req 5.4/3.5/3.6). This is opt-in; it does not fetch when the
    caller does not ask for it.
    """
    if export_range is not None:
        # Opt-in scoped export from the store (offline read; scoped to range).
        start, end = export_range
        export_ohlcv_for_backtest(ticker, "1d", start, end, out_dir=output_dir)

    csv_path = _dataset_path(ticker, output_dir)
    df = pd.read_csv(csv_path)

    signal_log = build_signal_log_from_dataset(df)
    price_series = build_price_series_from_dataset(df)

    result = BacktestEngine().run(signal_log, price_series, BacktestConfig(hold_period=hold_period))

    print("VPA Backtest Summary")
    print("====================")
    print(f"Ticker: {ticker}")
    print(f"Hold period: {hold_period}")
    print(f"Signals: {len(signal_log)}")
    print(f"Price points: {len(price_series)}")
    print(f"Trades: {len(result.trades)}")
    print(f"Skipped: {len(result.skipped)}")

    print("Skipped by reason:")
    for reason in SkipReason:
        count = sum(1 for s in result.skipped if s.reason == reason)
        print(f"  {reason.value}: {count}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VPA Backtesting Engine Runner")
    parser.add_argument("--ticker", type=str, default="SPY", help="Ticker symbol (default: SPY)")
    parser.add_argument("--hold-period", type=int, default=10, help="Hold period in trading days (default: 10)")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="ml_validation_output",
        help="Output directory (default: ml_validation_output)",
    )
    parser.add_argument(
        "--export-start",
        type=str,
        default=None,
        help="Optional: scoped-export range start. If set with --export-end, the "
        "runner materialises a scoped OHLCV CSV from the store before running "
        "(offline; no standing full-history file).",
    )
    parser.add_argument(
        "--export-end",
        type=str,
        default=None,
        help="Optional: scoped-export range end (used with --export-start).",
    )
    args = parser.parse_args()

    export_range = None
    if args.export_start and args.export_end:
        export_range = (args.export_start, args.export_end)

    main(
        ticker=args.ticker,
        hold_period=args.hold_period,
        output_dir=args.output_dir,
        export_range=export_range,
    )
