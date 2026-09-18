# Requirements Document

## Introduction

This feature adds the Double Smoothed Stochastic (DSS) Bressert oscillator as a
new indicator in the trading project (`d:\projects\trading\vpa`). The DSS Bressert
oscillator is produced by applying a classic stochastic over the close/high/low
series, smoothing that result with an EMA, applying a second stochastic over the
smoothed series, and smoothing that result with a second EMA; the trigger (signal)
line is an EMA of the DSS oscillator. The oscillator is bounded between 0 and 100.
Crossovers of the oscillator against its trigger line, and movements out of
overbought/oversold zones, generate trade signals.

The new indicator follows the established project conventions: a pure calculator
function in the style of `vpa/rsi.py`, a config-driven signal block in
`config/config.json` shaped like the existing `rsi` and `ma_crossover` blocks, a
`detect_dss_bressert_signals(row_index)` method on the `MarketAnalyzer` in
`vpa/app_runner.py` that contributes to the composite `trade_signal` summation, and
a standalone backtest through the existing engine in `vpa/backtesting/`. The signal
must degrade gracefully when disabled or when there is insufficient data, mirroring
how RSI returns a neutral value and how `ma_crossover` uses an `enabled` flag.

This work is tracked by Jira ticket SP-325 (Story, Side Projects / trading project).

## Glossary

- **DSS_Bressert**: The Double Smoothed Stochastic (Bressert) indicator, comprising
  the DSS oscillator and the trigger line.
- **DSS_Calculator**: The pure function that computes the DSS Bressert oscillator and
  trigger line from price data, analogous to `calculate_rsi` in `vpa/rsi.py`.
- **DSS_Oscillator**: The double-smoothed stochastic value, a float in the closed
  range 0.0 to 100.0.
- **Trigger_Line**: The smoothed signal line derived from the DSS_Oscillator; crossovers
  between the DSS_Oscillator and the Trigger_Line generate signals.
- **Stochastic_Period**: The lookback length used to compute the stochastic from
  high, low, and close prices. Maps to the Pine input PDS (default 10) and is used in
  BOTH stochastic passes of the DSS_Bressert calculation.
- **Smoothing_Period**: The EMA length applied after EACH stochastic pass to produce
  the DSS_Oscillator. Maps to the Pine input EMAlen (default 9).
- **Trigger_Period**: The EMA length used to derive the Trigger_Line from the
  DSS_Oscillator. Maps to the Pine input TriggerLen (default 5).
- **Overbought_Threshold**: The DSS_Oscillator level at or above which the market is
  considered overbought.
- **Oversold_Threshold**: The DSS_Oscillator level at or below which the market is
  considered oversold.
- **MarketAnalyzer**: The analysis class in `vpa/app_runner.py` that aggregates enabled
  signal categories into the composite trade_signal score.
- **Composite_Score**: The `trade_signal` value produced in `MarketAnalyzer.process_data()`
  as the sum of all enabled signal-category sub-scores.
- **DSS_Config**: The `dss_bressert` configuration block in `config/config.json`.
- **Backtesting_Engine**: The existing backtest engine in `vpa/backtesting/` that measures
  strategy performance from a signal log and price series.
- **DSS_Chart**: The candlestick chart artifact rendered by the MarketAnalyzer that plots
  the price candles with the DSS_Oscillator and Trigger_Line in a lower panel, saved as a
  PNG file under the existing `log/` chart output location, analogous to the output of
  `graph_intervals()`.
- **Neutral_Value**: The default DSS_Oscillator value (50.0) returned when there is
  insufficient data, consistent with how `calculate_rsi` returns 50.0.
- **Minimum warmup length**: The number of leading rows over which the DSS_Bressert
  cannot be computed, approximated as Stochastic_Period + Smoothing_Period +
  Trigger_Period minus 2. This is an approximation of the combined EMA/stochastic
  warmup; the exact warmup length will be defined in design.

## Requirements

### Requirement 1: DSS Bressert Oscillator and Trigger Line Calculation

**User Story:** As a trading system developer, I want a pure function that computes the
DSS Bressert oscillator and trigger line from price data, so that the indicator can be
reused consistently across the analyzer, feature extraction, and backtesting.

#### Acceptance Criteria

1. WHEN a price series of length greater than or equal to the minimum warmup length is
   provided AND the Stochastic_Period, Smoothing_Period, and Trigger_Period are each
   integers greater than or equal to 1, THE DSS_Calculator SHALL return a DSS_Oscillator
   value and a Trigger_Line value.
2. THE DSS_Calculator SHALL return a DSS_Oscillator value greater than or equal to 0.0
   and less than or equal to 100.0.
3. THE DSS_Calculator SHALL return a Trigger_Line value greater than or equal to 0.0
   and less than or equal to 100.0.
4. WHILE every price change across the provided series is strictly upward, THE
   DSS_Calculator SHALL return a DSS_Oscillator value greater than or equal to 50.0.
5. WHILE every price change across the provided series is strictly downward, THE
   DSS_Calculator SHALL return a DSS_Oscillator value less than or equal to 50.0.
6. WHILE every price across the provided series is equal (no variance), THE DSS_Calculator
   SHALL return the Neutral_Value of 50.0 for the DSS_Oscillator.
7. IF the Stochastic_Period, Smoothing_Period, or Trigger_Period is not an integer greater
   than or equal to 1, THEN THE DSS_Calculator SHALL return the Neutral_Value of 50.0 for
   the DSS_Oscillator and SHALL return no error.
8. WHEN invoked twice with identical inputs, THE DSS_Calculator SHALL return identical
   DSS_Oscillator and Trigger_Line values (deterministic and side-effect free).
9. THE DSS_Calculator SHALL compute the DSS_Oscillator as an EMA (of length
   Smoothing_Period) of a stochastic taken over an EMA (of length Smoothing_Period) of a
   stochastic (of length Stochastic_Period) of the close/high/low series, and SHALL
   compute the Trigger_Line as an EMA (of length Trigger_Period) of the DSS_Oscillator.

### Requirement 2: Config-Driven Parameters

**User Story:** As a trading system operator, I want the DSS Bressert parameters to be
configurable in `config/config.json`, so that periods, thresholds, and scores can be
tuned without code changes, matching the existing signal configuration blocks.

#### Acceptance Criteria

1. THE DSS_Config SHALL provide an `enabled` boolean flag, a Stochastic_Period, a
   Smoothing_Period, a Trigger_Period, an Overbought_Threshold, an Oversold_Threshold,
   and a scores block.
2. THE scores block within THE DSS_Config SHALL define a bullish-crossover score, a
   bearish-crossover score, an oversold-zone score, and an overbought-zone score, each
   an integer in the range -100 to 100 inclusive.
3. WHEN THE DSS_Config section is absent from `config/config.json`, THE MarketAnalyzer
   SHALL apply the following default values: `enabled` = true, Stochastic_Period (PDS) = 10,
   Smoothing_Period (EMAlen) = 9, Trigger_Period (TriggerLen) = 5, Overbought_Threshold = 80,
   Oversold_Threshold = 20, and the four scores block values = 0.
4. WHEN THE MarketAnalyzer reads THE DSS_Config, THE MarketAnalyzer SHALL use the
   configured Stochastic_Period, Smoothing_Period, and Trigger_Period when invoking
   THE DSS_Calculator.
5. WHILE THE DSS_Config `enabled` flag is false, THE MarketAnalyzer SHALL skip
   DSS_Bressert signal generation for the session.
6. IF THE Stochastic_Period, Smoothing_Period, or Trigger_Period is not an integer in the
   range 1 to 500 inclusive, THEN THE MarketAnalyzer SHALL log a warning identifying the
   invalid parameter, disable DSS_Bressert signal generation for the session, and retain
   the remaining configured values without modification.
7. IF THE Overbought_Threshold or Oversold_Threshold is not a number in the range 0 to 100
   inclusive, or IF THE Oversold_Threshold is greater than or equal to THE
   Overbought_Threshold, THEN THE MarketAnalyzer SHALL log a warning identifying the
   invalid threshold condition and disable DSS_Bressert signal generation for the session.
8. THE DSS_Bressert SHALL be computed on the bar series already used by the MarketAnalyzer,
   and THE DSS_Config SHALL NOT expose a resolution or timeframe parameter.

### Requirement 3: Crossover Signal Generation

**User Story:** As a trader, I want crossovers between the DSS oscillator and its trigger
line to generate directional signals, so that momentum shifts contribute to the composite
score.

#### Acceptance Criteria

1. WHEN the DSS_Oscillator value on the previous row is less than or equal to the
   Trigger_Line value on the previous row AND the DSS_Oscillator value on the current row
   is strictly greater than the Trigger_Line value on the current row, THE MarketAnalyzer
   SHALL emit a bullish DSS_Bressert crossover signal.
2. WHEN a bullish DSS_Bressert crossover signal is emitted, THE MarketAnalyzer SHALL add
   the configured bullish-crossover score to the DSS_Bressert sub-score.
3. WHEN the DSS_Oscillator value on the previous row is greater than or equal to the
   Trigger_Line value on the previous row AND the DSS_Oscillator value on the current row
   is strictly less than the Trigger_Line value on the current row, THE MarketAnalyzer
   SHALL emit a bearish DSS_Bressert crossover signal.
4. WHEN a bearish DSS_Bressert crossover signal is emitted, THE MarketAnalyzer SHALL
   subtract the configured bearish-crossover score from the DSS_Bressert sub-score.
5. WHILE the DSS_Oscillator remains on the same side of the Trigger_Line across the
   current and previous rows, THE MarketAnalyzer SHALL emit no DSS_Bressert crossover
   signal and SHALL leave the DSS_Bressert sub-score unchanged.
6. IF the DSS_Oscillator value or the Trigger_Line value is missing or undefined on either
   the previous row or the current row, THEN THE MarketAnalyzer SHALL emit no DSS_Bressert
   crossover signal and SHALL leave the DSS_Bressert sub-score unchanged.

### Requirement 4: Overbought and Oversold Zone Signal Generation

**User Story:** As a trader, I want the DSS oscillator's overbought and oversold zones to
contribute signals, so that extreme momentum readings adjust the composite score.

#### Acceptance Criteria

1. WHILE the DSS_Oscillator is a valid numeric value less than or equal to the
   Oversold_Threshold, THE MarketAnalyzer SHALL emit an oversold DSS_Bressert signal and
   add the configured oversold-zone score (a positive/bullish value) to the DSS_Bressert
   sub-score.
2. WHILE the DSS_Oscillator is a valid numeric value greater than or equal to the
   Overbought_Threshold, THE MarketAnalyzer SHALL emit an overbought DSS_Bressert signal
   and add the configured overbought-zone score (a negative/bearish value) to the
   DSS_Bressert sub-score.
3. WHILE the DSS_Oscillator is a valid numeric value strictly greater than the
   Oversold_Threshold and strictly less than the Overbought_Threshold, THE MarketAnalyzer
   SHALL emit no DSS_Bressert zone signal and contribute a zero DSS_Bressert sub-score.
4. IF the DSS_Oscillator cannot be computed for the current bar due to insufficient
   historical data or is not a valid finite number, THEN THE MarketAnalyzer SHALL emit no
   DSS_Bressert zone signal and contribute a zero DSS_Bressert sub-score.
5. IF the configured Oversold_Threshold is greater than or equal to the configured
   Overbought_Threshold, THEN THE MarketAnalyzer SHALL emit no DSS_Bressert zone signal
   and contribute a zero DSS_Bressert sub-score.

### Requirement 5: Composite Score Integration

**User Story:** As a trading system developer, I want the DSS Bressert sub-score to be
added into the composite trade_signal, so that the new indicator participates in the
overall trade decision alongside the existing MA crossover and RSI signals.

#### Acceptance Criteria

1. WHEN THE MarketAnalyzer processes a row AND the DSS_Bressert category is enabled, THE
   MarketAnalyzer SHALL add the DSS_Bressert sub-score as a single additive term to the
   Composite_Score, such that Composite_Score equals the arithmetic sum of every enabled
   category sub-score with no weighting, scaling, or ordering dependency.
2. THE MarketAnalyzer SHALL expose the DSS_Bressert result in the per-row signals
   dictionary as exactly two entries: a signals list containing zero or more signal-name
   strings, and a sub-score value of numeric type, matching the structure of the existing
   `rsi_signals` (list of strings) / `rsi_signal_score` (numeric) and
   `ma_crossover_signals` (list of strings) / `ma_crossover_signal_score` (numeric)
   entries.
3. WHEN the DSS_Bressert sub-score is added into the Composite_Score, THE MarketAnalyzer
   SHALL leave the numeric contribution of every other signal category identical to the
   value it would have without the DSS_Bressert term, so that Composite_Score with the
   DSS_Bressert term equals Composite_Score without it plus the DSS_Bressert sub-score.
4. IF the DSS_Bressert category is disabled OR the row has insufficient data to compute
   the DSS_Bressert indicator, THEN THE MarketAnalyzer SHALL set the DSS_Bressert sub-score
   to 0 and the DSS_Bressert signals list to empty, leaving the Composite_Score value
   unchanged.
5. WHEN the DSS_Bressert category is enabled AND no DSS_Bressert signal condition is
   triggered for the row, THE MarketAnalyzer SHALL set the DSS_Bressert sub-score to 0 and
   the DSS_Bressert signals list to empty.

### Requirement 6: Isolated Backtest of the DSS Bressert Signal

**User Story:** As a strategy analyst, I want to backtest the DSS Bressert signal in
isolation through the existing backtesting engine, so that I can measure its standalone
performance.

#### Acceptance Criteria

1. WHEN a strategy variation whose signal filter admits only DSS_Bressert signals
   (excluding every other signal type) is run, THE Backtesting_Engine SHALL invoke the
   existing engine exactly once through its public run interface and produce one variation
   run result containing the priced trades, the equity curve, and a computed metrics
   result.
2. WHEN the isolated DSS_Bressert backtest completes with one or more matched trades, THE
   Backtesting_Engine SHALL report, via the existing metrics pipeline, the complete
   performance metrics suite comprising total return, annualised return, buy-and-hold
   return, Sharpe ratio, maximum drawdown, win rate, profit factor, average win, average
   loss, expectancy, time in market, number of trades, and trades per year.
3. THE isolated DSS_Bressert backtest SHALL reuse the existing Backtesting_Engine via its
   public run interface without modifying, subclassing, or monkeypatching the engine.
4. IF the DSS_Bressert signal filter matches zero signals in the supplied signal log, THEN
   THE Backtesting_Engine SHALL complete without error and report a metrics result with a
   number of trades equal to 0 and every trade-derived metric equal to 0.0.
5. IF the isolated DSS_Bressert variation raises an error during its run, THEN THE
   Backtesting_Engine SHALL record that variation as a failure identified by its name
   together with a message indicating the cause, and SHALL not abort any other variations
   in the same batch.

### Requirement 7: Graceful Degradation When Disabled

**User Story:** As a trading system operator, I want the DSS Bressert signal to contribute
nothing and raise no error when disabled, so that turning the feature off is safe, matching
the behaviour of the RSI and MA crossover signals.

#### Acceptance Criteria

1. WHILE THE DSS_Config `enabled` flag is false, THE MarketAnalyzer SHALL emit a
   DSS_Bressert signals list containing zero elements.
2. WHILE THE DSS_Config `enabled` flag is false, THE MarketAnalyzer SHALL emit a
   DSS_Bressert sub-score of exactly 0.0.
3. WHILE THE DSS_Config `enabled` flag is false, THE MarketAnalyzer SHALL contribute
   exactly 0.0 to the Composite_Score from the DSS_Bressert category.
4. WHILE THE DSS_Config `enabled` flag is false, THE MarketAnalyzer SHALL skip invoking
   THE DSS_Calculator and SHALL complete processing of the current and subsequent rows
   without raising an error.
5. IF THE DSS_Config `enabled` flag is absent or not a boolean, THEN THE MarketAnalyzer
   SHALL treat the DSS_Bressert category as disabled.

### Requirement 8: Graceful Degradation on Insufficient Data

**User Story:** As a trading system developer, I want the DSS Bressert calculation to
return a neutral result and generate no signal when there is not enough data, so that early
rows and short series do not produce spurious signals or errors, mirroring how RSI returns
a neutral value.

#### Acceptance Criteria

1. IF the provided price series contains fewer rows than the minimum warmup length, THEN
   THE DSS_Calculator SHALL return the Neutral_Value of 50.0 for the DSS_Oscillator and
   SHALL return no error.
2. WHEN the DSS_Calculator computes over a series equal to or longer than the minimum
   warmup length, THE DSS_Calculator SHALL return the Neutral_Value of 50.0 for each row
   whose index is less than the minimum warmup length and SHALL return the computed
   DSS_Oscillator value for each row whose index is greater than or equal to the minimum
   warmup length.
3. IF the current row index is less than the minimum warmup length required to compute the
   DSS_Bressert, THEN THE MarketAnalyzer SHALL emit an empty DSS_Bressert signals list
   containing zero elements and a DSS_Bressert sub-score of 0.0.
4. IF the DSS_Oscillator value or the Trigger_Line value for the current row is not a
   number (NaN, null, or infinite), THEN THE MarketAnalyzer SHALL emit an empty
   DSS_Bressert signals list containing zero elements and a DSS_Bressert sub-score of 0.0.

### Requirement 9: Unit Test Coverage

**User Story:** As a trading system developer, I want unit tests covering the oscillator
maths and crossover detection, so that the DSS Bressert behaviour is verified and protected
against regressions.

#### Acceptance Criteria

1. WHEN the DSS_Calculator is invoked on a valid price series of length greater than or
   equal to the minimum warmup length, THE DSS_Bressert test suite SHALL verify the
   returned DSS_Oscillator value is greater than or equal to 0.0 and less than or equal to
   100.0.
2. WHEN the DSS_Calculator is invoked on a price series shorter than the minimum warmup
   length, THE DSS_Bressert test suite SHALL verify the returned DSS_Oscillator value is
   exactly 50.0.
3. WHEN a bullish crossover condition is applied, THE DSS_Bressert test suite SHALL verify
   the DSS_Bressert sub-score is strictly greater than 0.0.
4. WHEN a bearish crossover condition is applied, THE DSS_Bressert test suite SHALL verify
   the DSS_Bressert sub-score is strictly less than 0.0.
5. WHEN the DSS_Oscillator is at or above the Overbought_Threshold, THE DSS_Bressert test
   suite SHALL verify the DSS_Bressert sub-score equals the configured overbought-zone
   score.
6. WHEN the DSS_Oscillator is at or below the Oversold_Threshold, THE DSS_Bressert test
   suite SHALL verify the DSS_Bressert sub-score equals the configured oversold-zone score.
7. WHEN the DSS_Config is disabled, THE DSS_Bressert test suite SHALL verify the
   DSS_Bressert signals list is empty and the DSS_Bressert sub-score is 0.0.

### Requirement 10: DSS Bressert Visualization

**User Story:** As a trader/developer, I want to plot the DSS Bressert oscillator and
trigger line in a panel below the price chart, so that I can visually verify the indicator
behaves as expected versus TradingView.

#### Acceptance Criteria

1. WHEN the charting capability is invoked with the DSS_Bressert category enabled AND the
   DSS and DSS_Trigger columns are present, THE MarketAnalyzer SHALL render a DSS_Chart
   containing the price candles in the upper panel and the DSS_Oscillator and Trigger_Line
   together in a lower panel, using the same mplfinance approach (`mpf.plot(..., type="candle")`
   with `make_addplot(..., panel=N)`) as the existing `graph_intervals()` method.
2. THE MarketAnalyzer SHALL draw two horizontal reference lines in the lower panel of the
   DSS_Chart, one at the configured Overbought_Threshold and one at the configured
   Oversold_Threshold.
3. THE MarketAnalyzer SHALL render the DSS_Oscillator and the Trigger_Line as two distinct
   series in the lower panel of the DSS_Chart, visually distinguishable by colour and label.
4. THE MarketAnalyzer SHALL plot the DSS_Chart lower panel from the already-computed DSS and
   DSS_Trigger columns and SHALL NOT recompute the DSS_Bressert indicator during rendering,
   so that the plotted values are identical to the values the MarketAnalyzer scored.
5. WHEN the charting capability is invoked, THE MarketAnalyzer SHALL save the DSS_Chart as a
   PNG file under the existing `log/` chart output location, consistent with `graph_intervals()`.
6. IF the DSS_Bressert category is disabled OR the DSS or DSS_Trigger column is absent, THEN
   THE MarketAnalyzer SHALL render a price-only chart without the DSS panel and SHALL complete
   without raising an error.
