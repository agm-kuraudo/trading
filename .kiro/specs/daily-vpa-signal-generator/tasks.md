# Implementation Plan: Daily VPA Signal Generator

## Overview

Implement a CLI module (`vpa/ml_validation/daily_signal.py`) that downloads recent OHLCV data for a specified ticker, classifies the latest candle using VPA logic, applies contrarian inversion, and appends structured signals to a per-ticker CSV log. Uses Python with `argparse`, `pandas`, `yfinance`, `pathlib`, and `hypothesis` for property tests.

## Tasks

- [x] 1. Create module with data models and constants
  - [x] 1.1 Create `vpa/ml_validation/daily_signal.py` with imports, `SignalRecord` dataclass, confidence map, excluded signals set, CSV columns list, and confidence order
    - Import `SignalType`, `SignalDirection`, `SIGNAL_DIRECTIONS` from `signal_analysis`
    - Import `COMPOSITE_THRESHOLD`, `ACC_DIST_SCORE_THRESHOLD` from `SignalConditionalAnalyzer`
    - Import `InsufficientDataError` from `exceptions`
    - Import `VPAFeatureExtractor` from `feature_extractor`
    - Define `SignalRecord` frozen dataclass with fields: ticker, date, signal_type, original_direction, adjusted_direction, confidence_level, suggested_hold_days
    - Define `CONFIDENCE_MAP`, `CONFIDENCE_ORDER`, `EXCLUDED_SIGNALS`, `CSV_COLUMNS`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 8.2, 8.3, 8.4, 10.2, 10.3_

- [x] 2. Implement classification and signal building
  - [x] 2.1 Implement `classify_last_row(df: pd.DataFrame) -> set[SignalType]`
    - Extract `composite_score`, `acc_dist_flag`, `acc_dist_type`, `acc_dist_score` from the final row
    - Apply threshold logic: composite_score >= COMPOSITE_THRESHOLD → STRONG_BULLISH, <= -COMPOSITE_THRESHOLD → STRONG_BEARISH, flag=1 & type=1 → ACCUMULATION, flag=1 & type=-1 → DISTRIBUTION, flag=1 & type=1 & score >= ACC_DIST_SCORE_THRESHOLD → ACCUMULATION_TEST_PASS
    - Return empty set if relevant fields are NaN or no thresholds met
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

  - [x] 2.2 Implement `build_signal_records(ticker: str, date: str, signal_types: set[SignalType]) -> list[SignalRecord]`
    - Filter out EXCLUDED_SIGNALS (ACCUMULATION_TEST_PASS)
    - Create one SignalRecord per remaining type with correct original_direction from SIGNAL_DIRECTIONS, adjusted_direction="BUY", confidence from CONFIDENCE_MAP, suggested_hold_days=10
    - Sort records by CONFIDENCE_ORDER (High first)
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 10.2, 10.3_

  - [ ]* 2.3 Write property test for signal classification (Property 1)
    - **Property 1: Signal classification matches threshold rules**
    - Generate random feature vectors with hypothesis, verify classify_last_row returns exactly the set of types whose conditions are satisfied
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7**

  - [ ]* 2.4 Write property test for contrarian mapping (Property 2)
    - **Property 2: Contrarian mapping produces correctly ordered records**
    - Generate random signal type subsets and ticker strings, verify build_signal_records output has correct fields and confidence ordering
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 10.2, 10.3**

- [x] 3. Implement DailySignalGenerator class
  - [x] 3.1 Implement `DailySignalGenerator.__init__` and `run` method
    - `__init__(self, output_dir: Path, lookback_days: int = 200, ticker: str = "SPY")` stores params
    - `run()` orchestrates: load config, instantiate VPAFeatureExtractor with ticker, call generate_dataset with lookback_days, validate ≥50 rows after NaN removal, sort by date ascending, call classify_last_row on the processed DataFrame, call build_signal_records with ticker and latest date, return list of SignalRecord
    - Raise InsufficientDataError if < 50 valid rows or yfinance returns empty/errors
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 8.1, 10.1, 10.4_

  - [ ]* 3.2 Write property test for signal date (Property 3)
    - **Property 3: Signal date is the chronologically latest date**
    - Generate DataFrames with ≥50 rows in arbitrary order, verify signal date equals max date after sort
    - **Validates: Requirements 1.5**

  - [ ]* 3.3 Write property test for insufficient data detection (Property 4)
    - **Property 4: Insufficient data detection**
    - Generate DataFrames with < 50 valid rows, verify InsufficientDataError is raised
    - **Validates: Requirements 1.2, 10.4**

- [x] 4. Checkpoint
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement output functions
  - [x] 5.1 Implement `print_signals(ticker: str, date: str, records: list[SignalRecord]) -> None`
    - Print each record with labelled fields including ticker, date, signal_type, original_direction, adjusted_direction, confidence_level, suggested_hold_days
    - Print "No high-conviction signal today" with date and ticker if records is empty
    - Always include the date and ticker in output
    - _Requirements: 5.1, 5.2, 5.3, 10.5_

  - [x] 5.2 Implement `append_to_log(records: list[SignalRecord], log_path: Path) -> None`
    - Create parent directories if they don't exist
    - If CSV doesn't exist, write header row then data
    - If CSV exists, read existing rows and skip any record where (ticker, date, signal_type) already exists (deduplication)
    - Append new records only
    - Use `encoding="utf-8"` and `newline=""` for platform independence
    - Do nothing if records is empty
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 9.1, 9.4_

  - [x] 5.3 Write property test for CSV deduplication (Property 5)
    - **Property 5: CSV deduplication on append**
    - Generate signal records and existing CSV content, verify no duplicate (ticker, date, signal_type) rows after append
    - **Validates: Requirements 6.1**

- [x] 6. Implement CLI interface
  - [x] 6.1 Implement `parse_args(argv: list[str] | None = None) -> argparse.Namespace`
    - `--output-dir` (default "ml_validation_output")
    - `--lookback-days` (default 200, type int, range 70-3650 validated)
    - `--ticker` (default "SPY")
    - Exit code 2 for invalid args
    - _Requirements: 7.1, 7.2, 7.3, 7.6, 7.7, 7.8_

  - [x] 6.2 Implement `main()` function and `if __name__ == "__main__"` block
    - Parse args, construct log path as `{output_dir}/{ticker.lower()}_daily_signals.csv`
    - Instantiate DailySignalGenerator with output_dir, lookback_days, ticker
    - Call run(), then print_signals(), then append_to_log()
    - Handle InsufficientDataError → stderr + exit 1
    - Handle file I/O errors → stderr + exit 1
    - Exit 0 on success
    - _Requirements: 7.1, 7.4, 7.5, 6.6, 6.8_

  - [x] 6.3 Write property test for CLI lookback-days validation (Property 6)
    - **Property 6: CLI lookback-days range validation**
    - Generate integers, verify parse_args accepts [70, 3650] and rejects outside with SystemExit code 2
    - **Validates: Requirements 7.3, 7.6**

- [x] 7. Checkpoint
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Integration and wiring
  - [x] 8.1 Wire feature extraction equivalence and add `__init__.py` entry if needed
    - Verify VPAFeatureExtractor integration produces same features as generate_dataset for the same input
    - Ensure module is invocable via `python -m vpa.ml_validation.daily_signal`
    - _Requirements: 2.1, 2.2, 7.1, 9.2, 9.3_

  - [x] 8.2 Write property test for feature extraction equivalence (Property 7)
    - **Property 7: Feature extraction equivalence**
    - For a valid OHLCV dataset, verify final row feature vector matches what VPAFeatureExtractor.generate_dataset() would produce
    - **Validates: Requirements 2.1, 2.2**

  - [x] 8.3 Write unit tests for console output and edge cases
    - Test stdout format with capsys (verify ticker and fields present)
    - Test no-signal message includes date and ticker
    - Test CSV header creation vs append scenarios
    - Test multi-ticker log file naming
    - Test config loading error messages
    - _Requirements: 5.1, 5.2, 5.3, 6.3, 6.4, 6.6, 8.5, 10.5_

  - [x] 8.4 Write integration test with mocked yfinance
    - Mock yfinance download, run full pipeline for multiple tickers
    - Verify Signal_Records, CSV output, and console output end-to-end
    - _Requirements: 1.1, 10.1, 10.4, 10.5_

- [x] 9. Final checkpoint
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- All file I/O uses `pathlib.Path` and explicit UTF-8 encoding for platform independence
- Test file location: `vpa/tests/ml_validation/test_daily_signal.py`

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "2.2"] },
    { "id": 2, "tasks": ["2.3", "2.4", "3.1"] },
    { "id": 3, "tasks": ["3.2", "3.3", "5.1", "5.2"] },
    { "id": 4, "tasks": ["5.3", "6.1"] },
    { "id": 5, "tasks": ["6.2", "6.3"] },
    { "id": 6, "tasks": ["8.1"] },
    { "id": 7, "tasks": ["8.2", "8.3", "8.4"] }
  ]
}
```
