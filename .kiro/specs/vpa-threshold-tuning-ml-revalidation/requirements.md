# Requirements Document

## Introduction

This feature (Jira SP-313, a 5-point Story in the Side Projects project) tunes the Volume Price Analysis (VPA) scoring thresholds in the `trading` project and re-validates the predictive edge of VPA features with machine learning now that VPA 0.5 is complete (SP-304 MA crossover 50/200 SMA, SP-305 momentum/drawdown filter, SP-306 RSI overbought/oversold).

It builds directly on SP-312, which measured whether VPA features have predictive edge. SP-312 found, on ten years of daily SPY data (2461 labelled rows): a baseline rule-based VPA accuracy of 52.34% (a marginal edge above a 50% coin flip) and an ML walk-forward accuracy of 50.59% ± 3.09% (worse than the baseline). Feature importance was flat (the top feature contributed only 5.8%). The most useful features were `is_shooting_star`, `acc_dist_score`, and `spread_pct_p3`; the volume-backed signals `vol_backed_p1` and `vol_backed_p2` had zero importance. SP-312 concluded the rule-based approach is near-optimal.

The work has three independent-but-related workstreams: (1) tune VPA thresholds informed by the SP-312 feature-importance findings, (2) re-run the ML validation harness after VPA 0.5 and compare against the SP-312 baseline, and (3) test additional individual S&P 500 tickers to check whether VPA has a stronger edge on individual stocks than on the SPY index ETF.

This is an experimental, analysis-driven feature. Threshold changes are applied only when they measurably improve accuracy, every run must be reproducible, and all findings must be documented in Confluence with a clear recommendation on whether to pursue a production ML model.

## Glossary

- **VPA**: Volume Price Analysis — the rule-based scoring approach implemented in the `trading` project under `vpa/`.
- **VPA_Scoring_Engine**: The rule-based component that computes VPA sub-scores and the composite score. Candle-pattern detection (shooting star, hammer, long-legged doji) lives in the `Candle` class in `vpa/app.py`; accumulation/distribution detection lives in `identify_acc_or_dist` in `vpa/app.py`.
- **ML_Validation_Harness**: The analysis pipeline invoked by `python -m vpa.ml_validation.run_analysis`, which generates a labelled feature dataset, computes baseline VPA accuracy, runs walk-forward XGBoost validation, and extracts feature importance (`vpa/ml_validation/`).
- **Baseline_Accuracy**: The next-day-direction accuracy of the rule-based VPA composite score, as computed by the ML_Validation_Harness.
- **ML_Accuracy**: The mean next-day-direction accuracy of the walk-forward XGBoost model, as computed by the ML_Validation_Harness.
- **SP312_Baseline**: The reference results from SP-312 — Baseline_Accuracy 52.34% and ML_Accuracy 50.59% ± 3.09% on SPY.
- **Shooting_Star_Threshold**: The multiplier controlling shooting-star detection. In code, `Candle.CONFIG_SHOOTING_STAR_UPPER_WICK_X_TIMES_BIGGER_THAN_SPREAD` (currently 2) and `Candle.CONFIG_SHOOTING_STAR_UPPER_WICK_X_TIMES_BIGGER_THAN_LOWER_WICK` (currently 2).
- **Acc_Dist_Volume_Percentile**: The volume percentile used by `identify_acc_or_dist` to decide whether a bar is volume-significant (currently the 65th percentile).
- **Test_Count_Requirement**: The count of qualifying bars required to confirm an accumulation/distribution signal.
- **Period_One / Period_Two / Period_Three**: The three rolling look-back windows (5, 25, and 50 bars respectively, per `vpa/config/config.json`).
- **Composite_Score**: The sum of VPA sub-scores (single-candle, trend, multiple-bar, acc/dist, RSI) produced per bar.
- **Volume_Backed_Signal**: A multiple-bar signal flagged per period as `vol_backed_p1`, `vol_backed_p2`, `vol_backed_p3`.
- **Analyst**: The developer running the tuning experiments and ML re-validation.
- **Significant_Improvement**: An ML_Accuracy above 54% (the threshold defined in the ticket for considering a production ML model).

## Requirements

### Requirement 1: Reproducible experiment baseline

**User Story:** As the Analyst, I want every tuning and validation run to be reproducible, so that I can trust comparisons between runs and against the SP312_Baseline.

#### Acceptance Criteria

1. WHEN the ML_Validation_Harness is run, THE ML_Validation_Harness SHALL set the fixed random seed (value 42) before dataset generation and before model training.
2. WHEN the ML_Validation_Harness completes a run, THE ML_Validation_Harness SHALL record, in a single saved output artefact, the ticker, data date range, labelled row count, Baseline_Accuracy, mean ML_Accuracy, ML_Accuracy standard deviation, the number of skipped walk-forward folds, and the top five ranked feature-importance values with their scores, all numeric values expressed to at least two decimal places.
3. WHEN the ML_Validation_Harness completes a run, THE ML_Validation_Harness SHALL record the VPA threshold values in effect for that run in the same saved output artefact.
4. WHEN two runs use identical input data, identical threshold values, and identical seed, THE ML_Validation_Harness SHALL produce Baseline_Accuracy and mean ML_Accuracy values that are identical to two decimal places.
5. IF the ML_Validation_Harness produces zero labelled rows or the input data for the requested ticker is unavailable, THEN THE ML_Validation_Harness SHALL halt without writing a partial artefact and SHALL report an error identifying the ticker.

### Requirement 2: Tune shooting-star detection threshold

**User Story:** As the Analyst, I want to tune the Shooting_Star_Threshold, so that the most predictive VPA feature (`is_shooting_star`) contributes maximum accuracy.

#### Acceptance Criteria

1. THE Analyst SHALL evaluate Baseline_Accuracy on a single fixed held-out evaluation dataset for the current Shooting_Star_Threshold value (2) and for at least one tighter candidate value (greater than the current value) and one looser candidate value (less than the current value but greater than or equal to 1), using the same dataset and the same accuracy measurement for every candidate so that results are reproducible across repeated runs.
2. WHEN a candidate Shooting_Star_Threshold value increases Baseline_Accuracy by at least an improvement margin of 0.5 percentage points above the Baseline_Accuracy measured for the current threshold value, THE Analyst SHALL record the candidate value and its measured Baseline_Accuracy.
3. IF more than one candidate Shooting_Star_Threshold value increases Baseline_Accuracy by at least 0.5 percentage points above the current threshold value, THEN THE Analyst SHALL select and record the single candidate with the highest measured Baseline_Accuracy, resolving an exact tie in favor of the candidate closest to the current value (2).
4. IF no candidate Shooting_Star_Threshold value increases Baseline_Accuracy by at least 0.5 percentage points above the current threshold value, THEN THE Analyst SHALL retain the current threshold value (2) and record that no change was beneficial.
5. IF a candidate Shooting_Star_Threshold value is less than 1 or is not a positive number, THEN THE Analyst SHALL exclude that candidate from evaluation and record a validation message indicating the candidate was rejected as out of range.
6. WHERE a Shooting_Star_Threshold change is applied, THE VPA_Scoring_Engine SHALL use the new threshold value for all subsequent scoring.

### Requirement 3: Tune accumulation/distribution scoring

**User Story:** As the Analyst, I want to tune the Acc_Dist_Volume_Percentile and the Test_Count_Requirement, so that the second most predictive feature (`acc_dist_score`) contributes maximum accuracy.

#### Acceptance Criteria

1. THE Analyst SHALL evaluate Baseline_Accuracy for the current Acc_Dist_Volume_Percentile (65) and for at least one higher candidate value and one lower candidate value, where each candidate is a distinct integer in the range 1 to 99 inclusive and differs from the current value.
2. THE Analyst SHALL evaluate Baseline_Accuracy for at least two distinct Test_Count_Requirement candidate values, where each candidate is a distinct integer greater than or equal to 1 and differs from the current value (3).
3. WHEN a candidate Acc_Dist_Volume_Percentile or Test_Count_Requirement value yields a Baseline_Accuracy that is strictly greater than the Baseline_Accuracy measured for the current configuration by at least 0.1 percentage points, THE Analyst SHALL record the candidate value and its measured Baseline_Accuracy.
4. THE Analyst SHALL record the measured Baseline_Accuracy for every evaluated candidate value, whether or not it exceeds the current configuration's Baseline_Accuracy.
5. IF no candidate value yields a Baseline_Accuracy strictly greater than the current configuration's Baseline_Accuracy by at least 0.1 percentage points, THEN THE Analyst SHALL retain the current Acc_Dist_Volume_Percentile (65) and Test_Count_Requirement (3) values and record that no change was beneficial.
6. IF Baseline_Accuracy cannot be measured for a candidate value, THEN THE Analyst SHALL exclude that candidate from selection and record an error indicating the candidate value could not be evaluated, while retaining all previously recorded candidate results.

### Requirement 4: Weight period-three signals in the composite score

**User Story:** As the Analyst, I want to test weighting Period_Three signals more heavily in the Composite_Score, so that the composite reflects that period-three features (e.g. `spread_pct_p3`) are more predictive than period-one and period-two features.

#### Acceptance Criteria

1. WHEN evaluating composite weightings, THE Analyst SHALL measure Baseline_Accuracy for the current composite weighting and for at least one alternative weighting that increases the combined Period_Three contribution to the Composite_Score above the combined Period_One and Period_Two contributions, with every weighting configuration evaluated on identical input data and the same fixed random seed.
2. WHEN an increased Period_Three weighting produces a Baseline_Accuracy that exceeds the current weighting's Baseline_Accuracy by at least 0.10 percentage points, THE Analyst SHALL record the weighting configuration and its measured Baseline_Accuracy.
3. IF no increased Period_Three weighting produces a Baseline_Accuracy exceeding the current weighting's Baseline_Accuracy by at least 0.10 percentage points, THEN THE Analyst SHALL retain the current weighting and record that no change was beneficial.

### Requirement 5: Reduce or remove zero-importance volume-backed signals

**User Story:** As the Analyst, I want to reduce or remove the weight of the `vol_backed_p1` and `vol_backed_p2` signals, so that signals with zero measured importance do not dilute the Composite_Score.

#### Acceptance Criteria

1. THE Analyst SHALL evaluate Baseline_Accuracy on the same labelled dataset and scoring configuration for the current `vol_backed_p1` and `vol_backed_p2` contributions and for a configuration where those contributions are removed, or reduced to a non-negative weight below their current weight.
2. WHEN removing or reducing the `vol_backed_p1` and `vol_backed_p2` contributions produces a Baseline_Accuracy greater than or equal to the current configuration's Baseline_Accuracy minus 0.10 percentage points, THE Analyst SHALL record the change and its measured Baseline_Accuracy.
3. WHERE the `vol_backed_p1` and `vol_backed_p2` contributions are removed or reduced, THE VPA_Scoring_Engine SHALL continue to produce a Composite_Score for every scored bar.
4. IF removing or reducing the `vol_backed_p1` and `vol_backed_p2` contributions produces a Baseline_Accuracy more than 0.10 percentage points below the current configuration's Baseline_Accuracy, THEN THE Analyst SHALL retain the current contributions and record that no change was beneficial.

### Requirement 6: Apply threshold changes only when beneficial

**User Story:** As the Analyst, I want threshold changes gated on measured improvement, so that the VPA configuration is only altered when it demonstrably helps.

#### Acceptance Criteria

1. WHEN a tuned threshold value increases Baseline_Accuracy by at least the SP312_Baseline standard deviation (3.09 percentage points) above the Baseline_Accuracy measured for the value currently in effect in the VPA configuration, THE Analyst SHALL apply the tuned value to the VPA configuration.
2. IF a tuned threshold value increases Baseline_Accuracy by less than 3.09 percentage points above, equals, or decreases Baseline_Accuracy relative to the value currently in effect in the VPA configuration, THEN THE Analyst SHALL leave the currently-in-effect value unchanged.
3. WHEN a tuned threshold value is applied to the VPA configuration, THE Analyst SHALL document the prior value, the applied value, the prior Baseline_Accuracy, the new Baseline_Accuracy, and the Baseline_Accuracy difference that justified the change.

### Requirement 7: Re-run ML validation after VPA 0.5

**User Story:** As the Analyst, I want to re-run the ML_Validation_Harness on SPY after VPA 0.5, so that I can measure whether the completed VPA 0.5 features change the predictive edge versus the SP312_Baseline.

#### Acceptance Criteria

1. WHEN the Analyst runs `python -m vpa.ml_validation.run_analysis --ticker SPY`, THE ML_Validation_Harness SHALL produce and record a Baseline_Accuracy and a mean ML_Accuracy with its standard deviation for SPY, each expressed as a percentage to at least two decimal places.
2. IF the SPY run fails or SPY input data is unavailable, THEN THE ML_Validation_Harness SHALL report an error, SHALL NOT output a Baseline_Accuracy or ML_Accuracy, and the Analyst SHALL record that the run did not complete.
3. WHEN the SPY run completes, THE Analyst SHALL record the signed percentage-point difference of the SPY Baseline_Accuracy against the SP312_Baseline Baseline_Accuracy (52.34%) and of the SPY mean ML_Accuracy against the SP312_Baseline mean ML_Accuracy (50.59%).
4. WHEN the SPY run completes, THE Analyst SHALL classify the SPY mean ML_Accuracy as increased where it is above 53.68%, decreased where it is below 47.50%, or within the SP312_Baseline standard-deviation band where it is between 47.50% and 53.68% inclusive, and SHALL classify the SPY Baseline_Accuracy as increased, decreased, or unchanged relative to 52.34%.

### Requirement 8: Decide whether to pursue a production ML model

**User Story:** As the Analyst, I want a defined decision rule for pursuing a production ML model, so that further ML investment is justified by measured results.

#### Acceptance Criteria

1. WHEN the completed SPY run has produced a mean ML_Accuracy value and that value is strictly greater than 54.0% (a Significant_Improvement), THE Analyst SHALL record a recommendation to consider building a production ML model.
2. IF the completed SPY run has produced a mean ML_Accuracy value and that value is less than or equal to 54.0% (not a Significant_Improvement), THEN THE Analyst SHALL record a recommendation not to pursue a production ML model at this time.
3. WHEN the Analyst records a recommendation, THE Analyst SHALL state alongside it the mean ML_Accuracy value (expressed as a percentage to at least two decimal places) that supports the recommendation.
4. IF the SPY run did not produce a mean ML_Accuracy value, THEN THE Analyst SHALL record that no recommendation can be made and SHALL state that the SPY ML_Accuracy was unavailable.

### Requirement 9: Test additional individual tickers

**User Story:** As the Analyst, I want to run the ML_Validation_Harness on several individual S&P 500 stocks, so that I can test the hypothesis that VPA has a stronger edge on individual stocks than on the SPY index ETF.

#### Acceptance Criteria

1. THE Analyst SHALL run the ML_Validation_Harness on at least three and at most five individual S&P 500 stocks, selected so that each selected ticker's realized daily-return volatility over the run's data date range differs from every other selected ticker's by at least 10 percent of the lowest selected ticker's volatility.
2. WHEN each individual-ticker run completes, THE ML_Validation_Harness SHALL produce a Baseline_Accuracy and an ML_Accuracy for that ticker.
3. WHEN all individual-ticker runs complete, THE Analyst SHALL record, for each ticker, the difference between that ticker's Baseline_Accuracy and the SPY Baseline_Accuracy.
4. WHEN all individual-ticker runs complete, THE Analyst SHALL classify each ticker as showing a stronger VPA edge where its Baseline_Accuracy exceeds the SPY Baseline_Accuracy by more than 3.09 percentage points, a weaker VPA edge where its Baseline_Accuracy is below the SPY Baseline_Accuracy by more than 3.09 percentage points, and a comparable VPA edge where its Baseline_Accuracy is within 3.09 percentage points of the SPY Baseline_Accuracy.
5. IF the ML_Validation_Harness produces fewer than 2000 labelled rows for a selected ticker, THEN THE ML_Validation_Harness SHALL report an error that identifies the ticker, SHALL NOT record a Baseline_Accuracy or ML_Accuracy for that ticker, and the Analyst SHALL select a replacement ticker that satisfies the volatility-spread condition in criterion 1.

### Requirement 10: Document findings and recommendation

**User Story:** As the Analyst, I want all results and the final recommendation documented in Confluence, so that the experiment outcome is traceable and persists beyond the ticket.

#### Acceptance Criteria

1. WHEN the threshold-adjustment evaluation completes, THE Analyst SHALL document in the Side Projects Confluence space, for each threshold adjustment evaluated, the adjustment identifier, whether it was applied, and the measured accuracy difference versus baseline expressed as a signed numeric value.
2. WHEN the SPY re-validation completes, THE Analyst SHALL document in the Side Projects Confluence space the SPY re-validation ML_Accuracy value alongside the SP312_Baseline ML_Accuracy value and the signed difference between them.
3. WHEN the individual-ticker evaluation completes, THE Analyst SHALL document in the Side Projects Confluence space the ML_Accuracy value for each individual ticker evaluated and the signed difference between the SPY ML_Accuracy value and each individual-ticker ML_Accuracy value.
4. WHEN all evaluations are documented, THE Analyst SHALL document in the Side Projects Confluence space a recommendation stated as exactly one of "pursue" or "do not pursue" a production ML model, accompanied by the supporting ML_Accuracy value as a numeric value.
5. THE Analyst SHALL record in the Side Projects Confluence documentation, for each reported result, the exact threshold values and the integer random seed used to produce that result.
6. IF any required result value (accuracy difference, ML_Accuracy, threshold value, or seed) is unavailable at documentation time, THEN THE Analyst SHALL record in the Side Projects Confluence documentation an explicit marker indicating the value is unavailable and the reason it is unavailable.
