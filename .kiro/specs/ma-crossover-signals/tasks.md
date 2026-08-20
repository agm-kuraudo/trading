# Implementation Plan: MA Crossover Signals

## Overview

Extend the `MarketAnalyzer` class with multi-timeframe Moving Average crossover signal detection. Implementation adds config validation, SMA pre-computation on the DataFrame, crossover detection across three pairs, graduated price position scoring, and integration into the composite trade signal. All work is in `vpa/app_runner.py`, `vpa/config/config.json`, and a new test file `vpa/tests/test_ma_crossover.py`.

## Tasks

- [x] 1. Config schema and validation
  - [x] 1.1 Add `ma_crossover` section to `vpa/config/config.json`
    - Add the full `ma_crossover` configuration block with all default values: `enabled`, `ma_periods` (short/medium/long), `ma_data_days`, `crossover_scores` (short_medium/short_long/medium_long), `position_scores` (above_all/below_all/above_two/below_two)
    - _Requirements: 6.1_

  - [x] 1.2 Add MA config loading and validation to `MarketAnalyzer.__init__()`
    - Read `ma_crossover` section from config (default all values if section missing)
    - Store in `self.__ma_config` and set `self.__ma_enabled` flag
    - Validate period ordering: short < medium < long; if invalid, log warning and set `self.__ma_enabled = False`
    - Validate `ma_data_days` > long period; if not, auto-correct to `long_period + 100`
    - _Requirements: 6.2, 6.3, 6.4, 6.5_

  - [x] 1.3 Write unit tests for config validation
    - `test_config_defaults_when_missing`: No `ma_crossover` section uses all defaults, MA enabled
    - `test_invalid_period_order_disables`: short >= medium logs warning and disables MA
    - `test_data_days_auto_correction`: `ma_data_days` <= long period gets corrected to long + 100
    - `test_ma_disabled_returns_zero`: `enabled: false` results in zero score and empty signal list
    - _Requirements: 6.2, 6.3, 6.4, 6.5_

- [x] 2. Data window extension
  - [x] 2.1 Modify `MarketAnalyzer.load_data()` to use `ma_data_days`
    - When `self.__ma_enabled` is True, set `start_date = end_date - timedelta(days=ma_data_days)` instead of hardcoded 100
    - When `self.__ma_enabled` is False, retain existing 100-day behaviour
    - After download, check if DataFrame rows < configured long period; if so, log warning and set `self.__ma_enabled = False`
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [x] 2.2 Write unit tests for data window extension
    - `test_extended_data_window`: When MA enabled, verify `start_date` uses `ma_data_days`
    - `test_original_window_when_disabled`: When MA disabled, verify 100-day window preserved
    - `test_insufficient_data_warning`: When rows < long period, MA gets disabled with warning
    - Use `fixed_df` parameter to inject DataFrames of varying sizes
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 3. SMA computation
  - [x] 3.1 Implement `compute_sma_columns()` method on `MarketAnalyzer`
    - If `self.__ma_enabled` is False, return early
    - Add `SMA_short`, `SMA_medium`, `SMA_long` columns to `self.myDF` using `df["Close"].rolling(window=N, min_periods=N).mean()`
    - Use period values from `self.__ma_config["ma_periods"]`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x] 3.2 Write property test for SMA correctness
    - **Property 1: SMA correctness**
    - For any DataFrame with N rows of close prices, SMA at row i equals arithmetic mean of close[i-period+1 : i+1]. When i < period-1, value is NaN.
    - Generate random close price series (length 50-300), verify SMA columns match manual calculation
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6**

  - [x] 3.3 Write unit tests for SMA edge cases
    - `test_sma_short_calculation`: Known 10-day prices produce expected SMA
    - `test_sma_nan_during_warmup`: Rows before period have NaN SMA values
    - _Requirements: 2.1, 2.4, 2.5, 2.6_

- [x] 4. Crossover detection and price position
  - [x] 4.1 Implement `detect_ma_signals(row_index)` method on `MarketAnalyzer`
    - If `self.__ma_enabled` is False, return `{"ma_crossover_signals": [], "ma_crossover_signal_score": 0}`
    - Read SMA values for current row and previous row from DataFrame columns
    - For each of the 3 crossover pairs, detect Golden Cross and Death Cross per requirements
    - Handle NaN: skip crossover for pairs with NaN, set position to "unknown" with zero score
    - Classify price position (above_all, below_all, above_two, below_two) based on count of SMAs the close is strictly above
    - Compute total score: sum of crossover scores + position score
    - Log SMA values, crossover events, and final score per Requirement 7
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.4, 5.5, 7.1, 7.2, 7.3, 7.4_

  - [x] 4.2 Write property test for crossover mutual exclusivity
    - **Property 2: Crossover mutual exclusivity**
    - For any pair of consecutive SMA values, at most one of Golden_Cross or Death_Cross is detected (never both simultaneously)
    - Generate random pairs of (prev_faster, prev_slower, curr_faster, curr_slower) and verify exclusivity
    - **Validates: Requirements 3.5**

  - [x] 4.3 Write property test for crossover detection correctness
    - **Property 3: Crossover detection correctness**
    - For any pair where prev_faster < prev_slower AND curr_faster >= curr_slower, Golden_Cross is detected. For prev_faster > prev_slower AND curr_faster <= curr_slower, Death_Cross is detected.
    - Generate random SMA value transitions and verify correct classification
    - **Validates: Requirements 3.2, 3.3**

  - [x] 4.4 Write property test for NaN propagation
    - **Property 4: NaN propagation**
    - For any row where any SMA is NaN, no crossover event is detected for pairs involving that SMA, and Price_Position is "unknown" with zero score
    - Generate DataFrames with NaN values at various positions
    - **Validates: Requirements 3.4, 4.5**

  - [x] 4.5 Write property test for price position exhaustiveness
    - **Property 5: Price position exhaustiveness**
    - For any row with all three SMAs computed (non-NaN), the Price_Position is classified as exactly one of: above_all, below_all, above_two, or below_two
    - Generate random close prices and SMA triplets, verify exactly one classification
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4**

  - [x] 4.6 Write property test for score composition
    - **Property 6: Score composition**
    - For any trading day, MA_Signal_Score equals the sum of all detected crossover pair scores plus the Price_Position score. When disabled, score is exactly zero.
    - Generate random signal scenarios and verify score arithmetic
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.8**

  - [x] 4.7 Write unit tests for crossover and price position
    - `test_golden_cross_short_medium`: Detect golden cross on short/medium pair with known data
    - `test_death_cross_short_medium`: Detect death cross on short/medium pair
    - `test_golden_cross_medium_long`: Detect golden cross on medium/long pair
    - `test_multiple_crossovers_same_day`: Multiple pairs can cross on same day
    - `test_no_crossover_when_nan`: NaN SMAs prevent crossover detection
    - `test_price_position_above_all`: Close > all 3 SMAs gives above_all score
    - `test_price_position_below_all`: Close < all 3 SMAs gives below_all score
    - `test_price_position_above_two`: Close > 2 of 3 SMAs gives above_two score
    - `test_price_position_below_two`: Close < 2 of 3 SMAs gives below_two score
    - `test_price_position_unknown_nan`: NaN SMA gives unknown, zero score
    - `test_crossover_score_weights`: Per-pair scores match config values
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.7, 4.1, 4.2, 4.3, 4.4, 4.5, 5.2, 5.3, 5.5_

- [x] 5. Checkpoint - Core logic complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Integration into process_data()
  - [x] 6.1 Wire MA signals into `process_data()` loop
    - Call `self.compute_sma_columns()` once before the row loop
    - After `detect_signals(this_candle)`, call `ma_signals = self.detect_ma_signals(index)`
    - Add `ma_signals["ma_crossover_signal_score"]` to composite `trade_signal`
    - Merge `ma_crossover_signals` and `ma_crossover_signal_score` into the `signals` dict returned for logging
    - Update the `detect_signals()` return dict to include MA signal keys
    - _Requirements: 5.6, 5.7, 5.8_

  - [x] 6.2 Write integration test for composite score
    - `test_composite_score_integration`: Verify MA score is added to final trade_signal alongside all 4 existing signal scores
    - Use a fixed DataFrame that triggers a known crossover and verify end-to-end score
    - _Requirements: 5.6, 5.7_

- [x] 7. Final checkpoint - All tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- All tests use fixed DataFrames injected via the existing `fixed_df` parameter — no yfinance calls needed
- Property-based tests should use `hypothesis` library with `@given` decorator, minimum 100 examples per property
- Branch: `SP-304-ma-crossover-signals`

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["1.3", "2.1"] },
    { "id": 3, "tasks": ["2.2", "3.1"] },
    { "id": 4, "tasks": ["3.2", "3.3", "4.1"] },
    { "id": 5, "tasks": ["4.2", "4.3", "4.4", "4.5", "4.6", "4.7"] },
    { "id": 6, "tasks": ["6.1"] },
    { "id": 7, "tasks": ["6.2"] }
  ]
}
```
