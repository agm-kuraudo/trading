# Requirements Document

## Introduction

This feature combines multiple existing indicator signals into composite,
confluence-based entry/exit conditions and backtests them against the individual
signals, starting with the DSS Bressert crossover combined with the 10 SMA
(price-vs-SMA) crossover. Unlike the existing composite `trade_signal` summation,
which adds every signal category's sub-score together, a Combined_Signal fires on a
row ONLY when ALL of its constituent conditions hold on that row (confluence / AND
logic). For example, a combined bullish signal fires only when a DSS Bressert
bullish crossover coincides with price being above (or crossing above) the 10 SMA.

The two building-block signals already exist on the `MarketAnalyzer` in
`vpa/app_runner.py`: `detect_dss_bressert_signals(row_index)` (emitting
"DSS Bullish Crossover" / "DSS Bearish Crossover" / "DSS Oversold" /
"DSS Overbought", config block `dss_bressert`) and
`detect_price_vs_sma_signals(row_index)` (emitting "Price above SMA" /
"Price below SMA" / "Price crossed above SMA" / "Price crossed below SMA", config
block `price_vs_sma` whose period defaults to 10 — this is the "10 SMA" signal).

The new capability follows the established project conventions: a config-driven block
in `config/config.json` shaped like the existing signal blocks and backed by a frozen
dataclass in `vpa/config/settings.py`, a `detect_<x>_signals(row_index)`-style method
on the `MarketAnalyzer` that contributes a single additive term to the composite
`trade_signal`, and backtesting through the existing engine via new `SignalType`
member(s) and `StrategyVariation`(s). The combination logic must be config-driven and
must degrade gracefully when disabled, when a constituent signal is disabled, or when
there is insufficient data, mirroring the DSS Bressert and RSI patterns.

This work is tracked by Jira ticket SP-327 (Story, Side Projects / trading project).
SP-327 is blocked by SP-325 (DSS Bressert, Done) and builds on the price-vs-SMA /
10 SMA signal (SP-326, SP-340). The known drift between the two composite scores
(tracked by SP-340) is out of scope for this feature.

## Glossary

- **Combined_Signal**: A named signal defined by combining two or more Constituent_Conditions
  under a Confluence (AND) condition, where each Constituent_Condition is either a
  Presence_Condition or an Absence_Condition; it fires on a row only when every
  Constituent_Condition holds on that row.
- **Confluence**: The AND relationship between a Combined_Signal's Constituent_Conditions;
  all Constituent_Conditions (presence and absence) must hold on the same row for the
  Combined_Signal to fire, as opposed to summing the constituent sub-scores.
- **Constituent_Condition**: A single clause within a Combined_Signal's Confluence
  condition that references one signal-name string emitted by a Constituent_Signal and
  is evaluated as either a Presence_Condition or an Absence_Condition.
- **Presence_Condition**: A Constituent_Condition that holds on a row if and only if the
  configured signal-name string IS present in that row's Constituent_Signal signals list.
- **Absence_Condition**: A Constituent_Condition (also called a Negation_Condition) that
  holds on a row if and only if the configured signal-name string is NOT present in that
  row's Constituent_Signal signals list.
- **Combined_Config**: The `combined_signals` configuration block in
  `config/config.json`, backed by a frozen dataclass in `vpa/config/settings.py`,
  defining one or more named Combined_Signals, and seeding five starter definitions by
  default.
- **Starter_Combinations**: The five named Combined_Signals seeded by the Combined_Config
  by default: DSS_Cross_Plus_SMA_Position, DSS_Cross_Plus_SMA_Cross,
  DSS_Zone_Plus_SMA_Cross, DSS_Cross_From_Zone, and DSS_Cross_SMA_Not_Overbought.
- **DSS_Cross_Plus_SMA_Position**: The starter Combined_Signal whose bullish Confluence is
  "DSS Bullish Crossover" present AND "Price above SMA" present, with the bearish mirror
  "DSS Bearish Crossover" present AND "Price below SMA" present.
- **DSS_Cross_Plus_SMA_Cross**: The starter Combined_Signal whose bullish Confluence is
  "DSS Bullish Crossover" present AND "Price crossed above SMA" present, with the bearish
  mirror "DSS Bearish Crossover" present AND "Price crossed below SMA" present (both events
  on the same bar).
- **DSS_Zone_Plus_SMA_Cross**: The starter Combined_Signal whose bullish Confluence is
  "DSS Oversold" present AND "Price crossed above SMA" present, with the bearish mirror
  "DSS Overbought" present AND "Price crossed below SMA" present (mean-reversion entry).
- **DSS_Cross_From_Zone**: The starter Combined_Signal whose bullish Confluence is
  "DSS Bullish Crossover" present AND "DSS Oversold" present, with the bearish mirror
  "DSS Bearish Crossover" present AND "DSS Overbought" present; both Constituent_Conditions
  reference the same underlying DSS_Bressert_Signal (DSS-only self-confluence).
- **DSS_Cross_SMA_Not_Overbought**: The starter Combined_Signal whose bullish Confluence is
  "DSS Bullish Crossover" present AND "Price above SMA" present AND "DSS Overbought" absent,
  with the bearish mirror "DSS Bearish Crossover" present AND "Price below SMA" present AND
  "DSS Oversold" absent (three-way confluence including a Negation_Condition).
- **DSS_Bressert_Signal**: The existing DSS Bressert signal produced by
  `detect_dss_bressert_signals(row_index)`, whose crossover signal-name strings are
  "DSS Bullish Crossover" and "DSS Bearish Crossover" and whose zone signal-name strings
  are "DSS Oversold" and "DSS Overbought".
- **Price_vs_SMA_Signal**: The existing price-vs-SMA signal produced by
  `detect_price_vs_sma_signals(row_index)`, whose period defaults to 10 (the "10 SMA").
  Its position signal-name strings are "Price above SMA" / "Price below SMA" and its
  crossover signal-name strings are "Price crossed above SMA" / "Price crossed below SMA".
- **Constituent_Signal**: One of the existing signals (DSS_Bressert_Signal or
  Price_vs_SMA_Signal) whose signal-name strings a Combined_Signal references through its
  Constituent_Conditions; a single Combined_Signal MAY reference the same Constituent_Signal
  in more than one Constituent_Condition (for example, DSS_Cross_From_Zone references the
  DSS_Bressert_Signal twice).
- **Price above the 10 SMA**: The Price_vs_SMA_Signal position condition, present when the
  Price_vs_SMA_Signal emits "Price above SMA" (close above the SMA). Its bearish mirror is
  "Price below SMA".
- **Price crossing the 10 SMA**: The Price_vs_SMA_Signal crossover event condition, present
  when the Price_vs_SMA_Signal emits "Price crossed above SMA" (close moving from at/below to
  strictly above the SMA). Its bearish mirror is "Price crossed below SMA".
- **MarketAnalyzer**: The analysis class in `vpa/app_runner.py` that aggregates enabled
  signal categories into the composite trade_signal score.
- **Composite_Score**: The `trade_signal` value produced in
  `MarketAnalyzer.process_data()` as the sum of all enabled signal-category sub-scores.
- **Combined_Sub_Score**: The single additive numeric term contributed by the
  Combined_Signal category to the Composite_Score for a row.
- **Backtesting_Engine**: The existing backtest engine in `vpa/backtesting/` that measures
  strategy performance from a signal log and price series.
- **StrategyVariation**: The frozen dataclass in `vpa/backtesting/variations.py` carrying a
  `signal_filter: Callable[[SignalEntry], bool]`, run through the Backtesting_Engine via
  `run_variation()` -> `BacktestEngine().run(...)`.
- **SignalType**: The enum in `vpa/ml_validation/signal_analysis.py` whose members map
  feature-dataset columns to signal categories; `SIGNAL_DIRECTIONS` records each member's
  expected UP/DOWN direction and `classify_signals(df)` maps columns to row indices.
- **Combined_SignalType**: The new SignalType enum member(s) added for the Combined_Signal,
  with corresponding `SIGNAL_DIRECTIONS` entries (bullish UP, bearish DOWN).
- **Insufficient_Data**: The condition in which a Constituent_Signal cannot be evaluated
  for a row (disabled, column absent, row index below the constituent's warmup length, or a
  NaN/non-finite value), causing it to contribute no signal.

## Requirements

### Requirement 1: Config-Driven Combination Rules

**User Story:** As a trading system operator, I want a starter set of named combined signals
defined in `config/config.json`, so that several confluences can be tested out of the box and
new ones configured without code changes, matching the existing signal configuration blocks.

#### Acceptance Criteria

1. THE Combined_Config SHALL provide an `enabled` boolean flag and a collection of one or
   more named Combined_Signal definitions.
2. THE Combined_Config SHALL allow more than one Combined_Signal definition to be present
   so that different confluences can be configured and tested independently.
3. Each Combined_Signal definition within THE Combined_Config SHALL specify a unique name,
   two or more Constituent_Conditions, and a combined score contributed when the Confluence
   condition holds, where each Constituent_Condition references one signal-name string and is
   evaluated as a Presence_Condition or an Absence_Condition.
4. Each Constituent_Condition within THE Combined_Config MAY reference any of the known
   DSS_Bressert_Signal signal-name strings ("DSS Bullish Crossover", "DSS Bearish Crossover",
   "DSS Oversold", "DSS Overbought") or Price_vs_SMA_Signal signal-name strings
   ("Price above SMA", "Price below SMA", "Price crossed above SMA", "Price crossed below SMA").
5. THE Combined_Config SHALL seed the following five named Combined_Signals by default, each
   with a bullish definition and a bearish mirror:
   - DSS_Cross_Plus_SMA_Position — bullish: "DSS Bullish Crossover" AND "Price above SMA";
     bearish: "DSS Bearish Crossover" AND "Price below SMA".
   - DSS_Cross_Plus_SMA_Cross — bullish: "DSS Bullish Crossover" AND "Price crossed above SMA";
     bearish: "DSS Bearish Crossover" AND "Price crossed below SMA".
   - DSS_Zone_Plus_SMA_Cross — bullish: "DSS Oversold" AND "Price crossed above SMA";
     bearish: "DSS Overbought" AND "Price crossed below SMA".
   - DSS_Cross_From_Zone — bullish: "DSS Bullish Crossover" AND "DSS Oversold";
     bearish: "DSS Bearish Crossover" AND "DSS Overbought".
   - DSS_Cross_SMA_Not_Overbought — bullish: "DSS Bullish Crossover" AND "Price above SMA"
     AND NOT "DSS Overbought"; bearish: "DSS Bearish Crossover" AND "Price below SMA" AND
     NOT "DSS Oversold".
6. THE Combined_Config SHALL permit a single Combined_Signal definition to combine three or
   more Constituent_Conditions, as DSS_Cross_SMA_Not_Overbought does with two
   Presence_Conditions and one Absence_Condition.
7. WHEN THE Combined_Config section is absent from `config/config.json`, THE MarketAnalyzer
   SHALL apply default values that leave the Combined_Signal category disabled and SHALL
   complete processing without raising an error.
8. WHEN THE MarketAnalyzer reads THE Combined_Config, THE MarketAnalyzer SHALL use the
   configured Constituent_Conditions and combined score for each defined Combined_Signal
   when evaluating that Combined_Signal.
9. IF a Combined_Signal definition references a signal-name string that is not emitted by any
   known Constituent_Signal, THEN THE MarketAnalyzer SHALL log a warning identifying the
   unknown signal-name string and SHALL disable that Combined_Signal definition for the
   session while retaining the remaining valid definitions.

### Requirement 2: Confluence (AND) Evaluation

**User Story:** As a trader, I want a combined signal to fire only when all of its
constituent conditions hold on the same row, so that confluence logic produces
higher-conviction entries than any single signal alone.

#### Acceptance Criteria

1. THE MarketAnalyzer SHALL evaluate each Constituent_Condition of a Combined_Signal as
   either a Presence_Condition, which holds on a row if and only if the configured
   signal-name string IS present in that row's Constituent_Signal signals list, or an
   Absence_Condition, which holds on a row if and only if the configured signal-name string
   is NOT present in that row's Constituent_Signal signals list.
2. WHEN THE MarketAnalyzer evaluates a Combined_Signal on a row AND every Constituent_Condition
   for that Combined_Signal holds on that row, THE MarketAnalyzer SHALL emit the
   Combined_Signal and add its configured combined score to the Combined_Sub_Score.
3. WHILE at least one Constituent_Condition for a Combined_Signal does not hold on the
   current row, THE MarketAnalyzer SHALL emit no Combined_Signal for that definition and SHALL
   contribute zero to the Combined_Sub_Score from that definition.
4. THE MarketAnalyzer SHALL determine the Confluence condition by requiring the presence or
   absence of the configured constituent signal-name strings on the row, and SHALL NOT
   determine the Confluence condition by summing the Constituent_Signal sub-scores.
5. WHEN the DSS_Cross_Plus_SMA_Position bullish Confluence condition holds, THE
   MarketAnalyzer SHALL require the DSS_Bressert_Signal row signals to contain
   "DSS Bullish Crossover" AND the Price_vs_SMA_Signal row signals to contain
   "Price above SMA".
6. WHEN the DSS_Cross_Plus_SMA_Position bearish Confluence condition holds, THE
   MarketAnalyzer SHALL require the DSS_Bressert_Signal row signals to contain
   "DSS Bearish Crossover" AND the Price_vs_SMA_Signal row signals to contain
   "Price below SMA".
7. WHEN the DSS_Cross_SMA_Not_Overbought bullish Confluence condition holds, THE
   MarketAnalyzer SHALL require the DSS_Bressert_Signal row signals to contain
   "DSS Bullish Crossover" AND the Price_vs_SMA_Signal row signals to contain
   "Price above SMA" AND the DSS_Bressert_Signal row signals to NOT contain "DSS Overbought".
8. WHEN the DSS_Cross_SMA_Not_Overbought bearish Confluence condition holds, THE
   MarketAnalyzer SHALL require the DSS_Bressert_Signal row signals to contain
   "DSS Bearish Crossover" AND the Price_vs_SMA_Signal row signals to contain
   "Price below SMA" AND the DSS_Bressert_Signal row signals to NOT contain "DSS Oversold".
9. WHEN a Combined_Signal fires on a row, THE MarketAnalyzer SHALL add exactly one
   combined signal-name string identifying that Combined_Signal to the Combined_Signal
   signals list for the row.
10. IF a Constituent_Signal referenced by a Presence_Condition of a Combined_Signal is
    disabled, OR that Constituent_Signal reports Insufficient_Data for the current row, THEN
    THE MarketAnalyzer SHALL treat that Presence_Condition as not holding and SHALL emit no
    Combined_Signal for any definition that depends on that Presence_Condition.
11. IF a Constituent_Signal referenced by an Absence_Condition of a Combined_Signal is
    disabled, OR that Constituent_Signal reports Insufficient_Data for the current row, THEN
    THE MarketAnalyzer SHALL treat that Absence_Condition as holding, because a disabled or
    no-data Constituent_Signal cannot emit the referenced signal-name string, so the string
    is absent and the Absence_Condition is trivially satisfied.

### Requirement 3: Composite Score Integration

**User Story:** As a trading system developer, I want the combined sub-score added into the
composite trade_signal as a single additive term, so that combined signals participate in the
overall trade decision alongside the existing signal categories.

#### Acceptance Criteria

1. WHEN THE MarketAnalyzer processes a row AND the Combined_Signal category is enabled, THE
   MarketAnalyzer SHALL add the Combined_Sub_Score as a single additive term to the
   Composite_Score, such that Composite_Score equals the arithmetic sum of every enabled
   category sub-score with no weighting, scaling, or ordering dependency.
2. THE MarketAnalyzer SHALL expose the Combined_Signal result in the per-row signals
   dictionary as exactly two entries: a signals list containing zero or more combined
   signal-name strings, and a sub-score value of numeric type, matching the structure of the
   existing `dss_bressert_signals` (list of strings) / `dss_bressert_signal_score` (numeric)
   and `price_vs_sma_signals` (list of strings) / `price_vs_sma_signal_score` (numeric)
   entries.
3. WHEN the Combined_Sub_Score is added into the Composite_Score, THE MarketAnalyzer SHALL
   leave the numeric contribution of every other signal category identical to the value it
   would have without the Combined_Signal term, so that Composite_Score with the
   Combined_Signal term equals Composite_Score without it plus the Combined_Sub_Score.
4. IF the Combined_Signal category is disabled OR no Combined_Signal fires on the row, THEN
   THE MarketAnalyzer SHALL set the Combined_Sub_Score to 0 and the Combined_Signal signals
   list to empty, leaving the Composite_Score value unchanged.

### Requirement 4: Graceful Degradation

**User Story:** As a trading system operator, I want the combined signal to contribute nothing
and raise no error when it is disabled, when a constituent is disabled, or when there is
insufficient data, so that configuring and running combinations is safe, matching the DSS
Bressert and RSI patterns.

#### Acceptance Criteria

1. WHILE THE Combined_Config `enabled` flag is false, THE MarketAnalyzer SHALL emit a
   Combined_Signal signals list containing zero elements and a Combined_Sub_Score of exactly
   0.0, and SHALL contribute exactly 0.0 to the Composite_Score from the Combined_Signal
   category.
2. WHILE THE Combined_Config `enabled` flag is false, THE MarketAnalyzer SHALL skip evaluating
   every Combined_Signal definition and SHALL complete processing of the current and subsequent
   rows without raising an error.
3. IF THE Combined_Config `enabled` flag is absent or not a boolean, THEN THE MarketAnalyzer
   SHALL treat the Combined_Signal category as disabled.
4. IF a Constituent_Signal referenced by a Presence_Condition of a Combined_Signal reports
   Insufficient_Data for the current row, THEN THE MarketAnalyzer SHALL emit no Combined_Signal
   for any definition that depends on that Presence_Condition and SHALL contribute 0.0 to the
   Combined_Sub_Score for that definition.
5. WHILE the current row index is below the warmup length of any Constituent_Signal referenced
   by a Presence_Condition of a Combined_Signal, THE MarketAnalyzer SHALL emit no
   Combined_Signal for that definition and SHALL contribute 0.0 to the Combined_Sub_Score for
   that definition.

### Requirement 5: Backtest Comparison of Combined vs Individual Signals

**User Story:** As a strategy analyst, I want to backtest the combined signal through the
existing engine and compare its performance against the DSS-only and SMA-only signals, so that
I can measure whether confluence improves performance over the individual signals.

#### Acceptance Criteria

1. FOR EACH of the five Starter_Combinations, THE SignalType enum SHALL define one
   Combined_SignalType member for its bullish combined signal and one for its bearish combined
   signal, and THE SIGNAL_DIRECTIONS mapping SHALL map each bullish Combined_SignalType to the
   UP direction and each bearish Combined_SignalType to the DOWN direction.
2. WHEN a feature dataset contains a combined-signal column, THE `classify_signals`
   function SHALL map rows on which that combined signal fired to the corresponding
   Combined_SignalType row-index list, and WHEN a combined-signal column is absent THE
   `classify_signals` function SHALL leave that Combined_SignalType list empty.
3. FOR EACH of the five Starter_Combinations, THE feature set SHALL define a Combined
   StrategyVariation whose signal filter admits only that combination's Combined_SignalType
   member(s) and excludes every other signal type, alongside the existing DSS-only and SMA-only
   variations, so that each combined signal's performance can be compared against each
   individual signal.
4. WHEN any Combined StrategyVariation is run, THE Backtesting_Engine SHALL be invoked through
   its existing public run interface without modifying, subclassing, or monkeypatching the
   engine, and SHALL produce one variation run result containing the priced trades, the equity
   curve, and a computed metrics result.
5. WHEN a Combined StrategyVariation backtest completes with one or more matched trades, THE
   Backtesting_Engine SHALL report, via the existing metrics pipeline, the complete performance
   metrics suite comprising total return, annualised return, buy-and-hold return, Sharpe ratio,
   maximum drawdown, win rate, profit factor, average win, average loss, expectancy, time in
   market, number of trades, and trades per year.
6. IF a Combined StrategyVariation signal filter matches zero signals in the supplied signal
   log, THEN THE Backtesting_Engine SHALL complete without error and report a metrics result
   with a number of trades equal to 0 and every trade-derived metric equal to 0.0.
7. IF a Combined StrategyVariation raises an error during its run, THEN THE Backtesting_Engine
   SHALL record that variation as a failure identified by its name together with a message
   indicating the cause, and SHALL not abort any other variations in the same batch.

### Requirement 6: Unit Test Coverage

**User Story:** As a trading system developer, I want unit tests covering the combination
logic, so that the confluence behaviour is verified and protected against regressions.

#### Acceptance Criteria

1. WHEN both Constituent_Conditions of DSS_Cross_Plus_SMA_Position hold on a row (bullish
   DSS crossover AND price above the 10 SMA), THE Combined_Signal test suite SHALL verify the
   Combined_Signal fires and the Combined_Sub_Score is non-zero.
2. WHEN exactly one Constituent_Condition of DSS_Cross_Plus_SMA_Position holds on a row,
   THE Combined_Signal test suite SHALL verify the Combined_Signal does not fire and the
   Combined_Sub_Score is 0.0.
3. WHEN neither Constituent_Condition of DSS_Cross_Plus_SMA_Position holds on a row, THE
   Combined_Signal test suite SHALL verify the Combined_Signal does not fire and the
   Combined_Sub_Score is 0.0.
4. WHEN a Constituent_Signal referenced by DSS_Cross_Plus_SMA_Position is disabled, THE
   Combined_Signal test suite SHALL verify the Combined_Signal does not fire and the
   Combined_Sub_Score is 0.0 even when the other Constituent_Condition holds.
5. WHEN THE Combined_Config `enabled` flag is false, THE Combined_Signal test suite SHALL
   verify the Combined_Signal signals list is empty and the Combined_Sub_Score is 0.0.
6. WHEN THE Combined_Config `enabled` flag is true, THE Combined_Signal test suite SHALL
   verify DSS_Cross_Plus_SMA_Position is evaluated and produces its configured combined score
   when its Confluence condition holds.
7. WHEN the negated signal-name string of DSS_Cross_SMA_Not_Overbought's Absence_Condition is
   present on a row (for example "DSS Overbought" present) while its Presence_Conditions hold,
   THE Combined_Signal test suite SHALL verify the Combined_Signal does NOT fire and the
   Combined_Sub_Score is 0.0.
8. WHEN the negated signal-name string of DSS_Cross_SMA_Not_Overbought's Absence_Condition is
   absent on a row while all of its Presence_Conditions hold, THE Combined_Signal test suite
   SHALL verify the Combined_Signal fires and the Combined_Sub_Score is non-zero.
9. WHEN all three Constituent_Conditions of DSS_Cross_SMA_Not_Overbought hold on a row (two
   Presence_Conditions and one Absence_Condition), THE Combined_Signal test suite SHALL verify
   the three-way confluence fires and the Combined_Sub_Score is non-zero.
10. WHEN both Constituent_Conditions of DSS_Cross_From_Zone hold on a row ("DSS Bullish
    Crossover" present AND "DSS Oversold" present, both from the DSS_Bressert_Signal), THE
    Combined_Signal test suite SHALL verify the DSS-only self-confluence fires and the
    Combined_Sub_Score is non-zero.
