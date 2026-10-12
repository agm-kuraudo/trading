# Requirements Document

## Introduction

This feature integrates the existing **price vs SMA** signal (shipped live under SP-326 inside `MarketAnalyzer`) into the ML feature-extraction and backtesting / signal-analysis path, so that it can be studied as a first-class, independently backtestable signal alongside RSI, accumulation/distribution, and the DSS Bressert crossover.

The scope decision is **already settled** and is recorded here so it is not re-opened during design or implementation:

- **Decision: Option B — "keep standalone".** The price vs SMA signal is added as its own ML feature pair and its own backtestable `SignalType`, mirroring how RSI is represented as a feature and how the DSS crossover is represented as a signal. It is **not** merged into any existing signal and is **not** folded into the extractor's composite score.
- The ML / backtest path **reimplements the signal logic inline** in `VPAFeatureExtractor`. It MUST NOT call `MarketAnalyzer`; the live SP-326 implementation (`compute_price_vs_sma_column`, `detect_price_vs_sma_signals`) is a behavioural reference only.
- **Hard zero-regression constraint:** the extractor's `composite_score` line MUST remain byte-for-byte unchanged. `price_vs_sma_signal_score` is excluded from the composite, exactly like `ma_crossover_signal_score` is excluded today. This guarantees existing `STRONG_BULLISH` / `STRONG_BEARISH` classification, ML outputs, and backtest / daily-signal outputs do not change.

The feature touches four areas:
1. `VPAFeatureExtractor` — two new feature columns computed inline (`price_vs_sma_value`, `price_vs_sma_signal_score`).
2. `signal_analysis` — two new `SignalType` members (`PRICE_ABOVE_SMA`, `PRICE_BELOW_SMA`), their `SIGNAL_DIRECTIONS` entries, and column-presence-guarded classification.
3. `daily_signal` — `CONFIDENCE_MAP` and `classify_last_row` wiring following existing conventions.
4. Tests — new/updated unit tests, corrected hardcoded feature counts, and a composite-score regression guard.

## Glossary

- **VPAFeatureExtractor**: The class in `vpa/ml_validation/feature_extractor.py` that reproduces `MarketAnalyzer` logic inline to emit a fixed-order numeric feature vector per trading day for ML analysis.
- **FEATURE_COLUMNS**: The ordered list of ML feature column names on `VPAFeatureExtractor`. Currently 31 entries; becomes 33 after this feature.
- **Composite_Score**: The `composite_score` feature column = `single_candle_score + trend_score + multiple_bar_score + acc_dist_score + rsi_signal_score`. It deliberately omits `ma_crossover` and, per the settled decision, will continue to omit `price_vs_sma`.
- **Price_Vs_SMA_Value**: New ML feature column `price_vs_sma_value` holding the computed Simple Moving Average (SMA) of close over the configured period for the current row.
- **Price_Vs_SMA_Signal_Score**: New ML feature column `price_vs_sma_signal_score` holding the position-based score of close relative to the SMA, plus an optional crossover score when `price_vs_sma.detect_crossover` is enabled (the combined value, e.g. `+5` position plus `+3` cross-above = `+8`, mirroring the live `MarketAnalyzer.detect_price_vs_sma_signals` implementation). Its sign (positive / negative) drives the PRICE_ABOVE_SMA / PRICE_BELOW_SMA classification; crossover reinforces the same direction as the position score.
- **SMA**: Simple Moving Average of the close price over the configured period (`price_vs_sma.period`, default 10), computed with a minimum-periods requirement equal to the period (no partial-window value emitted during warm-up).
- **Price_Vs_SMA_Config**: The `price_vs_sma` configuration section, modelled by `PriceVsSMASettings` in `vpa/config/settings.py` and read via `self._config.price_vs_sma`. Fields: `enabled` (bool), `period` (int, default 10), `scores.above` / `scores.below` (numbers, default 5), `detect_crossover` (bool, default false), `crossover_scores.cross_above` / `crossover_scores.cross_below` (numbers, default 3).
- **SignalType**: The enum in `vpa/ml_validation/signal_analysis.py` enumerating backtestable high-conviction signal categories.
- **SIGNAL_DIRECTIONS**: The mapping in `signal_analysis` from each `SignalType` to its expected `SignalDirection` (UP / DOWN).
- **SignalConditionalAnalyzer**: The class in `signal_analysis` whose `classify_signals` method matches rows to signal types and whose pipeline computes per-signal hit-rate statistics across forward horizons.
- **classify_signals**: `SignalConditionalAnalyzer.classify_signals(df)` — returns matched row indices per `SignalType`; uses column-presence guards (e.g. `if "dss_bullish_cross" in df.columns:`) for optional columns.
- **classify_last_row**: `daily_signal.classify_last_row(df)` — classifies the final feature row into a set of `SignalType` values for the daily signal generator.
- **CONFIDENCE_MAP**: The `dict[SignalType, str]` in `daily_signal.py` mapping a signal type to a confidence label.
- **DSS_Precedent**: The existing DSS Bressert crossover integration (`SignalType.DSS_BULLISH` / `DSS_BEARISH`, their `SIGNAL_DIRECTIONS` entries, and the `if "dss_bullish_cross" in df.columns:` guarded classification) that this feature mirrors exactly.
- **MarketAnalyzer**: The live production analyzer in `vpa/app_runner.py` that holds the SP-326 price vs SMA implementation. Reference only — not called from the ML / backtest path.

## Requirements

### Requirement 1: Record the settled scope decision

**User Story:** As a maintainer, I want the "standalone, no composite fold" decision captured in the spec, so that the design and implementation do not re-open a settled question.

#### Acceptance Criteria

1. THE Requirements_Document SHALL record that the chosen approach is Option B (standalone price vs SMA signal with no composite fold).
2. THE Requirements_Document SHALL record that the ML / backtest path reimplements the price vs SMA logic inline and does not call MarketAnalyzer.
3. THE Requirements_Document SHALL record that `price_vs_sma_signal_score` is excluded from Composite_Score.

### Requirement 2: Add price vs SMA feature columns to the extractor

**User Story:** As an ML analyst, I want the price vs SMA signal represented in the feature dataset, so that its predictive value can be studied alongside existing features.

#### Acceptance Criteria

1. THE VPAFeatureExtractor SHALL include `price_vs_sma_value` and `price_vs_sma_signal_score` in FEATURE_COLUMNS.
2. THE VPAFeatureExtractor SHALL define FEATURE_COLUMNS with exactly 33 entries after `price_vs_sma_value` and `price_vs_sma_signal_score` are added to the existing 31.
3. WHEN a feature vector is extracted, THE VPAFeatureExtractor SHALL emit a numeric value for `price_vs_sma_value` and a numeric value for `price_vs_sma_signal_score`.
4. THE VPAFeatureExtractor SHALL produce `price_vs_sma_value` and `price_vs_sma_signal_score` keys whose position in the emitted feature-vector dict matches their position in FEATURE_COLUMNS.
5. THE VPAFeatureExtractor SHALL read price vs SMA configuration from `self._config.price_vs_sma`.

### Requirement 3: Compute the price vs SMA score inline, mirroring RSI

**User Story:** As a maintainer, I want the price vs SMA computation implemented inline in the extractor like RSI, so that the ML path stays self-contained and does not depend on MarketAnalyzer.

#### Acceptance Criteria

1. THE VPAFeatureExtractor SHALL compute Price_Vs_SMA_Value as the mean of the current period's close prices over `price_vs_sma.period` trading days.
2. WHILE fewer than `price_vs_sma.period` closes are available for the current row, THE VPAFeatureExtractor SHALL treat Price_Vs_SMA_Value as unavailable and SHALL emit a `price_vs_sma_signal_score` of 0.0.
3. WHEN the current close exceeds Price_Vs_SMA_Value, THE VPAFeatureExtractor SHALL set `price_vs_sma_signal_score` to positive `price_vs_sma.scores.above`.
4. WHEN the current close is below Price_Vs_SMA_Value, THE VPAFeatureExtractor SHALL set `price_vs_sma_signal_score` to negative `price_vs_sma.scores.below`.
5. WHEN the current close equals Price_Vs_SMA_Value, THE VPAFeatureExtractor SHALL set `price_vs_sma_signal_score` to 0.0.
6. WHERE `price_vs_sma.enabled` is false, THE VPAFeatureExtractor SHALL emit a `price_vs_sma_signal_score` of 0.0.
7. THE VPAFeatureExtractor SHALL compute `price_vs_sma_signal_score` using the same position-based scoring rules that MarketAnalyzer.detect_price_vs_sma_signals applies (close above SMA adds `scores.above`; close below SMA subtracts `scores.below`; equal yields 0).
8. WHERE `price_vs_sma.detect_crossover` is true AND a valid previous row exists (positional row index greater than 0) with a non-NaN previous close and a non-NaN previous SMA AND the previous close is at or below the previous SMA AND the current close exceeds Price_Vs_SMA_Value, THE VPAFeatureExtractor SHALL add positive `price_vs_sma.crossover_scores.cross_above` to `price_vs_sma_signal_score`.
9. WHERE `price_vs_sma.detect_crossover` is true AND a valid previous row exists (positional row index greater than 0) with a non-NaN previous close and a non-NaN previous SMA AND the previous close is at or above the previous SMA AND the current close is below Price_Vs_SMA_Value, THE VPAFeatureExtractor SHALL subtract `price_vs_sma.crossover_scores.cross_below` from `price_vs_sma_signal_score`.
10. WHERE `price_vs_sma.detect_crossover` is true AND no valid previous row exists (positional row index equal to 0) OR the previous close is NaN OR the previous SMA is NaN, THE VPAFeatureExtractor SHALL add no crossover contribution to `price_vs_sma_signal_score`.
11. WHERE `price_vs_sma.detect_crossover` is false, THE VPAFeatureExtractor SHALL add no crossover contribution to `price_vs_sma_signal_score`, leaving the position-only score.
12. THE VPAFeatureExtractor SHALL compute the combined `price_vs_sma_signal_score` as the sum of the position-based score and the optional crossover score, matching the combined score produced by MarketAnalyzer.detect_price_vs_sma_signals for the same row and configuration.

### Requirement 4: Preserve Composite_Score exactly (zero regression)

**User Story:** As a maintainer, I want the composite score untouched, so that existing classification, ML results, and backtest / daily outputs do not regress.

#### Acceptance Criteria

1. THE VPAFeatureExtractor SHALL compute Composite_Score as `single_candle_score + trend_score + multiple_bar_score + acc_dist_score + rsi_signal_score`.
2. THE VPAFeatureExtractor SHALL exclude `price_vs_sma_signal_score` from Composite_Score.
3. FOR ALL input rows, THE VPAFeatureExtractor SHALL produce a Composite_Score equal to the value produced before `price_vs_sma_value` and `price_vs_sma_signal_score` were added.

### Requirement 5: Register price vs SMA as a backtestable signal

**User Story:** As an analyst, I want price vs SMA recognised as its own signal in signal analysis, so that it gets hit-rate statistics across forward horizons like other signals.

#### Acceptance Criteria

1. THE signal_analysis module SHALL define `SignalType.PRICE_ABOVE_SMA` and `SignalType.PRICE_BELOW_SMA`.
2. THE signal_analysis module SHALL map `SignalType.PRICE_ABOVE_SMA` to `SignalDirection.UP` in SIGNAL_DIRECTIONS.
3. THE signal_analysis module SHALL map `SignalType.PRICE_BELOW_SMA` to `SignalDirection.DOWN` in SIGNAL_DIRECTIONS.
4. WHEN `price_vs_sma_signal_score` is present in the feature DataFrame, THE classify_signals method SHALL match rows with a positive `price_vs_sma_signal_score` to `SignalType.PRICE_ABOVE_SMA`.
5. WHEN `price_vs_sma_signal_score` is present in the feature DataFrame, THE classify_signals method SHALL match rows with a negative `price_vs_sma_signal_score` to `SignalType.PRICE_BELOW_SMA`.
6. IF `price_vs_sma_signal_score` is absent from the feature DataFrame, THEN THE classify_signals method SHALL leave the `PRICE_ABOVE_SMA` and `PRICE_BELOW_SMA` match lists empty.
7. IF a row's `price_vs_sma_signal_score` is NaN, THEN THE classify_signals method SHALL exclude that row from both `PRICE_ABOVE_SMA` and `PRICE_BELOW_SMA` matches.

### Requirement 6: Wire price vs SMA into the daily signal generator

**User Story:** As a daily-signal consumer, I want the price vs SMA signal to flow through the daily generator consistently, so that its daily classification follows the project's conventions.

#### Acceptance Criteria

1. THE daily_signal module SHALL add a `CONFIDENCE_MAP` entry for `SignalType.PRICE_ABOVE_SMA` with a confidence label drawn from CONFIDENCE_ORDER.
2. THE daily_signal module SHALL add a `CONFIDENCE_MAP` entry for `SignalType.PRICE_BELOW_SMA` with a confidence label drawn from CONFIDENCE_ORDER.
3. WHEN the final feature row has a positive `price_vs_sma_signal_score`, THE classify_last_row function SHALL add `SignalType.PRICE_ABOVE_SMA` to the returned set.
4. WHEN the final feature row has a negative `price_vs_sma_signal_score`, THE classify_last_row function SHALL add `SignalType.PRICE_BELOW_SMA` to the returned set.
5. IF the final feature row's `price_vs_sma_signal_score` is absent or NaN, THEN THE classify_last_row function SHALL add neither `PRICE_ABOVE_SMA` nor `PRICE_BELOW_SMA`.

### Requirement 7: Correct stale feature-count references

**User Story:** As a maintainer, I want outdated feature counts corrected, so that documentation and tests reflect the real 33-column vector.

#### Acceptance Criteria

1. THE VPAFeatureExtractor SHALL update the `_extract_feature_vector` docstring reference from "29 feature columns" to the correct count of 33.
2. THE VPAFeatureExtractor SHALL update the `generate_dataset` docstring reference from "27 feature columns" to the correct count of 33.
3. THE ml_validation test suite SHALL update the feature-importance report length assertion in `test_integration.py` from `== 31` to `== 33`.
4. THE ml_validation test suite SHALL update the stale "All 27 feature columns" comment in `test_integration.py` to reflect 33 feature columns.
5. THE spec implementation SHALL correct any other hardcoded feature-column counts discovered during an audit to 33 where they refer to the raw feature-column count.

### Requirement 8: No regressions across suites

**User Story:** As a maintainer, I want the full test suite to stay green with formatting and linting clean, so that the change is safe to merge and deploy.

#### Acceptance Criteria

1. WHEN the ml_validation and backtesting test suites run, THE Test_Suite SHALL pass with the new feature columns and signal types present.
2. THE Test_Suite SHALL include a regression test asserting that Composite_Score matches a captured baseline for a fixed input dataset.
3. WHEN `pytest -m ""` runs, THE Full_Test_Suite SHALL pass including the slow ML tests.
4. WHEN `ruff check .` runs, THE Linter SHALL report no violations.
5. WHEN `ruff format --check .` runs, THE Formatter SHALL report no formatting changes required.
