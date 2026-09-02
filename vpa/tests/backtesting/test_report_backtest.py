"""Integration tests for SPY dataset loading in the report CLI (SP-333, Task 12.2).

These tests exercise ``report_backtest`` end to end against a small synthetic
SPY Feature_Dataset written to a temporary directory (via the ``tmp_path``
fixture). They confirm the pipeline loads the CSV through the reused SP-317
builders (``build_signal_log_from_dataset`` / ``build_price_series_from_dataset``)
and cover the two hard-abort paths:

* a missing dataset file lets ``FileNotFoundError`` propagate, so the run
  terminates without producing a report (Req 21.2);
* a dataset missing a required OHLC column lets the builder's ``KeyError``
  propagate unchanged, naming the missing column (Req 21.3).

The synthetic CSV includes the OHLC/date columns required by
``build_price_series_from_dataset`` plus the signal columns read by
``SignalConditionalAnalyzer.classify_signals`` (``composite_score``,
``acc_dist_flag``, ``acc_dist_type``, ``acc_dist_score``) so both builders and
the happy-path variation run succeed (Req 21.1).
"""

import pandas as pd
import pytest

from vpa.backtesting import reporting
from vpa.backtesting.report_backtest import load_spy_dataset, main

_DATASET_FILENAME = "SPY_vpa_features.csv"

# Column order matching the SP-317 Feature_Dataset shape: date + OHLC required by
# build_price_series_from_dataset, plus the signal columns classify_signals reads.
_COLUMNS = (
    "date",
    "open",
    "high",
    "low",
    "close",
    "composite_score",
    "acc_dist_flag",
    "acc_dist_type",
    "acc_dist_score",
)


def _synthetic_rows() -> list[dict[str, object]]:
    """Build a small valid SPY dataset with a mix of firing signals.

    Prices trend and wobble enough for direction-aware trades to open and close
    within the default hold periods. ``composite_score`` crosses the +/-15
    strong bands and ``acc_dist_*`` drive accumulation/distribution so several
    signal types fire, exercising every default variation on the happy path.
    """
    base = pd.Timestamp("2020-01-01")
    prices = [100.0, 101.0, 99.5, 102.0, 104.0, 103.0, 101.5, 105.0, 107.0, 106.0,
              108.0, 110.0, 109.0, 111.5, 113.0, 112.0, 114.0, 116.0, 115.0, 118.0]
    composite = [20.0, 5.0, -20.0, 18.0, 25.0, -3.0, -18.0, 22.0, 8.0, -22.0,
                 19.0, 24.0, -1.0, 17.0, 26.0, -4.0, 21.0, 23.0, -19.0, 27.0]
    acc_flag = [1, 0, 1, 1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 1, 0]
    acc_type = [1, 0, -1, 1, 0, -1, 0, 1, 1, 0, -1, 0, 1, 1, 0, -1, 0, 1, -1, 0]
    acc_score = [20.0, 2.0, 18.0, 22.0, 1.0, 16.0, 0.0, 25.0, 21.0, 3.0,
                 17.0, 0.5, 24.0, 23.0, 2.5, 19.0, 1.5, 26.0, 18.5, 0.0]

    rows: list[dict[str, object]] = []
    for i, price in enumerate(prices):
        date = (base + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
        rows.append(
            {
                "date": date,
                "open": price,
                "high": price + 1.0,
                "low": price - 1.0,
                "close": price + 0.5,
                "composite_score": composite[i],
                "acc_dist_flag": acc_flag[i],
                "acc_dist_type": acc_type[i],
                "acc_dist_score": acc_score[i],
            }
        )
    return rows


def _write_dataset(directory, rows: list[dict[str, object]], columns=_COLUMNS) -> None:
    """Write ``rows`` as ``SPY_vpa_features.csv`` under ``directory``."""
    df = pd.DataFrame(rows, columns=list(columns))
    df.to_csv(directory / _DATASET_FILENAME, index=False)


# ---------------------------------------------------------------------------
# Happy path - the pipeline loads the CSV via the builders and runs (Req 21.1)
# ---------------------------------------------------------------------------


def test_load_spy_dataset_returns_dataframe_with_rows(tmp_path) -> None:
    """load_spy_dataset reads the SPY CSV into a DataFrame with all rows (Req 21.1)."""
    rows = _synthetic_rows()
    _write_dataset(tmp_path, rows)

    df = load_spy_dataset(str(tmp_path))

    assert isinstance(df, pd.DataFrame)
    assert len(df) == len(rows)
    for column in _COLUMNS:
        assert column in df.columns


def test_main_loads_dataset_and_writes_report(tmp_path, capsys) -> None:
    """main loads via the builders, writes CSVs, and prints the report (Req 21.1)."""
    _write_dataset(tmp_path, _synthetic_rows())
    out_dir = tmp_path / "out"

    main(output_dir=str(tmp_path), out_dir=str(out_dir))

    # Per-trade + equity CSVs are written for the Baseline variation.
    assert (out_dir / "baseline_trades.csv").exists()
    assert (out_dir / "baseline_equity.csv").exists()

    # The stdout report includes the comparison table and the tradeability verdict.
    captured = capsys.readouterr().out
    assert "Buy_And_Hold_SPY" in captured
    assert "Best Strategy_Variation by Sharpe_Ratio" in captured


# ---------------------------------------------------------------------------
# Missing file - FileNotFoundError propagates, no report produced (Req 21.2)
# ---------------------------------------------------------------------------


def test_load_spy_dataset_missing_file_raises_filenotfound(tmp_path) -> None:
    """A missing SPY dataset lets FileNotFoundError propagate (Req 21.2)."""
    with pytest.raises(FileNotFoundError):
        load_spy_dataset(str(tmp_path))


def test_main_missing_file_raises_filenotfound(tmp_path) -> None:
    """main terminates via FileNotFoundError when the dataset is absent (Req 21.2)."""
    with pytest.raises(FileNotFoundError):
        main(output_dir=str(tmp_path), out_dir=str(tmp_path / "out"))


# ---------------------------------------------------------------------------
# Missing OHLC column - builder KeyError propagates unchanged (Req 21.3)
# ---------------------------------------------------------------------------


def test_main_missing_ohlc_column_raises_keyerror_naming_column(tmp_path) -> None:
    """A dataset missing 'high' raises the builder's KeyError, naming it (Req 21.3).

    The CSV still has date/open/low/close plus the signal columns, so pandas
    read_csv succeeds and the KeyError comes from build_price_series_from_dataset,
    not from pandas.
    """
    columns_without_high = tuple(column for column in _COLUMNS if column != "high")
    _write_dataset(tmp_path, _synthetic_rows(), columns=columns_without_high)

    with pytest.raises(KeyError, match="high"):
        main(output_dir=str(tmp_path), out_dir=str(tmp_path / "out"))


# ---------------------------------------------------------------------------
# End-to-end - main over a synthetic SPY dataset writes CSVs and prints the
# full report: per-variation summaries, the comparison table (Baseline /
# Contrarian_Only / All_Signals plus buy-and-hold), and the tradeability
# conclusion net of costs and direction-aware P&L (Task 12.3;
# Req 1.1, 19.1, 19.4, 20.3, 20.5)
# ---------------------------------------------------------------------------

# Variations that Task 12.3 explicitly requires to appear in the report. Their
# CSV slugs are confirmed via reporting.variation_filename so the assertions
# stay robust to the module's own slugification rules (Req 19.1, 19.4).
_REQUIRED_VARIATIONS = ("Baseline", "Contrarian_Only", "All_Signals")


def test_main_end_to_end_writes_csvs_and_prints_full_report(tmp_path, capsys) -> None:
    """main runs end to end over a synthetic SPY CSV (Req 1.1, 19.1, 19.4, 20.3, 20.5).

    Writes the synthetic dataset, runs the whole pipeline into a separate output
    directory, and asserts that (a) the per-trade and equity CSVs are written for
    each required variation, (b) the comparison table lists Baseline,
    Contrarian_Only, All_Signals and the buy-and-hold SPY row, and (c) the
    tradeability conclusion is printed with the cost / direction-aware P&L note.
    """
    _write_dataset(tmp_path, _synthetic_rows())
    out_dir = tmp_path / "out"

    main(output_dir=str(tmp_path), out_dir=str(out_dir))

    # (a) Per-trade + equity CSVs exist for each required variation. Slug names
    # are resolved via reporting.variation_filename to stay in lockstep with the
    # renderer rather than hard-coding the slug rules.
    for variation_name in _REQUIRED_VARIATIONS:
        trades_name = reporting.variation_filename(variation_name, "trades")
        equity_name = reporting.variation_filename(variation_name, "equity")
        assert (out_dir / trades_name).exists(), f"missing {trades_name}"
        assert (out_dir / equity_name).exists(), f"missing {equity_name}"

    # Sanity-check the resolved slugs match the documented names (Req 19.1).
    assert reporting.variation_filename("Baseline", "trades") == "baseline_trades.csv"
    assert reporting.variation_filename("Baseline", "equity") == "baseline_equity.csv"
    assert reporting.variation_filename("Contrarian_Only", "trades") == "contrarian_only_trades.csv"
    assert reporting.variation_filename("Contrarian_Only", "equity") == "contrarian_only_equity.csv"
    assert reporting.variation_filename("All_Signals", "trades") == "all_signals_trades.csv"
    assert reporting.variation_filename("All_Signals", "equity") == "all_signals_equity.csv"

    captured = capsys.readouterr().out

    # (b) The comparison table names each required variation plus buy-and-hold.
    for variation_name in _REQUIRED_VARIATIONS:
        assert variation_name in captured
    assert "Buy_And_Hold_SPY" in captured

    # (c) The tradeability conclusion is printed net of costs / direction-aware P&L.
    assert "Best Strategy_Variation by Sharpe_Ratio" in captured
    assert "Results are net of the round-trip cost and use direction-aware P&L." in captured
