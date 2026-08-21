# Requirements Document

## Introduction

Daily VPA Signal Generator for any ticker (defaulting to SPY) that produces actionable trading signals based on the signal-conditional analysis findings from SP-314. The key insight is that bearish VPA signals (Distribution, Strong Bearish) are reliable contrarian indicators — when VPA says bearish on SPY, the correct action is to go long. Bullish signals have a weak edge at the 10-day horizon, barely exceeding SPY's natural upward drift. The generator runs daily after market close, classifies the latest candle, applies contrarian inversion logic, and logs structured signals to a persistent CSV.

## Glossary

- **Signal_Generator**: The daily signal generation module (`vpa/ml_validation/daily_signal.py`) that processes any specified ticker's market data, classifies VPA signals, applies contrarian logic, and outputs actionable trading signals.
- **Feature_Extractor**: The existing `VPAFeatureExtractor` class that downloads OHLCV data from yfinance, processes it through VPA rolling-window logic, and produces 29-feature vectors including `composite_score`, `acc_dist_flag`, and `acc_dist_type`.
- **Signal_Classifier**: The classification logic (derived from `SignalConditionalAnalyzer.classify_signals()`) that maps feature vector values to `SignalType` categories using thresholds on `composite_score` (±15) and accumulation/distribution fields.
- **Contrarian_Inversion**: The process of inverting a bearish VPA signal direction to produce a bullish (BUY) trading signal, based on SP-314 statistical findings showing sub-50% hit rates for bearish signals on SPY.
- **Signal_Record**: A structured output containing date, signal type, original VPA direction, adjusted direction after contrarian logic, confidence level, and suggested holding period in trading days.
- **Signals_Log**: A persistent CSV file that accumulates Signal_Records over time, appending new entries on each run.
- **Warm_Up_Period**: The minimum number of candles (50, matching `PERIOD_THREE_LENGTH`) required for VPA rolling-window calculations to produce valid feature vectors.
- **Composite_Score**: The sum of single-candle, trend, multiple-bar, accumulation/distribution, and RSI sub-scores that determines overall VPA signal strength and direction.
- **Confidence_Level**: A categorical rating (High, Medium-High, Low-Medium, Low) derived from SP-314 statistical hit rates for each signal type on SPY at the 10-day horizon.

## Requirements

### Requirement 1: Data Acquisition for Daily Processing

**User Story:** As a trader, I want the Signal_Generator to download sufficient recent data for the specified ticker for VPA processing, so that I can get a valid signal for the most recent trading day without needing to maintain a full 10-year dataset.

#### Acceptance Criteria

1. WHEN the Signal_Generator is invoked, THE Feature_Extractor SHALL download OHLCV data for the specified ticker from yfinance spanning the number of calendar days specified by the `--lookback-days` argument (default 200), ending on the current date.
2. WHEN the downloaded data contains fewer than 50 valid trading-day rows after removing rows with NaN values in any OHLCV column (Open, High, Low, Close, Volume), THE Signal_Generator SHALL raise an InsufficientDataError with a message that includes the number of valid rows found and the minimum required (50).
3. THE Signal_Generator SHALL NOT enforce the 2000-row minimum that exists in the Feature_Extractor's `generate_dataset()` method, as daily signal generation requires only enough data for warm-up.
4. IF yfinance returns no data, an empty DataFrame, or raises a network-related exception during download, THEN THE Signal_Generator SHALL raise an InsufficientDataError indicating the data source is unavailable.
5. WHEN data is downloaded successfully, THE Signal_Generator SHALL sort rows by date ascending and use the final row's date as the signal date, regardless of whether the generator is run on a trading day or a non-trading day.

### Requirement 2: VPA Feature Extraction for Latest Candle

**User Story:** As a trader, I want the Signal_Generator to process the latest candle for the specified ticker through the full VPA pipeline, so that I receive an accurate feature vector reflecting current market conditions.

#### Acceptance Criteria

1. WHEN sufficient data is downloaded, THE Signal_Generator SHALL process all rows through VPA rolling-window logic (spread/volume percentiles, ADX, accumulation/distribution detection, signal scoring, RSI calculation) such that, given identical input OHLCV data, the feature vector for any row matches the values the existing Feature_Extractor would produce for that same row.
2. THE Signal_Generator SHALL extract a single feature vector for the final (most recent) trading day in the processed dataset, containing all 29 features defined in Feature_Extractor.FEATURE_COLUMNS.
3. THE Signal_Generator SHALL use the VPA configuration from `vpa/config/config.json` with period lengths of 5, 25, and 50, percentile start of 5, and percentile increments of 5.
4. WHILE processing candles through the rolling window, THE Signal_Generator SHALL skip rows until the period-three deque (50 candles) is full, consistent with existing Warm_Up_Period behaviour.
5. IF all downloaded rows are consumed by the Warm_Up_Period such that zero feature vectors are produced, THEN THE Signal_Generator SHALL raise an InsufficientDataError indicating that no valid feature rows could be extracted.

### Requirement 3: Signal Classification

**User Story:** As a trader, I want the Signal_Generator to classify the latest candle's feature vector into known VPA signal types, so that I know which (if any) high-conviction signal has fired.

#### Acceptance Criteria

1. WHEN the latest feature vector has a non-NaN `composite_score` greater than or equal to 15.0, THE Signal_Classifier SHALL classify it as STRONG_BULLISH.
2. WHEN the latest feature vector has a non-NaN `composite_score` less than or equal to -15.0, THE Signal_Classifier SHALL classify it as STRONG_BEARISH.
3. WHEN the latest feature vector has a non-NaN `acc_dist_flag` equal to 1 and a non-NaN `acc_dist_type` equal to 1, THE Signal_Classifier SHALL classify it as ACCUMULATION.
4. WHEN the latest feature vector has a non-NaN `acc_dist_flag` equal to 1 and a non-NaN `acc_dist_type` equal to -1, THE Signal_Classifier SHALL classify it as DISTRIBUTION.
5. WHEN the latest feature vector has a non-NaN `acc_dist_flag` equal to 1, a non-NaN `acc_dist_type` equal to 1, and a non-NaN `acc_dist_score` greater than or equal to 15.0, THE Signal_Classifier SHALL classify it as ACCUMULATION_TEST_PASS.
6. THE Signal_Classifier SHALL allow a single candle to match multiple signal types simultaneously (a candle can be both STRONG_BULLISH and ACCUMULATION, and ACCUMULATION_TEST_PASS always co-occurs with ACCUMULATION).
7. IF the latest feature vector's relevant fields are NaN or no classification thresholds are met, THEN THE Signal_Classifier SHALL return an empty set of signal types for that candle, indicating no signal fired.

### Requirement 4: Contrarian Inversion and Confidence Assignment

**User Story:** As a trader, I want bearish VPA signals to be inverted to BUY signals with appropriate confidence levels, so that I can act on the contrarian edge identified in SP-314.

#### Acceptance Criteria

1. WHEN a DISTRIBUTION signal is classified, THE Signal_Generator SHALL produce a Signal_Record with original_direction DOWN, adjusted_direction BUY, confidence_level High, and suggested_hold_days 10.
2. WHEN a STRONG_BEARISH signal is classified, THE Signal_Generator SHALL produce a Signal_Record with original_direction DOWN, adjusted_direction BUY, confidence_level Medium-High, and suggested_hold_days 10.
3. WHEN a STRONG_BULLISH signal is classified, THE Signal_Generator SHALL produce a Signal_Record with original_direction UP, adjusted_direction BUY, confidence_level Low-Medium, and suggested_hold_days 10.
4. WHEN an ACCUMULATION signal is classified, THE Signal_Generator SHALL produce a Signal_Record with original_direction UP, adjusted_direction BUY, confidence_level Low, and suggested_hold_days 10.
5. WHEN an ACCUMULATION_TEST_PASS signal is classified, THE Signal_Generator SHALL NOT produce a Signal_Record (signal is inconclusive per SP-314 findings).
6. WHEN multiple signal types fire on the same candle, THE Signal_Generator SHALL produce a separate Signal_Record for each applicable signal type, ordered by confidence level descending: High, Medium-High, Low-Medium, Low.

### Requirement 5: Console Output

**User Story:** As a trader, I want to see a clear summary of today's signal printed to stdout, so that I can quickly understand the trading recommendation.

#### Acceptance Criteria

1. WHEN one or more signals fire for the latest trading day, THE Signal_Generator SHALL print each Signal_Record to stdout including: date (ISO 8601 YYYY-MM-DD), signal type, original VPA direction, adjusted direction, confidence level, and suggested hold days, with each field on a labelled line.
2. WHEN no actionable signals fire for the latest trading day, THE Signal_Generator SHALL print "No high-conviction signal today" to stdout.
3. THE Signal_Generator SHALL always print the date of the most recent candle processed to stdout, including in the no-signal case, so that the trader can confirm the output corresponds to the expected trading day.

### Requirement 6: Persistent Signals Log

**User Story:** As a trader, I want each signal to be appended to a CSV log file, so that I can track signal history over time and validate performance.

#### Acceptance Criteria

1. WHEN one or more signals fire, THE Signal_Generator SHALL append one row per signal to the Signals_Log CSV file, skipping any row where a record with the same date and signal_type combination already exists in the file.
2. THE Signals_Log SHALL contain columns in this fixed order: date (ISO 8601 YYYY-MM-DD format), signal_type, original_direction, adjusted_direction, confidence_level, suggested_hold_days.
3. IF the Signals_Log CSV file does not exist, THEN THE Signal_Generator SHALL create it with a header row before appending the first signal.
4. IF the Signals_Log CSV file already exists, THEN THE Signal_Generator SHALL append to it without overwriting existing data and without repeating the header row.
5. WHEN no signals fire, THE Signal_Generator SHALL NOT write any row to the Signals_Log.
6. THE Signal_Generator SHALL store the Signals_Log at a configurable path, defaulting to `ml_validation_output/{ticker}_daily_signals.csv` relative to the working directory (e.g. `spy_daily_signals.csv` for SPY, `aapl_daily_signals.csv` for AAPL).
7. IF the parent directory of the Signals_Log path does not exist, THEN THE Signal_Generator SHALL create it (including any intermediate directories) before writing.
8. IF writing to the Signals_Log fails due to a file system error (permissions, disk full, locked file), THEN THE Signal_Generator SHALL print an error message to stderr indicating the failure reason and exit with a non-zero exit code without silently discarding the signal data.

### Requirement 7: CLI Interface

**User Story:** As a trader, I want to invoke the Signal_Generator from the command line, so that I can run it manually or schedule it via cron/task scheduler.

#### Acceptance Criteria

1. THE Signal_Generator SHALL be invocable via `python -m vpa.ml_validation.daily_signal`.
2. THE Signal_Generator SHALL accept an optional `--output-dir` argument to specify where the Signals_Log CSV is written, defaulting to `ml_validation_output`.
3. THE Signal_Generator SHALL accept an optional `--lookback-days` argument to control how many calendar days of data to download, defaulting to 200, with a minimum accepted value of 70 and a maximum accepted value of 3650.
4. THE Signal_Generator SHALL exit with code 0 on successful execution (regardless of whether a signal fired).
5. IF a fatal error occurs (data unavailable, configuration missing), THEN THE Signal_Generator SHALL print an error message to stderr indicating the cause of failure and exit with code 1.
6. IF the `--lookback-days` value is outside the accepted range of 70 to 3650 or is not a positive integer, THEN THE Signal_Generator SHALL print an error message to stderr indicating the valid range and exit with code 2.
7. IF an unrecognized argument is provided, THEN THE Signal_Generator SHALL print a usage summary to stderr and exit with code 2.
8. THE Signal_Generator SHALL accept an optional `--ticker` argument to specify which ticker symbol to analyse, defaulting to "SPY".

### Requirement 8: Configuration Reuse

**User Story:** As a developer, I want the Signal_Generator to reuse the existing VPA configuration and signal thresholds, so that signal definitions remain consistent with the validated SP-314 analysis.

#### Acceptance Criteria

1. WHEN the Signal_Generator is invoked, THE Signal_Generator SHALL read VPA configuration from `vpa/config/config.json`, loading at minimum the `PERIOD_ONE_LENGTH`, `PERIOD_TWO_LENGTH`, `PERIOD_THREE_LENGTH`, and `ticker_symbol` values required for Feature_Extractor processing.
2. THE Signal_Generator SHALL use the same composite score threshold (15.0) as `SignalConditionalAnalyzer.COMPOSITE_THRESHOLD` for Strong Bullish and Strong Bearish classification.
3. THE Signal_Generator SHALL use the same accumulation/distribution score threshold (15.0) as `SignalConditionalAnalyzer.ACC_DIST_SCORE_THRESHOLD` for Accumulation Test Pass classification.
4. THE Signal_Generator SHALL import threshold constants directly from the `SignalConditionalAnalyzer` class rather than redefining them, so that a change to `COMPOSITE_THRESHOLD` or `ACC_DIST_SCORE_THRESHOLD` in `signal_analysis.py` is automatically reflected without separate updates.
5. IF `vpa/config/config.json` is missing or contains invalid JSON, THEN THE Signal_Generator SHALL raise a descriptive error indicating the configuration file could not be loaded and exit with a non-zero exit code.

### Requirement 9: Platform Independence

**User Story:** As a developer, I want the Signal_Generator to run on both Windows and Linux, so that it can be scheduled on any available machine.

#### Acceptance Criteria

1. THE Signal_Generator SHALL use `pathlib.Path` for all file system path construction, resolution, and directory creation operations.
2. THE Signal_Generator SHALL NOT use platform-specific path separators, shell commands, or OS-specific APIs (such as `os.system`, hardcoded `/` or `\\` separators, or platform-gated imports).
3. THE Signal_Generator SHALL produce identical Signal_Records and Signals_Log content when given the same input data on Windows (x64) and Linux (x64, ARM) running Python 3.10 or later.
4. THE Signal_Generator SHALL open all file I/O with explicit `encoding="utf-8"` and `newline=""` parameters to ensure consistent CSV output across platforms.

### Requirement 10: Multi-Ticker Generality

**User Story:** As a trader, I want to run the Signal_Generator against any yfinance-supported ticker, so that I can monitor signals beyond SPY.

#### Acceptance Criteria

1. THE Signal_Generator SHALL accept any valid yfinance ticker symbol via the `--ticker` argument.
2. THE Signal_Generator SHALL apply the same classification thresholds (composite_score ±15, acc_dist fields) regardless of ticker.
3. THE Signal_Generator SHALL apply the same contrarian inversion rules and confidence levels (derived from SPY analysis) as defaults for all tickers until ticker-specific configuration is available (see SP-322).
4. IF the specified ticker has no data available on yfinance, THEN THE Signal_Generator SHALL raise an InsufficientDataError.
5. THE Signal_Generator SHALL include the ticker symbol in console output and Signal_Record for identification.
