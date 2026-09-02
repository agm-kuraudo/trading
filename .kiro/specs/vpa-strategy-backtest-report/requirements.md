# Requirements Document

## Introduction

SP-333 extends the completed SP-317 core backtesting engine to evaluate whether VPA (Volume Price Analysis) signal-based trading edges on SPY are tradeable after costs. SP-314 found promising contrarian and directional hit rates on SPY VPA signals (Distribution 67-74%, Strong Bearish 63-69%, Strong Bullish 60-66%). SP-317 built a deterministic, network-free engine that produces a per-trade log. This feature turns that per-trade log into strategy profit-and-loss (P&L), a full performance-metrics suite, comparison against buy-and-hold SPY, equity-curve data, and a clear tradeability conclusion.

The feature MUST build on the existing `vpa/backtesting/` engine (BacktestEngine, BacktestConfig, ExitStrategy, PositionMode) rather than re-implementing it. New behaviour (stop-loss and variable-hold exits, stacking) is added through new ExitStrategy implementations and existing config options plugged into the engine. All new metric, P&L, equity-curve, and reporting logic is added as new modules that consume the engine's `BacktestResult`. The engine core MUST remain pure and deterministic with no network or yfinance dependency.

## Glossary

- **Backtest_Engine**: The existing SP-317 `BacktestEngine`. Consumes a Signal_Log, a Price_Series, and a Backtest_Config; produces a Backtest_Result. Not re-implemented by this feature.
- **Backtest_Config**: The existing SP-317 `BacktestConfig(hold_period, round_trip_cost, position_mode, exit_strategy)`.
- **Backtest_Result**: The existing SP-317 `BacktestResult` with `trades: list[TradeRecord]` and `skipped: list[SkippedSignal]`.
- **Trade_Record**: The existing SP-317 `TradeRecord` with fields `entry_date`, `exit_date`, `entry_price`, `exit_price`, `return_pct`, `signal_type`. `return_pct` is the long-basis net return `exit_price / entry_price - 1 - round_trip_cost`.
- **Signal_Entry**: The existing SP-317 `SignalEntry` with `date`, `signal_type` (Signal_Type), and `direction` (Signal_Direction UP or DOWN).
- **Signal_Type**: One of STRONG_BULLISH, STRONG_BEARISH, ACCUMULATION, DISTRIBUTION, ACCUMULATION_TEST_PASS.
- **Signal_Direction**: UP or DOWN, mapped from Signal_Type by the existing `SIGNAL_DIRECTIONS` map (STRONG_BULLISH=UP, STRONG_BEARISH=DOWN, ACCUMULATION=UP, DISTRIBUTION=DOWN, ACCUMULATION_TEST_PASS=UP).
- **Exit_Strategy**: The existing SP-317 `ExitStrategy` Protocol with `resolve_exit(entry_index, price_series, hold_period) -> ExitResult`. This feature adds new implementations.
- **Position_Mode**: The existing SP-317 `PositionMode` enum (NO_OVERLAP, STACKING).
- **Price_Series**: An ordered list of `PricePoint(date, open, high, low, close)`, built by `build_price_series_from_dataset`.
- **Signal_Log**: A list of Signal_Entry records, built by `build_signal_log_from_dataset`.
- **Feature_Dataset**: The `{ticker}_vpa_features.csv` dataset; SPY is at `ml_validation_output/SPY_vpa_features.csv`.
- **Strategy_Variation**: A named, fully-specified configuration (signal filter, direction handling, hold period, exit strategy, position mode) that produces one Backtest_Result and one metrics set.
- **Strategy_Return**: The direction-aware per-trade return derived from a Trade_Record. For an UP signal, Strategy_Return equals Trade_Record.return_pct. For a DOWN signal, Strategy_Return is the short-equivalent return of the same price move.
- **Equity_Curve**: A daily time series of cumulative strategy capital across the backtest date span, including days with no open position.
- **Buy_And_Hold_Return**: The return of holding SPY continuously over the backtest date span, computed from the Price_Series.
- **Risk_Free_Rate**: The configurable annual risk-free rate used by the Sharpe ratio, default 4% (0.04).
- **Metrics_Calculator**: The new component that computes the performance-metrics suite from a Trade_Log and Equity_Curve.
- **Report_Generator**: The new component that produces stdout summary, comparison table, per-trade CSV, and equity-curve CSV.
- **Trade_Log**: The ordered list of Trade_Record values in a Backtest_Result.
- **Trading_Days_Per_Year**: The annualisation constant of 252 trading days.

## Requirements

### Requirement 1: Reuse the SP-317 engine without re-implementation

**User Story:** As a developer, I want the reporting feature to run strategies through the existing engine, so that trade simulation logic stays in one tested place.

#### Acceptance Criteria

1. WHEN a Strategy_Variation is executed, THE Strategy_Variation runner SHALL call `BacktestEngine.run(signal_log, price_series, config)` exactly once for that variation and SHALL NOT re-implement trade entry, exit, or overlap simulation.
2. THE Strategy_Variation runner SHALL supply all price data as in-memory Price_Series values obtained from `build_price_series_from_dataset`.
3. THE Metrics_Calculator SHALL consume only the `trades` list of a Backtest_Result as its per-trade input and SHALL exclude the `skipped` list.
4. WHERE a Strategy_Variation requires a hold period, stop loss, or stacking behaviour, THE Strategy_Variation runner SHALL configure that behaviour through Backtest_Config fields (`hold_period`, `exit_strategy`, `position_mode`) and SHALL NOT modify, subclass, or monkeypatch `BacktestEngine`.
5. IF `BacktestEngine.run` raises an error for a Strategy_Variation, THEN THE Strategy_Variation runner SHALL abort that Strategy_Variation, retain the results of previously completed Strategy_Variations, and surface an error identifying the failed Strategy_Variation.

### Requirement 2: Engine-core purity preserved

**User Story:** As a maintainer, I want the engine core to remain pure and offline, so that backtests stay deterministic and reproducible.

#### Acceptance Criteria

1. THE Backtest_Engine core, all new Exit_Strategy implementations, and the Metrics_Calculator SHALL operate only on caller-supplied in-memory inputs and SHALL NOT perform network access, filesystem access, or import yfinance.
2. WHEN the same Signal_Log, Price_Series, and Backtest_Config are supplied on repeated runs, THE Backtest_Engine SHALL produce an identical Backtest_Result.
3. WHEN the same Trade_Log, Price_Series, and Risk_Free_Rate are supplied on repeated runs, THE Metrics_Calculator SHALL produce identical metric values.
4. IF a required in-memory input to the Backtest_Engine, an Exit_Strategy, or the Metrics_Calculator is missing or empty, THEN THE receiving component SHALL reject the input with an error identifying the missing or empty input.

### Requirement 3: Baseline strategy variation

**User Story:** As an analyst, I want a baseline strategy that enters on any signal and holds a fixed period, so that I have a reference edge to compare against.

#### Acceptance Criteria

1. THE Baseline Strategy_Variation SHALL include every Signal_Entry in the Signal_Log without filtering by Signal_Type.
2. THE Baseline Strategy_Variation SHALL configure a fixed hold period of 10 trading days by setting `Backtest_Config.hold_period` to 10 and `Backtest_Config.exit_strategy` to a `FixedHoldExitStrategy`.
3. WHILE Position_Mode is NO_OVERLAP, THE Backtest_Engine SHALL ignore a Signal_Entry that fires while a trade is open so that at most one trade is open at any time.
4. THE Baseline Strategy_Variation SHALL compute Strategy_Return for each trade using direction-aware P&L per Requirement 8, with the round-trip cost applied exactly once.
5. IF the Baseline Strategy_Variation produces zero trades, THEN THE Metrics_Calculator SHALL report the no-trades metric set per Requirement 15.

### Requirement 4: Contrarian-only strategy variation

**User Story:** As an analyst, I want a contrarian-only strategy that trades inverted bearish signals, so that I can evaluate the SP-314 contrarian edge in isolation.

#### Acceptance Criteria

1. THE Contrarian_Only Strategy_Variation SHALL include only Signal_Entry records whose Signal_Type is DISTRIBUTION or STRONG_BEARISH and SHALL exclude Signal_Entry records of every other Signal_Type.
2. THE Contrarian_Only Strategy_Variation SHALL treat each included signal as a short position, computing Strategy_Return as the short-equivalent of the trade's price move per Requirement 8.
3. IF the filtered Signal_Log for the Contrarian_Only Strategy_Variation contains zero signals, THEN THE Metrics_Calculator SHALL report the no-trades metric set per Requirement 15.

### Requirement 5: All-signals strategy variation

**User Story:** As an analyst, I want an all-signals strategy that trades every signal in its natural direction, so that I can measure the full directional edge.

#### Acceptance Criteria

1. THE All_Signals Strategy_Variation SHALL generate exactly one trade per Signal_Entry in the Signal_Log.
2. THE All_Signals Strategy_Variation SHALL compute Strategy_Return for each trade using the Signal_Direction obtained from `SIGNAL_DIRECTIONS` per Requirement 8.
3. IF a Signal_Entry has a Signal_Type that is absent from `SIGNAL_DIRECTIONS`, THEN THE All_Signals Strategy_Variation SHALL exclude that Signal_Entry and record an indication of the exclusion without halting the run.
4. IF the Signal_Log is empty, THEN THE All_Signals Strategy_Variation SHALL produce an empty trade set.

### Requirement 6: Variable-hold strategy variations

**User Story:** As an analyst, I want to test multiple hold periods, so that I can find the hold length with the best risk-adjusted return.

#### Acceptance Criteria

1. THE Variable_Hold Strategy_Variation set SHALL produce exactly one backtest for each hold period in the set {5, 10, 15, 20} trading days, for a total of four backtests.
2. WHEN a Variable_Hold Strategy_Variation is run, THE Strategy_Variation runner SHALL set `Backtest_Config.hold_period` to that variation's hold period before invoking the Backtest_Engine.
3. IF a hold period value is not an integer greater than or equal to 1, THEN THE Strategy_Variation runner SHALL reject the configuration with a descriptive error and SHALL NOT invoke the Backtest_Engine for that value.
4. IF the Backtest_Engine raises a ValueError for one Variable_Hold Strategy_Variation, THEN THE Strategy_Variation runner SHALL record that variation as failed and SHALL continue executing the remaining Variable_Hold Strategy_Variations.

### Requirement 7: Stop-loss and stacking strategy variations

**User Story:** As an analyst, I want stop-loss and signal-stacking variations, so that I can test whether risk controls or position adds improve tradeability.

#### Acceptance Criteria

1. THE feature SHALL provide a new Stop_Loss Exit_Strategy that implements the existing `ExitStrategy` Protocol via `resolve_exit(entry_index, price_series, hold_period) -> ExitResult`.
2. THE Stop_Loss Exit_Strategy SHALL compute the long stop price as `entry_price * (1 + threshold)` with the configured threshold expressed as a negative fraction.
3. WHILE a long trade is open, THE Stop_Loss Exit_Strategy SHALL detect a stop breach on the first forward PricePoint, in ascending index order, whose `low` is less than or equal to the long stop price.
4. WHILE a short trade is open, THE Stop_Loss Exit_Strategy SHALL detect a stop breach on the first forward PricePoint, in ascending index order, whose `high` is greater than or equal to the short stop price.
5. WHEN a stop breach is detected on a forward PricePoint, THE Stop_Loss Exit_Strategy SHALL resolve the exit on that breach day at the stop price.
6. IF the breach day's `open` has already gapped past the stop price, THEN THE Stop_Loss Exit_Strategy SHALL resolve the exit on that day at the day's `open`.
7. IF a stop breach and the fixed hold-period exit fall on the same day, THEN THE Stop_Loss Exit_Strategy SHALL treat the exit as a stop breach.
8. WHEN the configured stop-loss threshold is not breached within the hold period, THE Stop_Loss Exit_Strategy SHALL resolve the exit at the fixed-hold exit price.
9. THE Stop_Loss Strategy_Variation set SHALL support configurable stop-loss thresholds and SHALL include the values -2% and -3%.
10. THE Signal_Stacking Strategy_Variation SHALL configure Position_Mode STACKING so that a new signal firing while a trade is open opens an additional trade.
11. WHERE Position_Mode is the default NO_OVERLAP, THE Strategy_Variation runner SHALL cause a signal firing while a trade is open to be ignored by the Backtest_Engine.

### Requirement 8: Direction-aware per-trade P&L

**User Story:** As an analyst, I want strategy P&L to account for signal direction, so that short (DOWN) signals correctly profit when price falls.

#### Acceptance Criteria

1. WHERE a trade's Signal_Direction is UP, THE Metrics_Calculator SHALL set Strategy_Return equal to Trade_Record.return_pct.
2. WHERE a trade's Signal_Direction is DOWN, THE Metrics_Calculator SHALL set Strategy_Return equal to `(entry_price / exit_price) - 1 - round_trip_cost`, computed from the raw Trade_Record entry_price and exit_price and SHALL NOT derive Strategy_Return from Trade_Record.return_pct.
3. WHEN a DOWN-signal trade's exit_price is less than its entry_price, THE Metrics_Calculator SHALL yield a raw short-equivalent return `(entry_price / exit_price) - 1` that is greater than 0 before costs.
4. THE Metrics_Calculator SHALL subtract the round-trip cost exactly once per trade when computing Strategy_Return, avoiding double-counting the long-basis cost already embedded in Trade_Record.return_pct.
5. IF a trade's exit_price equals 0, THEN THE Metrics_Calculator SHALL exclude that trade from Strategy_Return computation and record an indication of the exclusion.
6. IF a trade's Signal_Direction is neither UP nor DOWN, THEN THE Metrics_Calculator SHALL exclude that trade from Strategy_Return computation and record an indication of the exclusion.

### Requirement 9: Equity curve construction

**User Story:** As an analyst, I want a daily equity curve, so that drawdown, time in market, and buy-and-hold comparison can be computed and the curve can be plotted later.

#### Acceptance Criteria

1. THE Metrics_Calculator SHALL construct an Equity_Curve containing exactly one data point per date in the Price_Series, ordered chronologically ascending.
2. THE Metrics_Calculator SHALL initialise the Equity_Curve at a starting capital of 1.0 on the first date of the Price_Series.
3. WHEN exactly one trade closes on a given date, THE Metrics_Calculator SHALL set `capital_after = capital_before * (1 + Strategy_Return)` on that trade's exit_date.
4. WHEN two or more trades close on the same date, THE Metrics_Calculator SHALL set `capital_after = capital_before * product_over_i(1 + Strategy_Return_i)` so that the result is independent of the order in which the closing trades are applied.
5. WHILE no trade closes on a given date, THE Metrics_Calculator SHALL carry the previous cumulative capital forward unchanged for that date.
6. THE Metrics_Calculator SHALL produce an Equity_Curve whose length equals the number of dates in the Price_Series.

### Requirement 10: Total return and buy-and-hold comparison

**User Story:** As an analyst, I want total strategy return compared to buy-and-hold SPY over the same period, so that I can judge whether the strategy beats simply holding.

#### Acceptance Criteria

1. WHEN the Equity_Curve contains two or more data points, THE Metrics_Calculator SHALL compute Total_Return as `(final_equity / initial_equity) - 1`.
2. WHEN the Price_Series contains two or more PricePoint values, THE Metrics_Calculator SHALL compute Buy_And_Hold_Return as `(last_close / first_close) - 1` using the first and last close prices of the Price_Series.
3. THE Metrics_Calculator SHALL compute Total_Return and Buy_And_Hold_Return over the identical date span used for the Strategy_Variation.
4. IF the Price_Series contains fewer than two PricePoint values, THEN THE Metrics_Calculator SHALL report Total_Return and Buy_And_Hold_Return as 0.0.
5. IF the initial_equity is 0 or the first_close is 0, THEN THE Metrics_Calculator SHALL report the affected metric as 0.0 and record an indication of the affected metric.

### Requirement 11: Annualised return and trade frequency

**User Story:** As an analyst, I want annualised return and trades per year, so that results are comparable regardless of the backtest length.

#### Acceptance Criteria

1. THE Metrics_Calculator SHALL compute trading_days_in_span as the number of distinct Price_Series dates minus 1.
2. THE Metrics_Calculator SHALL compute years as `trading_days_in_span / 252`, using the Trading_Days_Per_Year constant of 252.
3. WHEN years is greater than 0 AND Total_Return is greater than -1, THE Metrics_Calculator SHALL compute Annualised_Return as `(1 + Total_Return) ** (1 / years) - 1`.
4. WHEN years is greater than 0, THE Metrics_Calculator SHALL compute Trades_Per_Year as `number_of_trades / years`.
5. IF years equals 0, THEN THE Metrics_Calculator SHALL report Annualised_Return and Trades_Per_Year as 0.0.
6. IF Total_Return is less than or equal to -1, THEN THE Metrics_Calculator SHALL report Annualised_Return as -1.0 without evaluating the negative-base power expression.

### Requirement 12: Sharpe ratio

**User Story:** As an analyst, I want a Sharpe ratio with a configurable risk-free rate, so that I can assess risk-adjusted return.

#### Acceptance Criteria

1. THE Metrics_Calculator SHALL accept a configurable annual Risk_Free_Rate expressed as a decimal fraction in the range 0.0 to 1.0 inclusive.
2. WHERE a Risk_Free_Rate is not supplied, THE Metrics_Calculator SHALL use a default Risk_Free_Rate of 0.04.
3. THE Metrics_Calculator SHALL compute daily strategy returns as the fractional day-over-day change of Equity_Curve capital, producing one daily return per consecutive pair of Equity_Curve data points.
4. THE Metrics_Calculator SHALL compute daily_risk_free_rate as `Risk_Free_Rate / 252`.
5. THE Metrics_Calculator SHALL compute the standard deviation of daily strategy returns as the sample standard deviation using a divisor of N-1.
6. WHEN the standard deviation of daily strategy returns is greater than 0 AND at least two daily returns are available, THE Metrics_Calculator SHALL compute Sharpe_Ratio as `((mean_daily_return - daily_risk_free_rate) / std_daily_return) * sqrt(252)`.
7. IF the standard deviation of daily strategy returns equals 0, THEN THE Metrics_Calculator SHALL report Sharpe_Ratio as 0.0.
8. IF fewer than two daily returns are available, THEN THE Metrics_Calculator SHALL report Sharpe_Ratio as 0.0.

### Requirement 13: Max drawdown

**User Story:** As an analyst, I want maximum drawdown, so that I understand the worst peak-to-trough loss.

#### Acceptance Criteria

1. THE Metrics_Calculator SHALL compute running_peak_at_t as the running maximum equity from the first Equity_Curve point through the point at time t inclusive.
2. THE Metrics_Calculator SHALL compute Max_Drawdown as the minimum over all t of `(equity_at_t / running_peak_at_t) - 1`, bounded to the range -1.0 to 0.0 inclusive.
3. WHERE the Equity_Curve never falls below its running peak, THE Metrics_Calculator SHALL report Max_Drawdown as 0.0.
4. IF the Equity_Curve is empty, THEN THE Metrics_Calculator SHALL report Max_Drawdown as 0.0.
5. IF a running_peak_at_t equals 0.0, THEN THE Metrics_Calculator SHALL avoid division by zero and report Max_Drawdown as 0.0 with an indication.

### Requirement 14: Win rate, profit factor, average win/loss, and expectancy

**User Story:** As an analyst, I want per-trade quality metrics, so that I can judge the consistency and payoff profile of the edge.

#### Acceptance Criteria

1. THE Metrics_Calculator SHALL classify a trade as a win when its Strategy_Return is greater than 0 and as a loss when its Strategy_Return is less than 0, and SHALL treat a trade with a Strategy_Return of exactly 0 as neither a win nor a loss and exclude that trade from the win count and the loss count.
2. THE Metrics_Calculator SHALL compute Win_Rate as `number_of_wins / number_of_trades`, where number_of_trades includes zero-return trades, and SHALL report Win_Rate in the range 0 to 1 inclusive.
3. THE Metrics_Calculator SHALL compute Average_Win as the mean Strategy_Return of winning trades only and Average_Loss as the mean Strategy_Return of losing trades only.
4. THE Metrics_Calculator SHALL compute Profit_Factor as `sum_of_winning_returns / absolute_value_of_sum_of_losing_returns`.
5. THE Metrics_Calculator SHALL compute Expectancy as the mean Strategy_Return across all trades.
6. THE Metrics_Calculator SHALL treat a position as open from its entry_date inclusive to its exit_date exclusive, and SHALL count each calendar day that has at least one open position exactly once so that overlapping positions in STACKING mode are not double-counted.
7. THE Metrics_Calculator SHALL compute Time_In_Market as `days_with_an_open_position / total_days_in_span` and SHALL report Time_In_Market in the range 0 to 1 inclusive.

### Requirement 15: Edge-case handling for metrics

**User Story:** As a developer, I want metrics to handle empty, single-trade, and no-loss cases safely, so that reporting never crashes on divide-by-zero or empty input.

#### Acceptance Criteria

1. IF a Strategy_Variation produces zero trades, THEN THE Metrics_Calculator SHALL report Total_Return, Annualised_Return, Sharpe_Ratio, Max_Drawdown, Win_Rate, Profit_Factor, Average_Win, Average_Loss, Expectancy, Time_In_Market, and Trades_Per_Year as 0.0 without raising an error.
2. IF a Strategy_Variation produces trades with at least one positive-return trade and no negative-return trade, THEN THE Metrics_Calculator SHALL report Profit_Factor as `float("inf")`.
3. IF a Strategy_Variation produces trades with no positive-return trade and no negative-return trade, THEN THE Metrics_Calculator SHALL report Profit_Factor as 0.0.
4. IF a Strategy_Variation produces trades with no positive-return trade, THEN THE Metrics_Calculator SHALL report Average_Win as 0.0.
5. IF a Strategy_Variation produces trades with no negative-return trade, THEN THE Metrics_Calculator SHALL report Average_Loss as 0.0.
6. WHEN a Strategy_Variation produces exactly one trade, THE Metrics_Calculator SHALL compute Win_Rate, Expectancy, and Profit_Factor from that single trade without error.
7. IF the Price_Series is empty, THEN THE Metrics_Calculator SHALL report the no-trades metric set and SHALL produce an empty Equity_Curve without error.

### Requirement 16: Per-trade CSV output

**User Story:** As an analyst, I want a per-trade CSV log, so that I can inspect and post-process every simulated trade.

#### Acceptance Criteria

1. WHEN a Strategy_Variation completes, THE Report_Generator SHALL write exactly one per-trade CSV whose filename uniquely identifies the Strategy_Variation, containing one data row per Trade_Record.
2. THE Report_Generator SHALL write a header row followed by the data rows, where the header and every data row contain exactly the columns entry_date, exit_date, entry_price, exit_price, signal_type, signal_direction, and strategy_return in that order.
3. THE Report_Generator SHALL order the per-trade CSV data rows by entry_date ascending and then by exit_date ascending.
4. IF a Strategy_Variation produces zero trades, THEN THE Report_Generator SHALL write a per-trade CSV containing only the header row.

### Requirement 17: Equity curve CSV output

**User Story:** As an analyst, I want equity curve data as CSV, so that I can plot the equity curve later.

#### Acceptance Criteria

1. WHEN a Strategy_Variation completes, THE Report_Generator SHALL write an equity-curve CSV containing one data row per date in the backtest span.
2. THE Report_Generator SHALL write a header row followed by the data rows, where the header and every data row contain exactly the columns date and then equity in that order.
3. THE Report_Generator SHALL order the equity-curve CSV data rows by date ascending.
4. IF the backtest span is empty, THEN THE Report_Generator SHALL write an equity-curve CSV containing only the header row.

### Requirement 18: Stdout performance summary

**User Story:** As an analyst, I want a performance summary printed to stdout, so that I can read results immediately after a run.

#### Acceptance Criteria

1. WHEN a Strategy_Variation completes, THE Report_Generator SHALL print a performance summary to stdout that includes Total_Return, Annualised_Return, Sharpe_Ratio, Max_Drawdown, Win_Rate, Profit_Factor, Average_Win, Average_Loss, Expectancy, Time_In_Market, number of trades, and Trades_Per_Year.
2. THE Report_Generator SHALL print each metric name and its value on the same line in the stdout summary.
3. THE Report_Generator SHALL print the Strategy_Variation name and the number of trades in the stdout summary.
4. WHEN the number of trades is 0, THE Report_Generator SHALL print 0 for the number of trades in the stdout summary.

### Requirement 19: Strategy-vs-buy-and-hold comparison table

**User Story:** As an analyst, I want a comparison table across strategies and buy-and-hold, so that I can rank variations at a glance.

#### Acceptance Criteria

1. WHEN all requested Strategy_Variations complete, THE Report_Generator SHALL print a comparison table with one row per completed Strategy_Variation and one row for buy-and-hold SPY.
2. THE Report_Generator SHALL populate the Total_Return, Annualised_Return, Sharpe_Ratio, and Max_Drawdown columns for every row in the comparison table.
3. THE Report_Generator SHALL compute the buy-and-hold SPY row using the same start date and end date used by the Strategy_Variations.
4. THE Report_Generator SHALL run and compare at least three Strategy_Variations, including Baseline, Contrarian_Only, and All_Signals.
5. IF a Strategy_Variation fails to complete, THEN THE Report_Generator SHALL omit that Strategy_Variation's row from the comparison table and include an indication naming the failed Strategy_Variation.

### Requirement 20: Tradeability conclusion

**User Story:** As an analyst, I want a clear tradeability verdict, so that I know whether the detected edges are worth trading after costs.

#### Acceptance Criteria

1. WHEN the comparison across Strategy_Variations completes, THE Report_Generator SHALL print a tradeability conclusion that names the best-performing Strategy_Variation by highest Sharpe_Ratio.
2. IF two or more Strategy_Variations share the highest Sharpe_Ratio, THEN THE Report_Generator SHALL break the tie by selecting the Strategy_Variation with the highest Total_Return and then by ascending Strategy_Variation name.
3. THE tradeability conclusion SHALL state whether the best-performing Strategy_Variation's Total_Return is strictly greater than the Buy_And_Hold_Return over the same start-to-end span.
4. WHERE no Strategy_Variation's Total_Return is strictly greater than the Buy_And_Hold_Return, THE Report_Generator SHALL state that the detected edges are not tradeable after costs.
5. THE tradeability conclusion SHALL report metrics net of the round-trip cost applied by the Backtest_Engine and the direction-aware P&L.

### Requirement 21: SPY dataset loading

**User Story:** As an analyst, I want the report to run on the SPY feature dataset, so that the conclusion applies to SPY as required by the Definition of Done.

#### Acceptance Criteria

1. THE Strategy_Variation runner SHALL build the Signal_Log via `build_signal_log_from_dataset` and the Price_Series via `build_price_series_from_dataset` from the SPY Feature_Dataset at `ml_validation_output/SPY_vpa_features.csv`.
2. IF the SPY Feature_Dataset file does not exist, THEN THE Strategy_Variation runner SHALL terminate and surface a not-found error without producing a report.
3. IF the SPY Feature_Dataset is missing a required date or OHLC column, THEN THE Strategy_Variation runner SHALL terminate and surface the descriptive error raised by the builder unchanged without producing a report.
