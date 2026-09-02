# Requirements Document

## Introduction

This feature adds the core VPA backtesting engine for SPY, implementing Jira ticket **SP-317**. The engine simulates trading SPY based on VPA signals produced by SP-314 (the signal-conditional analysis and daily signal work) and produces a correct per-trade log. It is the foundational simulation engine only: strategy variations, the full performance-metrics suite, and reporting are deferred to follow-on ticket SP-333 (see the Out of Scope subsection).

The engine operates purely on an in-memory, date-ordered OHLC price series (open, high, low, close per trading day) and a signal log. It MUST NOT introduce a network or `yfinance` dependency; all price data is supplied by the caller.

**Dependency (SP-335):** Ticket **SP-335** ("Add OHLC (open/high/low) to VPA feature datasets") extends the SP-314 feature datasets (`{ticker}_vpa_features.csv`) so that each row includes raw `open`, `high`, and `low` columns alongside `close`. SP-335 **blocks SP-317**: the dataset-extraction change lives in SP-335, and SP-317 consumes the enriched OHLC series. SP-317 itself does not modify the dataset extraction.

**Deviation from ticket wording (entry price):** The SP-317 ticket originally described trade entry at the "next open". This spec instead specifies trade entry at the **next-day close**, with a close-based fixed-hold exit. For the fixed-hold strategy implemented in SP-317 we use close-based entry/exit: entry price = `close[t+1]` where `t` is the signal-day index in the price series, and exit price = `close[t+1+N]` for a hold period of `N` days. The `open`, `high`, and `low` columns are carried in the Price_Series (via SP-335) to support richer exit strategies later, but are unused by the SP-317 fixed-hold strategy. This deviation is intentional and settled.

The engine lives in a new package `vpa/backtesting/`, separate from `vpa/ml_validation/`, and reuses the signal definitions (`SignalType`, `SignalDirection`, `SIGNAL_DIRECTIONS`, `SignalConditionalAnalyzer.classify_signals`) already defined in `vpa/ml_validation/signal_analysis.py`.

## Glossary

- **Backtest_Engine**: The core simulation component that consumes a Signal_Log and a Price_Series and produces a Trade_Log.
- **Signal_Log**: An ordered collection of Signal_Entry records used as input to the Backtest_Engine.
- **Signal_Entry**: A single input signal record with fields: `date` (ISO 8601 YYYY-MM-DD), `signal_type` (a SignalType value), and `direction` (a SignalDirection value: UP or DOWN).
- **Price_Series**: A date-ordered (ascending) sequence in which each element represents one trading day and contains a `date` (ISO 8601 YYYY-MM-DD) and `open`, `high`, `low`, `close` (all floats) values, with no gaps introduced by the engine (each consecutive element represents one trading day).
- **Signal_Type**: One of the five VPA signal categories defined in `vpa/ml_validation/signal_analysis.py`: STRONG_BULLISH, STRONG_BEARISH, ACCUMULATION, DISTRIBUTION, ACCUMULATION_TEST_PASS.
- **Signal_Direction**: The expected price direction for a signal, UP or DOWN, as defined by `SIGNAL_DIRECTIONS`.
- **Signal_Confidence_Order**: The descending confidence ranking of SignalType values reused from `vpa/ml_validation/daily_signal.py` (its `CONFIDENCE_MAP` and `CONFIDENCE_ORDER`), from highest to lowest rank: DISTRIBUTION (High), then STRONG_BEARISH (Medium-High), then STRONG_BULLISH (Low-Medium), then ACCUMULATION (Low). Any SignalType not present in this ranking (for example ACCUMULATION_TEST_PASS, which `daily_signal.py` excludes via `EXCLUDED_SIGNALS`) is treated as lower rank than every ranked SignalType. Ties in rank between two SignalType values (including two unranked SignalType values) are broken deterministically by SignalType enum declaration order in `vpa/ml_validation/signal_analysis.py` (STRONG_BULLISH, STRONG_BEARISH, ACCUMULATION, DISTRIBUTION, ACCUMULATION_TEST_PASS), so the resulting total order is fully deterministic.
- **Feature_Dataset**: The CSV file produced by SP-314 (`{ticker}_vpa_features.csv`) containing at least `date` and `close` columns plus VPA feature columns (composite_score, acc_dist_flag, acc_dist_type, acc_dist_score). Via SP-335, the dataset also includes raw `open`, `high`, and `low` columns alongside `close`.
- **Signal_Log_Builder**: The component that constructs a Signal_Log from a Feature_Dataset by reusing SP-314 signal classification.
- **Hold_Period**: The configurable number of trading days `N` a trade is held before exit. Exit occurs `N` trading days after entry.
- **Entry_Index**: The positional index `t+1` in the Price_Series at which a trade is entered, where `t` is the positional index of the signal day in the Price_Series.
- **Exit_Index**: The positional index `t+1+N` in the Price_Series at which a trade is exited.
- **Exit_Strategy**: A pluggable component that, given an open trade (including its Entry_Index) and the forward Price_Series, determines the trade's Exit_Index and `exit_price`.
- **Fixed_Hold_Exit_Strategy**: The sole Exit_Strategy implementation in SP-317, which exits a trade at Exit_Index `t+1+N` using `close[t+1+N]`, where `t` is the signal-day index and `N` is the Hold_Period.
- **Round_Trip_Cost**: The configurable total transaction cost (spread + commission) applied once per trade to model the combined cost of entering and exiting, expressed as a decimal fraction (default 0.001, i.e. 0.1%).
- **Gross_Return**: The return of a trade before transaction costs, computed as `exit_price / entry_price - 1`.
- **Net_Return**: The return of a trade after transaction costs, computed as `Gross_Return - Round_Trip_Cost`.
- **Position_Mode**: The configurable trade-tracking behaviour: NO_OVERLAP (a new trade cannot open while an existing trade is open) or STACKING (concurrent trades are permitted).
- **Trade_Log**: The ordered output collection of Trade_Record entries produced by the Backtest_Engine.
- **Trade_Record**: A single simulated trade with fields: `entry_date`, `exit_date`, `entry_price`, `exit_price`, `return_pct`, `signal_type`.

## Requirements

### Requirement 1: Input Contract

**User Story:** As a quantitative developer, I want the backtesting engine to accept a well-defined signal log and price series, so that simulation inputs are unambiguous and validated before trades are simulated.

#### Acceptance Criteria

1. THE Backtest_Engine SHALL accept a Signal_Log where each Signal_Entry contains a `date` field formatted as an ISO 8601 date string (YYYY-MM-DD), a `signal_type` field holding a SignalType value, and a `direction` field holding a SignalDirection value.
2. THE Backtest_Engine SHALL accept a Price_Series where each element contains a `date` field formatted as an ISO 8601 date string (YYYY-MM-DD) and `open`, `high`, `low`, and `close` fields each holding a floating-point price.
3. THE Backtest_Engine SHALL treat the Price_Series as ordered by `date` ascending, where each consecutive element represents one trading day, and the positional index of an element is its Entry_Index / Exit_Index reference.
4. IF the Price_Series is not sorted by `date` in ascending order, THEN THE Backtest_Engine SHALL sort the Price_Series by `date` ascending before simulation.
5. IF a Signal_Entry `date` does not correspond to any `date` present in the Price_Series, THEN THE Backtest_Engine SHALL exclude that Signal_Entry from simulation and record that the Signal_Entry was skipped due to a missing matching price date.
6. THE Backtest_Engine SHALL process Signal_Entry records in ascending `date` order regardless of the input order of the Signal_Log.

### Requirement 2: Signal Log Generation from a Feature Dataset

**User Story:** As a quantitative developer, I want to build a historical signal log from an existing feature dataset by reusing SP-314 classification, so that I can backtest against real historical signals without duplicating signal logic.

#### Acceptance Criteria

1. THE Signal_Log_Builder SHALL construct a Signal_Log from a Feature_Dataset by reusing the SP-314 signal classification defined in `vpa/ml_validation/signal_analysis.py`.
2. WHEN the Signal_Log_Builder classifies a Feature_Dataset row as matching one or more SignalType values, THE Signal_Log_Builder SHALL create one Signal_Entry per matched SignalType, using the row `date`, the matched SignalType as `signal_type`, and the direction from `SIGNAL_DIRECTIONS` as `direction`.
3. THE Signal_Log_Builder SHALL derive the Price_Series from the `date`, `open`, `high`, `low`, and `close` columns of the same Feature_Dataset, sorted by `date` ascending.
4. WHERE a caller provides a pre-built Signal_Log directly, THE Backtest_Engine SHALL accept that Signal_Log without requiring a Feature_Dataset.
5. IF a Feature_Dataset row contains a NaN value in a field required by a signal filter, THEN THE Signal_Log_Builder SHALL treat that row as not matching the signal filter that depends on the missing field, consistent with the SP-314 classification behaviour.

### Requirement 3: Trade Simulation

**User Story:** As a quantitative researcher, I want each signal to be simulated as a trade entered at the next-day close and exited after a configurable hold period, so that I can measure the return attributable to each signal.

#### Acceptance Criteria

1. WHEN a Signal_Entry matches a Price_Series element at positional index `t`, THE Backtest_Engine SHALL set the trade Entry_Index to `t+1` and use `close[t+1]` as the `entry_price`.
2. WHEN a trade is entered at Entry_Index `t+1` with Hold_Period `N`, THE Backtest_Engine SHALL set the Exit_Index to `t+1+N` and use `close[t+1+N]` as the `exit_price`.
3. THE Backtest_Engine SHALL set the trade `entry_date` to the `date` at the Entry_Index and the trade `exit_date` to the `date` at the Exit_Index.
4. THE Backtest_Engine SHALL set the trade `signal_type` to the `signal_type` of the originating Signal_Entry.
5. THE Backtest_Engine SHALL accept a configurable Hold_Period `N` where `N` is a positive integer, with the Hold_Period being applied uniformly to every simulated trade in a single backtest run.
6. THE Backtest_Engine SHALL compute the trade Gross_Return as `exit_price / entry_price - 1`.

### Requirement 4: Transaction Cost Model

**User Story:** As a quantitative researcher, I want configurable transaction costs applied to each trade, so that simulated returns reflect realistic net outcomes rather than frictionless prices.

#### Acceptance Criteria

1. THE Backtest_Engine SHALL accept a configurable Round_Trip_Cost expressed as a decimal fraction, defaulting to 0.001 (0.1%) when not supplied.
2. THE Backtest_Engine SHALL compute the trade Net_Return as `Gross_Return - Round_Trip_Cost`.
3. THE Backtest_Engine SHALL set the trade `return_pct` field to the Net_Return.
4. WHERE a caller supplies a Round_Trip_Cost of 0, THE Backtest_Engine SHALL set `return_pct` equal to the Gross_Return.
5. THE Backtest_Engine SHALL apply the Round_Trip_Cost exactly once per trade, representing the combined cost of entering and exiting the position.

### Requirement 5: Position Tracking Modes

**User Story:** As a quantitative researcher, I want to choose between non-overlapping and stacking position modes, so that I can compare a single-position strategy against one that permits concurrent trades.

#### Acceptance Criteria

1. THE Backtest_Engine SHALL accept a configurable Position_Mode with the values NO_OVERLAP and STACKING.
2. WHILE the Position_Mode is NO_OVERLAP AND an existing trade remains open (its Exit_Index has not been reached), THE Backtest_Engine SHALL skip any Signal_Entry whose Entry_Index falls on or before the open trade's Exit_Index, and SHALL record that the Signal_Entry was skipped due to an overlapping open position.
3. WHILE the Position_Mode is NO_OVERLAP AND no trade is currently open, THE Backtest_Engine SHALL open a new trade for the next eligible Signal_Entry.
4. WHEN the Position_Mode is NO_OVERLAP AND no trade is currently open AND two or more eligible Signal_Entry records share the same Entry_Index, THE Backtest_Engine SHALL open a single trade for the Signal_Entry whose `signal_type` ranks highest in the Signal_Confidence_Order.
5. WHEN the Position_Mode is NO_OVERLAP AND a single trade is opened from two or more Signal_Entry records that share the same Entry_Index, THE Backtest_Engine SHALL skip each remaining same-Entry_Index Signal_Entry due to the overlapping open position and SHALL record that each such Signal_Entry was skipped due to an overlapping open position, consistent with acceptance criterion 5.2.
6. WHILE the Position_Mode is STACKING, THE Backtest_Engine SHALL open a trade for every eligible Signal_Entry regardless of whether other trades are currently open.
7. WHERE the Position_Mode is STACKING, THE Backtest_Engine SHALL NOT apply the Signal_Confidence_Order same-Entry_Index tie-break, so every eligible Signal_Entry sharing an Entry_Index opens its own trade.
8. THE Backtest_Engine SHALL evaluate Position_Mode eligibility by processing Signal_Entry records in ascending `date` order.

### Requirement 6: Trade Log Output

**User Story:** As a quantitative researcher, I want a structured per-trade log, so that I can inspect and later analyse each simulated trade.

#### Acceptance Criteria

1. THE Backtest_Engine SHALL produce a Trade_Log where each Trade_Record contains the fields `entry_date`, `exit_date`, `entry_price`, `exit_price`, `return_pct`, and `signal_type`.
2. THE Backtest_Engine SHALL order the Trade_Log by `entry_date` ascending.
3. THE Backtest_Engine SHALL format the `entry_date` and `exit_date` fields as ISO 8601 date strings (YYYY-MM-DD).
4. THE Backtest_Engine SHALL set the `signal_type` field of each Trade_Record to the SignalType value of the originating Signal_Entry.
5. WHEN the Signal_Log contains no eligible Signal_Entry records, THE Backtest_Engine SHALL produce an empty Trade_Log.

### Requirement 7: Edge Cases and Data Integrity

**User Story:** As a quantitative developer, I want the engine to handle boundary conditions and invalid prices gracefully, so that I can trust the trade log without manual data cleaning.

#### Acceptance Criteria

1. IF a Signal_Entry maps to a signal-day index `t` where `t+1` is beyond the last positional index of the Price_Series, THEN THE Backtest_Engine SHALL skip that Signal_Entry and record that it was skipped due to insufficient future data for entry.
2. IF a Signal_Entry maps to a signal-day index `t` where the Exit_Index `t+1+N` is beyond the last positional index of the Price_Series, THEN THE Backtest_Engine SHALL skip that Signal_Entry and record that it was skipped due to insufficient future data for the exit horizon.
3. WHEN the Signal_Log is empty, THE Backtest_Engine SHALL produce an empty Trade_Log without raising an error.
4. IF the `entry_price` at the Entry_Index is zero or NaN, THEN THE Backtest_Engine SHALL skip that trade and record that it was skipped due to an invalid entry price.
5. IF the `exit_price` at the Exit_Index is zero or NaN, THEN THE Backtest_Engine SHALL skip that trade and record that it was skipped due to an invalid exit price.
6. THE Backtest_Engine SHALL leave the input Signal_Log and Price_Series unmodified after a backtest run completes.

### Requirement 8: Determinism and Testability

**User Story:** As a developer, I want the engine to produce deterministic results on a small known signal set, so that I can verify correctness with automated tests.

#### Acceptance Criteria

1. WHEN the Backtest_Engine is run twice with identical Signal_Log, Price_Series, and configuration inputs, THE Backtest_Engine SHALL produce identical Trade_Log output.
2. THE Backtest_Engine SHALL produce a Trade_Log whose Trade_Records match hand-computed expected trades for a small known Signal_Log and Price_Series under a specified Hold_Period, Round_Trip_Cost, and Position_Mode.
3. THE Backtest_Engine SHALL depend only on the in-memory Signal_Log and Price_Series inputs and configuration, with no network or `yfinance` dependency.

### Requirement 9: Exit Strategy Abstraction

**User Story:** As a quantitative developer, I want the engine's exit logic to be defined behind a pluggable strategy abstraction, so that richer exit strategies can be added later without rewriting the engine core.

#### Acceptance Criteria

1. THE Backtest_Engine SHALL determine each trade's Exit_Index and `exit_price` through a pluggable Exit_Strategy.
2. THE Backtest_Engine SHALL provide a Fixed_Hold_Exit_Strategy that exits a trade `N` trading days after entry at Exit_Index `t+1+N` using `close[t+1+N]`, and SHALL use the Fixed_Hold_Exit_Strategy as the default Exit_Strategy.
3. THE Exit_Strategy SHALL receive the open trade's Entry_Index and the forward Price_Series, including the `open`, `high`, and `low` values, so that path-based Exit_Strategy implementations can be added later without changing the Backtest_Engine core.
4. THE Backtest_Engine SHALL implement only the Fixed_Hold_Exit_Strategy in SP-317.

## Out of Scope

The following items are explicitly out of scope for SP-317 and are handled in follow-on ticket **SP-333**:

- **Strategy variations**: baseline, contrarian, all-signals, variable-hold, stop-loss, and stacking strategy configurations beyond the single configurable Position_Mode and Hold_Period defined above.
- **Non-fixed-hold Exit_Strategy implementations**: path-based, stop-loss, and R-multiple exit strategies (for example, a stop set at the lowest low of the last X days as 1R, with a profit target at a multiple of R) and any Exit_Strategy implementation other than the Fixed_Hold_Exit_Strategy. SP-317 defines the Exit_Strategy abstraction and implements only the Fixed_Hold_Exit_Strategy; these additional strategies are handled in SP-333.
- **Full performance-metrics suite**: Sharpe ratio, maximum drawdown, profit factor, expectancy, and any other aggregate performance statistics.
- **Reporting**: summary reports, per-trade CSV export, equity curve generation, and buy-and-hold comparison.
- **Tradeability conclusion**: any automated verdict on whether the signals are tradeable.
- **Live trading integration**: any connection to brokers, order routing, or execution against live or paper accounts.

The following item is a prerequisite dependency for SP-317 but is not implemented within SP-317 itself:

- **OHLC dataset enrichment (SP-335)**: extending the SP-314 feature datasets to include raw `open`, `high`, and `low` columns alongside `close` is handled in **SP-335**, which blocks SP-317. SP-317 only consumes the enriched OHLC Price_Series; the dataset-extraction change lives in SP-335.
