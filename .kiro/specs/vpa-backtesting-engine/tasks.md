# Implementation Plan: VPA Backtesting Engine

## Overview

Implement the core VPA backtesting engine (SP-317) and its prerequisite dataset enrichment (SP-335). SP-335 comes first because it blocks SP-317: it extends the SP-314 feature datasets so each row carries raw `open`/`high`/`low` alongside `close`, and SP-317 consumes that enriched OHLC series. The engine lives in a new `vpa/backtesting/` package operating on in-memory inputs only (no network / `yfinance` dependency), simulating trades entered at the next-day close and exited after a fixed hold period, and producing a per-trade log plus an audit list of skipped signals. Implementation is Python 3.11 with pandas, Hypothesis for property tests, and ruff (line-length 120, double quotes). All work runs under `.venv` with pytest.

## Tasks

- [x] 1. [SP-335] Write the dataset-enrichment test first
  - Create `vpa/tests/ml_validation/test_feature_extractor_ohlc.py`
  - Mock yfinance so the test is offline and deterministic
  - Assert `generate_dataset` emits `date`, `open`, `high`, `low`, `close` metadata columns
  - Assert the emitted `open`/`high`/`low` are the RAW yfinance values (not the synthesised candle open / clamped high / low)
  - Assert the synthesised-candle feature computation is unchanged (feature columns identical to pre-change behaviour)
  - _Requirements: SP-335 DoD (raw OHLC in dataset); Design: Part A, SP-335 Tests_

- [x] 2. [SP-335] Emit raw OHLC from the feature extractor
  - Extend `METADATA_COLUMNS` in `vpa/ml_validation/feature_extractor.py` to `["date", "open", "high", "low", "close"]`
  - In the `generate_dataset` row loop, attach `float(row["Open"])`, `float(row["High"])`, `float(row["Low"])` alongside the existing `close`
  - Keep the synthesised `Candle` (open = previous close, clamped high/low) feeding VPA feature computation unchanged
  - Run the SP-335 test from task 1 and confirm it passes
  - _Requirements: SP-335 DoD; Design: Part A (VPAFeatureExtractor.generate_dataset)_

- [x] 3. [SP-335] Provide the dataset regeneration run path
  - Ensure a runnable entry (or documented command) exists to regenerate `SPY_vpa_features.csv` with the new `open`/`high`/`low` columns via the extractor
  - This is a manual run step (a live yfinance download cannot run offline in CI) — surface it as a coding/runner task only, not an automated test
  - _Requirements: SP-335 DoD; Design: Part A (regeneration is a run step)_

- [x] 4. [SP-317] Create the backtesting package and data models
  - Create `vpa/backtesting/__init__.py` and `vpa/backtesting/models.py`
  - Define frozen dataclasses `PricePoint`, `SignalEntry`, `TradeRecord`, `SkippedSignal`, `ExitResult`, `BacktestResult`
  - Define `PositionMode` enum (`NO_OVERLAP`, `STACKING`) and `SkipReason` enum (`MISSING_PRICE_DATE`, `OVERLAPPING_POSITION`, `INSUFFICIENT_FUTURE_DATA_ENTRY`, `INSUFFICIENT_FUTURE_DATA_EXIT`, `INVALID_ENTRY_PRICE`, `INVALID_EXIT_PRICE`)
  - Reuse `SignalType` / `SignalDirection` from `vpa/ml_validation/signal_analysis.py`
  - _Requirements: 1.1, 1.2, 5.1, 6.1, 7.6; Design: Part B models.py, Data Models, Enums_

- [x] 5. [SP-317] Implement the exit strategy abstraction
  - [x] 5.1 Implement `vpa/backtesting/exit_strategy.py`
    - Define the `ExitStrategy` Protocol (`resolve_exit(entry_index, price_series, hold_period) -> ExitResult`), receiving the full forward Price_Series including open/high/low so future path-based strategies plug in unchanged
    - Implement `FixedHoldExitStrategy`: `exit_index = entry_index + hold_period`; return `ExitResult` with `INSUFFICIENT_FUTURE_DATA_EXIT` when the exit index is beyond the series, else `close[exit_index]`
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 7.2; Design: Part B exit_strategy.py_

  - [x]* 5.2 Write property test for fixed-hold exit pricing
    - `# Feature: vpa-backtesting-engine, Property 2: Fixed-hold exit pricing`
    - Generate random Price_Series and hold_period; assert `exit_index == entry_index + N` maps to `close[t+1+N]` and `exit_date == date[t+1+N]` when in bounds
    - **Validates: Requirements 3.2, 3.3, 9.2; Design: Correctness Property 2**

  - [x]* 5.3 Write unit tests for exit strategy bounds
    - Exit index exactly beyond the last index returns `INSUFFICIENT_FUTURE_DATA_EXIT`
    - Exit index on the last valid index returns a resolved `ExitResult`
    - _Requirements: 7.2, 9.2; Design: test_exit_strategy.py_

- [x] 6. [SP-317] Implement backtest configuration
  - Implement `vpa/backtesting/config.py` with frozen `BacktestConfig` (`hold_period` required, `round_trip_cost=0.001`, `position_mode=NO_OVERLAP`, `exit_strategy=FixedHoldExitStrategy()` via `default_factory`)
  - _Requirements: 3.5, 4.1, 5.1, 9.2; Design: Part B config.py, Configuration table_

- [x] 7. [SP-317] Implement the signal log builder
  - [x] 7.1 Implement `vpa/backtesting/signal_log_builder.py`
    - `build_signal_log_from_dataset(df)`: reuse `SignalConditionalAnalyzer.classify_signals` and `SIGNAL_DIRECTIONS` to emit one `SignalEntry` per matched SignalType per row (row `date`, matched SignalType, direction); NaN fields excluded per `classify_signals` behaviour
    - `build_price_series_from_dataset(df)`: build a date-ascending `list[PricePoint]` from `date`/`open`/`high`/`low`/`close`; raise a naming error if an OHLC column is missing (SP-335 not applied)
    - _Requirements: 2.1, 2.2, 2.3, 2.5; Design: Part B signal_log_builder.py, Key Method Contracts_

  - [x]* 7.2 Write property test for signal-log construction
    - `# Feature: vpa-backtesting-engine, Property 12: Signal-Log construction from dataset`
    - Generate random Feature_Dataset rows with mixed signal fields; assert one SignalEntry per matched SignalType with correct date and `SIGNAL_DIRECTIONS[signal_type]`
    - **Validates: Requirements 2.1, 2.2, 2.5; Design: Correctness Property 12**

  - [x]* 7.3 Write unit tests for the price-series builder
    - Unsorted rows are returned date-ascending (Req 2.3)
    - Missing `open`/`high`/`low` column raises a `KeyError`/`ValueError` naming the column
    - _Requirements: 2.3; Design: Error Handling (Missing OHLC columns), test_signal_log_builder.py_

- [x] 8. [SP-317] Implement the confidence-rank helper
  - Implement `signal_confidence_rank(signal_type) -> tuple[int, int]` in `vpa/backtesting/engine.py`, reusing `CONFIDENCE_MAP`/`CONFIDENCE_ORDER`/`EXCLUDED_SIGNALS` from `daily_signal.py`; unranked types rank below all ranked types; enum declaration order is the final deterministic tie-break (lower = higher priority)
  - _Requirements: 5.4, 8.1 (Glossary Signal_Confidence_Order); Design: Part B engine.py signal_confidence_rank, Key Method Contracts_

- [x] 9. [SP-317] Implement the engine run loop
  - [x] 9.1 Implement input handling and validation in `BacktestEngine.run`
    - Raise `ValueError` when `config.hold_period <= 0`
    - Work on local copies (never mutate inputs); sort copied Price_Series by `date` ascending if needed; sort copied Signal_Log by `date` ascending
    - Build the `date -> index` map; record `MISSING_PRICE_DATE` and skip signals with no matching price date; compute `entry_index = t + 1` and group eligible entries by `entry_index`
    - _Requirements: 1.4, 1.5, 1.6, 3.5, 5.8, 7.6; Design: Simulation Loop steps 1-3_

  - [x] 9.2 Implement entry pricing, exit resolution, price validation, and return math
    - Bounds-check entry (`INSUFFICIENT_FUTURE_DATA_ENTRY` when `entry_index` beyond last index)
    - Resolve exit via `config.exit_strategy.resolve_exit(...)`; record `INSUFFICIENT_FUTURE_DATA_EXIT` when unresolved
    - `entry_price = close[entry_index]` / `exit_price` from ExitResult; record `INVALID_ENTRY_PRICE` / `INVALID_EXIT_PRICE` for zero or NaN
    - `gross = exit_price / entry_price - 1`; `net = gross - round_trip_cost` applied exactly once; `return_pct = net` (equals gross when cost is 0)
    - Build `TradeRecord` with `entry_date`/`exit_date` as ISO 8601 strings and originating `signal_type`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.6, 4.2, 4.3, 4.4, 4.5, 6.1, 6.3, 6.4, 7.1, 7.2, 7.4, 7.5, 9.1; Design: Simulation Loop step 4_

  - [x] 9.3 Implement position-mode eligibility and ordered output
    - NO_OVERLAP: skip groups where a trade is open and `entry_index <= open_exit_index` (record `OVERLAPPING_POSITION`); on an open slot with 2+ entries, open one trade for the best `signal_confidence_rank` and record `OVERLAPPING_POSITION` for each remaining same-Entry_Index entry; update `open_exit_index`
    - STACKING: open a trade for every eligible entry with no tie-break
    - Sort the Trade_Log by `entry_date` ascending; return empty Trade_Log for empty/fully-skipped input
    - _Requirements: 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 6.2, 6.5, 7.3; Design: Simulation Loop steps 4-5_

  - [x]* 9.4 Write property test for next-day-close entry pricing
    - `# Feature: vpa-backtesting-engine, Property 1: Next-day-close entry pricing`
    - Random Price_Series + single in-bounds signal; assert `entry_price == close[t+1]` and `entry_date == date[t+1]`
    - **Validates: Requirements 3.1, 3.3; Design: Correctness Property 1**

  - [x]* 9.5 Write property test for gross and net return formulas
    - `# Feature: vpa-backtesting-engine, Property 3: Gross and net return formulas`
    - Random valid entry/exit prices and cost; assert `gross == exit/entry - 1` and `return_pct == gross - cost` within 1e-9
    - **Validates: Requirements 3.6, 4.2, 4.3; Design: Correctness Property 3**

  - [x]* 9.6 Write property test for round-trip cost applied once
    - `# Feature: vpa-backtesting-engine, Property 4: Round-trip cost applied exactly once`
    - Random cost including 0.0; assert `return_pct` differs from gross by exactly `cost`, and equals gross when cost is 0
    - **Validates: Requirements 4.4, 4.5; Design: Correctness Property 4**

  - [x]* 9.7 Write property test for NO_OVERLAP non-overlapping trades
    - `# Feature: vpa-backtesting-engine, Property 5: NO_OVERLAP produces no overlapping trades`
    - Random signal dates over a series in NO_OVERLAP; assert each trade's Entry_Index > previous trade's Exit_Index
    - **Validates: Requirements 5.2, 5.3; Design: Correctness Property 5**

  - [x]* 9.8 Write property test for NO_OVERLAP tie-break selection and determinism
    - `# Feature: vpa-backtesting-engine, Property 6: NO_OVERLAP same-Entry_Index tie-break is highest confidence and deterministic`
    - Random multi-signal same-date clusters; assert the opened trade has the best `signal_confidence_rank`, each loser is skipped with `OVERLAPPING_POSITION`, and selection is stable across runs
    - **Validates: Requirements 5.4, 5.5; Design: Correctness Property 6**

  - [x]* 9.9 Write property test for STACKING one trade per eligible signal
    - `# Feature: vpa-backtesting-engine, Property 7: STACKING opens a trade per eligible signal`
    - Random overlapping signals in STACKING; assert every eligible entry produces exactly one trade with no tie-break
    - **Validates: Requirements 5.6, 5.7; Design: Correctness Property 7**

  - [x]* 9.10 Write property test for skip-reason recording
    - `# Feature: vpa-backtesting-engine, Property 8: Skip reasons recorded for each edge case`
    - Fixtures forcing each edge (short series, missing dates, zero/NaN prices, overlap); assert exactly one SkippedSignal with the matching reason
    - **Validates: Requirements 1.5, 7.1, 7.2, 7.4, 7.5; Design: Correctness Property 8**

  - [x]* 9.11 Write property test for input immutability
    - `# Feature: vpa-backtesting-engine, Property 9: Input immutability`
    - Random inputs; assert Signal_Log and Price_Series equal pre-run deep copies
    - **Validates: Requirements 7.6; Design: Correctness Property 9**

  - [x]* 9.12 Write property test for determinism
    - `# Feature: vpa-backtesting-engine, Property 10: Determinism`
    - Random inputs run twice; assert identical trades and skipped lists in identical order
    - **Validates: Requirements 8.1; Design: Correctness Property 10**

  - [x]* 9.13 Write property test for Trade_Log ordering
    - `# Feature: vpa-backtesting-engine, Property 11: Trade_Log ordering`
    - Random shuffled Signal_Log; assert output Trade_Log is ordered by `entry_date` ascending
    - **Validates: Requirements 6.2; Design: Correctness Property 11**

- [x] 10. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. [SP-317] Engine unit and integration tests
  - [x] 11.1 Write engine edge-case unit tests
    - Signal near end of series (`t+1` valid, `t+1+N` out of bounds) → skipped `INSUFFICIENT_FUTURE_DATA_EXIT` (Req 7.2)
    - Signal on the last day (`t+1` out of bounds) → skipped `INSUFFICIENT_FUTURE_DATA_ENTRY` (Req 7.1)
    - Empty Signal_Log → empty Trade_Log, no error (Req 6.5, 7.3)
    - Zero / NaN entry and exit prices → `INVALID_ENTRY_PRICE` / `INVALID_EXIT_PRICE` (Req 7.4, 7.5)
    - Signal date missing from Price_Series → `MISSING_PRICE_DATE` (Req 1.5)
    - Unsorted Price_Series and Signal_Log get sorted (Req 1.4, 1.6)
    - Non-positive `hold_period` raises `ValueError` (Req 3.5)
    - STACKING opens concurrent trades (Req 5.6)
    - _Requirements: 1.4, 1.5, 1.6, 3.5, 5.6, 6.5, 7.1, 7.2, 7.3, 7.4, 7.5; Design: Testing Strategy Unit Tests_

  - [x] 11.2 Write the hand-computed integration test
    - Small hand-computed Signal_Log + Price_Series with fixed Hold_Period, Round_Trip_Cost, and Position_Mode; assert the Trade_Log matches manually derived entry/exit dates, prices, and net returns exactly
    - _Requirements: 8.2; Design: Testing Strategy Integration test_

- [x] 12. [SP-317] Optional CLI runner
  - [x] 12.1 Implement `vpa/backtesting/run_backtest.py`
    - Thin `main(ticker="SPY", hold_period=10)` that loads `{ticker}_vpa_features.csv`, builds Signal_Log and Price_Series, runs the engine, and prints a trade-count summary only (counts of trades and skips by reason); no metrics/reporting (SP-333)
    - _Requirements: 8.3; Design: Optional Runner run_backtest.py_

  - [x] 12.2 Write a light smoke test for the runner
    - With a small mocked/fixture dataset, assert `main` runs and reports counts without error
    - _Design: Optional Runner run_backtest.py_

- [x] 13. Final checkpoint - Full suite and lint
  - Run the full pytest suite for both tickets: `pytest vpa/tests/backtesting/ vpa/tests/ml_validation/test_feature_extractor_ohlc.py -v`
  - Run `ruff check` (line-length 120, double quotes, target py311) and fix any lint or test failures
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- SP-335 (tasks 1-3) is sequenced first because it blocks SP-317; SP-317 (tasks 4-13) consumes the enriched OHLC series.
- Tasks marked with `*` are optional and can be skipped for faster MVP; core implementation tasks are never optional.
- Each task references specific acceptance criteria and design elements (component names, Correctness Property numbers) for traceability.
- Property tests use Hypothesis with `@settings(max_examples=100)` and carry the design tag comment `# Feature: vpa-backtesting-engine, Property {n}: {text}`; each Correctness Property maps to exactly one property test.
- Unit tests cover edge cases plus the hand-computed integration case; the engine core has no network, `yfinance`, or filesystem access.
- Package layout: `vpa/backtesting/` (`models.py`, `exit_strategy.py`, `config.py`, `signal_log_builder.py`, `engine.py`, optional `run_backtest.py`); tests under `vpa/tests/backtesting/` (`test_backtest_engine.py`, `test_exit_strategy.py`, `test_signal_log_builder.py`) and `vpa/tests/ml_validation/test_feature_extractor_ohlc.py` for SP-335.
- All work runs under `.venv` with pytest and ruff (line-length 120, double quotes, py311).
- Task 3 (dataset regeneration) is a manual run step that requires a live yfinance download and cannot run offline in CI.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "4", "8"] },
    { "id": 1, "tasks": ["2", "5.1", "7.1"] },
    { "id": 2, "tasks": ["3", "5.2", "5.3", "6", "7.2", "7.3"] },
    { "id": 3, "tasks": ["9.1"] },
    { "id": 4, "tasks": ["9.2"] },
    { "id": 5, "tasks": ["9.3"] },
    { "id": 6, "tasks": ["9.4", "9.5", "9.6", "9.7", "9.8", "9.9", "9.10", "9.11", "9.12", "9.13", "11.1", "11.2"] },
    { "id": 7, "tasks": ["12.1"] },
    { "id": 8, "tasks": ["12.2"] }
  ]
}
```
