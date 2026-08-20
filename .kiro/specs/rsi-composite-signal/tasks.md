# Implementation Plan: RSI Composite Signal

## Overview

Add RSI (Relative Strength Index) as the 6th signal component to the VPA MarketAnalyzer composite trading score. Implementation follows the existing MA crossover pattern: standalone calculation module, config-driven initialization, pre-computed DataFrame column, and per-row signal detection method.

## Tasks

- [x] 1. Create RSI calculator module
  - [x] 1.1 Create `vpa/rsi.py` with `calculate_rsi()` function
    - Implement Wilder's smoothed moving average method
    - Handle edge cases: insufficient data (return 50.0), all gains (return 100.0), all losses (return 0.0), all unchanged (return 50.0)
    - Accept `closes: list[float]` and `period: int = 14` parameters
    - Return float in range 0.0 to 100.0 inclusive
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

  - [x] 1.2 Write property tests for RSI calculator
    - **Property 1: RSI Boundedness** - For any valid sequence of positive closing prices of length >= period+1, output is in [0.0, 100.0]
    - **Property 2: Monotonic Bullish** - Strictly increasing prices produce RSI > 50.0
    - **Property 3: Monotonic Bearish** - Strictly decreasing prices produce RSI < 50.0
    - **Property 4: Insufficient Data Neutrality** - Series of length < period+1 returns exactly 50.0
    - **Validates: Requirements 1.2, 1.3, 1.4, 1.5**

  - [x] 1.3 Write example-based tests for RSI calculator
    - Test insufficient data (10 prices, period=14) returns 50.0
    - Test all gains (15 increasing prices) returns 100.0
    - Test all losses (15 decreasing prices) returns 0.0
    - Test all flat (15 identical prices) returns 50.0
    - _Requirements: 1.2, 1.4, 1.5, 1.6_

- [x] 2. Add RSI configuration
  - [x] 2.1 Add `rsi` section to `vpa/config/config.json`
    - Add `enabled`, `period`, `overbought_threshold`, `oversold_threshold`, and `scores` object with `overbought` and `oversold` keys
    - Use default values: enabled=true, period=14, overbought_threshold=70, oversold_threshold=30, scores.overbought=-5, scores.oversold=5
    - _Requirements: 3.1_

  - [x] 2.2 Implement `_init_rsi_config()` in `vpa/app_runner.py`
    - Load RSI config section with fallback defaults when section is absent
    - Set `self.__rsi_enabled = False` if `enabled` is false
    - Validate thresholds: if oversold >= overbought, log warning and disable RSI
    - Call from `__init__()` after `_init_drawdown_config()`
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [x] 3. Checkpoint - Ensure RSI module and config load correctly
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Integrate RSI into MarketAnalyzer signal detection
  - [x] 4.1 Implement `compute_rsi_column()` in `vpa/app_runner.py`
    - Pre-compute RSI for all rows in the DataFrame using `calculate_rsi` from `vpa/rsi.py`
    - Skip computation if `self.__rsi_enabled` is False
    - Call from `process_data()` after `compute_sma_columns()`
    - _Requirements: 1.1, 3.2_

  - [x] 4.2 Implement `detect_rsi_signals()` in `vpa/app_runner.py`
    - Read pre-computed RSI value from DataFrame row
    - Apply overbought/oversold thresholds from config to determine signal score
    - Return dict with `rsi_signals` (list of strings) and `rsi_signal_score` (float)
    - Log RSI value and triggered signals at INFO level per requirements
    - Return zero score and empty signals when RSI is disabled or data is insufficient
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6, 4.1, 4.2, 4.3, 4.4_

  - [x] 4.3 Update `process_data()` composite score calculation
    - Call `detect_rsi_signals(row_index)` in the row loop after MA crossover detection
    - Add `rsi_signals` and `rsi_signal_score` keys to the `signals` dictionary
    - Include `rsi_signal_score` in the `trade_signal` summation
    - _Requirements: 2.5, 2.6_

  - [x] 4.4 Write example-based tests for signal scoring logic
    - **Property 5: Signal Score Consistency** - RSI > overbought produces negative score; RSI < oversold produces positive score; between thresholds produces zero
    - Test overbought signal (RSI=75) returns score=-5 and signals=["RSI Overbought"]
    - Test oversold signal (RSI=25) returns score=+5 and signals=["RSI Oversold"]
    - Test neutral (RSI=50) returns score=0 and signals=[]
    - Test disabled config returns score=0 and no RSI computation
    - Test invalid thresholds (oversold >= overbought) disables RSI with warning
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 3.2, 3.4**

- [x] 5. Checkpoint - Ensure MarketAnalyzer RSI integration works
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Integrate RSI into Feature Extractor
  - [x] 6.1 Update `FEATURE_COLUMNS` in `vpa/ml_validation/feature_extractor.py`
    - Insert `rsi_value` and `rsi_signal_score` after `acc_dist_score` and before `composite_score`
    - _Requirements: 5.1_

  - [x] 6.2 Update `_extract_feature_vector()` in `vpa/ml_validation/feature_extractor.py`
    - Compute RSI by calling `calculate_rsi` with closing prices from `period_three` deque
    - Read RSI period from `rsi` config section (default 14)
    - Derive `rsi_signal_score` using same threshold logic as MarketAnalyzer
    - Include `rsi_signal_score` in the `composite_score` summation
    - If `rsi.enabled` is false, set `rsi_value` to 50.0 and `rsi_signal_score` to 0.0
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 6.3 Write integration test verifying composite score includes RSI
    - **Property 6: Composite Additivity** - Composite trade_signal equals sum of all 6 sub-scores
    - Construct a DataFrame where RSI enters overbought/oversold territory
    - Confirm trade_signal differs by expected RSI score contribution
    - Verify feature vector includes rsi_value and rsi_signal_score columns
    - **Validates: Requirements 2.5, 5.1, 5.4**

- [x] 7. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The RSI module (`vpa/rsi.py`) is intentionally stateless and pure for easy testing
- The implementation follows the established MA crossover pattern in the codebase

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "2.2"] },
    { "id": 2, "tasks": ["4.1", "4.2"] },
    { "id": 3, "tasks": ["4.3", "4.4"] },
    { "id": 4, "tasks": ["6.1"] },
    { "id": 5, "tasks": ["6.2"] },
    { "id": 6, "tasks": ["6.3"] }
  ]
}
```
