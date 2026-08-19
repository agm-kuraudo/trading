# Implementation Plan: VPA Signal-Conditional Analysis

## Overview

Implement the `SignalConditionalAnalyzer` pipeline that isolates high-conviction VPA signal events across 11 tickers, computes directional hit rates over 3/5/10-day forward-return horizons, performs statistical significance testing, and produces structured CSV and text output artefacts. The implementation follows the existing `AnalysisScript` pattern in `vpa/ml_validation/`.

## Tasks

- [x] 1. Set up module structure and data models
  - [x] 1.1 Create `vpa/ml_validation/signal_analysis.py` with enums, constants, and dataclasses
    - Define `SignalType` enum with 5 signal types
    - Define `SignalDirection` enum (UP/DOWN)
    - Define `SIGNAL_DIRECTIONS` mapping and `FORWARD_HORIZONS` list
    - Define `SignalMetrics` and `CrossTickerSummary` frozen dataclasses
    - Define `SignalConditionalAnalyzer` class skeleton with all constants (thresholds, ticker universe, bootstrap params)
    - _Requirements: 1.1-1.5, 2.1-2.3, 3.1-3.9, 4.1-4.5, 5.1_

  - [x] 1.2 Create `vpa/ml_validation/run_signal_analysis.py` CLI entry point
    - Implement argparse with `--output-dir` argument (default: `ml_validation_output/`)
    - Set numpy random seed 42
    - Instantiate and run `SignalConditionalAnalyzer`
    - _Requirements: 9.1, 9.2_

- [x] 2. Implement data loading and signal classification
  - [x] 2.1 Implement `load_dataset()` method
    - Load CSV from correct path per ticker (SPY at root, others in subdirectory)
    - Sort by date ascending
    - Drop rows with NaN in close column
    - Raise `InsufficientDataError` if fewer than 2 rows remain
    - _Requirements: 5.1, 8.1, 8.3, 8.6, 9.3_

  - [x] 2.2 Implement `classify_signals()` method
    - Apply 5 signal filter conditions to each row
    - Handle NaN fields by treating as non-matching for dependent filters
    - Allow rows to match multiple signal types simultaneously
    - Return `dict[SignalType, list[int]]` mapping signal types to row indices
    - _Requirements: 1.1-1.8, 8.2_

  - [x]* 2.3 Write property tests for signal classification (Properties 1, 2, 3)
    - **Property 1: Signal classification completeness** - verify all qualifying rows are captured
    - **Property 2: Signal non-exclusivity** - verify rows matching multiple filters appear in all sets
    - **Property 3: NaN signal field handling** - verify NaN fields exclude row from dependent filters only
    - **Validates: Requirements 1.1-1.7, 8.2**

- [x] 3. Implement forward return calculation
  - [x] 3.1 Implement `compute_forward_returns()` method
    - Compute `close[t+N] / close[t] - 1` for each signal event index
    - Exclude events with insufficient future rows (< N rows after index t)
    - Exclude events where close[t] == 0
    - Return numpy array of forward returns
    - _Requirements: 2.1-2.7_

  - [x] 3.2 Implement `compute_base_rate()` method
    - Compute unconditional positive-return rate across ALL dataset rows for given horizon
    - Only include rows with sufficient future data
    - _Requirements: 4.1_

  - [x]* 3.3 Write property tests for forward returns (Properties 4, 5, 8)
    - **Property 4: Forward return formula correctness** - verify formula to within 1e-10 tolerance
    - **Property 5: Forward return exclusion on insufficient data** - verify events near end are excluded
    - **Property 8: Base rate independence from signal events** - verify all rows used, not just signal rows
    - **Validates: Requirements 2.1-2.6, 4.1**

- [x] 4. Implement metrics computation
  - [x] 4.1 Implement `compute_metrics()` method
    - Compute hit_rate based on signal direction (bullish: return > 0, bearish: return < 0)
    - Compute avg_win (mean of absolute winning returns)
    - Compute avg_loss (mean of absolute losing returns)
    - Compute profit_factor (sum abs wins / sum abs losses), handle all-wins (inf) and all-losses (0.0)
    - Compute signals_per_year
    - Return `SignalMetrics` with None fields if event_count < MIN_EVENTS_FOR_STATS
    - _Requirements: 3.1-3.10_

  - [x]* 4.2 Write property tests for metrics (Properties 6, 7)
    - **Property 6: Hit rate direction correctness** - verify bullish counts positive returns, bearish counts negative
    - **Property 7: Profit factor boundary conditions** - verify inf for all-wins, 0 for all-losses, correct ratio for mixed
    - **Validates: Requirements 3.1, 3.2, 3.5, 3.7, 3.8**

- [x] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Implement statistical testing
  - [x] 6.1 Implement `binomial_test()` method
    - Two-sided binomial test via scipy.stats.binomtest
    - Compare observed hits against base_rate
    - Return p-value float
    - _Requirements: 4.2, 4.3_

  - [x] 6.2 Implement `bootstrap_ci()` method
    - 10000 resamples with replacement, seeded with numpy random_state 42
    - Compute mean of each resample
    - Return (2.5th percentile, 97.5th percentile) as CI bounds
    - _Requirements: 4.4, 8.4_

  - [x]* 6.3 Write property test for bootstrap reproducibility (Property 9)
    - **Property 9: Bootstrap reproducibility** - verify same input + same seed produces identical CI bounds
    - **Validates: Requirements 4.4, 8.4**

- [x] 7. Implement interpretation and cross-ticker analysis
  - [x] 7.1 Implement `interpret()` method
    - Apply hit-rate band logic with correct precedence (contrarian < 45% takes priority)
    - Return conclusion string matching exact text from requirements
    - _Requirements: 7.1-7.6_

  - [x] 7.2 Implement `analyse_ticker()` method
    - Load dataset, classify signals, compute returns, compute metrics for all signal/horizon combos
    - Handle insufficient events gracefully (set stats fields to None)
    - Print progress to stdout in required format
    - _Requirements: 3.10, 4.5, 5.3, 9.4_

  - [x] 7.3 Implement `compute_cross_ticker_summary()` method
    - Compute median/mean hit rate across tickers with sufficient data
    - Count significant tickers (p < 0.05)
    - Identify best/worst ticker by hit rate
    - Note insufficient ticker coverage (< 3 tickers)
    - Apply interpretation logic
    - _Requirements: 5.4, 5.5, 7.1-7.6_

  - [x]* 7.4 Write property test for interpretation precedence (Property 10)
    - **Property 10: Interpretation precedence** - verify contrarian conclusion takes precedence over noise when both match
    - **Validates: Requirements 7.4**

- [x] 8. Implement output writers
  - [x] 8.1 Implement `write_per_ticker_csv()` method
    - Write CSV with exact column headers specified in Requirement 6.1
    - Format numbers to 4 decimal places, event_count as integer, signals_per_year to 1 decimal
    - Include rows for insufficient-data signal types with empty metric columns
    - Handle None/NaN fields appropriately
    - _Requirements: 6.1, 6.5, 6.6_

  - [x] 8.2 Implement `write_comparison_csv()` method
    - Write cross-ticker summary CSV with exact column headers from Requirement 6.2
    - Same numeric formatting rules
    - _Requirements: 6.2, 6.5, 6.6_

  - [x] 8.3 Implement `write_summary_text()` method
    - Write interpretation table showing band boundaries and conclusions
    - Write per-signal-type-per-horizon conclusion
    - Write ranked list of signals ordered by median hit rate descending per horizon
    - _Requirements: 6.3_

  - [x] 8.4 Implement `run()` method to orchestrate full pipeline
    - Iterate through ticker universe, call analyse_ticker for each
    - Handle missing/malformed ticker files (log warning, skip, continue)
    - Raise InsufficientDataError if no valid tickers loaded
    - Compute cross-ticker summaries
    - Write all output artefacts to output directory
    - _Requirements: 5.2, 6.4, 8.5, 9.4, 9.5_

- [x] 9. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Integration tests and deterministic output verification
  - [x]* 10.1 Write integration test for full pipeline with known test data
    - Create small fixture datasets with known signal events and expected outputs
    - Verify CSV output matches expected values
    - Verify column headers and numeric formatting
    - Verify summary text content
    - _Requirements: 6.1-6.6, 9.1, 9.2_

  - [x]* 10.2 Write property test for deterministic output (Property 11)
    - **Property 11: Deterministic output** - verify running pipeline twice on same input produces identical output
    - **Validates: Requirements 8.5**

  - [x]* 10.3 Write unit tests for edge cases
    - Test zero signal events for a type
    - Test all wins / all losses profit factor
    - Test single event (metrics computed, stats skipped)
    - Test dataset with exactly 2 rows
    - Test dataset with 1 row (InsufficientDataError)
    - Test all signal fields NaN (empty signal sets)
    - Test zero close price (event excluded)
    - Test missing ticker file (logged and skipped)
    - _Requirements: 3.6-3.8, 4.5, 5.2, 8.1-8.6_

- [x] 11. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- All tests live in `vpa/tests/ml_validation/test_signal_analysis.py`
- The implementation uses Python with pandas, numpy, scipy, and Hypothesis for property tests

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1", "2.2"] },
    { "id": 2, "tasks": ["2.3", "3.1", "3.2"] },
    { "id": 3, "tasks": ["3.3", "4.1"] },
    { "id": 4, "tasks": ["4.2", "6.1", "6.2"] },
    { "id": 5, "tasks": ["6.3", "7.1", "7.2"] },
    { "id": 6, "tasks": ["7.3", "7.4"] },
    { "id": 7, "tasks": ["8.1", "8.2", "8.3"] },
    { "id": 8, "tasks": ["8.4"] },
    { "id": 9, "tasks": ["10.1", "10.2", "10.3"] }
  ]
}
```
