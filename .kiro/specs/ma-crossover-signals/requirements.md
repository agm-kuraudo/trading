# Requirements Document

## Introduction

This feature adds Moving Average (MA) crossover signal detection to the VPA MarketAnalyzer. It introduces three configurable Simple Moving Average periods — short (default 10), medium (default 50), and long (default 200) — detects golden cross and death cross events across multiple crossover pairs (short/medium, short/long, medium/long), evaluates price position relative to all three MAs with graduated scoring, and integrates all of these as a new signal category (`ma_crossover_signal_score`) into the existing composite trading signal. The data window must be extended from 100 to at least 250 trading days to accommodate a fully warmed-up long-period SMA.

## Glossary

- **MarketAnalyzer**: The existing core analysis class in `vpa/app_runner.py` that processes market data, detects signals, and produces a composite trading signal score.
- **SMA_Short**: The Simple Moving Average of closing prices over the most recent short period (default 10 trading days).
- **SMA_Medium**: The Simple Moving Average of closing prices over the most recent medium period (default 50 trading days).
- **SMA_Long**: The Simple Moving Average of closing prices over the most recent long period (default 200 trading days).
- **Crossover_Pair**: An ordered pair of two SMAs (faster, slower) monitored for crossover events. The three default pairs are Short/Medium, Short/Long, and Medium/Long.
- **Golden_Cross**: A crossover event where the faster SMA of a Crossover_Pair crosses above the slower SMA, transitioning from faster < slower on the previous trading day to faster >= slower on the current trading day.
- **Death_Cross**: A crossover event where the faster SMA of a Crossover_Pair crosses below the slower SMA, transitioning from faster > slower on the previous trading day to faster <= slower on the current trading day.
- **Price_Position**: The relationship of the current close price to all three SMAs, classified as above-all, below-all, or mixed.
- **MA_Signal_Score**: The numeric score contribution from moving average analysis, added to the composite trade signal alongside existing signal categories.
- **Warmup_Period**: The minimum number of trading days of historical data required before the longest-period SMA can be computed (equal to the long period value, default 200 days).
- **Config**: The JSON configuration file (`vpa/config/config.json`) that controls all tuneable parameters in the MarketAnalyzer.

## Requirements

### Requirement 1: Data Window Extension

**User Story:** As a quantitative researcher, I want the MarketAnalyzer to load sufficient historical data for the longest-period SMA to be fully computed, so that MA crossover signals are based on complete data.

#### Acceptance Criteria

1. THE MarketAnalyzer SHALL load at least `ma_data_days` trading days of historical close price data when MA crossover signals are enabled in the Config.
2. WHEN MA crossover signals are disabled in the Config, THE MarketAnalyzer SHALL retain its existing data loading behaviour (100 days).
3. THE MarketAnalyzer SHALL read the number of days to load from the Config parameter `ma_crossover.ma_data_days` (default: 300) rather than using a hardcoded value.
4. IF yfinance returns fewer rows of data than the configured long period for a ticker, THEN THE MarketAnalyzer SHALL log a warning indicating that MA crossover signals will be unavailable for that ticker and skip MA signal computation.

### Requirement 2: SMA Calculation

**User Story:** As a quantitative researcher, I want accurate short, medium, and long Simple Moving Averages computed from closing prices, so that crossover detection across multiple time horizons has a reliable mathematical foundation.

#### Acceptance Criteria

1. THE MarketAnalyzer SHALL compute SMA_Short as the arithmetic mean of the most recent short-period closing prices (inclusive of the current day), where the short period is read from Config parameter `ma_crossover.ma_periods.short` (default: 10).
2. THE MarketAnalyzer SHALL compute SMA_Medium as the arithmetic mean of the most recent medium-period closing prices (inclusive of the current day), where the medium period is read from Config parameter `ma_crossover.ma_periods.medium` (default: 50).
3. THE MarketAnalyzer SHALL compute SMA_Long as the arithmetic mean of the most recent long-period closing prices (inclusive of the current day), where the long period is read from Config parameter `ma_crossover.ma_periods.long` (default: 200).
4. WHEN fewer than the configured short-period closing prices are available at a given row, THE MarketAnalyzer SHALL set SMA_Short to NaN for that row.
5. WHEN fewer than the configured medium-period closing prices are available at a given row, THE MarketAnalyzer SHALL set SMA_Medium to NaN for that row.
6. WHEN fewer than the configured long-period closing prices are available at a given row, THE MarketAnalyzer SHALL set SMA_Long to NaN for that row.
7. THE MarketAnalyzer SHALL compute SMA values using the close prices from the date-sorted dataset, where each row represents one trading day.

### Requirement 3: Crossover Detection

**User Story:** As a quantitative researcher, I want the system to detect golden cross and death cross events across multiple MA pairs (short/medium, short/long, medium/long), so that I can identify trend reversal signals at different time horizons.

#### Acceptance Criteria

1. THE MarketAnalyzer SHALL monitor three Crossover_Pairs for crossover events: Short/Medium (SMA_Short vs SMA_Medium), Short/Long (SMA_Short vs SMA_Long), and Medium/Long (SMA_Medium vs SMA_Long).
2. WHEN the faster SMA of a Crossover_Pair was strictly less than the slower SMA on the previous trading day AND the faster SMA is greater than or equal to the slower SMA on the current trading day, THE MarketAnalyzer SHALL classify the current day as a Golden_Cross event for that pair.
3. WHEN the faster SMA of a Crossover_Pair was strictly greater than the slower SMA on the previous trading day AND the faster SMA is less than or equal to the slower SMA on the current trading day, THE MarketAnalyzer SHALL classify the current day as a Death_Cross event for that pair.
4. WHEN either SMA in a Crossover_Pair is NaN on the current day or the previous day, THE MarketAnalyzer SHALL not classify that day as any crossover event for that pair.
5. THE MarketAnalyzer SHALL detect at most one crossover event type (Golden_Cross or Death_Cross) per Crossover_Pair per trading day.
6. THE MarketAnalyzer SHALL store the previous day's SMA_Short, SMA_Medium, and SMA_Long values to enable crossover comparison on the current day.
7. THE MarketAnalyzer SHALL evaluate each Crossover_Pair independently, allowing multiple crossover events across different pairs on the same trading day.

### Requirement 4: Price Position Signal

**User Story:** As a quantitative researcher, I want to assess the current price position relative to all three moving averages, so that I can gauge the strength of the prevailing trend with graduated confidence.

#### Acceptance Criteria

1. WHEN the current close price is strictly above SMA_Short, SMA_Medium, and SMA_Long, THE MarketAnalyzer SHALL classify the Price_Position as "above_all" and assign a strongly bullish score contribution equal to the Config parameter `ma_crossover.position_scores.above_all` (default: 5).
2. WHEN the current close price is strictly below SMA_Short, SMA_Medium, and SMA_Long, THE MarketAnalyzer SHALL classify the Price_Position as "below_all" and assign a strongly bearish score contribution equal to the negative of the Config parameter `ma_crossover.position_scores.below_all` (default: 5).
3. WHEN the current close price is above exactly two of the three SMAs, THE MarketAnalyzer SHALL classify the Price_Position as "above_two" and assign a moderately bullish score contribution equal to the Config parameter `ma_crossover.position_scores.above_two` (default: 2).
4. WHEN the current close price is below exactly two of the three SMAs (above exactly one), THE MarketAnalyzer SHALL classify the Price_Position as "below_two" and assign a moderately bearish score contribution equal to the negative of the Config parameter `ma_crossover.position_scores.below_two` (default: 2).
5. WHEN any of SMA_Short, SMA_Medium, or SMA_Long is NaN, THE MarketAnalyzer SHALL classify the Price_Position as "unknown" and assign a score contribution of zero.

### Requirement 5: Signal Score Integration

**User Story:** As a quantitative researcher, I want the MA crossover signal to integrate into the existing composite trade signal score with per-pair weighting, so that higher-timeframe crossovers carry appropriately greater significance.

#### Acceptance Criteria

1. THE MarketAnalyzer SHALL compute MA_Signal_Score as the sum of all crossover event scores across all pairs plus the Price_Position score for the current trading day.
2. WHEN a Golden_Cross event is detected for a Crossover_Pair, THE MarketAnalyzer SHALL add that pair's configured crossover score to the MA_Signal_Score.
3. WHEN a Death_Cross event is detected for a Crossover_Pair, THE MarketAnalyzer SHALL subtract that pair's configured crossover score from the MA_Signal_Score.
4. WHEN no crossover event is detected for a Crossover_Pair, THE MarketAnalyzer SHALL add zero crossover contribution for that pair to the MA_Signal_Score.
5. THE MarketAnalyzer SHALL read per-pair crossover scores from Config parameters: `ma_crossover.crossover_scores.short_medium` (default: 5), `ma_crossover.crossover_scores.short_long` (default: 8), and `ma_crossover.crossover_scores.medium_long` (default: 10).
6. THE MarketAnalyzer SHALL add the MA_Signal_Score to the composite trade signal alongside `single_candle_signal_score`, `trend_signal_score`, `multiple_bar_signal_score`, and `acc_dist_signal_score`.
7. THE MarketAnalyzer SHALL include `ma_crossover_signals` (list of detected signal names including pair identifiers) and `ma_crossover_signal_score` (numeric score) in the dictionary returned by `detect_signals()`.
8. WHEN MA crossover signals are disabled in Config or all SMA values are unavailable, THE MarketAnalyzer SHALL set `ma_crossover_signal_score` to zero and `ma_crossover_signals` to an empty list.

### Requirement 6: Configuration Parameters

**User Story:** As a developer, I want all MA crossover tuneable values to live in the JSON config file with support for three named periods and per-pair weights, so that the system remains consistent with the existing config-driven architecture and is flexible for future period changes.

#### Acceptance Criteria

1. THE Config file SHALL contain an `ma_crossover` section with the following parameters: `enabled` (boolean, default: true), `ma_periods` (object with keys `short`, `medium`, `long`, defaults: 10, 50, 200), `ma_data_days` (integer, default: 300), `crossover_scores` (object with keys `short_medium`, `short_long`, `medium_long`, defaults: 5, 8, 10), and `position_scores` (object with keys `above_all`, `below_all`, `above_two`, `below_two`, defaults: 5, 5, 2, 2).
2. WHEN the `ma_crossover.enabled` parameter is false, THE MarketAnalyzer SHALL skip all MA computation and signal detection.
3. IF the `ma_crossover` section is missing from the Config file, THEN THE MarketAnalyzer SHALL use the default values for all MA parameters and enable MA crossover signals.
4. IF any period value in `ma_periods` is not strictly less than the next longer period (short < medium < long), THEN THE MarketAnalyzer SHALL log a warning and disable MA crossover signals for that run.
5. THE MarketAnalyzer SHALL validate that `ma_data_days` is greater than the configured long period, and IF it is not, THEN THE MarketAnalyzer SHALL set `ma_data_days` to the long period plus 100.

### Requirement 7: Logging and Diagnostics

**User Story:** As a developer, I want the MA crossover signal detection to log its state in the same format as existing signal categories, so that debugging and analysis remain consistent.

#### Acceptance Criteria

1. THE MarketAnalyzer SHALL log current SMA_Short, SMA_Medium, and SMA_Long values at INFO level in the format: `SMA_Short: {value:.2f}, SMA_Medium: {value:.2f}, SMA_Long: {value:.2f}`.
2. WHEN a Golden_Cross event is detected for a Crossover_Pair, THE MarketAnalyzer SHALL log `Golden Cross detected ({pair_name})` at INFO level, where pair_name identifies the specific pair (e.g. "short/medium").
3. WHEN a Death_Cross event is detected for a Crossover_Pair, THE MarketAnalyzer SHALL log `Death Cross detected ({pair_name})` at INFO level, where pair_name identifies the specific pair.
4. THE MarketAnalyzer SHALL log the MA signal summary in the format: `MA Crossover Signals: {signals_list}` and `MA Crossover Signal Score: {score}` at INFO level, matching the pattern used by existing signal categories.
