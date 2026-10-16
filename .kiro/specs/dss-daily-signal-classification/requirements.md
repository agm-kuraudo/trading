# Requirements Document

## Introduction

The Daily Signal Generator (`vpa/ml_validation/daily_signal.py`) classifies the latest OHLCV candle for a ticker and emits actionable, contrarian-inverted trading signals. Today it only recognises the five core VPA signal types (`STRONG_BULLISH`, `STRONG_BEARISH`, `ACCUMULATION`, `ACCUMULATION_TEST_PASS`, `DISTRIBUTION`). It does not recognise DSS (Double Smoothed Stochastic / Bressert) crossover signals, nor the DSS/SMA combo (confluence) signals.

The analysis layer (`vpa/ml_validation/signal_analysis.py` `classify_signals`) and the per-ticker config generator (SP-322) already produce DSS signals, the ten DSS/SMA combo signals, and their config rules (for example, AAPL's generated entry contains `dss_bullish` / `dss_bearish` and `combo_dss_*` rules). Those config rules are inert at runtime because the daily generator never produces the DSS crossover feature columns nor the combo feature columns, and never classifies them. SP-359 closes this gap.

This feature (SP-359, Side Projects / trading, re-estimated to 5 story points, now titled "Classify DSS and DSS/SMA combo signals in the daily signal generator") makes the Daily Signal Generator a first-class producer and classifier of both the DSS crossover signals and the ten DSS/SMA combo signals. The combo signals use the exact same end-to-end mechanism as the DSS crossover signals: they are produced in the daily run, classified on the latest candle, mapped to default confidence levels, governed by regenerated SPY config rules, and covered by tests. The Daily_Generator must compute the DSS crossover feature columns and the combo feature columns during its run (mirroring the feature extractor's precompute, gating, and warm-up), classify those columns on the latest candle, map the DSS and combo signal types to default confidence levels, regenerate SPY's config entry to include DSS and combo rules, and be covered by tests. These signals apply to SPY and other tickers alike.

RSI signals and standalone price-crossed-SMA signals are explicitly out of scope for this feature.

Traceability: all work for this feature is linked to Jira ticket SP-359. The trading bot runs on a Raspberry Pi; because this code runs on a deployment target, "done" requires deploy and verification on the Pi, otherwise the ticket remains in Mostly Done.

## Glossary

- **Daily_Generator**: The daily signal pipeline implemented in `vpa/ml_validation/daily_signal.py`, comprising `DailySignalGenerator.run`, `classify_last_row`, and `build_signal_records`.
- **Feature_Extractor**: `VPAFeatureExtractor.generate_dataset` in `vpa/ml_validation/feature_extractor.py`, whose DSS precompute behaviour the Daily_Generator mirrors.
- **DSS_Precompute**: The step in which the DSS Bressert oscillator and trigger series are computed over the entire OHLCV frame via `vpa.dss_bressert.calculate_dss_bressert`, then reduced per row into `dss_bullish_cross` / `dss_bearish_cross` crossover flags.
- **DSS_Crossover_Columns**: The two integer feature columns `dss_bullish_cross` and `dss_bearish_cross`, each 0 or 1 per row.
- **DSS_Zone_Flags**: The two per-row integer flags `dss_oversold` and `dss_overbought`, each 0 or 1, derived from the DSS oscillator value versus `DSS_Config.oversold_threshold` and `DSS_Config.overbought_threshold`. `dss_oversold` equals 1 when the oscillator value is less than or equal to `oversold_threshold`; `dss_overbought` equals 1 when the oscillator value is greater than or equal to `overbought_threshold`. The DSS_Zone_Flags are gated by the same DSS_Enabled, DSS_Warmup, and finite-value guards as DSS_Crossover_Columns, and are 0 otherwise.
- **Price_Vs_SMA_Flags**: The four per-row integer flags `price_above_sma`, `price_below_sma`, `price_crossed_above_sma`, and `price_crossed_below_sma`, each 0 or 1, already computed in `DailySignalGenerator.run` from the price-vs-SMA precompute introduced in SP-340 (close versus the SMA series, using the prior row for the crossed flags).
- **Combo_Signals**: The ten DSS/SMA confluence signal types defined end-to-end in `vpa/ml_validation/signal_analysis.py`: `COMBO_DSS_CROSS_SMA_POS_BULL`, `COMBO_DSS_CROSS_SMA_POS_BEAR`, `COMBO_DSS_CROSS_SMA_CROSS_BULL`, `COMBO_DSS_CROSS_SMA_CROSS_BEAR`, `COMBO_DSS_ZONE_SMA_CROSS_BULL`, `COMBO_DSS_ZONE_SMA_CROSS_BEAR`, `COMBO_DSS_CROSS_FROM_ZONE_BULL`, `COMBO_DSS_CROSS_FROM_ZONE_BEAR`, `COMBO_DSS_CROSS_SMA_NOT_OB_BULL`, and `COMBO_DSS_CROSS_SMA_NOT_OB_BEAR`. `SIGNAL_DIRECTIONS` maps every `_BULL` member to UP and every `_BEAR` member to DOWN.
- **Combo_Columns**: The ten integer feature columns whose names equal the values of the Combo_Signals members (for example `combo_dss_cross_sma_pos_bull`), each 0 or 1 per row, derived by the confluence (logical AND) of DSS_Crossover_Columns, DSS_Zone_Flags, and Price_Vs_SMA_Flags per the Combo_Expressions.
- **Combo_Expressions**: The per-column confluence definitions, each `int(<expression>)` on the row's flags: `combo_dss_cross_sma_pos_bull` = `dss_bullish_cross AND price_above_sma`; `combo_dss_cross_sma_pos_bear` = `dss_bearish_cross AND price_below_sma`; `combo_dss_cross_sma_cross_bull` = `dss_bullish_cross AND price_crossed_above_sma`; `combo_dss_cross_sma_cross_bear` = `dss_bearish_cross AND price_crossed_below_sma`; `combo_dss_zone_sma_cross_bull` = `dss_oversold AND price_crossed_above_sma`; `combo_dss_zone_sma_cross_bear` = `dss_overbought AND price_crossed_below_sma`; `combo_dss_cross_from_zone_bull` = `dss_bullish_cross AND dss_oversold`; `combo_dss_cross_from_zone_bear` = `dss_bearish_cross AND dss_overbought`; `combo_dss_cross_sma_not_ob_bull` = `dss_bullish_cross AND price_above_sma AND NOT dss_overbought`; `combo_dss_cross_sma_not_ob_bear` = `dss_bearish_cross AND price_below_sma AND NOT dss_oversold`.
- **Combo_Column_Map**: The module-level dict `_COMBO_COLUMN_TO_TYPE` in `signal_analysis.py` mapping each Combo_Columns column name to its Combo_Signals `SignalType`, reused by both `classify_signals` and Classify_Last_Row to classify combo columns.
- **DSS_Config**: The `dss_bressert` section of the loaded VPA config, holding the `enabled` flag, `stochastic_period`, `smoothing_period`, `trigger_period`, `oversold_threshold`, and `overbought_threshold`.
- **DSS_Enabled**: The boolean gating condition that is true only when `DSS_Config.enabled` is true AND `stochastic_period`, `smoothing_period`, and `trigger_period` are each integers (not booleans) in the range 1 to 500 inclusive AND `oversold_threshold` and `overbought_threshold` are each numbers in the range 0 to 100 inclusive with `oversold_threshold` strictly less than `overbought_threshold`.
- **DSS_Warmup**: The warm-up row count equal to `stochastic_period + smoothing_period + trigger_period - 2`, measured in positional index over the processed frame.
- **DSS_BULLISH / DSS_BEARISH**: The `SignalType` enum members with values `"dss_bullish"` and `"dss_bearish"`; `SIGNAL_DIRECTIONS` maps `DSS_BULLISH` to UP and `DSS_BEARISH` to DOWN.
- **Feature_Extractor_Combo_Block**: The block in `VPAFeatureExtractor.generate_dataset` that computes the DSS_Zone_Flags and the Combo_Columns per row from the DSS precompute and the price-vs-SMA precompute, whose behaviour the Daily_Generator mirrors.
- **CONFIDENCE_MAP**: The default mapping from `SignalType` to a confidence-level string in `daily_signal.py`, used by `build_signal_records` when no ticker-specific rule applies.
- **Ticker_Config**: The per-ticker rule set loaded from `vpa/config/ticker_signals.json`.
- **Classify_Last_Row**: The `classify_last_row` function that classifies the final row of a feature DataFrame into a set of `SignalType` values.
- **Build_Signal_Records**: The `build_signal_records` function that turns classified signal types into sorted `SignalRecord` values, applying `Ticker_Config` rules, exclusions, and confidence sorting.

## Requirements

### Requirement 1: Produce DSS crossover columns in the daily run

**User Story:** As a trading-bot operator, I want the Daily_Generator to compute the DSS crossover feature columns during its run, so that DSS crossover signals can actually fire at runtime instead of being inert.

#### Acceptance Criteria

1. WHEN `DailySignalGenerator.run` processes the OHLCV frame AND DSS_Enabled is true, THE Daily_Generator SHALL compute the DSS Bressert oscillator and trigger series over the entire frame in a single call to `vpa.dss_bressert.calculate_dss_bressert` using `stochastic_period`, `smoothing_period`, and `trigger_period` from DSS_Config, aligning each returned value to its row by positional index.
2. WHEN the Daily_Generator computes the DSS series, THE Daily_Generator SHALL compute DSS_Warmup as the integer value `stochastic_period + smoothing_period + trigger_period - 2`.
3. WHILE DSS_Enabled is true, WHEN the Daily_Generator emits a feature row at positional index `pos` such that `pos` is greater than or equal to DSS_Warmup AND `pos` is greater than 0 AND the oscillator and trigger values at `pos` and `pos - 1` are each a finite real number (not NaN and not infinite), THE Daily_Generator SHALL set `dss_bullish_cross` to 1 for that row WHERE the oscillator value at `pos - 1` is less than or equal to the trigger value at `pos - 1` AND the oscillator value at `pos` is strictly greater than the trigger value at `pos`, and SHALL set `dss_bullish_cross` to 0 otherwise.
4. WHILE DSS_Enabled is true, WHEN the Daily_Generator emits a feature row at positional index `pos` such that `pos` is greater than or equal to DSS_Warmup AND `pos` is greater than 0 AND the oscillator and trigger values at `pos` and `pos - 1` are each a finite real number (not NaN and not infinite), THE Daily_Generator SHALL set `dss_bearish_cross` to 1 for that row WHERE the oscillator value at `pos - 1` is greater than or equal to the trigger value at `pos - 1` AND the oscillator value at `pos` is strictly less than the trigger value at `pos`, and SHALL set `dss_bearish_cross` to 0 otherwise.
5. IF DSS_Enabled is false, THEN THE Daily_Generator SHALL NOT call `vpa.dss_bressert.calculate_dss_bressert` AND SHALL set `dss_bullish_cross` and `dss_bearish_cross` to 0 for every emitted feature row.
6. IF an emitted feature row is at a positional index less than DSS_Warmup, OR at positional index 0, OR has any oscillator or trigger value at `pos` or `pos - 1` that is not a finite real number, THEN THE Daily_Generator SHALL set `dss_bullish_cross` and `dss_bearish_cross` to 0 for that row.
7. THE Daily_Generator SHALL emit `dss_bullish_cross` and `dss_bearish_cross` as integer-valued columns, each value equal to 0 or 1, in the feature DataFrame passed to Classify_Last_Row.

### Requirement 2: Produce DSS/SMA combo columns in the daily run

**User Story:** As a trading-bot operator, I want the Daily_Generator to compute the ten DSS/SMA combo feature columns during its run, so that combo confluence signals can actually fire at runtime instead of being inert.

#### Acceptance Criteria

1. WHEN `DailySignalGenerator.run` processes the OHLCV frame AND DSS_Enabled is true, THE Daily_Generator SHALL compute the DSS_Zone_Flags `dss_oversold` and `dss_overbought` for each feature row by mirroring the Feature_Extractor_Combo_Block, setting `dss_oversold` to 1 WHERE the oscillator value at that row is less than or equal to `DSS_Config.oversold_threshold` and 0 otherwise, and setting `dss_overbought` to 1 WHERE the oscillator value at that row is greater than or equal to `DSS_Config.overbought_threshold` and 0 otherwise.
2. IF a feature row is at a positional index less than DSS_Warmup, OR has an oscillator value that is not a finite real number, OR DSS_Enabled is false, THEN THE Daily_Generator SHALL set `dss_oversold` and `dss_overbought` to 0 for that row.
3. WHEN `DailySignalGenerator.run` processes the OHLCV frame, THE Daily_Generator SHALL compute each of the ten Combo_Columns for every feature row as `int(<expression>)` of the corresponding Combo_Expressions, using that row's DSS_Crossover_Columns, DSS_Zone_Flags, and Price_Vs_SMA_Flags values.
4. IF DSS_Enabled is false, THEN THE Daily_Generator SHALL set every one of the ten Combo_Columns to 0 for every emitted feature row.
5. THE Daily_Generator SHALL emit each of the ten Combo_Columns as an integer-valued column whose value for every row is exactly 0 or 1, in the feature DataFrame passed to Classify_Last_Row.
6. WHEN the Daily_Generator computes the Combo_Columns, THE Daily_Generator SHALL produce, for each row and each Combo_Columns column, the same 0-or-1 value that the Feature_Extractor_Combo_Block produces for that row and column given identical OHLCV input and configuration.

### Requirement 3: Classify DSS crossovers on the latest candle

**User Story:** As a trading-bot operator, I want Classify_Last_Row to recognise DSS crossovers on the latest candle, so that DSS signals appear in the daily output.

#### Acceptance Criteria

1. WHEN the feature DataFrame contains a `dss_bullish_cross` column AND the final row's `dss_bullish_cross` value, after numeric coercion, is equal to 1, THE Classify_Last_Row SHALL include `DSS_BULLISH` in the returned signal-type set.
2. WHEN the feature DataFrame contains a `dss_bearish_cross` column AND the final row's `dss_bearish_cross` value, after numeric coercion, is equal to 1, THE Classify_Last_Row SHALL include `DSS_BEARISH` in the returned signal-type set.
3. IF the feature DataFrame does not contain a `dss_bullish_cross` column, THEN THE Classify_Last_Row SHALL omit `DSS_BULLISH` from the returned signal-type set without raising an error.
4. IF the feature DataFrame does not contain a `dss_bearish_cross` column, THEN THE Classify_Last_Row SHALL omit `DSS_BEARISH` from the returned signal-type set without raising an error.
5. IF the final row's `dss_bullish_cross` value is NaN, absent, non-numeric, or a numeric value other than 1, THEN THE Classify_Last_Row SHALL omit `DSS_BULLISH` from the returned signal-type set.
6. IF the final row's `dss_bearish_cross` value is NaN, absent, non-numeric, or a numeric value other than 1, THEN THE Classify_Last_Row SHALL omit `DSS_BEARISH` from the returned signal-type set.
7. IF the feature DataFrame is empty, THEN THE Classify_Last_Row SHALL return an empty signal-type set without raising an error.
8. WHEN Classify_Last_Row evaluates DSS crossovers, THE Classify_Last_Row SHALL leave the classification of the existing core signal types (`STRONG_BULLISH`, `STRONG_BEARISH`, `ACCUMULATION`, `ACCUMULATION_TEST_PASS`, `DISTRIBUTION`) and the price-vs-SMA signal types unchanged.

### Requirement 4: Classify DSS/SMA combo signals on the latest candle

**User Story:** As a trading-bot operator, I want Classify_Last_Row to recognise the ten DSS/SMA combo signals on the latest candle, so that combo confluence signals appear in the daily output.

#### Acceptance Criteria

1. WHEN the feature DataFrame is non-empty AND, for one of the ten Combo_Columns, the final row's value in that column can be coerced to a number AND that coerced number is equal to 1, THE Classify_Last_Row SHALL add the single Combo_Signals `SignalType` that Combo_Column_Map associates with that column to the returned signal-type set.
2. WHEN Classify_Last_Row classifies the ten Combo_Columns, THE Classify_Last_Row SHALL resolve each column-to-`SignalType` association from the Combo_Column_Map dict defined in `signal_analysis.py`, applying the same column-present guard, not-NaN mask, and equal-to-1 test that `classify_signals` applies to those combo columns.
3. IF the feature DataFrame does not contain a given one of the ten Combo_Columns, THEN THE Classify_Last_Row SHALL omit that column's Combo_Signals `SignalType` from the returned signal-type set and SHALL NOT raise an error.
4. IF a given one of the ten Combo_Columns is present but the final row's value in that column is NaN, non-numeric, or a number other than 1 after coercion, THEN THE Classify_Last_Row SHALL omit that column's Combo_Signals `SignalType` from the returned signal-type set and SHALL NOT raise an error.
5. IF the feature DataFrame is empty, THEN THE Classify_Last_Row SHALL return an empty signal-type set and SHALL NOT raise an error.
6. WHEN Classify_Last_Row evaluates the ten Combo_Columns, THE Classify_Last_Row SHALL leave the membership of the existing core signal types, the price-vs-SMA signal types, and the `DSS_BULLISH` and `DSS_BEARISH` signal types in the returned set identical to what it would be if no combo column were evaluated.

### Requirement 5: Default confidence levels for DSS and combo signal types

**User Story:** As a trading-bot operator, I want DSS and combo signal types to have sensible default confidence levels, so that these signals are ranked meaningfully when no ticker-specific rule applies.

#### Acceptance Criteria

1. THE CONFIDENCE_MAP SHALL contain an entry for `DSS_BULLISH` whose value is one of `"High"`, `"Medium-High"`, or `"Low-Medium"` (that is, strictly higher than `"Low"` in CONFIDENCE_ORDER).
2. THE CONFIDENCE_MAP SHALL contain an entry for `DSS_BEARISH` whose value is one of `"High"`, `"Medium-High"`, or `"Low-Medium"` (that is, strictly higher than `"Low"` in CONFIDENCE_ORDER).
3. THE CONFIDENCE_MAP SHALL contain an entry for each of the ten Combo_Signals signal types, each entry's value being one of `"High"`, `"Medium-High"`, `"Low-Medium"`, or `"Low"` (that is, a value present in CONFIDENCE_ORDER).
4. WHERE the default confidence band for the Combo_Signals signal types is chosen, THE CONFIDENCE_MAP SHALL set each Combo_Signals entry to `"Medium-High"`, reflecting that combo signals are confluence (higher-conviction) signals, with the specific band being a configurable default rather than a value mandated beyond membership in CONFIDENCE_ORDER.
5. WHEN Build_Signal_Records processes a `DSS_BULLISH`, `DSS_BEARISH`, or Combo_Signals signal type for a ticker that has no matching Ticker_Config rule, THE Build_Signal_Records SHALL assign the confidence level from CONFIDENCE_MAP for that signal type, an `adjusted_direction` of `"BUY"`, and a `suggested_hold_days` of 10.
6. WHEN Build_Signal_Records processes a `DSS_BULLISH`, `DSS_BEARISH`, or Combo_Signals signal type for a ticker that has a matching Ticker_Config rule whose `adjusted_direction` is not `"NONE"`, THE Build_Signal_Records SHALL apply that rule's `adjusted_direction`, `confidence_level`, and `suggested_hold_days`.
7. IF a matching Ticker_Config rule for a `DSS_BULLISH`, `DSS_BEARISH`, or Combo_Signals signal type has an `adjusted_direction` equal to `"NONE"`, THEN THE Build_Signal_Records SHALL omit that signal from the returned records.
8. WHEN Build_Signal_Records returns records including DSS or combo signal types, THE Build_Signal_Records SHALL order all records by their confidence level according to CONFIDENCE_ORDER (`"High"` first), with any confidence level not present in CONFIDENCE_ORDER sorted last.

### Requirement 6: SPY config includes DSS and combo rules

**User Story:** As a trading-bot operator, I want SPY's entry in the ticker signals config to include DSS and combo rules, so that DSS and combo signals are governed by explicit SPY configuration like other tickers.

#### Acceptance Criteria

1. THE SPY entry in `vpa/config/ticker_signals.json` SHALL contain exactly one `dss_bullish` rule object and exactly one `dss_bearish` rule object.
2. THE SPY entry in `vpa/config/ticker_signals.json` SHALL contain exactly one rule object for each of the ten Combo_Signals column names (`combo_dss_cross_sma_pos_bull`, `combo_dss_cross_sma_pos_bear`, `combo_dss_cross_sma_cross_bull`, `combo_dss_cross_sma_cross_bear`, `combo_dss_zone_sma_cross_bull`, `combo_dss_zone_sma_cross_bear`, `combo_dss_cross_from_zone_bull`, `combo_dss_cross_from_zone_bear`, `combo_dss_cross_sma_not_ob_bull`, `combo_dss_cross_sma_not_ob_bear`), following the same schema the SP-322 generator produces for AAPL's combo rules.
3. THE SPY `dss_bullish`, `dss_bearish`, and combo rules SHALL each contain an `adjusted_direction` value whose value is one of the directions already used by existing entries (`"BUY"`, `"SELL"`, or `"NONE"`).
4. WHERE a SPY DSS or combo rule has an `adjusted_direction` other than `"NONE"`, THE rule SHALL contain a `confidence_level` value drawn from the set of values already used by existing entries (e.g. `"High"`) and a `suggested_hold_days` value that is an integer greater than or equal to 1.
5. IF a SPY DSS or combo rule has an `adjusted_direction` of `"NONE"`, THEN THE rule SHALL be treated as disabled and SHALL NOT be required to contain `confidence_level` or `suggested_hold_days` values.
6. WHEN `vpa/config/ticker_signals.json` is loaded by the Daily_Generator, THE file SHALL parse as valid JSON without error.
7. WHEN `vpa/config/ticker_signals.json` is loaded by the Daily_Generator, THE existing non-DSS, non-combo SPY rules and the existing AAPL entry SHALL remain unchanged from their pre-modification state.

### Requirement 7: Test coverage for DSS and combo classification and signal-record building

**User Story:** As a developer, I want automated tests for the DSS and combo classification and signal-record-building paths, so that the new behaviour is verified and protected against regression.

#### Acceptance Criteria

1. WHEN the final row has `dss_bullish_cross` equal to 1, THE test suite SHALL include a test asserting that Classify_Last_Row returns a signal-type collection containing `DSS_BULLISH`.
2. WHEN the final row has `dss_bearish_cross` equal to 1, THE test suite SHALL include a test asserting that Classify_Last_Row returns a signal-type collection containing `DSS_BEARISH`.
3. IF the `dss_bullish_cross` and `dss_bearish_cross` columns are both absent from the input, THEN THE test suite SHALL include a test asserting that Classify_Last_Row returns a signal-type collection containing no `DSS_BULLISH` or `DSS_BEARISH` entries and does not raise an error.
4. IF the final row's `dss_bullish_cross` or `dss_bearish_cross` value is NaN or any value other than 1, THEN THE test suite SHALL include a test asserting that Classify_Last_Row returns a signal-type collection containing no corresponding `DSS_BULLISH` or `DSS_BEARISH` entry.
5. WHEN the final row has a given Combo_Columns column equal to 1, THE test suite SHALL include a test asserting that Classify_Last_Row returns a signal-type collection containing that column's Combo_Signals `SignalType`.
6. IF a given Combo_Columns column is absent from the input, OR the final row's value in that column is NaN or any value other than 1, THEN THE test suite SHALL include a test asserting that Classify_Last_Row returns a signal-type collection containing no corresponding Combo_Signals `SignalType` and does not raise an error.
7. WHEN no Ticker_Config rule applies to a DSS or Combo_Signals signal type, THE test suite SHALL include a test asserting that Build_Signal_Records assigns that signal record the confidence level defined for that signal type in CONFIDENCE_MAP.
8. WHEN a Ticker_Config rule applies to a DSS or Combo_Signals signal type, THE test suite SHALL include a test asserting that Build_Signal_Records applies the rule's `adjusted_direction`, and a test asserting that the signal record is omitted from the output WHERE the rule's `adjusted_direction` equals `"NONE"`.
9. WHEN the Daily_Generator is run, THE test suite SHALL include a test asserting that the output contains `dss_bullish_cross` and `dss_bearish_cross` columns whose values match the DSS_Precompute crossover logic for rows at or after the warm-up boundary, equal 0 for every pre-warm-up row, and equal 0 for every row when DSS_Enabled is false.
10. WHEN the Daily_Generator is run, THE test suite SHALL include a test asserting that the output contains all ten Combo_Columns whose values match the Combo_Expressions evaluated from the DSS_Crossover_Columns, DSS_Zone_Flags, and Price_Vs_SMA_Flags, equal 0 for every pre-warm-up row, and equal 0 for every row when DSS_Enabled is false.
11. WHEN the full test suite is run via `pytest -m ""`, THE test suite SHALL complete with every test passing, including all tests added under criteria 1 through 10.

### Requirement 8: Traceability and deployment

**User Story:** As a trading-bot operator, I want the DSS and combo classification work to be traceable to its Jira ticket and verified on the deployment target, so that the change is auditable and confirmed working in production.

#### Acceptance Criteria

1. THE branch name for this work SHALL begin with Jira issue key `SP-359` followed by a hyphen and a short description (e.g. `SP-359-dss-combo-classification`).
2. THE commit message subject lines for this work SHALL begin with `SP-359:` followed by a description of what was done.
3. WHEN the implementation is complete, THE code SHALL pass `ruff check .` with zero reported lint issues.
4. WHEN the implementation is complete, THE code SHALL pass `ruff format --check .` with zero files reported as requiring reformatting.
5. IF `ruff check .` or `ruff format --check .` reports one or more issues, THEN THE work SHALL NOT be pushed, opened as a pull request, or moved to Done until all reported issues are resolved.
6. WHILE the DSS and combo classification code has not been both deployed to the Raspberry Pi (via pulling the latest changes and rebuilding the container using the project build scripts) and verified running on it, THE SP-359 ticket SHALL remain in Mostly Done rather than Done.
7. WHEN the DSS and combo classification code has been deployed to and verified running on the Raspberry Pi, THE SP-359 ticket SHALL record a completion comment that states both the deploy and the verification were performed, before the ticket is moved to Done.
