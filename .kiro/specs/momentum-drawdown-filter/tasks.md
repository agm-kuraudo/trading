# Implementation Plan: Momentum/Drawdown Filter

## Overview

Implement a new screening feature that identifies SP-500 tickers trading 20%+ below their 52-week high while exhibiting positive short-term momentum. The implementation creates a pure-function module (`vpa/opportunities.py`), modifies the data window coordination in `MarketAnalyzer`, integrates into the daily scan loop, and adds configuration support.

## Tasks

- [x] 1. Create filter module with configuration and core calculations
  - [x] 1.1 Create `vpa/opportunities.py` with config loading and validation
    - Create new file `vpa/opportunities.py`
    - Implement `DEFAULT_DRAWDOWN_CONFIG` dict with defaults: enabled=True, drawdown_threshold=20, momentum_period=20, data_days=365
    - Implement `load_drawdown_config(config: dict) -> dict` that extracts the `drawdown_filter` section, applies defaults for missing keys, validates `momentum_period >= 1` (log warning and use default 20 if invalid), validates `drawdown_threshold` in [0, 100] (log warning and use default 20 if invalid)
    - Use Python `logging` module at WARNING level for validation messages
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 1.2 Implement `compute_52_week_high()` and `compute_drawdown_percentage()`
    - Implement `compute_52_week_high(closes: pd.Series, window: int = 252) -> Optional[float]` returning max of last `window` entries, or None if insufficient data
    - Implement `compute_drawdown_percentage(current_close: float, fifty_two_week_high: float) -> float` using formula `((current_close - fifty_two_week_high) / fifty_two_week_high) * 100`
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 1.3 Implement `compute_momentum()`
    - Implement `compute_momentum(closes: pd.Series, period: int = 20) -> Optional[float]` using formula `((closes[-1] - closes[-period - 1]) / closes[-period - 1]) * 100`
    - Return None if Series has fewer than `period + 1` entries
    - Handle division by zero defensively (return None if close N days ago is 0)
    - _Requirements: 3.1, 3.2, 3.3_

  - [x] 1.4 Implement `evaluate_ticker()`
    - Implement `evaluate_ticker(df: pd.DataFrame, drawdown_threshold: float = 20.0, momentum_period: int = 20) -> Optional[dict]`
    - Return None if DataFrame has fewer than 252 rows
    - Return None if insufficient data remains for momentum calculation after 252-day warm-up
    - Compute 52-week high, drawdown percentage, and momentum
    - Return result dict only when `drawdown_pct <= -drawdown_threshold` AND `momentum > 0`
    - Log warnings for insufficient data cases
    - _Requirements: 1.2, 2.1, 2.2, 3.1, 3.2, 4.1, 4.2, 4.3_

  - [x] 1.5 Write property tests for core calculations (Properties 1–6)
    - **Property 1: Insufficient data exclusion** — For any DataFrame with < 252 rows, `evaluate_ticker()` returns None
    - **Property 2: 52-week high correctness** — For any Series with >= 252 entries, result equals `max(closes[-252:])`
    - **Property 3: Drawdown formula correctness** — For any valid pair, result equals `((current_close - high) / high) * 100`
    - **Property 4: Momentum formula correctness** — For any valid Series, result equals `((closes[-1] - closes[-period-1]) / closes[-period-1]) * 100`
    - **Property 5: Momentum insufficient data exclusion** — For DataFrames with 252 rows but insufficient trailing data, returns None
    - **Property 6: Filter predicate correctness** — Returns non-None iff `drawdown_pct <= -threshold` AND `momentum > 0`
    - Create `vpa/tests/test_opportunities.py` using hypothesis strategies
    - Follow patterns from `test_ma_crossover.py` (make_temp_config, make_minimal_df helpers)
    - **Validates: Requirements 1.2, 2.1, 2.2, 2.3, 3.1, 3.2, 4.1**

  - [x] 1.6 Write unit tests for config loading and edge cases
    - Test defaults applied when `drawdown_filter` section is missing
    - Test valid config section is parsed correctly
    - Test `enabled: false` flag is respected
    - Test invalid `momentum_period` (< 1) logs warning and uses default
    - Test invalid `drawdown_threshold` (< 0, > 100) logs warning and uses default
    - Test all-time-high ticker (drawdown ≈ 0, not in opportunities)
    - Test exactly-at-threshold boundary (drawdown = -20 exactly)
    - Test zero momentum excluded
    - **Validates: Requirements 6.2, 6.3, 6.4, 6.5, 4.1**

- [x] 2. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Report formatting and output
  - [x] 3.1 Implement `format_opportunities_report()`
    - Implement `format_opportunities_report(opportunities: list[dict]) -> str`
    - Format header "Opportunities\n=============" followed by table with Ticker, Drawdown%, Momentum% columns
    - Input list is pre-sorted by drawdown_pct ascending (largest drawdown first)
    - When list is empty, output "No opportunities found" under the header
    - Include a separate code path for the disabled case: "Opportunities: disabled"
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [x] 3.2 Write property tests for report formatting (Properties 7–8)
    - **Property 7: Report contains all required fields** — For any non-empty opportunity list, output contains every ticker name, drawdown%, and momentum value
    - **Property 8: Report sorted by drawdown ascending** — Drawdown values in output appear in ascending order
    - Add to `vpa/tests/test_opportunities.py`
    - **Validates: Requirements 5.1, 5.2**

  - [x] 3.3 Write unit tests for report formatting
    - Test empty opportunities list produces "No opportunities found"
    - Test disabled message produces "Opportunities: disabled"
    - Test single entry format
    - Test multiple entries with correct column alignment
    - **Validates: Requirements 5.1, 5.2, 5.3**

- [x] 4. Data window coordination in MarketAnalyzer
  - [x] 4.1 Add `_init_drawdown_config()` and `_get_data_days()` to `MarketAnalyzer`
    - Add `_init_drawdown_config()` method paralleling `_init_ma_config()` — loads config, sets `self.__drawdown_enabled` and `self.__drawdown_config`
    - Call `_init_drawdown_config()` in `__init__` after `_init_ma_config()`
    - Implement `_get_data_days()` returning `max(100, ma_data_days_if_enabled, drawdown_data_days_if_enabled)`
    - Modify `load_data()` to use `_get_data_days()` instead of the inline conditional logic
    - Add `get_dataframe()` public accessor returning `self.myDF`
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 1.1, 1.3_

  - [x] 4.2 Write property test for data window coordination (Property 10)
    - **Property 10: Data window coordination returns max** — For any pair of (ma_data_days, drawdown_data_days) with both enabled, `_get_data_days()` returns `max(ma_data_days, drawdown_data_days)`
    - Create `vpa/tests/test_data_window.py`
    - **Validates: Requirements 7.1**

  - [x] 4.3 Write unit tests for data window coordination
    - Test max logic with both features enabled
    - Test with only drawdown enabled (uses drawdown data_days)
    - Test with only MA enabled (uses MA data_days)
    - Test with both disabled (falls back to 100)
    - Test insufficient data disables feature for that ticker with warning
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4**

- [x] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Integration and configuration
  - [x] 6.1 Add `drawdown_filter` section to `vpa/config/config.json`
    - Add new `drawdown_filter` section with keys: enabled (true), drawdown_threshold (20), momentum_period (20), data_days (365)
    - _Requirements: 6.1, 6.2_

  - [x] 6.2 Integrate filter into `app_all_shares.py` scan loop
    - Import `evaluate_ticker`, `format_opportunities_report`, `load_drawdown_config` from `vpa.opportunities`
    - Load config and drawdown settings at start
    - Store each ticker's DataFrame during the scan loop (dict keyed by ticker)
    - After existing scan loop, iterate stored DataFrames calling `evaluate_ticker()` for each
    - Collect qualifying tickers into opportunities list
    - Sort opportunities by `drawdown_pct` ascending
    - Call `format_opportunities_report()` and write to log file after existing Top 5 / Bottom 5 sections
    - Handle disabled case: write "Opportunities: disabled" section
    - _Requirements: 4.1, 4.2, 4.3, 5.1, 5.2, 5.3, 5.4, 6.3_

  - [x] 6.3 Write integration tests with synthetic DataFrames
    - Test end-to-end flow: config load → evaluate multiple tickers → format report
    - Test with mix of qualifying and non-qualifying tickers
    - Test disabled config produces correct output
    - No yfinance calls — use synthetic DataFrames only
    - **Validates: Requirements 1.2, 4.1, 5.1, 5.4, 6.3**

- [x] 7. Add config validation for invalid momentum_period (Property 9)
  - [x] 7.1 Write property test for config validation (Property 9)
    - **Property 9: Invalid config values use defaults** — For any momentum_period < 1 OR drawdown_threshold outside [0, 100], `load_drawdown_config()` returns default value 20 for the invalid field
    - Add to `vpa/tests/test_opportunities.py`
    - **Validates: Requirements 6.4, 6.5**

- [x] 8. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- All test files follow established patterns from `vpa/tests/test_ma_crossover.py`
- Implementation uses Python with pandas, hypothesis, and pytest (matching existing project stack)
- The new module `vpa/opportunities.py` is pure-functional and testable in isolation without yfinance

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "3.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "6.1"] },
    { "id": 2, "tasks": ["1.4", "3.2", "3.3", "7.1"] },
    { "id": 3, "tasks": ["1.5", "1.6", "4.1"] },
    { "id": 4, "tasks": ["4.2", "4.3"] },
    { "id": 5, "tasks": ["6.2"] },
    { "id": 6, "tasks": ["6.3"] }
  ]
}
```
