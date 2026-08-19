# Requirements Document

## Introduction

This feature adds a signal-conditional statistical analysis pipeline to the VPA system. Rather than evaluating VPA as a daily direction predictor (which SP-312 showed yields ~50% accuracy), this analysis isolates high-conviction signal events that fire on only ~3-10% of trading days and measures their directional hit rate over multiple forward-return horizons. The goal is to determine whether VPA signals contain tradeable information when measured only on the days they fire, across SPY and 10 individual stocks.

## Glossary

- **Signal_Conditional_Analyzer**: The analysis component that filters datasets to high-conviction events and computes hit-rate statistics.
- **Feature_Dataset**: The CSV file produced by SP-312 (`{ticker}_vpa_features.csv`) containing 27 feature columns plus metadata (date, close) and the next_day_direction label.
- **High_Conviction_Event**: A trading day where one or more of the defined signal filters evaluates to true.
- **Forward_Return**: The percentage change in close price from signal day (t) to a future day (t+N), calculated as `close[t+N] / close[t] - 1`.
- **Hit_Rate**: The percentage of signal events where the forward return direction matches the expected signal direction (positive for bullish signals, negative for bearish signals).
- **Profit_Factor**: The ratio of the sum of winning returns to the absolute sum of losing returns for a set of signal events.
- **Base_Rate**: The unconditional probability of a positive forward return over the given horizon, measured across the full dataset (all days, not just signal days).
- **Signal_Type**: One of the five defined high-conviction event categories (Strong Bullish, Strong Bearish, Accumulation, Distribution, Accumulation Test Pass).
- **Ticker_Universe**: The set of 11 symbols analysed: SPY, AAPL, MSFT, NVDA, TSLA, AMD, KO, JNJ, CAT, BA, XOM.
- **Comparison_Table**: The output summary aggregating all signal types, horizons, and tickers into a single structured result.

## Requirements

### Requirement 1: Signal Filter Definitions

**User Story:** As a quantitative researcher, I want to define high-conviction VPA signal events using thresholds on existing features, so that I can isolate the small subset of days where VPA generates strong directional conviction.

#### Acceptance Criteria

1. WHEN the Signal_Conditional_Analyzer processes a Feature_Dataset row with composite_score >= 15, THE Signal_Conditional_Analyzer SHALL classify that row as a Strong Bullish event with expected direction UP.
2. WHEN the Signal_Conditional_Analyzer processes a Feature_Dataset row with composite_score <= -15, THE Signal_Conditional_Analyzer SHALL classify that row as a Strong Bearish event with expected direction DOWN.
3. WHEN the Signal_Conditional_Analyzer processes a Feature_Dataset row with acc_dist_flag == 1 AND acc_dist_type == 1, THE Signal_Conditional_Analyzer SHALL classify that row as an Accumulation event with expected direction UP.
4. WHEN the Signal_Conditional_Analyzer processes a Feature_Dataset row with acc_dist_flag == 1 AND acc_dist_type == -1, THE Signal_Conditional_Analyzer SHALL classify that row as a Distribution event with expected direction DOWN.
5. WHEN the Signal_Conditional_Analyzer processes a Feature_Dataset row with acc_dist_flag == 1 AND acc_dist_type == 1 AND acc_dist_score >= 15, THE Signal_Conditional_Analyzer SHALL classify that row as an Accumulation Test Pass event with expected direction UP.
6. THE Signal_Conditional_Analyzer SHALL allow a single row to match multiple Signal_Types simultaneously (signal categories are not mutually exclusive).
7. IF any of the fields composite_score, acc_dist_flag, acc_dist_type, or acc_dist_score contain NaN or null values in a Feature_Dataset row, THEN THE Signal_Conditional_Analyzer SHALL treat that row as not matching any signal filter that depends on the missing field.
8. THE Signal_Conditional_Analyzer SHALL return a list of matched Signal_Types for each processed row, where the list is empty if no filters match.

### Requirement 2: Forward Return Calculation

**User Story:** As a quantitative researcher, I want to measure price movement over 3, 5, and 10 trading days after each signal event, so that I can evaluate signal effectiveness across multiple time horizons.

#### Acceptance Criteria

1. WHEN a signal event occurs at row index t, THE Signal_Conditional_Analyzer SHALL compute the 3-day forward return as `close[t+3] / close[t] - 1`.
2. WHEN a signal event occurs at row index t, THE Signal_Conditional_Analyzer SHALL compute the 5-day forward return as `close[t+5] / close[t] - 1`.
3. WHEN a signal event occurs at row index t, THE Signal_Conditional_Analyzer SHALL compute the 10-day forward return as `close[t+10] / close[t] - 1`.
4. IF a signal event occurs at row index t and fewer than N rows exist after index t in the dataset (where N is the forward-return horizon), THEN THE Signal_Conditional_Analyzer SHALL exclude that event from the N-day horizon analysis rather than computing a partial return.
5. THE Signal_Conditional_Analyzer SHALL use the close column from the Feature_Dataset for all forward return calculations, where row index refers to positional index in the date-sorted dataset and each consecutive row represents one trading day.
6. IF a signal event occurs at row index t and the close value at row t is zero, THEN THE Signal_Conditional_Analyzer SHALL exclude that event from all forward return calculations.
7. IF a signal event occurs at row index t and the close value at any required future row (t+3, t+5, or t+10) is NaN after NaN-row exclusion has been applied, THEN THE Signal_Conditional_Analyzer SHALL exclude that event from the corresponding horizon analysis.

### Requirement 3: Hit Rate and Performance Metrics

**User Story:** As a quantitative researcher, I want to calculate hit rate, average win, average loss, and profit factor for each signal type and horizon, so that I can assess both the accuracy and the risk-reward profile of each signal.

#### Acceptance Criteria

1. WHEN computing hit rate for a bullish Signal_Type at a given horizon, THE Signal_Conditional_Analyzer SHALL count a hit as any event where the forward return is strictly greater than zero, and a miss for forward returns less than or equal to zero.
2. WHEN computing hit rate for a bearish Signal_Type at a given horizon, THE Signal_Conditional_Analyzer SHALL count a hit as any event where the forward return is strictly less than zero, and a miss for forward returns greater than or equal to zero.
3. THE Signal_Conditional_Analyzer SHALL compute average win as the mean of the absolute values of all forward returns where the signal direction was correct (hits only).
4. THE Signal_Conditional_Analyzer SHALL compute average loss as the mean of the absolute values of all forward returns where the signal direction was incorrect (misses only).
5. THE Signal_Conditional_Analyzer SHALL compute profit factor as the sum of absolute winning returns divided by the sum of absolute losing returns for the signal event set.
6. IF a Signal_Type produces zero signal events for a given ticker at a given horizon, THEN THE Signal_Conditional_Analyzer SHALL report that Signal_Type as having insufficient data for that ticker and horizon rather than computing metrics.
7. IF all forward returns for a Signal_Type are hits (zero misses), THEN THE Signal_Conditional_Analyzer SHALL report profit factor as infinity (represented as `float('inf')` in Python).
8. IF all forward returns for a Signal_Type are misses (zero hits), THEN THE Signal_Conditional_Analyzer SHALL report profit factor as zero.
9. THE Signal_Conditional_Analyzer SHALL compute signal frequency as the number of signal events divided by the number of years in the dataset, where years is calculated as (last_date - first_date).days / 365.25.
10. THE Signal_Conditional_Analyzer SHALL compute all metrics independently for each combination of Signal_Type and forward-return horizon (3-day, 5-day, 10-day).

### Requirement 4: Statistical Significance Testing

**User Story:** As a quantitative researcher, I want to test whether observed hit rates are statistically distinguishable from chance, so that I can avoid acting on random noise.

#### Acceptance Criteria

1. THE Signal_Conditional_Analyzer SHALL compute the unconditional Base_Rate for each forward-return horizon independently per ticker, as the proportion of all dataset rows (not just signal rows) where the forward return for that horizon is strictly positive.
2. WHEN evaluating a Signal_Type at a given horizon for a given ticker, THE Signal_Conditional_Analyzer SHALL perform a two-sided binomial test (scipy.stats.binom_test or scipy.stats.binomtest) comparing the observed number of hits against the unconditional Base_Rate for the corresponding horizon and ticker.
3. THE Signal_Conditional_Analyzer SHALL report the p-value from the binomial test for each Signal_Type, horizon, and ticker combination.
4. THE Signal_Conditional_Analyzer SHALL compute a bootstrap 95% confidence interval on the hit rate using 10000 resamples with replacement, where each resample draws N values (with replacement) from the binary hit/miss array and computes the mean, then reports the 2.5th and 97.5th percentiles as the CI bounds, seeded with numpy random_state 42 for reproducibility.
5. IF a Signal_Type has fewer than 5 events for a given ticker at a given horizon, THEN THE Signal_Conditional_Analyzer SHALL set p_value, ci_lower, and ci_upper to NaN for that combination and include a note in the per-ticker CSV indicating "n<5: insufficient for statistical inference".

### Requirement 5: Multi-Ticker Analysis

**User Story:** As a quantitative researcher, I want to run the analysis across 11 tickers (SPY + 10 stocks), so that I can assess whether signals generalise beyond a single instrument.

#### Acceptance Criteria

1. THE Signal_Conditional_Analyzer SHALL load the Feature_Dataset for each ticker in the Ticker_Universe from its expected file path: `ml_validation_output/SPY_vpa_features.csv` for SPY, and `ml_validation_output/{ticker}/{ticker}_vpa_features.csv` for all other tickers.
2. IF a Feature_Dataset file does not exist or cannot be parsed as valid CSV for a ticker, THEN THE Signal_Conditional_Analyzer SHALL log a warning identifying the missing or malformed ticker file and continue processing the remaining tickers.
3. THE Signal_Conditional_Analyzer SHALL produce metrics independently for each ticker (no cross-ticker aggregation of raw data).
4. THE Signal_Conditional_Analyzer SHALL produce a cross-ticker summary showing, for each Signal_Type and horizon, the median hit rate and the count of tickers where the hit rate is statistically significant at p < 0.05, excluding tickers that had insufficient data for that Signal_Type from both the median calculation and the significance count.
5. IF fewer than 3 tickers have sufficient data for a given Signal_Type and horizon combination, THEN THE Signal_Conditional_Analyzer SHALL note that the cross-ticker summary for that combination has insufficient ticker coverage for reliable conclusions.

### Requirement 6: Output Artefacts

**User Story:** As a quantitative researcher, I want structured output files summarising all results, so that I can review findings and document them in Confluence.

#### Acceptance Criteria

1. THE Signal_Conditional_Analyzer SHALL produce a per-ticker detail CSV (`{ticker}_signal_analysis.csv`) containing one row per Signal_Type per horizon, with columns: signal_type, horizon_days, event_count, hit_rate, base_rate, p_value, ci_lower, ci_upper, avg_win, avg_loss, profit_factor, signals_per_year. IF a Signal_Type has insufficient data for a given ticker (as defined in Requirement 3 criterion 6), THEN THE Signal_Conditional_Analyzer SHALL still include the row in the CSV with event_count set to the actual count and all metric columns (hit_rate, p_value, ci_lower, ci_upper, avg_win, avg_loss, profit_factor) left empty.
2. THE Signal_Conditional_Analyzer SHALL produce a cross-ticker comparison CSV (`signal_comparison_summary.csv`) containing one row per Signal_Type per horizon, with columns: signal_type, horizon_days, median_hit_rate, mean_hit_rate, significant_ticker_count, total_ticker_count, median_profit_factor, best_ticker, best_hit_rate, worst_ticker, worst_hit_rate. The total_ticker_count column SHALL reflect only tickers with sufficient data for that Signal_Type.
3. THE Signal_Conditional_Analyzer SHALL produce a summary text file (`signal_analysis_summary.txt`) containing: the interpretation table (listing each hit-rate band boundary and its corresponding conclusion text as defined in Requirement 7), a per-signal-type-per-horizon conclusion stating which interpretation band the signal falls into based on its median hit rate across tickers, and a ranked list of signals ordered by median hit rate descending (highest median hit rate first) for each horizon.
4. THE Signal_Conditional_Analyzer SHALL write all output artefacts to the `ml_validation_output/` directory.
5. THE Signal_Conditional_Analyzer SHALL include column headers as the first row in all CSV output files, using the exact column names specified in criteria 1 and 2.
6. THE Signal_Conditional_Analyzer SHALL write all numeric values in CSV files as decimal numbers rounded to 4 decimal places (e.g., hit_rate of 55% written as 0.5500), with the exception of event_count which SHALL be written as an integer and signals_per_year which SHALL be rounded to 1 decimal place.

### Requirement 7: Interpretation and Conclusion Logic

**User Story:** As a quantitative researcher, I want an automated interpretation of results based on predefined hit-rate bands, so that I can quickly identify actionable signals.

#### Acceptance Criteria

1. WHEN the median hit rate for a Signal_Type across tickers at a given horizon is less than or equal to 55% AND more than 50% of tickers with sufficient data show p >= 0.05, THE Signal_Conditional_Analyzer SHALL conclude "Signal is noise — remove or reduce signal weight".
2. WHEN the median hit rate for a Signal_Type across tickers at a given horizon is between 55% (exclusive) and 60% (exclusive) AND at least one ticker shows p < 0.05, THE Signal_Conditional_Analyzer SHALL conclude "Weak but real edge — keep signal, consider as filter only".
3. WHEN the median hit rate for a Signal_Type across tickers at a given horizon is greater than or equal to 60% AND at least one ticker shows p < 0.01, THE Signal_Conditional_Analyzer SHALL conclude "Strong signal — build trading strategy around this event type".
4. WHEN the median hit rate for a Signal_Type across tickers at a given horizon is less than 45% AND at least one ticker shows p < 0.05, THE Signal_Conditional_Analyzer SHALL conclude "Reliable contrarian indicator — invert the signal". This criterion takes precedence over criterion 1 when both conditions are met.
5. THE Signal_Conditional_Analyzer SHALL apply the interpretation logic independently for each forward-return horizon (3-day, 5-day, 10-day).
6. IF none of criteria 1-4 match for a Signal_Type at a given horizon, THEN THE Signal_Conditional_Analyzer SHALL conclude "Inconclusive — insufficient statistical evidence".

### Requirement 8: Data Integrity and Robustness

**User Story:** As a quantitative researcher, I want the analysis to handle edge cases gracefully, so that I can trust the results without manual data cleaning.

#### Acceptance Criteria

1. WHEN the Feature_Dataset contains rows with NaN values in the close column, THE Signal_Conditional_Analyzer SHALL exclude those rows before computing forward returns.
2. WHEN the Feature_Dataset contains rows with NaN values in composite_score, acc_dist_flag, acc_dist_type, or acc_dist_score, THE Signal_Conditional_Analyzer SHALL treat those rows as not matching any signal filter.
3. THE Signal_Conditional_Analyzer SHALL sort the Feature_Dataset by date in ascending order before computing forward returns, regardless of the input row order.
4. THE Signal_Conditional_Analyzer SHALL use numpy random_state 42 for the bootstrap confidence interval computation to ensure reproducible results.
5. WHEN the same analysis is run twice on the same input data, THE Signal_Conditional_Analyzer SHALL produce bit-for-byte identical output files.
6. IF after excluding NaN rows and rows with insufficient future data the remaining dataset contains fewer than 2 rows, THEN THE Signal_Conditional_Analyzer SHALL skip the analysis for that ticker and report a warning indicating insufficient data rather than producing empty or erroneous results.

### Requirement 9: Integration with Existing Infrastructure

**User Story:** As a developer, I want the signal-conditional analysis to integrate cleanly with the existing VPA ML validation codebase, so that the project remains maintainable and consistent.

#### Acceptance Criteria

1. THE Signal_Conditional_Analyzer SHALL be implemented as a Python module at `vpa/ml_validation/signal_analysis.py` with a corresponding CLI entry point at `vpa/ml_validation/run_signal_analysis.py`, following the same file and class naming conventions as the existing `analysis.py` and `run_analysis.py`.
2. THE Signal_Conditional_Analyzer CLI entry point SHALL accept optional command-line arguments for output directory (default: `ml_validation_output/`) and SHALL run the full 11-ticker analysis pipeline when invoked with `python -m vpa.ml_validation.run_signal_analysis`.
3. THE Signal_Conditional_Analyzer SHALL import and raise `InsufficientDataError` from `vpa.ml_validation.exceptions` when a ticker has fewer than 2 rows of usable data after NaN exclusion.
4. THE Signal_Conditional_Analyzer SHALL print progress to stdout in the format: `Processing {ticker} ({n}/{total})... {signal_count} signal events found` for each ticker processed.
5. THE Signal_Conditional_Analyzer SHALL complete the full 11-ticker analysis within 60 seconds on a machine with a 4-core CPU and 16GB RAM, given pre-existing CSV files (no network I/O required).
