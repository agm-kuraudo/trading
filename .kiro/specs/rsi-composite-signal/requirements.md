# Requirements Document

## Introduction

This feature re-integrates RSI (Relative Strength Index) calculation into the VPA MarketAnalyzer composite scoring system. RSI was present in VPA 0.1 on QuantConnect but is absent from the current local Python codebase. The RSI signal will become the 6th sub-score component of the composite trade signal, providing overbought/oversold context alongside the existing single-candle, trend, multiple-bar, accumulation/distribution, and MA crossover signals.

## Glossary

- **RSI_Calculator**: The module-level function or method responsible for computing the Relative Strength Index from a series of closing prices using the smoothed moving average (Wilder's method).
- **MarketAnalyzer**: The main analysis engine class in `app_runner.py` that processes OHLCV data through rolling windows and produces a composite trade signal.
- **Feature_Extractor**: The `VPAFeatureExtractor` class in `ml_validation/feature_extractor.py` that extracts structured feature vectors for ML analysis.
- **RSI_Period**: The lookback window (number of bars) used to calculate RSI. Default is 14.
- **Overbought_Threshold**: The RSI level above which the market is considered overbought. Default is 70.
- **Oversold_Threshold**: The RSI level below which the market is considered oversold. Default is 30.
- **Composite_Score**: The sum of all sub-signal scores produced by MarketAnalyzer, used to determine trade direction.
- **Config**: The JSON configuration file (`config/config.json`) that stores all tuneable parameters for the system.

## Requirements

### Requirement 1: RSI Calculation

**User Story:** As a trader, I want RSI(14) calculated for each bar during processing, so that overbought and oversold conditions can inform the composite trading signal.

#### Acceptance Criteria

1. THE RSI_Calculator SHALL compute RSI using Wilder's smoothed moving average method with a configurable period defaulting to 14.
2. WHEN fewer than RSI_Period + 1 closing prices are available, THE RSI_Calculator SHALL return a neutral value of 50.0 indicating insufficient data.
3. THE RSI_Calculator SHALL produce values in the range 0.0 to 100.0 inclusive for all valid inputs.
4. WHEN all price changes in the lookback window are gains (no losses), THE RSI_Calculator SHALL return 100.0.
5. WHEN all price changes in the lookback window are losses (no gains), THE RSI_Calculator SHALL return 0.0.
6. WHEN all price changes in the lookback window are zero, THE RSI_Calculator SHALL return 50.0.

### Requirement 2: RSI Signal Scoring

**User Story:** As a trader, I want overbought and oversold RSI levels to contribute a bearish or bullish component to the composite score, so that extreme momentum conditions are factored into trade decisions.

#### Acceptance Criteria

1. WHEN the RSI value exceeds the Overbought_Threshold, THE MarketAnalyzer SHALL add a score component of -5 (bearish) to the RSI signal score and append "RSI Overbought" to the rsi_signals list.
2. WHEN the RSI value falls below the Oversold_Threshold, THE MarketAnalyzer SHALL add a score component of +5 (bullish) to the RSI signal score and append "RSI Oversold" to the rsi_signals list.
3. WHILE the RSI value is between the Oversold_Threshold and Overbought_Threshold inclusive, THE MarketAnalyzer SHALL set the RSI signal score to zero and leave the rsi_signals list empty.
4. IF the RSI value cannot be calculated for the current bar due to insufficient historical data, THEN THE MarketAnalyzer SHALL set the RSI signal score to zero and leave the rsi_signals list empty.
5. THE MarketAnalyzer SHALL include the RSI signal score in the composite trade signal summation by adding it to the existing five sub-scores (single_candle_signal_score, trend_signal_score, multiple_bar_signal_score, acc_dist_signal_score, ma_crossover_signal_score).
6. THE MarketAnalyzer SHALL store the RSI signal score and descriptive signal names in the all_signals dictionary returned by signal detection, using keys `rsi_signals` (list of strings) and `rsi_signal_score` (numeric value of type float).

### Requirement 3: RSI Configuration

**User Story:** As a developer, I want RSI parameters to be configurable via JSON, so that thresholds and scoring weights can be tuned without code changes.

#### Acceptance Criteria

1. THE Config SHALL contain an `rsi` section with keys: `enabled` (boolean), `period` (integer), `overbought_threshold` (numeric), `oversold_threshold` (numeric), and `scores` (object with `overbought` and `oversold` numeric values).
2. WHEN the `rsi.enabled` field is set to false, THE MarketAnalyzer SHALL skip RSI calculation and return an RSI signal score of zero.
3. WHEN the `rsi` section is absent from Config, THE MarketAnalyzer SHALL use default values: enabled=true, period=14, overbought_threshold=70, oversold_threshold=30, scores.overbought=-5, scores.oversold=5.
4. IF the configured `oversold_threshold` is greater than or equal to `overbought_threshold`, THEN THE MarketAnalyzer SHALL log a warning and disable RSI signal scoring.

### Requirement 4: RSI Logging

**User Story:** As a trader, I want the RSI value and any triggered signals logged during processing, so that I can understand how RSI influenced the composite score.

#### Acceptance Criteria

1. WHEN RSI is calculated for a bar, THE MarketAnalyzer SHALL log the ticker symbol, bar timestamp, and numeric RSI value (formatted to 2 decimal places) at INFO level.
2. WHEN an overbought or oversold signal is triggered, THE MarketAnalyzer SHALL log the signal name, ticker symbol, and score contribution (formatted to 2 decimal places) at INFO level.
3. WHILE RSI is disabled via configuration, THE MarketAnalyzer SHALL not log RSI-related messages.
4. WHEN RSI cannot be calculated due to insufficient data, THE MarketAnalyzer SHALL not log RSI-related messages for that bar.

### Requirement 5: Feature Extractor Integration

**User Story:** As a data scientist, I want RSI values and RSI signal scores included in the ML feature vector, so that the machine learning model can use momentum context for predictions.

#### Acceptance Criteria

1. THE Feature_Extractor SHALL include `rsi_value` and `rsi_signal_score` in the FEATURE_COLUMNS list, positioned after the existing feature columns and before `composite_score`.
2. WHEN generating feature vectors, THE Feature_Extractor SHALL compute RSI by calling RSI_Calculator with the closing prices from the period_three deque and the RSI_Period value from the `rsi` section of Config (defaulting to 14 if absent).
3. WHEN generating feature vectors, THE Feature_Extractor SHALL derive `rsi_signal_score` by applying the same overbought/oversold threshold and scoring logic defined in Requirement 2 (negative score when RSI exceeds Overbought_Threshold, positive score when RSI falls below Oversold_Threshold, zero otherwise).
4. THE Feature_Extractor SHALL include the `rsi_signal_score` in the `composite_score` summation alongside the existing sub-scores (single_candle_score, trend_score, multiple_bar_score, acc_dist_score, and ma_crossover_score).
5. IF the `rsi.enabled` configuration flag is set to false, THEN THE Feature_Extractor SHALL set `rsi_value` to 50.0 and `rsi_signal_score` to 0.0 for all feature vectors.

### Requirement 6: Unit and Property Testing

**User Story:** As a developer, I want comprehensive tests for the RSI calculation and signal thresholds, so that correctness is verified and regressions are caught.

#### Acceptance Criteria

1. THE test suite SHALL include a property test verifying that RSI_Calculator output is always in the range 0.0 to 100.0 for any generated sequence of positive closing prices with values between 0.01 and 999,999.99 and series length between RSI_Period + 1 and 500.
2. THE test suite SHALL include a property test verifying that for a monotonically increasing price series of at least RSI_Period + 1 closing prices, RSI_Calculator returns a value above 50.0.
3. THE test suite SHALL include a property test verifying that for a monotonically decreasing price series of at least RSI_Period + 1 closing prices, RSI_Calculator returns a value below 50.0.
4. THE test suite SHALL include example-based tests verifying that RSI above the Overbought_Threshold produces a negative signal score equal to the configured `scores.overbought` value, and RSI below the Oversold_Threshold produces a positive signal score equal to the configured `scores.oversold` value.
5. THE test suite SHALL include example-based tests verifying that RSI between the Oversold_Threshold and Overbought_Threshold inclusive produces a zero signal score.
6. THE test suite SHALL include a test verifying that when `rsi.enabled` is set to false, MarketAnalyzer returns an RSI signal score of zero and RSI_Calculator is not invoked.
7. THE test suite SHALL include an example-based test verifying that when fewer than RSI_Period + 1 closing prices are provided, RSI_Calculator returns the neutral value of 50.0.
