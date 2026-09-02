"""CLI entry point for the VPA strategy backtest report (SP-333, Req 21).

This is the ONLY module in the backtesting package that touches the filesystem:
it reads the SPY Feature_Dataset CSV and writes the per-trade and equity CSVs.
Everything else (``pnl``, ``equity_curve``, ``metrics``, ``variations``,
``reporting``) stays pure, so this module simply orchestrates the load, the
variation runs, and the persistence/printing of results.

No network / ``yfinance`` usage: the loader only reads a local CSV. A missing
SPY dataset lets ``FileNotFoundError`` propagate so the run terminates without a
report (Req 21.2); a dataset missing a required date/OHLC column lets the
builder's ``KeyError`` propagate unchanged (Req 21.3).
"""

import csv
import os

import pandas as pd

from vpa.backtesting import metrics, reporting
from vpa.backtesting.metrics import DEFAULT_RISK_FREE_RATE
from vpa.backtesting.signal_log_builder import (
    build_price_series_from_dataset,
    build_signal_log_from_dataset,
)
from vpa.backtesting.variations import build_default_variations, run_variations


def load_spy_dataset(output_dir: str = "ml_validation_output") -> pd.DataFrame:
    """Read the SPY Feature_Dataset CSV into a DataFrame (Req 21.1, 21.2).

    Reads ``{output_dir}/SPY_vpa_features.csv`` following the SP-314 convention
    (SPY lives directly under ``output_dir``). If the file is missing, the
    ``FileNotFoundError`` raised by pandas is allowed to propagate so the caller
    terminates without producing a report (Req 21.2). Builder ``KeyError``s for
    missing date/OHLC columns are raised later, when the builders are called in
    :func:`main`, and propagate unchanged (Req 21.3).
    """
    csv_path = f"{output_dir}/SPY_vpa_features.csv"
    return pd.read_csv(csv_path)


def _write_csv(out_dir: str, filename: str, rows: list[list[str]]) -> None:
    """Write ``rows`` to ``{out_dir}/{filename}`` using the csv module.

    The output directory is created if it does not already exist. This is the
    single low-level filesystem-writing primitive used for both the per-trade
    and equity CSVs.
    """
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, filename)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)


def main(
    output_dir: str = "ml_validation_output",
    out_dir: str = "ml_validation_output",
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> None:
    """Run the full VPA strategy backtest report end to end (Req 1.2, 19, 20, 21).

    Loads the SPY Feature_Dataset (Req 21.1), builds the Signal_Log and
    Price_Series via the reused SP-317 builders, runs the full default catalogue
    of variations with per-variation error isolation, writes each successful
    run's per-trade and equity CSVs into ``out_dir`` (Req 19.1), prints each
    variation's performance summary, prints the strategy-vs-buy-and-hold
    comparison table (Req 19.4), and prints the tradeability conclusion
    (Req 20.1, 20.3, 20.4).

    A missing SPY dataset lets ``FileNotFoundError`` propagate (Req 21.2); a
    dataset missing a required date/OHLC column lets the builder's ``KeyError``
    propagate unchanged (Req 21.3).
    """
    df = load_spy_dataset(output_dir)

    signal_log = build_signal_log_from_dataset(df)
    price_series = build_price_series_from_dataset(df)

    variations = build_default_variations()
    runs, failures = run_variations(variations, signal_log, price_series)

    for run in runs:
        name = run.variation.name
        _write_csv(out_dir, reporting.variation_filename(name, "trades"), reporting.per_trade_rows(run))
        _write_csv(out_dir, reporting.variation_filename(name, "equity"), reporting.equity_rows(run.equity_curve))
        print(reporting.format_summary(run))
        print()

    buy_and_hold = metrics.buy_and_hold_return(price_series)
    bnh_annualised = metrics.annualised_return(buy_and_hold, price_series)

    print(reporting.format_comparison_table(runs, failures, buy_and_hold, bnh_annualised))
    print()
    print(reporting.format_tradeability_conclusion(runs, buy_and_hold))


if __name__ == "__main__":
    main()
