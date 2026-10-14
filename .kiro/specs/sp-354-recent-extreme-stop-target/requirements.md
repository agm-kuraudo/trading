# Requirements Document

## Introduction

This feature adds a configurable recent-extreme stop-loss and risk-based profit-target exit strategy to the VPA backtesting engine, implementing Jira ticket **SP-354**. It extends the exit-strategy layer established in SP-317 (`vpa/backtesting/`) and the path-based percentage stop added in SP-333, without rewriting the Backtest_Engine core.

The new behaviour is delivered as an opt-in implementation of the existing Exit_Strategy protocol (`resolve_exit(self, entry_index, price_series, hold_period) -> ExitResult`). It places a stop loss derived from a recent price extreme (lowest low for long trades, highest high for short trades) measured over a configurable lookback window of bars **strictly before** entry, and derives a profit target from the resulting risk distance using a configurable reward-to-risk multiplier. The strategy scans forward OHLC bars from the bar after entry up to and including the Hold_Period boundary and exits on the first stop or target breach, mirroring the gap-through-at-open and stop-first conventions of the existing `StopLossExitStrategy`. If neither level is breached within the hold window, resolution delegates to the fixed-hold fallback.

The strategy is pure: it reads only the supplied Price_Series, returns raw prices (the engine validates them via `_is_valid_price`), never mutates its inputs, and is deterministic. It reuses the signal direction definitions (`SignalDirection`) from `vpa/ml_validation/signal_analysis.py` and carries direction as a field on the strategy, because the Exit_Strategy signature does not pass direction.

The existing Fixed_Hold_Exit_Strategy and percentage-based StopLossExitStrategy MUST remain unchanged and available as defaults/options when this new strategy is not selected. The Trade_Record is extended with optional, additive fields (`stop_loss`, `profit_target`, `exit_reason`) that default to absent so existing consumers (engine, pnl, metrics, equity_curve, reporting, data_export) are unaffected.

Integrating the Recent_Extreme_Exit_Strategy into the existing strategy-comparison harness (`vpa/backtesting/variations.py` and `report_backtest.py`) so that a single default report run compares all existing strategy variations plus the new recent-extreme variations **is in scope** and is specified in Requirements 10-12.

### Out of Scope

- Changes to the Backtest_Engine core simulation loop beyond consuming the new Exit_Strategy and the additive Trade_Record fields.
- Direction-aware return computation (handled downstream in `PricedTrade.strategy_return` / `pnl.py`); this Exit_Strategy only resolves Exit_Index and `exit_price`.
- Modifying the existing Fixed_Hold_Exit_Strategy or percentage-based StopLossExitStrategy behaviour.
- Modifying the `StrategyVariation` dataclass, the `run_variations` harness, or the `report_backtest.py` reporting pipeline beyond adding the new recent-extreme variations to the default catalogue.
- Trailing stops, R-multiple partial exits, multiple concurrent targets, or any exit rule other than the single recent-extreme stop plus single risk-based target defined here.

## Glossary

- **Backtest_Engine**: The core simulation component (SP-317) that consumes a Signal_Log and a Price_Series and produces a Trade_Log, delegating exit resolution to an Exit_Strategy.
- **Price_Series**: A date-ordered (ascending) sequence in which each element is one trading day holding `date` (ISO 8601 YYYY-MM-DD) and `open`, `high`, `low`, `close` floating-point prices, as defined in the vpa-backtesting-engine spec.
- **PricePoint**: One element of the Price_Series: a frozen record with `date`, `open`, `high`, `low`, `close`.
- **Exit_Strategy**: The pluggable protocol (SP-317) with signature `resolve_exit(self, entry_index: int, price_series: list[PricePoint], hold_period: int) -> ExitResult` that determines a trade's Exit_Index and `exit_price`.
- **ExitResult**: The frozen result of an Exit_Strategy resolution with fields `exit_index`, `exit_price`, and `reason` (a SkipReason set when the exit cannot be resolved).
- **Entry_Index**: The positional index in the Price_Series at which a trade is entered.
- **Exit_Index**: The positional index in the Price_Series at which a trade is exited.
- **Hold_Period**: The configurable number of trading days `N` after entry at which a fixed-hold exit occurs; also the forward scan boundary for the Recent_Extreme_Exit_Strategy.
- **Entry_Price**: The `close` price at the Entry_Index, used as the reference for the stop and target.
- **Signal_Direction**: The trade direction UP (long) or DOWN (short), reused from `SignalDirection` in `vpa/ml_validation/signal_analysis.py`.
- **Recent_Extreme_Exit_Strategy**: The new opt-in Exit_Strategy implementation introduced by SP-354 that places a recent-extreme stop loss and a risk-based profit target.
- **Lookback_Window**: The configurable number of bars `L`, a positive integer, immediately preceding the Entry_Index, from which the Recent_Extreme is measured. The window covers the positional indices `Entry_Index - L` through `Entry_Index - 1` inclusive, using only bars strictly before entry.
- **Recent_Extreme**: For a long trade, the lowest `low` among the bars in the Lookback_Window; for a short trade, the highest `high` among the bars in the Lookback_Window.
- **Buffer**: The configurable non-negative price offset applied beyond the Recent_Extreme when placing the stop (below the recent low for long trades, above the recent high for short trades).
- **Stop_Loss**: The computed stop price. Long: `Recent_Extreme - Buffer`. Short: `Recent_Extreme + Buffer`.
- **Risk_Distance**: The absolute price distance between the Entry_Price and the Stop_Loss, i.e. `abs(Entry_Price - Stop_Loss)`.
- **Reward_Risk_Multiplier**: The configurable strictly-positive multiplier `M` applied to the Risk_Distance to size the profit target.
- **Profit_Target**: The computed target price. Long: `Entry_Price + Risk_Distance * M`. Short: `Entry_Price - Risk_Distance * M`.
- **Fixed_Hold_Fallback**: The Fixed_Hold_Exit_Strategy delegated to when neither the Stop_Loss nor the Profit_Target is breached within the hold window.
- **Trade_Record**: A single simulated trade in the Trade_Log; extended by SP-354 with optional additive fields `stop_loss`, `profit_target`, and `exit_reason`.
- **Exit_Reason**: An indication of how a trade resolved: stop breach, target breach, or fixed-hold expiry.
- **SkipReason**: The enum recording why a signal did not produce a valid trade, extended by SP-354 for recent-extreme and risk-distance degenerate cases.
- **Round_Trip_Cost**: The configurable per-trade transaction cost from the vpa-backtesting-engine spec; unaffected by this feature.
- **Strategy_Variation**: A fully specified, named backtest configuration in `vpa/backtesting/variations.py` (the frozen `StrategyVariation` dataclass), carrying a `name`, a `signal_filter`, `hold_period`, `round_trip_cost`, `position_mode`, a zero-argument `exit_strategy_factory` callable that constructs the run's Exit_Strategy, and `risk_free_rate`. Its `to_config` method builds a `BacktestConfig` so the Backtest_Engine is reused unchanged.
- **Default_Variation_Catalogue**: The list of Strategy_Variation records returned by `build_default_variations()` in `vpa/backtesting/variations.py` (Baseline, Contrarian_Only, All_Signals, Variable_Hold_{5,10,15,20}, Stop_Loss_-2pct/-3pct, Signal_Stacking, DSS_Bressert_Only, and the five Combo_* variations), which `report_backtest.py` runs through `run_variations` to produce the comparison output.
- **Comparison_Output**: The single default report-run artefact set produced by `report_backtest.py`: a printed metrics comparison table (including buy-and-hold) plus per-variation per-trade and equity CSVs, one pair per Strategy_Variation, each keyed by the variation's distinct `name`.
- **Variation_Failure**: The `VariationFailure(name, error)` record produced by `run_variations` when a single Strategy_Variation raises during its run, allowing the remaining variations to still execute (per-variation failure isolation).

## Requirements

### Requirement 1: Opt-in Recent-Extreme Exit Strategy

**User Story:** As a quantitative researcher, I want recent-extreme stop losses and risk-based profit targets available as an opt-in exit strategy, so that I can backtest this exit model without changing the engine or affecting existing strategies.

#### Acceptance Criteria

1. THE Recent_Extreme_Exit_Strategy SHALL implement the Exit_Strategy protocol with the signature `resolve_exit(self, entry_index: int, price_series: list[PricePoint], hold_period: int) -> ExitResult`.
2. WHERE a caller configures a backtest run with the Recent_Extreme_Exit_Strategy, THE Backtest_Engine SHALL resolve each trade's Exit_Index and `exit_price` through the Recent_Extreme_Exit_Strategy.
3. WHERE a caller does not select the Recent_Extreme_Exit_Strategy, THE Backtest_Engine SHALL continue to use the configured Exit_Strategy with behaviour identical to the behaviour before SP-354.
4. THE Recent_Extreme_Exit_Strategy SHALL read only the supplied `price_series` argument and SHALL NOT access external data sources.
5. THE Recent_Extreme_Exit_Strategy SHALL leave the supplied `price_series` and its PricePoint elements unmodified after `resolve_exit` returns.
6. WHEN the Recent_Extreme_Exit_Strategy is invoked twice with identical `entry_index`, `price_series`, and `hold_period` arguments and identical configuration, THE Recent_Extreme_Exit_Strategy SHALL return an identical ExitResult.

### Requirement 2: Configuration and Validation

**User Story:** As a quantitative developer, I want the strategy's parameters to be configurable and validated, so that misconfigured backtests fail fast instead of producing invalid trades.

#### Acceptance Criteria

1. THE Recent_Extreme_Exit_Strategy SHALL accept a configurable Lookback_Window, a Buffer, a Reward_Risk_Multiplier, and a Signal_Direction.
2. THE Recent_Extreme_Exit_Strategy SHALL default the Signal_Direction to UP (long).
3. IF the Lookback_Window is not a positive integer, THEN THE Recent_Extreme_Exit_Strategy SHALL raise a ValueError at construction time.
4. IF the Buffer is negative, THEN THE Recent_Extreme_Exit_Strategy SHALL raise a ValueError at construction time.
5. IF the Reward_Risk_Multiplier is not strictly greater than zero, THEN THE Recent_Extreme_Exit_Strategy SHALL raise a ValueError at construction time.
6. WHERE the Buffer is not supplied, THE Recent_Extreme_Exit_Strategy SHALL default the Buffer to zero, placing the Stop_Loss exactly at the Recent_Extreme.

### Requirement 3: Recent-Extreme Stop-Loss Placement

**User Story:** As a quantitative researcher, I want the stop loss placed from a recent price extreme over a configurable lookback of prior bars, so that the stop reflects recent structure without look-ahead bias.

#### Acceptance Criteria

1. WHEN the Signal_Direction is UP, THE Recent_Extreme_Exit_Strategy SHALL set the Recent_Extreme to the lowest `low` among the bars at positional indices `entry_index - L` through `entry_index - 1` inclusive, where `L` is the Lookback_Window.
2. WHEN the Signal_Direction is DOWN, THE Recent_Extreme_Exit_Strategy SHALL set the Recent_Extreme to the highest `high` among the bars at positional indices `entry_index - L` through `entry_index - 1` inclusive, where `L` is the Lookback_Window.
3. THE Recent_Extreme_Exit_Strategy SHALL measure the Recent_Extreme using only bars strictly before the Entry_Index.
4. WHEN the Signal_Direction is UP, THE Recent_Extreme_Exit_Strategy SHALL set the Stop_Loss to `Recent_Extreme - Buffer`.
5. WHEN the Signal_Direction is DOWN, THE Recent_Extreme_Exit_Strategy SHALL set the Stop_Loss to `Recent_Extreme + Buffer`.

### Requirement 4: Risk Distance and Profit Target

**User Story:** As a quantitative researcher, I want the profit target derived from the risk distance by a reward-to-risk multiplier, so that targets scale with each trade's stop placement.

#### Acceptance Criteria

1. THE Recent_Extreme_Exit_Strategy SHALL compute the Risk_Distance as `abs(Entry_Price - Stop_Loss)`, where the Entry_Price is `close[entry_index]`.
2. WHEN the Signal_Direction is UP, THE Recent_Extreme_Exit_Strategy SHALL set the Profit_Target to `Entry_Price + Risk_Distance * M`, where `M` is the Reward_Risk_Multiplier.
3. WHEN the Signal_Direction is DOWN, THE Recent_Extreme_Exit_Strategy SHALL set the Profit_Target to `Entry_Price - Risk_Distance * M`, where `M` is the Reward_Risk_Multiplier.

### Requirement 5: Forward Scan and Exit Resolution

**User Story:** As a quantitative researcher, I want the strategy to scan forward bars and exit on the first stop or target breach, so that trade outcomes reflect realistic intrabar exits.

#### Acceptance Criteria

1. THE Recent_Extreme_Exit_Strategy SHALL scan the Price_Series bars from positional index `entry_index + 1` up to and including `min(entry_index + hold_period, last_index)`, where `last_index` is the final positional index of the Price_Series.
2. WHEN the Signal_Direction is UP AND a scanned bar's `low` is less than or equal to the Stop_Loss, THE Recent_Extreme_Exit_Strategy SHALL exit at that bar with an Exit_Reason of stop breach.
3. WHEN the Signal_Direction is UP AND a scanned bar's `high` is greater than or equal to the Profit_Target AND the Stop_Loss is not breached on that bar, THE Recent_Extreme_Exit_Strategy SHALL exit at that bar with an Exit_Reason of target breach.
4. WHEN the Signal_Direction is DOWN AND a scanned bar's `high` is greater than or equal to the Stop_Loss, THE Recent_Extreme_Exit_Strategy SHALL exit at that bar with an Exit_Reason of stop breach.
5. WHEN the Signal_Direction is DOWN AND a scanned bar's `low` is less than or equal to the Profit_Target AND the Stop_Loss is not breached on that bar, THE Recent_Extreme_Exit_Strategy SHALL exit at that bar with an Exit_Reason of target breach.
6. WHEN both the Stop_Loss and the Profit_Target could be breached within the same scanned bar, THE Recent_Extreme_Exit_Strategy SHALL resolve the exit as a Stop_Loss breach.
7. WHEN the Recent_Extreme_Exit_Strategy exits on a stop breach AND the scanned bar's `open` has already gapped through the Stop_Loss, THE Recent_Extreme_Exit_Strategy SHALL set the `exit_price` to the bar's `open`; otherwise THE Recent_Extreme_Exit_Strategy SHALL set the `exit_price` to the Stop_Loss.
8. WHEN the Recent_Extreme_Exit_Strategy exits on a target breach AND the scanned bar's `open` has already gapped through the Profit_Target, THE Recent_Extreme_Exit_Strategy SHALL set the `exit_price` to the bar's `open`; otherwise THE Recent_Extreme_Exit_Strategy SHALL set the `exit_price` to the Profit_Target.
9. IF neither the Stop_Loss nor the Profit_Target is breached within the scan window, THEN THE Recent_Extreme_Exit_Strategy SHALL delegate exit resolution to the Fixed_Hold_Fallback and return that ExitResult.

### Requirement 6: Edge Cases and Degenerate Configuration at Runtime

**User Story:** As a quantitative developer, I want the strategy to skip trades it cannot price safely, so that the trade log never contains invalid or divide-by-zero outcomes.

#### Acceptance Criteria

1. IF the Lookback_Window extends before the start of the Price_Series, so that fewer than `L` bars exist strictly before the Entry_Index (`entry_index - L < 0`), THEN THE Recent_Extreme_Exit_Strategy SHALL return an ExitResult carrying a SkipReason indicating an unavailable recent extreme, with `exit_index` and `exit_price` unset.
2. IF the computed Risk_Distance is zero, THEN THE Recent_Extreme_Exit_Strategy SHALL return an ExitResult carrying a SkipReason indicating a degenerate risk distance, with `exit_index` and `exit_price` unset.
3. IF the computed Stop_Loss is on the losing side such that it is not adverse to the Entry_Price for the Signal_Direction (Stop_Loss greater than or equal to Entry_Price for UP, or Stop_Loss less than or equal to Entry_Price for DOWN), THEN THE Recent_Extreme_Exit_Strategy SHALL return an ExitResult carrying a SkipReason indicating a degenerate risk distance, with `exit_index` and `exit_price` unset.
4. WHEN the Recent_Extreme_Exit_Strategy returns an ExitResult carrying a SkipReason, THE Backtest_Engine SHALL skip the originating signal and record the skip with that SkipReason, consistent with the existing engine skip handling.
5. THE SkipReason enum SHALL include a distinct value for an unavailable recent extreme and a distinct value for a degenerate risk distance.

### Requirement 7: Trade Output Extension and Backward Compatibility

**User Story:** As a quantitative researcher, I want the resolved stop, target, and exit reason exposed on each trade, so that I can inspect how trades were resolved without breaking existing tooling.

#### Acceptance Criteria

1. THE Trade_Record SHALL provide optional additive fields `stop_loss`, `profit_target`, and `exit_reason`.
2. THE Trade_Record SHALL default `stop_loss`, `profit_target`, and `exit_reason` to an absent value (None) when they are not supplied.
3. WHEN a trade is resolved by the Recent_Extreme_Exit_Strategy, THE Backtest_Engine SHALL populate the Trade_Record `stop_loss` with the computed Stop_Loss, `profit_target` with the computed Profit_Target, and `exit_reason` with the resolved Exit_Reason.
4. WHEN a trade is resolved by an Exit_Strategy that does not supply a stop, target, or exit reason, THE Backtest_Engine SHALL leave the Trade_Record `stop_loss`, `profit_target`, and `exit_reason` fields at their absent default.
5. THE existing consumers of Trade_Record (pnl, metrics, equity_curve, reporting, data_export) SHALL operate unchanged when the `stop_loss`, `profit_target`, and `exit_reason` fields are absent.

### Requirement 8: Preservation of Existing Strategies

**User Story:** As a quantitative researcher, I want the existing fixed-hold and percentage-stop strategies untouched, so that prior backtest configurations reproduce identical results.

#### Acceptance Criteria

1. THE Fixed_Hold_Exit_Strategy SHALL remain available and SHALL retain the behaviour defined in the vpa-backtesting-engine spec.
2. THE percentage-based StopLossExitStrategy SHALL remain available and SHALL retain its SP-333 behaviour.
3. WHEN a backtest run is configured with the Fixed_Hold_Exit_Strategy or the percentage-based StopLossExitStrategy, THE Backtest_Engine SHALL produce a Trade_Log identical to the Trade_Log it produced for that configuration before SP-354.

### Requirement 9: Determinism and Testability

**User Story:** As a developer, I want the strategy to produce deterministic, hand-verifiable results, so that I can cover it with automated tests.

#### Acceptance Criteria

1. THE Recent_Extreme_Exit_Strategy SHALL depend only on its configuration and the in-memory `entry_index`, `price_series`, and `hold_period` arguments, with no network or `yfinance` dependency.
2. THE Recent_Extreme_Exit_Strategy SHALL return an ExitResult whose `exit_index` and `exit_price` match hand-computed expected values for a small known Price_Series under specified Lookback_Window, Buffer, Reward_Risk_Multiplier, Signal_Direction, and Hold_Period.
3. THE Recent_Extreme_Exit_Strategy SHALL resolve long and short trades using the direction carried on the strategy, independent of any direction field on the signal.

### Requirement 10: Comparison-Harness Integration of Recent-Extreme Variations

**User Story:** As a quantitative researcher, I want a single default report run to compare all existing strategy variations alongside the new recent-extreme variations in one output, so that I can evaluate the recent-extreme exit model against the existing strategies without a separate run.

#### Acceptance Criteria

1. THE Default_Variation_Catalogue SHALL include the existing strategy variations and the new recent-extreme Strategy_Variation records in a single list returned by `build_default_variations()`.
2. WHEN `report_backtest.py` executes a default report run, THE Comparison_Output SHALL include the metrics and per-variation CSVs for every existing variation and every new recent-extreme variation together.
3. THE recent-extreme Strategy_Variation records SHALL be built through the existing `StrategyVariation.exit_strategy_factory` mechanism as a zero-argument callable that constructs a configured Recent_Extreme_Exit_Strategy, reusing the Backtest_Engine and the reporting pipeline without modifying, subclassing, or monkeypatching them.
4. THE comparison-harness integration SHALL leave the existing variations' presence, names, and ordering in the Default_Variation_Catalogue unchanged, adding the recent-extreme variations in addition to them.

### Requirement 11: Direction-Specific Default Recent-Extreme Sweep

**User Story:** As a quantitative researcher, I want the default catalogue to sweep the recent-extreme strategy across its key parameters with explicit long and short variations, so that I can compare its behaviour across configurations and directions in one run.

#### Acceptance Criteria

1. THE Default_Variation_Catalogue SHALL add one recent-extreme Strategy_Variation for each combination of Reward_Risk_Multiplier in {1, 2, 3}, Lookback_Window in {5, 10}, and Signal_Direction in {UP, DOWN}, producing twelve recent-extreme variations.
2. WHERE a recent-extreme Strategy_Variation is added to the Default_Variation_Catalogue, THE recent-extreme Strategy_Variation SHALL carry its Signal_Direction explicitly as either UP (long) or DOWN (short).
3. THE Default_Variation_Catalogue SHALL set the Buffer to zero for every recent-extreme Strategy_Variation it adds.
4. THE Recent_Extreme_Exit_Strategy SHALL keep the Lookback_Window, Buffer, Reward_Risk_Multiplier, and Signal_Direction configurable per Requirement 2, independent of the fixed values the Default_Variation_Catalogue selects.
5. THE Default_Variation_Catalogue SHALL assign each recent-extreme Strategy_Variation a distinct, descriptive `name` that includes its Signal_Direction, Reward_Risk_Multiplier, and Lookback_Window, so that per-variation CSV slugs in the Comparison_Output remain unique.

### Requirement 12: Failure Isolation and Trade Output for Recent-Extreme Variations

**User Story:** As a quantitative researcher, I want a failing recent-extreme variation to be isolated and the resolved stop, target, and exit reason carried through per-trade output, so that one bad configuration does not abort the comparison and I can still inspect how recent-extreme trades resolved.

#### Acceptance Criteria

1. IF a recent-extreme Strategy_Variation raises during its run, THEN `run_variations` SHALL record it as a Variation_Failure and SHALL continue running the remaining variations, consistent with the existing per-variation failure isolation.
2. WHEN a recent-extreme Strategy_Variation completes successfully, THE Comparison_Output SHALL include that variation's metrics and per-variation CSVs alongside the other variations.
3. WHEN a trade in a recent-extreme Strategy_Variation is resolved by the Recent_Extreme_Exit_Strategy, THE per-trade output for that variation SHALL carry the Trade_Record `stop_loss`, `profit_target`, and `exit_reason` fields defined in Requirement 7.
4. THE existing per-trade and equity CSV consumers in `report_backtest.py` SHALL operate unchanged for variations whose trades leave the `stop_loss`, `profit_target`, and `exit_reason` fields at their absent default.
