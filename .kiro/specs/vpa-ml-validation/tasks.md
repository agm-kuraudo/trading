# Implementation Plan: VPA ML Validation

## Overview

Build a pipeline that extracts VPA intermediate features from the existing `MarketAnalyzer`, generates a labelled historical dataset, trains an XGBoost classifier with walk-forward validation, and produces a go/no-go conclusion on whether VPA features contain predictive signal for next-day SPY direction. Implementation uses Python with pandas, scikit-learn, XGBoost, yfinance, and Hypothesis for property-based testing.

## Tasks

- [x] 1. Set up module structure, dependencies, and shared utilities
  - [x] 1.1 Create the `vpa/ml_validation/` package directory with `__init__.py`, and `vpa/tests/ml_validation/` test package with `__init__.py`
    - Create both directories and empty `__init__.py` files
    - _Requirements: 7.4 (output directory creation pattern)_

  - [x] 1.2 Create the custom exception class and shared data models
    - Create `vpa/ml_validation/exceptions.py` with `InsufficientDataError`
    - Define the `WalkForwardResult` dataclass in `vpa/ml_validation/walk_forward.py` (just the dataclass for now)
    - _Requirements: 4.7, 4.8, 2.4 (error handling throughout pipeline)_

  - [x] 1.3 Add `enable_feature_extraction` field to config.json (default `false`)
    - Add the new field to `vpa/config/config.json`
    - _Requirements: 1.3_

- [x] 2. Implement ConclusionEngine (pure logic, no dependencies)
  - [x] 2.1 Implement `vpa/ml_validation/conclusion.py` with `ConclusionEngine.determine_conclusion()`
    - Implement the five-branch decision tree using 52% edge threshold and 2pp improvement threshold
    - Return exactly one of the five defined conclusion strings
    - _Requirements: 6.2, 6.3, 6.4, 6.5, 6.6_

  - [x] 2.2 Write property test for ConclusionEngine (Property 12)
    - **Property 12: Conclusion engine correctness**
    - Generate random (baseline_pct, ml_pct) pairs in [0, 100] and verify output is always one of the five strings matching the correct branch
    - **Validates: Requirements 6.2, 6.3, 6.4, 6.5, 6.6**

  - [x] 2.3 Write unit tests for ConclusionEngine boundary cases
    - Test exact boundary values: 52.0%, 52.01%, baseline+2.0pp, baseline+2.01pp, baseline-2.0pp, baseline-2.01pp
    - _Requirements: 6.2, 6.3, 6.4, 6.5, 6.6_

- [x] 3. Implement WalkForwardValidator
  - [x] 3.1 Implement `vpa/ml_validation/walk_forward.py` with `WalkForwardValidator.validate()`
    - Use scikit-learn `TimeSeriesSplit` with `n_splits=5`
    - Skip folds where train < 30 samples or test < 10 samples, log warnings
    - Train `XGBClassifier(random_state=42)` per fold, compute accuracy
    - Return `WalkForwardResult` with fold accuracies, mean, std, model (from last valid fold), skipped folds
    - Raise `InsufficientDataError` if all folds are skipped
    - _Requirements: 4.1, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8_

  - [x] 3.2 Write property test for chronological ordering (Property 9)
    - **Property 9: Walk-forward chronological ordering**
    - Generate time-indexed DataFrames, verify max train date < min test date for each fold
    - **Validates: Requirements 4.3**

  - [x] 3.3 Write property test for fold skip threshold (Property 10)
    - **Property 10: Fold skip on insufficient samples**
    - Generate datasets of varying sizes and verify folds with train<30 or test<10 are skipped
    - **Validates: Requirements 4.7**

  - [x] 3.4 Write unit tests for WalkForwardValidator edge cases
    - Test all-folds-skipped raises `InsufficientDataError`
    - Test with exactly the minimum viable dataset size
    - Test that XGBoost random_state is 42
    - _Requirements: 4.4, 4.7, 4.8_

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement VPAFeatureExtractor
  - [x] 5.1 Implement `vpa/ml_validation/feature_extractor.py` with `VPAFeatureExtractor.__init__()` and `_extract_feature_vector()`
    - Wrap `MarketAnalyzer` via composition (pass config_path, ticker_symbol)
    - Implement `_extract_feature_vector()` returning a dict with all 27 named feature columns in fixed order
    - Include metadata fields (date as ISO-8601, close as float) separate from numeric feature array
    - Respect `enable_feature_extraction` config flag — when disabled, delegate to MarketAnalyzer with no extraction
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [x] 5.2 Implement `VPAFeatureExtractor.generate_dataset()`
    - Download 3650+ calendar days (10 years) of OHLCV from yfinance
    - Drop rows with NaN in OHLCV columns
    - Process candles through MarketAnalyzer, extract feature vectors once rolling windows are full (skip before PERIOD_THREE_LENGTH warm-up)
    - Label each row with `next_day_direction` (1 if next close > current close, 0 otherwise including equal)
    - Exclude final row (no next-day label)
    - Raise `InsufficientDataError` if fewer than 2000 valid labelled rows
    - Return DataFrame with feature columns + metadata + label
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [x] 5.3 Write property tests for feature extraction (Properties 1, 2)
    - **Property 1: Feature vector structure completeness** — verify 27 numeric features + separate metadata
    - **Property 2: Feature vector column order invariance** — verify identical column names/order across invocations
    - **Validates: Requirements 1.1, 1.4, 1.5**

  - [x] 5.4 Write property tests for labelling and dataset shape (Properties 3, 4, 5)
    - **Property 3: Next-day direction labelling** — random closing price sequences, verify label correctness
    - **Property 4: Dataset excludes unlabellable final row** — N trading days yields N-1 rows
    - **Property 5: NaN OHLCV rows are dropped** — DataFrames with random NaN insertions
    - **Validates: Requirements 2.2, 2.5, 2.6**

  - [x] 5.5 Write unit tests for VPAFeatureExtractor
    - Test `enable_feature_extraction=false` produces no Feature_Vectors
    - Test dataset with exactly 2000 rows (boundary pass)
    - Test dataset with 1999 rows (raises InsufficientDataError)
    - Test warm-up period skipping
    - _Requirements: 1.2, 1.3, 2.4_

- [x] 6. Implement AnalysisScript
  - [x] 6.1 Implement `vpa/ml_validation/analysis.py` — baseline accuracy and feature importance methods
    - `compute_baseline_accuracy()`: classify UP when composite_score > 0, DOWN when <= 0; exclude null composite rows; raise `InsufficientDataError` on zero labelled rows
    - `extract_feature_importance()`: gain-based importance from XGBoost model, normalised to sum 1.0, sorted descending, 4 decimal places; warn if all zero
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 5.1, 5.2, 5.3, 5.4_

  - [x] 6.2 Implement `vpa/ml_validation/analysis.py` — walk-forward orchestration, conclusion, and output generation
    - `run_walk_forward_validation()`: filter to feature-only columns (exclude date, close, next_day_direction), pass to WalkForwardValidator
    - `generate_conclusion()`: delegate to ConclusionEngine
    - `save_outputs()`: create output directory, write CSV dataset, feature importance CSV, and analysis summary text file; overwrite existing files; log and continue on filesystem errors
    - _Requirements: 4.2, 6.1, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

  - [x] 6.3 Write property tests for baseline and feature importance (Properties 6, 7, 8, 11)
    - **Property 6: Baseline classification rule** — random floats, verify UP when >0, DOWN when <=0
    - **Property 7: Baseline accuracy computation** — random prediction/label arrays, verify accuracy formula
    - **Property 8: Model receives only feature columns** — verify metadata columns excluded
    - **Property 11: Feature importance report validity** — random importance arrays, verify sorted descending and sum to 1.0
    - **Validates: Requirements 3.1, 3.2, 3.4, 4.2, 5.2, 5.3**

  - [x] 6.4 Write unit tests for AnalysisScript
    - Test all composite scores null raises InsufficientDataError
    - Test zero labelled rows raises error
    - Test all-zero importances produces warning and 0.0000 scores
    - Test output file creation and overwrite behaviour (mocked filesystem)
    - Test summary text file format matches expected structure
    - _Requirements: 3.4, 3.5, 5.4, 7.1, 7.2, 7.3, 7.5, 7.6_

- [x] 7. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Implement entry point and wire pipeline end-to-end
  - [x] 8.1 Implement `vpa/ml_validation/run_analysis.py` — CLI entry point
    - Set `numpy.random.seed(42)` at start
    - Wire: generate_dataset → save CSV → compute baseline → run walk-forward → extract importance → generate conclusion → save all outputs
    - Print summary to stdout with baseline accuracy, ML accuracy (+/- std), top 5 features, conclusion, data date range, and valid row count
    - Accept ticker (default "SPY") and output_dir (default "ml_validation_output") as arguments
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 6.1_

  - [x] 8.2 Write property test for reproducibility (Property 13)
    - **Property 13: Reproducibility — deterministic output**
    - Run the pipeline twice with the same input data and verify identical accuracy metrics and feature importance
    - **Validates: Requirements 8.5**

  - [x] 8.3 Write integration tests for the full pipeline
    - Test with a small mocked dataset (50+ rows) to verify end-to-end wiring
    - Test output files exist with correct names and headers
    - Test summary file contains all required sections (baseline, ML accuracy, top 5 features, conclusion, date range)
    - _Requirements: 7.1, 7.2, 7.3, 8.3, 8.4_

- [x] 9. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples, edge cases, and integration points
- The implementation uses Python throughout — pandas, scikit-learn, XGBoost, yfinance, Hypothesis
- The `MarketAnalyzer` class lives in `vpa/app_runner.py` — the feature extractor wraps it via composition
- All random seeds fixed to 42 for reproducibility (numpy + XGBoost)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["2.1", "3.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "3.2", "3.3", "3.4"] },
    { "id": 3, "tasks": ["5.1"] },
    { "id": 4, "tasks": ["5.2"] },
    { "id": 5, "tasks": ["5.3", "5.4", "5.5", "6.1"] },
    { "id": 6, "tasks": ["6.2"] },
    { "id": 7, "tasks": ["6.3", "6.4"] },
    { "id": 8, "tasks": ["8.1"] },
    { "id": 9, "tasks": ["8.2", "8.3"] }
  ]
}
```
