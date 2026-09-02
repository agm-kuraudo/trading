# Implementation Plan: VPA Strategy Backtest Report (SP-333)

## Overview

This plan turns the SP-317 `BacktestEngine` per-trade log into a full strategy
performance report through strictly additive, test-first steps. The engine,
`BacktestConfig`, `FixedHoldExitStrategy`, the `ExitStrategy` Protocol,
`PositionMode`, and the dataset builders are reused unchanged. New behaviour is
delivered via a `StopLossExitStrategy` (added to `exit_strategy.py`) and new pure
modules `pnl.py`, `equity_curve.py`, `metrics.py`, `variations.py`, and
`reporting.py`, with `report_backtest.py` as the only filesystem-touching module.

Each task builds on prior ones, ending with the CLI that runs Baseline,
Contrarian_Only, All_Signals (plus the Variable_Hold, Stop_Loss, and
Signal_Stacking variations), compares against buy-and-hold SPY, and prints the
tradeability conclusion. Property tests use Hypothesis (`@settings(max_examples=100)`)
tagged `Feature: vpa-strategy-backtest-report, Property N`, matching the existing
`vpa/tests/backtesting/` pytest+Hypothesis conventions. Engine, `exit_strategy`,
`pnl`, `equity_curve`, and `metrics` stay pure (no network/filesystem/yfinance).

## Tasks

- [x] 1. Set up new data records
  - [x] 1.1 Add new data records to `vpa/backtesting/models.py`
    - Add frozen dataclasses `PricedTrade` (trade, direction, strategy_return), `TradeExclusion` (trade, reason), `EquityPoint` (date, equity), and `MetricsResult` (all metric fields plus `number_of_trades: int` and `notes: tuple[str, ...] = ()`)
    - Keep all records frozen dataclasses matching the existing SP-317 convention; do not redefine reused SP-317 types
    - Import `SignalDirection` from `vpa.ml_validation.signal_analysis` for the `PricedTrade.direction` field
    - _Requirements: 8.1, 8.5, 8.6, 9.1, 15.1_

- [x] 2. Implement `StopLossExitStrategy` in `vpa/backtesting/exit_strategy.py`
  - [x] 2.1 Implement the path-based stop-loss exit strategy
    - Add a frozen dataclass `StopLossExitStrategy` with fields `threshold: float`, `direction: SignalDirection = SignalDirection.UP`, and a `FixedHoldExitStrategy` fallback field
    - Implement `resolve_exit(entry_index, price_series, hold_period) -> ExitResult` conforming to the existing `ExitStrategy` Protocol; keep it pure (reads only `price_series`)
    - Compute stop price `entry_price * (1 + threshold)`; scan forward bars ascending from `entry_index + 1` to `min(entry_index + hold_period, last_index)` inclusive so a same-day breach wins the tie
    - Long breach when `low <= stop` (exit at `open` if `open <= stop`, else `stop`); short breach when `high >= stop` (exit at `open` if `open >= stop`, else `stop`); no breach delegates to the fixed-hold fallback verbatim
    - Return raw prices and let the engine validate via `_is_valid_price`
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8_
  - [x] 2.2 Write property test for the stop price formula
    - **Property 1: Stop price formula**
    - **Validates: Requirements 7.2**
    - In `vpa/tests/backtesting/test_stop_loss_exit_strategy.py`, assert stop price equals `entry_price * (1 + threshold)` and is strictly less than entry price for positive prices and negative thresholds
  - [x] 2.3 Write property test for first-breach resolution
    - **Property 2: Stop breach resolves at the first breaching bar**
    - **Validates: Requirements 7.3, 7.4, 7.5, 7.6**
    - Generate OHLC paths with `low <= open,close <= high` (including gapped opens) for both long and short; assert exit resolves on the earliest breaching bar at stop-or-open
  - [x] 2.4 Write property test for the no-breach fallback
    - **Property 3: No breach falls back to the fixed-hold exit**
    - **Validates: Requirements 7.7, 7.8**
    - Assert the returned `ExitResult` equals `FixedHoldExitStrategy.resolve_exit(...)` for the same entry index and hold period when the stop is never breached
  - [x] 2.5 Write example tests for gap-through, same-day tie, and no-breach cases
    - Cover open-gapped-past-stop exit pricing, the stop-vs-hold same-day tie resolving as a stop breach, and the `INSUFFICIENT_FUTURE_DATA_EXIT` fallback near the series end
    - _Requirements: 7.5, 7.6, 7.7, 7.8_

- [x] 3. Implement direction-aware P&L in `vpa/backtesting/pnl.py`
  - [x] 3.1 Implement `strategy_return`, `direction_for`, and `price_trades`
    - `direction_for(signal_type)` looks up `SIGNAL_DIRECTIONS`, returning `None` when absent
    - `strategy_return(trade, round_trip_cost)`: UP returns `trade.return_pct`; DOWN returns `(entry_price / exit_price) - 1 - round_trip_cost` from raw prices with the cost applied exactly once
    - `price_trades(trades, round_trip_cost)` maps each trade to a `PricedTrade` and collects `TradeExclusion` for `exit_price == 0` (`"exit_price_zero"`) and unknown direction (`"unknown_direction"`) without raising
    - Keep the module pure (no network/filesystem/yfinance)
    - _Requirements: 1.3, 2.1, 8.1, 8.2, 8.4, 8.5, 8.6_
  - [x] 3.2 Write property test for direction-aware P&L
    - **Property 4: Direction-aware P&L**
    - **Validates: Requirements 8.1, 8.2, 8.3**
    - In `vpa/tests/backtesting/test_pnl.py`, assert UP returns equal `return_pct` and DOWN returns equal the raw short-equivalent formula; include the falling-price > 0 before-cost check
  - [x] 3.3 Write property test for cost-applied-once on DOWN trades
    - **Property 5: Round-trip cost applied exactly once for DOWN trades**
    - **Validates: Requirements 8.4**
    - Assert DOWN `strategy_return` equals `(entry/exit) - 1` minus the cost exactly once, never derived from `return_pct`
  - [x] 3.4 Write example tests for P&L exclusions
    - Cover `exit_price == 0` exclusion and unknown-direction exclusion, asserting the correct `TradeExclusion.reason` and no raise
    - _Requirements: 8.5, 8.6_

- [x] 4. Implement equity-curve construction in `vpa/backtesting/equity_curve.py`
  - [x] 4.1 Implement `build_equity_curve`
    - Produce one `EquityPoint` per Price_Series date, ascending, starting at capital 1.0 on the first date
    - Group closing trades by `exit_date` into `dict[str, list[float]]`; per-date multiplier is `math.prod(1 + r for r in returns_that_day)` (order-independent); carry capital forward on days with no close
    - Empty Price_Series yields an empty curve; keep the module pure
    - _Requirements: 2.1, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 15.7_
  - [x] 4.2 Write property test for equity-curve length and initial value
    - **Property 6: Equity-curve length and initial value invariant**
    - **Validates: Requirements 9.1, 9.2, 9.6**
    - In `vpa/tests/backtesting/test_equity_curve.py`, assert one point per date ascending and first point equals 1.0
  - [x] 4.3 Write property test for order-independent same-day compounding
    - **Property 7: Same-day compounding is order-independent**
    - **Validates: Requirements 9.3, 9.4, 9.5**
    - Generate trade sets with clustered same-day `exit_date`; assert the post-date capital is invariant under permutation of the same-day group and no-close days carry forward
  - [x] 4.4 Write example test for the empty Price_Series case
    - Assert an empty Price_Series produces an empty equity curve without error
    - _Requirements: 15.7_

- [x] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Implement the metrics helper functions in `vpa/backtesting/metrics.py`
  - [x] 6.1 Implement return/annualisation helpers
    - Add module constants `TRADING_DAYS_PER_YEAR = 252` and `DEFAULT_RISK_FREE_RATE = 0.04`
    - Implement `total_return`, `buy_and_hold_return`, `annualised_return`, `trades_per_year` with the guards: `< 2` points -> 0.0; zero initial equity / first close -> 0.0 with a note; `years == 0` -> 0.0; `total_return <= -1` -> `-1.0` without evaluating the negative-base power
    - Keep the module pure (no network/filesystem/yfinance)
    - _Requirements: 2.1, 10.1, 10.2, 10.3, 10.4, 10.5, 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_
  - [x] 6.2 Implement `daily_returns`, `sharpe_ratio`, and `max_drawdown`
    - `daily_returns` computes the fractional day-over-day change of the equity curve (one per consecutive pair)
    - `sharpe_ratio`: `daily_rf = risk_free_rate / 252`, sample std via `statistics.stdev` (N-1), `((mean - daily_rf) / std) * sqrt(252)`; 0.0 when `std == 0` or fewer than two daily returns
    - `max_drawdown`: single forward pass running peak, `min(equity_t / peak_t - 1)` clamped to `[-1.0, 0.0]`; 0.0 for empty curve or zero running peak (with a note)
    - _Requirements: 12.3, 12.4, 12.5, 12.6, 12.7, 12.8, 13.1, 13.2, 13.3, 13.4, 13.5_
  - [x] 6.3 Implement per-trade quality helpers
    - Implement `win_rate`, `profit_factor`, `average_win`, `average_loss`, `expectancy`, `time_in_market`
    - Zero-return trades count in the denominator but as neither win nor loss; profit factor -> `float("inf")` when wins but no losses, 0.0 when neither; time-in-market treats a position open on `[entry_date, exit_date)` and counts each covered Price_Series date once
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7, 15.2, 15.3, 15.4, 15.5_
  - [x] 6.4 Write property test for total return and buy-and-hold formulas
    - **Property 8: Total return and buy-and-hold formulas**
    - **Validates: Requirements 10.1, 10.2, 10.3**
    - In `vpa/tests/backtesting/test_metrics.py`, assert the two formulas hold for curves/series with >= 2 points using `math.isclose(abs_tol=1e-9)`
  - [x] 6.5 Write property test for annualisation formula and guards
    - **Property 9: Annualisation formula and guards**
    - **Validates: Requirements 11.2, 11.3, 11.4**
    - Assert `annualised_return` and `trades_per_year` match the reference computation with `years = (distinct_dates - 1) / 252`
  - [x] 6.6 Write property test for the Sharpe ratio
    - **Property 10: Sharpe ratio equals the reference computation**
    - **Validates: Requirements 12.3, 12.4, 12.5, 12.6**
    - Assert Sharpe equals `((mean_daily - rf/252) / sample_std) * sqrt(252)` computed independently via `statistics`
  - [x] 6.7 Write property test for max drawdown
    - **Property 11: Max drawdown is the deepest peak-relative decline and lies in [-1, 0]**
    - **Validates: Requirements 13.1, 13.2, 13.3**
    - Assert drawdown equals the reference running-max computation, lies in `[-1.0, 0.0]`, and is 0.0 for a never-declining curve
  - [x] 6.8 Write property test for win rate and expectancy
    - **Property 12: Win rate lies in [0, 1] and expectancy is the mean strategy return**
    - **Validates: Requirements 14.1, 14.2, 14.5**
  - [x] 6.9 Write property test for profit factor
    - **Property 13: Profit factor equals wins over absolute losses**
    - **Validates: Requirements 14.4**
  - [x] 6.10 Write property test for time in market
    - **Property 14: Time in market counts each open day once and lies in [0, 1]**
    - **Validates: Requirements 14.6, 14.7**
    - Include overlapping STACKING-style trades to confirm each open day counts once

- [x] 7. Implement the `calculate` orchestrator in `vpa/backtesting/metrics.py`
  - [x] 7.1 Wire the helpers into `calculate`
    - Implement `calculate(priced_trades, equity_curve, price_series, risk_free_rate=DEFAULT_RISK_FREE_RATE) -> MetricsResult`, combining all helpers into a single `MetricsResult`
    - Return the no-trades `MetricsResult` (all metrics 0.0, `number_of_trades = 0`) for zero trades or empty Price_Series without raising; still compute `buy_and_hold_return` when the series has >= 2 points; surface zero-denominator/exclusion notes on `MetricsResult.notes`
    - Reject a missing/empty required in-memory input with an error naming it (Req 2.4)
    - _Requirements: 2.3, 2.4, 15.1, 15.6, 15.7_
  - [x] 7.2 Write property test for metrics-pipeline determinism
    - **Property 17: Determinism of the metrics pipeline**
    - **Validates: Requirements 2.2, 2.3**
    - Run `calculate` twice on the same inputs; assert identical priced trades, equity curve, and `MetricsResult`
  - [x] 7.3 Write example tests for all Req 15 metric edge cases
    - Cover zero trades, all-wins (`inf` profit factor), no-wins-no-losses (0.0 profit factor), a single trade, and an empty Price_Series
    - _Requirements: 15.1, 15.2, 15.3, 15.6, 15.7_

- [x] 8. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Implement strategy configuration and runner in `vpa/backtesting/variations.py`
  - [x] 9.1 Implement `StrategyVariation`, run records, and `to_config`
    - Add the `SignalFilter` alias, the frozen `StrategyVariation` dataclass with `to_config()` building a `BacktestConfig` from its fields, and the `VariationRun` / `VariationFailure` records
    - Keep the module pure; do not modify, subclass, or monkeypatch `BacktestEngine`
    - _Requirements: 1.4, 2.1_
  - [x] 9.2 Implement `validate_hold_period` and `run_variation`
    - `validate_hold_period` rejects non-int or `< 1` with a descriptive `ValueError` before the engine is invoked
    - `run_variation` applies `variation.signal_filter`, calls `BacktestEngine.run` exactly once, then threads results through `pnl.price_trades`, `equity_curve.build_equity_curve`, and `metrics.calculate` into a `VariationRun`
    - _Requirements: 1.1, 1.2, 1.3, 5.1, 6.2, 6.3_
  - [x] 9.3 Implement `run_variations` with per-variation error isolation
    - Wrap each `run_variation`; on engine error record a `VariationFailure(name, error)`, retain completed runs, and continue the remaining variations
    - _Requirements: 1.5, 6.4_
  - [x] 9.4 Implement `build_default_variations`
    - Build Baseline (no filter, hold 10, `FixedHoldExitStrategy`, NO_OVERLAP), Contrarian_Only (DISTRIBUTION/STRONG_BEARISH), All_Signals (types in `SIGNAL_DIRECTIONS`, unknown excluded with indication), Variable_Hold {5,10,15,20}, Stop_Loss {-0.02,-0.03} via `StopLossExitStrategy`, and Signal_Stacking (`PositionMode.STACKING`)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 5.1, 5.2, 5.3, 5.4, 6.1, 7.9, 7.10, 7.11, 19.4_
  - [x] 9.5 Write example tests for variation filters and single-failure isolation
    - Assert each filter selects the correct signal types, `to_config` maps fields correctly, `run_variation` calls the engine once, and one failing variation does not stop the others; cover `validate_hold_period` rejection and All_Signals unknown-type exclusion
    - _Requirements: 1.1, 1.4, 1.5, 3.1, 4.1, 5.1, 5.3, 6.3, 6.4, 7.10, 7.11_

- [x] 10. Implement rendering in `vpa/backtesting/reporting.py`
  - [x] 10.1 Implement CSV row builders and filename helper
    - Add `PER_TRADE_HEADER` and `EQUITY_HEADER` constants; `per_trade_rows(run)` emits header + one row per `PricedTrade` ordered by `(entry_date, exit_date)` (header-only for zero trades); `equity_rows(equity_curve)` emits header + one date-ascending row per date (header-only for empty span); `variation_filename(name, kind)` returns a unique filesystem-safe name
    - Keep rendering pure (no filesystem)
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 17.1, 17.2, 17.3, 17.4_
  - [x] 10.2 Implement summary, comparison table, best-selection, and verdict
    - `format_summary(run)` prints variation name, trade count (0 when empty), and every metric on its own `name: value` line
    - `format_comparison_table(runs, failures, buy_and_hold, bnh_annualised)` prints one row per completed variation plus a buy-and-hold SPY row with Total_Return/Annualised_Return/Sharpe_Ratio/Max_Drawdown, naming failed variations
    - `select_best(runs)` picks highest Sharpe, tie-break highest Total_Return then ascending name; `format_tradeability_conclusion(runs, buy_and_hold)` names the best variation and states whether its Total_Return is strictly greater than buy-and-hold, else states edges are not tradeable after costs
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 19.1, 19.2, 19.4, 19.5, 20.1, 20.2, 20.3, 20.4, 20.5_
  - [x] 10.3 Write property test for per-trade CSV ordering
    - **Property 15: Per-trade CSV ordering**
    - **Validates: Requirements 16.2, 16.3**
    - In `vpa/tests/backtesting/test_reporting.py`, assert rows are ordered by `(entry_date, exit_date)` and the seven columns appear in the exact order
  - [x] 10.4 Write property test for best-variation selection
    - **Property 16: Best-variation selection and tie-break ordering**
    - **Validates: Requirements 20.1, 20.2**
    - Assert `select_best` picks highest Sharpe with the documented tie-breaks
  - [x] 10.5 Write example tests for CSV, summary, comparison, and verdict
    - Assert header-only CSVs for zero trades / empty spans, unique filenames, stdout summary content (via injected writer/`capsys`), a comparison row per completed variation plus buy-and-hold, a named/omitted failed variation, and the strictly-greater-than wording including the tie case
    - _Requirements: 16.1, 16.4, 17.1, 17.4, 18.1, 18.3, 18.4, 19.1, 19.3, 19.5, 20.3, 20.4_

- [x] 11. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Implement the CLI in `vpa/backtesting/report_backtest.py`
  - [x] 12.1 Implement `load_spy_dataset` and `main`
    - `load_spy_dataset(output_dir="ml_validation_output")` reads `SPY_vpa_features.csv`, letting `FileNotFoundError` propagate (terminate without a report) and builder `KeyError` propagate unchanged
    - `main(...)` loads SPY, builds the Signal_Log via `build_signal_log_from_dataset` and Price_Series via `build_price_series_from_dataset`, runs all default variations, writes per-trade + equity CSVs, and prints each summary, the comparison table (>= Baseline, Contrarian_Only, All_Signals plus buy-and-hold), and the tradeability conclusion
    - This is the only module that touches the filesystem
    - _Requirements: 1.2, 19.1, 19.4, 20.1, 20.3, 20.4, 21.1, 21.2, 21.3_
  - [x] 12.2 Write integration tests for dataset loading
    - In `vpa/tests/backtesting/test_report_backtest.py`, write a temporary SPY CSV and assert the pipeline loads it via the builders; a missing file raises `FileNotFoundError` (no report); a CSV missing an OHLC column raises the builder's `KeyError` unchanged
    - _Requirements: 21.1, 21.2, 21.3_
  - [x] 12.3 Write an end-to-end integration test over a synthetic dataset
    - Run `main` over a small synthetic SPY CSV (via a temp dir); assert per-trade and equity CSVs are written, the comparison table includes Baseline/Contrarian_Only/All_Signals plus buy-and-hold, and the tradeability conclusion is printed net of costs and direction-aware P&L
    - _Requirements: 1.1, 19.1, 19.4, 20.3, 20.5_

- [x] 13. Final checkpoint - Run ruff and the full pytest suite
  - Run `ruff check` (line-length 120, double quotes, target-version py311) over the new modules and tests and fix any findings
  - Run the full `pytest` suite (use `pytest --no-header -q`, single-run, not watch mode) and ensure all tests pass; ask the user if questions arise
  - Run the report end-to-end against the real SPY dataset: execute the `report_backtest.py` CLI on `ml_validation_output/SPY_vpa_features.csv`, confirm the per-trade and equity CSVs are written, and review the stdout output for sanity — the per-variation performance summaries, the strategy-vs-buy-and-hold comparison table, and the tradeability conclusion (metrics in expected ranges, buy-and-hold row present, a clear verdict)
    - _Requirements: 18, 19, 20, 21_

## Notes

- All test sub-tasks are required; the full property, unit, and integration test suite must be implemented alongside the core tasks.
- Property tests use Hypothesis `@settings(max_examples=100)` (minimum 100 examples) and are tagged `# Feature: vpa-strategy-backtest-report, Property N`.
- Engine, `exit_strategy`, `pnl`, `equity_curve`, and `metrics` stay pure: no network, filesystem, or `yfinance` imports. Only `report_backtest.py` touches the filesystem.
- Each task references specific requirement sub-clauses for traceability; checkpoints ensure incremental validation.
- Tests live under `vpa/tests/backtesting/` and reuse the SP-317 `_make_price_series` / sequential ISO-date generator patterns.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "3.1", "6.1"] },
    { "id": 2, "tasks": ["2.2", "3.2", "4.1", "6.2"] },
    { "id": 3, "tasks": ["2.3", "3.3", "4.2", "6.3"] },
    { "id": 4, "tasks": ["2.4", "3.4", "4.3", "6.4", "7.1"] },
    { "id": 5, "tasks": ["2.5", "4.4", "6.5", "7.2", "9.1"] },
    { "id": 6, "tasks": ["6.6", "7.3", "9.2"] },
    { "id": 7, "tasks": ["6.7", "9.3", "10.1"] },
    { "id": 8, "tasks": ["6.8", "9.4", "12.1"] },
    { "id": 9, "tasks": ["6.9", "9.5", "10.2"] },
    { "id": 10, "tasks": ["6.10", "10.3", "12.2"] },
    { "id": 11, "tasks": ["10.4"] },
    { "id": 12, "tasks": ["10.5", "12.3"] }
  ]
}
```
