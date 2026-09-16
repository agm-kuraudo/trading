# Implementation Plan: DSS Bressert Signal

## Overview

This plan implements the Double Smoothed Stochastic (DSS) Bressert oscillator as a new,
config-driven signal category in the trading project (`d:\projects\trading\vpa`), tracked by
Jira ticket **SP-325**. Work proceeds bottom-up: the pure calculator first, then config
typing, then the `MarketAnalyzer` wiring that folds a single sub-score into the composite
`trade_signal`, then the isolated backtest path and feature-extractor integration, then the
visualization, and finally a full-suite verification pass.

Each task references the requirement clauses it satisfies. Property-based test sub-tasks
reference the design's Property numbers and are marked optional with `*`. Tasks are coding
tasks only; SP-325's definition of done also requires the code be exercised/verified locally,
which the final verification task covers (manual TradingView comparison is noted as a
sub-step, not an automatable task).

## Tasks

- [ ] 1. Create the pure DSS Bressert calculator module `vpa/dss_bressert.py`
  - [x] 1.1 Implement `_stochastic_series`, `_ema_series`, and `calculate_dss_bressert`
    - Create `vpa/dss_bressert.py` mirroring the purity/neutral-value discipline of `vpa/rsi.py`
    - `_stochastic_series(high, low, close, period)`: trailing-window %K, guarding flat-range windows (max == min) by carrying forward the prior stochastic value, or `50.0` when there is no prior value
    - `_ema_series(values, length)`: EMA with `alpha = 2 / (length + 1)`, seeded from the first element
    - `calculate_dss_bressert(high, low, close, stochastic_period=10, smoothing_period=9, trigger_period=5)`: apply the exact Pine chain `xPreCalc = ema(stoch(close,high,low,PDS), EMAlen)`, `oscillator = ema(stoch(xPreCalc,xPreCalc,xPreCalc,PDS), EMAlen)`, `trigger = ema(oscillator, TriggerLen)`; return `(oscillator, trigger)` as aligned lists
    - Define `minimum_warmup_length = stochastic_period + smoothing_period + trigger_period - 2`; set every index below it to `50.0` for both lists
    - Return all-`50.0`/all-`50.0` when the series is shorter than warmup, or when any period is not an integer `>= 1` (no error raised); deterministic and side-effect free
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 8.1, 8.2_

  - [ ]* 1.2 Write property test for oscillator/trigger bounds
    - **Property 1: Oscillator and trigger are bounded**
    - Random OHLC series (length >= warmup) with valid periods; assert every oscillator and trigger value in `[0.0, 100.0]`
    - Tag: `# Feature: dss-bressert-signal, Property 1`; `@settings(max_examples=100)`
    - **Validates: Requirements 1.1, 1.2, 1.3**

  - [ ]* 1.3 Write property test for monotone series driving the oscillator
    - **Property 2: Monotone series drive the oscillator to the correct side of 50**
    - Strictly increasing series -> post-warmup oscillator `>= 50.0`; strictly decreasing -> `<= 50.0`
    - Tag: `# Feature: dss-bressert-signal, Property 2`; `@settings(max_examples=100)`
    - **Validates: Requirements 1.4, 1.5**

  - [ ]* 1.4 Write property test for warmup-neutral behaviour
    - **Property 3: Series shorter than or earlier than warmup are neutral**
    - Series shorter than warmup -> all `50.0`; series >= warmup -> every index below warmup equals `50.0`
    - Tag: `# Feature: dss-bressert-signal, Property 3`; `@settings(max_examples=100)`
    - **Validates: Requirements 8.1, 8.2, 8.3**

  - [ ]* 1.5 Write property test for determinism
    - **Property 4: Determinism**
    - Any OHLC series; assert two invocations return identical oscillator and trigger lists
    - Tag: `# Feature: dss-bressert-signal, Property 4`; `@settings(max_examples=100)`
    - **Validates: Requirements 1.8**

  - [ ]* 1.6 Write property test for invalid periods
    - **Property 5: Invalid periods yield a neutral series with no error**
    - Draw invalid period values (0, negatives, floats); assert all-`50.0` and no exception
    - Tag: `# Feature: dss-bressert-signal, Property 5`; `@settings(max_examples=100)`
    - **Validates: Requirements 1.7**

  - [x] 1.7 Write unit/reference tests for the calculator chain
    - Hand-computed small series compared to expected oscillator/trigger values, verifying the exact `ema(stoch(ema(stoch(...))))` chain and `trigger = ema(oscillator, TriggerLen)` (Req 1.9)
    - Flat (constant) price series -> oscillator exactly `50.0` (Req 1.6)
    - Series shorter than warmup -> oscillator exactly `50.0` (Req 9.2)
    - Valid series bounds spot-check -> oscillator in `[0, 100]` (Req 9.1)
    - _Requirements: 1.6, 1.9, 9.1, 9.2_

- [ ] 2. Checkpoint - calculator complete
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 3. Add DSS Bressert config typing in `vpa/config/settings.py`
  - [x] 3.1 Define `DSSScores` and `DSSBressertSettings` dataclasses and the `dss_bressert` field
    - Add frozen `DSSScores` (`bullish_crossover`, `bearish_crossover`, `oversold`, `overbought`, all `float`, default `0`)
    - Add frozen `DSSBressertSettings` (`enabled: bool = True`, `stochastic_period: int = 10`, `smoothing_period: int = 9`, `trigger_period: int = 5`, `overbought_threshold: float = 80`, `oversold_threshold: float = 20`, `scores: DSSScores = DSSScores()`)
    - Add a `dss_bressert: DSSBressertSettings` field to the `Settings` dataclass
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 3.2 Implement `_dss_bressert_settings` loader and wire into `load_settings`
    - Add `_dss_bressert_settings(raw)` reusing `_section`, `_optional`, `_number`, matching the `_price_vs_sma_settings` pattern (no deep-range validation at load time)
    - In `load_settings()`, add `dss_bressert=_dss_bressert_settings(_section(raw, "dss_bressert", "dss_bressert"))` to the `Settings(...)` construction so an absent block yields the Req 2.3 defaults
    - _Requirements: 2.1, 2.3, 2.4_

  - [x] 3.3 Add the `dss_bressert` block to `config/config.json`
    - Add the block shaped like `rsi` / `ma_crossover`: `enabled`, `stochastic_period` 10, `smoothing_period` 9, `trigger_period` 5, `overbought_threshold` 80, `oversold_threshold` 20, and a `scores` sub-block (all `0`)
    - _Requirements: 2.1, 2.2_

  - [ ] 3.4 Write unit tests for config defaults and typing
    - Settings loaded with no `dss_bressert` block -> documented Req 2.3 defaults
    - Settings loaded with a full block -> values round-trip onto `DSSBressertSettings` / `DSSScores`
    - _Requirements: 2.1, 2.2, 2.3_

- [ ] 4. Wire the DSS Bressert signal into `MarketAnalyzer` (`vpa/app_runner.py`)
  - [x] 4.1 Implement `_init_dss_bressert_config` with validation and call it from `__init__`
    - Set `self.__dss_bressert_config` / `self.__dss_bressert_enabled`, mirroring `_init_rsi_config`
    - Disabled when `enabled` is false/absent/non-boolean (Req 7.5)
    - WARN + disable when any period is not an int in `1..500` (Req 2.6)
    - WARN + disable when a threshold is outside `0..100` or `oversold >= overbought` (Req 2.7)
    - Add `self._init_dss_bressert_config()` alongside the existing `_init_*_config()` calls in `__init__`
    - _Requirements: 2.5, 2.6, 2.7, 7.5_

  - [x] 4.2 Implement `compute_dss_bressert_columns`
    - Pre-compute `DSS` and `DSS_Trigger` columns on `self.myDF` from `High`/`Low`/`Close` via `calculate_dss_bressert`, using the configured periods; no-op when disabled (mirrors `compute_rsi_column`)
    - _Requirements: 2.4, 8.1, 8.2_

  - [x] 4.3 Implement `detect_dss_bressert_signals(row_index)`
    - Return exactly `{"dss_bressert_signals": list[str], "dss_bressert_signal_score": float}`
    - Crossover detection against `iloc[row_index - 1]`: bullish (prev DSS <= prev trig AND curr DSS > curr trig) adds `bullish_crossover`; bearish (prev DSS >= prev trig AND curr DSS < curr trig) subtracts `bearish_crossover` (Req 3.1-3.5)
    - Zone scoring: DSS <= oversold adds `oversold` score; DSS >= overbought adds `overbought` score; strictly between -> no zone signal (Req 4.1-4.3)
    - Graceful degradation: empty list + `0.0` when disabled (Req 7.1-7.3), when `row_index < warmup` (Req 8.3), or when current/previous DSS or trigger is NaN/non-finite (Req 3.6, 4.4, 8.4)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.1, 4.2, 4.3, 4.4, 5.5, 7.1, 7.2, 7.3, 8.3, 8.4_

  - [x] 4.4 Edit `process_data` to compute, detect, merge, and sum
    - Call `self.compute_dss_bressert_columns()` beside the other `compute_*` calls
    - Add Step 6.4: call `detect_dss_bressert_signals(row_position)` and merge both entries into `signals`
    - Add `+ signals["dss_bressert_signal_score"]` to the `trade_signal` summation (single additive term, no weighting/scaling/ordering dependency)
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 7.4_

  - [ ]* 4.5 Write property test for bullish crossover sign
    - **Property 6: Bullish crossover yields a positive sub-score**
    - Seed `fixed_df` MarketAnalyzer with crafted `DSS`/`DSS_Trigger` producing an upward cross at the tested row, positive `bullish_crossover`, DSS in neutral zone; assert sub-score `> 0.0`
    - Tag: `# Feature: dss-bressert-signal, Property 6`; `@settings(max_examples=100)`
    - **Validates: Requirements 3.1, 3.2**

  - [ ]* 4.6 Write property test for bearish crossover sign
    - **Property 7: Bearish crossover yields a negative sub-score**
    - Crafted downward cross, positive `bearish_crossover`, DSS in neutral zone; assert sub-score `< 0.0`
    - Tag: `# Feature: dss-bressert-signal, Property 7`; `@settings(max_examples=100)`
    - **Validates: Requirements 3.3, 3.4**

  - [ ]* 4.7 Write property test for no-signal-zero
    - **Property 8: No signal condition contributes zero**
    - Same-side pair AND DSS strictly between thresholds; assert empty signals list and sub-score exactly `0.0`
    - Tag: `# Feature: dss-bressert-signal, Property 8`; `@settings(max_examples=100)`
    - **Validates: Requirements 3.5, 4.3, 5.5**

  - [ ]* 4.8 Write property test for oversold zone score
    - **Property 9: Oversold zone contributes the configured oversold score**
    - DSS <= oversold, no crossover; assert sub-score equals configured oversold-zone score
    - Tag: `# Feature: dss-bressert-signal, Property 9`; `@settings(max_examples=100)`
    - **Validates: Requirements 4.1, 9.6**

  - [ ]* 4.9 Write property test for overbought zone score
    - **Property 10: Overbought zone contributes the configured overbought score**
    - DSS >= overbought, no crossover; assert sub-score equals configured overbought-zone score
    - Tag: `# Feature: dss-bressert-signal, Property 10`; `@settings(max_examples=100)`
    - **Validates: Requirements 4.2, 9.5**

  - [ ]* 4.10 Write property test for disabled degradation
    - **Property 11: Disabled degradation**
    - Disabled config, any row index; assert empty list + `0.0` and the calculator is not invoked
    - Tag: `# Feature: dss-bressert-signal, Property 11`; `@settings(max_examples=100)`
    - **Validates: Requirements 2.5, 5.4, 7.1, 7.2, 7.3, 7.4, 9.7**

  - [ ]* 4.11 Write property test for composite additivity and invariance
    - **Property 12: Composite additivity and invariance**
    - Any processed row; assert composite-with-DSS == composite-without + DSS sub-score, and every other category's contribution is unchanged
    - Tag: `# Feature: dss-bressert-signal, Property 12`; `@settings(max_examples=100)`
    - **Validates: Requirements 5.1, 5.3**

  - [ ]* 4.12 Write property test for output shape
    - **Property 13: Output shape**
    - Any row; assert dict has exactly two entries: `dss_bressert_signals` (list of strings) and `dss_bressert_signal_score` (numeric)
    - Tag: `# Feature: dss-bressert-signal, Property 13`; `@settings(max_examples=100)`
    - **Validates: Requirements 5.2**

  - [ ] 4.13 Write example tests for NaN guards, config validation, and disabled behaviour
    - NaN/inf DSS or trigger on current/previous row -> empty list + `0.0` (Req 3.6, 4.4, 8.4)
    - Invalid periods and inverted/out-of-range thresholds -> signal disabled, WARN logged (Req 2.6, 2.7)
    - Disabled config -> empty list + `0.0` (Req 9.7)
    - Bullish/bearish sub-score sign spot-checks (Req 9.3, 9.4); zone-score equality (Req 9.5, 9.6)
    - _Requirements: 2.6, 2.7, 3.6, 4.4, 8.4, 9.3, 9.4, 9.5, 9.6, 9.7_

- [ ] 5. Checkpoint - analyzer integration complete
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Wire the isolated backtest path
  - [x] 6.1 Add DSS `SignalType` members and extend `classify_signals` in `vpa/ml_validation/signal_analysis.py`
    - Add `DSS_BULLISH = "dss_bullish"` and `DSS_BEARISH = "dss_bearish"` to `SignalType`
    - Add `SIGNAL_DIRECTIONS` entries: `DSS_BULLISH -> UP`, `DSS_BEARISH -> DOWN`
    - Extend `classify_signals(df)` with two `notna`-masked reads of `dss_bullish_cross` / `dss_bearish_cross` (value `== 1` marks a matched row); absent columns default to empty lists
    - _Requirements: 6.1, 6.4_

  - [x] 6.2 Add `_include_dss` filter and `DSS_Bressert_Only` variation in `vpa/backtesting/variations.py`
    - Define `_DSS_SIGNAL_TYPES = frozenset({SignalType.DSS_BULLISH, SignalType.DSS_BEARISH})` and `_include_dss(entry)` accepting only those types
    - Append a `StrategyVariation(name="DSS_Bressert_Only", signal_filter=_include_dss)` inside `build_default_variations()`; reuse the existing engine unchanged (no modify/subclass/monkeypatch)
    - _Requirements: 6.1, 6.3_

  - [ ] 6.3 Write integration tests for the isolated backtest
    - DSS-only run: fixture signal log (DSS + non-DSS entries) + price series -> `run_variation` calls `BacktestEngine().run(...)` once via its public API, only DSS entries priced, full `MetricsResult` suite produced (total/annualised/buy-and-hold return, Sharpe, max drawdown, win rate, profit factor, avg win, avg loss, expectancy, time in market, num trades, trades/year) (Req 6.1, 6.2, 6.3)
    - Zero matches: log with no DSS entries -> completes without error, `num_trades == 0`, every trade-derived metric `0.0` (Req 6.4)
    - Failure isolation: a deliberately failing variation in a batch -> `VariationFailure(name, error)` recorded, other variations still run (Req 6.5)
    - `classify_signals` DSS columns: DataFrame with `dss_bullish_cross`/`dss_bearish_cross` -> correct `SignalEntry` directions; absent columns -> no DSS entries
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

- [ ] 7. Emit DSS crossover columns from the feature extractor (`vpa/ml_validation/feature_extractor.py`)
  - [ ] 7.1 Add `dss_bullish_cross` / `dss_bearish_cross` to `FEATURE_COLUMNS` and populate per row
    - Add both columns to `FEATURE_COLUMNS` following the existing `rsi_value` / `rsi_signal_score` additions
    - In `_extract_feature_vector`, populate each from `detect_dss_bressert_signals(row_index)`: `1` when the respective crossover signal name is present in `dss_bressert_signals`, else `0`
    - _Requirements: 6.1_

  - [ ]* 7.2 Write unit test for feature-extractor DSS columns
    - Assert both columns are emitted and set to `1` on crafted crossover rows, `0` otherwise
    - _Requirements: 6.1_

- [ ] 8. Add the DSS Bressert chart (`MarketAnalyzer.graph_dss_bressert` in `vpa/app_runner.py`)
  - [x] 8.1 Implement `graph_dss_bressert`
    - Build a plotting copy of `self.myDF` with `Date` parsed to datetime and set as the index (mplfinance requires a `DatetimeIndex`)
    - Reuse the `graph_intervals()` mplfinance approach (`mpf.plot(..., type="candle", style="charles", volume=True)`); route `DSS` and `DSS_Trigger` to a distinct lower panel via `make_addplot(..., panel=2)`, distinguished by colour and label (Req 10.1, 10.3)
    - Draw two horizontal reference lines in the lower panel at `overbought_threshold` and `oversold_threshold` (Req 10.2)
    - Read the already-computed `DSS`/`DSS_Trigger` columns without recomputing the indicator (Req 10.4)
    - Save a PNG under `log/` (e.g. `log/{ticker}_dss_bressert.png`) and optionally display when `show_chart` is true (Req 10.5)
    - Fall back to a price-only chart with no error when disabled or when the columns are absent (Req 10.6)
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

  - [x]* 8.2 Write smoke tests for the chart
    - Enabled with `DSS`/`DSS_Trigger` present -> PNG produced under `log/` without raising (Req 10.5)
    - Disabled, and columns absent -> price-only chart produced without an exception (Req 10.6)
    - Note: manual TradingView visual comparison of the lower panel is a manual verification step (see task 9), not automatable
    - _Requirements: 10.5, 10.6_

- [ ] 9. Final verification and wiring
  - Run the full test suite with `pytest` and the `ruff` linter over the new/changed modules; fix any failures or lint issues
  - Confirm the DSS panel renders on a real ticker (e.g. SPY) by invoking `graph_dss_bressert`, and note the output PNG path for the manual TradingView visual comparison (SP-325 definition of done: code exercised/verified locally)
  - _Requirements: 5.1, 6.1, 9.1, 10.1_

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP; core implementation tasks are never optional.
- Each task references specific requirement clauses for traceability, and property-test tasks reference the design's Property numbers.
- Checkpoints (tasks 2 and 5) ensure incremental validation before the analyzer and backtest layers build on the calculator.
- Property-based tests (Hypothesis, `@settings(max_examples=100)`) validate the universal calculator and scoring properties; unit/integration tests cover reference values, edge cases, config validation, and the backtest pipeline.
- SP-325's definition of done includes the code being exercised/verified locally (task 9), including the manual TradingView chart comparison. No production deployment task is in scope for this feature.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "3.1", "6.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "1.4", "1.5", "1.6", "1.7", "3.2", "3.3", "6.2"] },
    { "id": 2, "tasks": ["3.4", "4.1", "6.3"] },
    { "id": 3, "tasks": ["4.2"] },
    { "id": 4, "tasks": ["4.3"] },
    { "id": 5, "tasks": ["4.4", "8.1"] },
    { "id": 6, "tasks": ["4.5", "4.6", "4.7", "4.8", "4.9", "4.10", "4.11", "4.12", "4.13", "7.1", "8.2"] },
    { "id": 7, "tasks": ["7.2"] }
  ]
}
```
