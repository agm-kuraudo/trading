# Requirements Document

## Introduction

This feature validates whether VPA (Volume Price Analysis) intermediate features contain predictive information about next-day price direction for SPY. The output is a go/no-go decision: either VPA has a measurable predictive edge (and where that edge comes from), or it does not. This is an experimental spike — the primary deliverable is a documented conclusion backed by reproducible analysis.

## Glossary

- **VPA_Feature_Extractor**: The component that extracts intermediate signal features from the existing MarketAnalyzer during candle processing
- **Feature_Vector**: A single row of extracted VPA features corresponding to one trading day, including spread percentiles, volume percentiles, ADX values, bar counts, candle pattern flags, and sub-scores
- **Historical_Dataset**: A CSV file containing Feature_Vectors for 2500+ trading days of SPY data, each labelled with actual next-day price direction
- **Analysis_Script**: The component that trains an XGBoost model on Feature_Vectors and produces accuracy metrics and feature importance rankings
- **Walk_Forward_Validator**: The component that implements TimeSeriesSplit cross-validation to prevent look-ahead bias in model evaluation
- **VPA_Composite_Score**: The existing final trade_signal value produced by MarketAnalyzer (sum of all sub-scores)
- **Predictive_Edge**: Classification accuracy statistically above 50% (random baseline) on unseen future data
- **Feature_Importance_Report**: A ranked list of VPA features by their contribution to model predictive power

## Requirements

### Requirement 1: Feature Extraction from MarketAnalyzer

**User Story:** As a quantitative researcher, I want to extract VPA intermediate features as a structured vector for each trading day, so that I can analyse their predictive power independently of the existing scoring rules.

#### Acceptance Criteria

1. WHEN the VPA_Feature_Extractor processes a candle and all rolling windows are full, THE VPA_Feature_Extractor SHALL produce a Feature_Vector containing one numeric value per field: spread percentile for period_one, spread percentile for period_two, spread percentile for period_three; volume percentile for period_one, volume percentile for period_two, volume percentile for period_three; ADX value; smoothed DM+ value; smoothed DM- value; smoothed Average True Range; up bar ratio for period_one, up bar ratio for period_two, up bar ratio for period_three; candle pattern flags (shooting_star, hammer, long_legged_doji) each represented as 1 or 0; volume-backed signal flag for period_one, volume-backed signal flag for period_two, volume-backed signal flag for period_three each represented as 1 or 0; accumulation/distribution flag represented as 1 or 0; accumulation/distribution type encoded as 1 for accumulation, -1 for distribution, and 0 for neither; and each of the four VPA sub-scores (single_candle_signal_score, trend_signal_score, multiple_bar_signal_score, acc_dist_signal_score) as floating-point values
2. WHEN the VPA_Feature_Extractor processes a candle before the period_three rolling window contains the configured PERIOD_THREE_LENGTH number of candles, THE VPA_Feature_Extractor SHALL skip that candle and produce no Feature_Vector
3. IF feature extraction is not enabled via the configuration flag, THEN THE VPA_Feature_Extractor SHALL delegate processing to MarketAnalyzer and produce identical outputs to the existing MarketAnalyzer behaviour with no Feature_Vector generation
4. WHEN a Feature_Vector is produced, THE VPA_Feature_Extractor SHALL include the trading date as an ISO-8601 date string and the closing price as a floating-point number in separate metadata fields that are excluded from the numeric feature array
5. WHEN a Feature_Vector is produced, THE VPA_Feature_Extractor SHALL return the Feature_Vector as a single row appendable to a tabular dataset, with one named column per feature in a fixed order consistent across all invocations

### Requirement 2: Historical Dataset Generation

**User Story:** As a quantitative researcher, I want to generate a labelled historical dataset of VPA features over 500+ trading days, so that I can train and evaluate ML models.

#### Acceptance Criteria

1. WHEN the Historical_Dataset generation is run for a ticker symbol, THE VPA_Feature_Extractor SHALL download at least 10 years (3650 calendar days) of daily OHLCV data from yfinance (to yield 2500+ trading days after rolling window warm-up)
2. WHEN the Historical_Dataset is generated, THE VPA_Feature_Extractor SHALL label each Feature_Vector row with the actual next-day price direction (1 for UP, 0 for DOWN) based on whether the next day's close is strictly higher than the current day's close; IF the next day's close equals the current day's close, THEN THE VPA_Feature_Extractor SHALL label that row as 0 (DOWN)
3. THE VPA_Feature_Extractor SHALL output the Historical_Dataset as a CSV file named "{ticker}_vpa_features.csv" with a header row containing descriptive column names
4. IF the downloaded data contains fewer than 2000 valid labelled rows after rolling window warm-up, THEN THE VPA_Feature_Extractor SHALL raise an error indicating insufficient data
5. WHEN the Historical_Dataset is generated, THE VPA_Feature_Extractor SHALL exclude the final row (which has no next-day label)
6. IF any downloaded row contains NaN or missing values in OHLCV columns, THEN THE VPA_Feature_Extractor SHALL drop that row before processing

### Requirement 3: Baseline VPA Accuracy Measurement

**User Story:** As a quantitative researcher, I want to measure the raw predictive accuracy of the existing VPA composite score, so that I have a baseline to compare ML performance against.

#### Acceptance Criteria

1. WHEN the Analysis_Script evaluates baseline accuracy, THE Analysis_Script SHALL classify each row as UP (predicted) when VPA_Composite_Score is greater than zero, and DOWN (predicted) when VPA_Composite_Score is less than or equal to zero
2. WHEN the Analysis_Script evaluates baseline accuracy, THE Analysis_Script SHALL compute accuracy as the proportion of rows where the predicted direction matches the Actual_Direction label, divided by the total count of rows with a non-null Actual_Direction label
3. THE Analysis_Script SHALL report the baseline VPA accuracy as a percentage with two decimal places to standard output
4. IF any row has a null or missing VPA_Composite_Score value, THEN THE Analysis_Script SHALL exclude that row from the baseline accuracy calculation
5. IF the Historical_Dataset contains zero labelled rows, THEN THE Analysis_Script SHALL report an error and terminate without producing a baseline accuracy value

### Requirement 4: Walk-Forward ML Model Training

**User Story:** As a quantitative researcher, I want to train an XGBoost classifier on VPA features using walk-forward validation, so that I can measure predictive power without look-ahead bias.

#### Acceptance Criteria

1. THE Walk_Forward_Validator SHALL use scikit-learn TimeSeriesSplit with exactly 5 splits for cross-validation
2. WHEN training the model, THE Analysis_Script SHALL use only Feature_Vector columns as inputs (excluding metadata columns: date, closing price, and the label column)
3. WHEN the Walk_Forward_Validator performs a split, THE Walk_Forward_Validator SHALL use only chronologically earlier data for training and chronologically later data for testing
4. THE Analysis_Script SHALL use XGBoost (XGBClassifier) with default hyperparameters as the classification model, with a fixed random_state seed of 42 for reproducibility
5. WHEN model evaluation is complete, THE Analysis_Script SHALL report mean accuracy across all walk-forward splits as a percentage with two decimal places (e.g. "72.34%")
6. WHEN model evaluation is complete, THE Analysis_Script SHALL report standard deviation of accuracy across splits as a percentage with two decimal places (e.g. "3.21%")
7. IF a walk-forward split produces a training fold with fewer than 30 samples or a test fold with fewer than 10 samples, THEN THE Walk_Forward_Validator SHALL skip that split and log a warning indicating the fold number and available sample count
8. IF all walk-forward splits are skipped due to insufficient data, THEN THE Analysis_Script SHALL terminate evaluation and report an error message indicating that the dataset contains insufficient rows for walk-forward validation with 5 splits

### Requirement 5: Feature Importance Ranking

**User Story:** As a quantitative researcher, I want to know which VPA features contribute most to predictive power, so that I can understand where signal exists.

#### Acceptance Criteria

1. WHEN model training is complete, THE Analysis_Script SHALL extract gain-based feature importance scores from the trained XGBoost model
2. THE Analysis_Script SHALL produce the Feature_Importance_Report as a ranked list of all VPA features sorted by importance score in descending order
3. WHEN the Feature_Importance_Report is generated, THE Analysis_Script SHALL include both the feature name and its normalised importance score (summing to 1.0) with 4 decimal places
4. IF all features have zero importance, THEN THE Analysis_Script SHALL report a warning indicating that the model found no distinguishing features and produce the report with all scores set to 0.0000

### Requirement 6: Conclusion and Interpretation

**User Story:** As a quantitative researcher, I want a clear documented conclusion on whether VPA has predictive edge, so that I can decide the next step for the ML trader project.

#### Acceptance Criteria

1. WHEN the Analysis_Script completes all evaluations, THE Analysis_Script SHALL print a summary containing: baseline VPA accuracy, ML walk-forward mean accuracy, the top 5 features by gain-based importance, and a conclusion statement as defined in criteria 2 through 6
2. IF VPA baseline accuracy is less than or equal to 52% AND ML mean accuracy is less than or equal to 52%, THEN THE Analysis_Script SHALL conclude "No predictive edge detected"
3. IF VPA baseline accuracy is less than or equal to 52% AND ML mean accuracy exceeds 52%, THEN THE Analysis_Script SHALL conclude "Features have signal but scoring rules are suboptimal"
4. IF VPA baseline accuracy exceeds 52% AND ML mean accuracy exceeds VPA baseline accuracy by more than 2 percentage points, THEN THE Analysis_Script SHALL conclude "Real edge exists and ML improves it"
5. IF VPA baseline accuracy exceeds 52% AND ML mean accuracy is within 2 percentage points (inclusive) of VPA baseline accuracy, THEN THE Analysis_Script SHALL conclude "Rule-based approach is near-optimal"
6. IF VPA baseline accuracy exceeds 52% AND ML mean accuracy is more than 2 percentage points below VPA baseline accuracy, THEN THE Analysis_Script SHALL conclude "Rule-based approach outperforms ML on this dataset"

### Requirement 7: Output Artefacts

**User Story:** As a quantitative researcher, I want all outputs saved to disk, so that I can review results later and share findings.

#### Acceptance Criteria

1. THE Analysis_Script SHALL save the Historical_Dataset CSV to the ml_validation output directory with filename "{ticker}_vpa_features.csv"
2. THE Analysis_Script SHALL save the Feature_Importance_Report to the ml_validation output directory as a CSV file with filename "{ticker}_feature_importance.csv"
3. THE Analysis_Script SHALL save the summary conclusion as a text file to the ml_validation output directory with filename "{ticker}_analysis_summary.txt" containing baseline accuracy, ML accuracy, top 5 features, conclusion statement, and data date range
4. WHEN the Analysis_Script is executed, THE Analysis_Script SHALL create the ml_validation output directory if it does not already exist
5. IF any output file already exists in the ml_validation output directory, THEN THE Analysis_Script SHALL overwrite the existing file without prompting
6. IF writing any output file fails due to a filesystem error, THEN THE Analysis_Script SHALL log the error with the file path and continue processing remaining outputs

### Requirement 8: Reproducibility

**User Story:** As a quantitative researcher, I want the analysis to be reproducible, so that I can re-run it and get consistent results.

#### Acceptance Criteria

1. THE Analysis_Script SHALL set the XGBoost random_state parameter to a fixed seed value of 42
2. THE Analysis_Script SHALL set the NumPy random seed to 42 at the start of execution
3. THE Analysis_Script SHALL log the date range (earliest and latest trading dates) of data used in the analysis to the summary output
4. THE Analysis_Script SHALL log the number of valid feature rows used after warm-up period exclusion to the summary output
5. WHEN the Analysis_Script is run with the same input data CSV file, THE Analysis_Script SHALL produce identical accuracy metrics and feature importance rankings regardless of execution date or environment
