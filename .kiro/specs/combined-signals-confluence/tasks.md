# Implementation Plan: Combined Signals (Confluence)

## Overview

This plan implements the Combined_Signal (confluence) category in the trading project
(`d:\projects\trading\vpa`), tracked by Jira ticket **SP-327**. A Combined_Signal fires on a
row only when **all** of its constituent conditions hold on that row (AND / confluence), as
opposed to the composite `trade_signal` which sums every category's sub-score. Work proceeds
bottom-up: config typing first, then the `MarketAnalyzer` init hook, then the
`detect_combined_signals` post-pass detector, then the `process_data` wiring that folds a
single sub-score into the composite `trade_signal`, then the isolated backtest path
(feature-extractor inline columns, `classify_signals` SignalTypes, backtest variations), and
finally a full-suite lint + verification pass.

Each task references the requirement clauses it satisfies. Property-based test sub-tasks
reference the design's Property numbers and are marked optional with `*`. Tasks are coding
tasks only. The live confluence detector is a post-pass over the already-computed per-row DSS
and price-vs-SMA signal-name lists, and the backtest path stays separate from `MarketAnalyzer`
(SP-340 hard rule), so `composite_score` in the feature extractor stays byte-for-byte
unchanged.

## Tasks

- [x] 1. Add combined-signals config typing in `vpa/config/settings.py`
  - [x] 1.1 Define the three frozen dataclasses and the `combined_signals` field
    - Add frozen `CombinedCondition` (`signal_name: str`, `kind: str = "presence"` — `"presence"`/`"absence"`)
    - Add frozen `CombinedSignalDef` (`name: str`, `score: float = 0.0`, `conditions: tuple[CombinedCondition, ...] = ()`)
    - Add frozen `CombinedSignalsSettings` (`enabled: bool = False`, `combinations: tuple[CombinedSignalDef, ...] = ()`) — defaults OFF (Req 1.7), unlike `dss_bressert`
    - Add a `combined_signals: CombinedSignalsSettings = CombinedSignalsSettings()` field to the `Settings` dataclass (default-constructed so an absent block is disabled)
    - _Requirements: 1.1, 1.2, 1.3, 1.6, 1.7_

  - [x] 1.2 Implement `_combined_signals_settings` loader and wire into `load_settings`
    - Add `_combined_signals_settings(raw)` reusing `_section`, `_optional`, `_number`, `_value`; iterate the JSON `combinations` list, each a dict with `name` (str), `score` (number, default 0), and a nested `conditions` list of dicts with `signal_name` (str) and `kind` (str, default `"presence"`)
    - Raise `ConfigurationError` on malformed shapes: `combinations` not a list, a combination not an object, `conditions` not a list (type/shape validation only — deep validation is deferred to the analyzer init hook)
    - In `load_settings()`, add `combined_signals=_combined_signals_settings(_section(raw, "combined_signals", "combined_signals"))` to the `Settings(...)` construction so an absent block yields `enabled=False`, no combinations (Req 1.7)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6, 1.7, 1.8_

  - [x] 1.3 Add the `combined_signals` block to `config/config.json`
    - Seed the block `enabled: true` with all ten starter entries (five combinations, each a `_Bull` positive-score and `_Bear` negative-score mirror) exactly as the design's JSON: DSS_Cross_Plus_SMA_Position, DSS_Cross_Plus_SMA_Cross, DSS_Zone_Plus_SMA_Cross, DSS_Cross_From_Zone, DSS_Cross_SMA_Not_Overbought (the last with its `absence` negation condition)
    - _Requirements: 1.5, 1.6_

  - [x] 1.4 Write unit tests for config defaults, round-trip, and malformed shapes
    - Settings loaded with no `combined_signals` block -> `enabled=False`, empty `combinations`, no error (Req 1.7)
    - Settings loaded with a full block -> values round-trip onto the three dataclasses, including a three-condition combination and each of the eight known signal-name strings; the committed `config.json` loads all ten starter entries (Req 1.1-1.6)
    - Malformed shapes raise `ConfigurationError`: `combinations` not a list, a combination not an object, `conditions` not a list, `name` not a string
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7_

- [x] 2. Wire the combined-signals init hook into `MarketAnalyzer` (`vpa/app_runner.py`)
  - [x] 2.1 Implement `_init_combined_signals_config` with deep validation and call it from `__init__`
    - Define the module-level `_KNOWN_COMBINED_SIGNAL_NAMES` frozenset of the 8 valid strings ("DSS Bullish Crossover", "DSS Bearish Crossover", "DSS Oversold", "DSS Overbought", "Price above SMA", "Price below SMA", "Price crossed above SMA", "Price crossed below SMA")
    - Read `self.__config.combined_signals`; when `enabled` is false/absent/non-boolean set `self.__combined_signals_enabled = False`, `self.__combined_signals = []` and return (defaults OFF — Req 1.7, 4.1-4.3)
    - When enabled, deep-validate each combination: drop with a `WARN` if it has fewer than two conditions (Req 1.3) or references any unknown signal-name string (Req 1.9), retaining the remaining valid combinations; store the survivors in `self.__combined_signals` and set `self.__combined_signals_enabled = True`
    - Add `self._init_combined_signals_config()` alongside the existing `_init_price_vs_sma_config()` / `_init_dss_bressert_config()` calls in `__init__` (pure config inspection, no data access)
    - _Requirements: 1.3, 1.4, 1.9, 4.1, 4.2, 4.3_

- [x] 3. Implement the confluence detector `detect_combined_signals` (`vpa/app_runner.py`)
  - [x] 3.1 Implement `detect_combined_signals(row_index, dss_signals, price_vs_sma_signals, log=True)`
    - Return exactly `{"combined_signals": list[str], "combined_signal_score": float}` (Req 3.2)
    - When `self.__combined_signals_enabled` is false, return `{"combined_signals": [], "combined_signal_score": 0.0}` without inspecting any combination (Req 3.4, 4.1, 4.2)
    - Build the union `present = set(dss_signals) | set(price_vs_sma_signals)`; for each enabled combination evaluate every condition as AND: a `presence` condition holds iff its string is in `present`, an `absence` condition holds iff its string is NOT in `present` (Req 2.1, 2.4)
    - On a combination where all conditions hold, append exactly its `name` once (Req 2.9) and add its signed `score` (bullish positive adds, bearish negative subtracts) to the running total (Req 2.2); otherwise contribute nothing (Req 2.3)
    - Negation + degradation fall out of empty constituent lists: a disabled/no-data/warmup constituent yields an empty list, so presence conditions on it fail and absence conditions on it pass with no special casing (Req 2.5-2.8, 2.10, 2.11, 4.4, 4.5)
    - Log the fired combinations and score at INFO only when `log` is true and something fired
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 2.11, 3.2, 3.4, 4.4, 4.5_

- [x] 4. Wire the detector into `process_data` (`vpa/app_runner.py`)
  - [x] 4.1 Add Step 6.5 detect-and-merge and the additive composite term
    - After Step 6.4 (DSS), add Step 6.5: call `detect_combined_signals(row_position, signals["dss_bressert_signals"], signals["price_vs_sma_signals"], log=row_position >= log_start_index)` and merge `combined_signals` and `combined_signal_score` into the row `signals` dict
    - Add `+ signals["combined_signal_score"]` as a single additive term to the `trade_signal` summation (no weighting, scaling, or ordering dependency; term is `0.0` and `trade_signal` unchanged when disabled or nothing fires)
    - _Requirements: 3.1, 3.3_

- [x] 5. Checkpoint - live analyzer integration complete
  - Ensure all tests pass, ask the user if questions arise.

  - [ ]* 5.1 Write property test for the confluence oracle
    - **Property 1: Confluence oracle — fires iff all conditions hold, by presence/absence only**
    - Draw random combinations (random names, signed scores, 2-3 conditions over the 8 known strings with random presence/absence) and random DSS / price-vs-SMA present-string subsets (incl. empty); build a `fixed_df` `MarketAnalyzer` from the config and assert the fired set + score equal a reference AND-of-conditions oracle; include the metamorphic sub-check that mutating only the unused constituent sub-scores leaves the fired set and score unchanged (Req 2.4), and that an empty constituent list fails its presence conditions and satisfies its absence conditions
    - Tag: `# Feature: combined-signals-confluence, Property 1`; `@settings(max_examples=100)`
    - **Validates: Requirements 1.8, 2.1, 2.2, 2.3, 2.4, 2.9, 2.10, 2.11, 4.4, 4.5**

  - [ ]* 5.2 Write property test for composite additivity and non-interference
    - **Property 2: Composite additivity and non-interference**
    - Any processed row; assert composite `trade_signal` with the combined term == composite without it + `combined_signal_score`, and every other category's contribution is unchanged
    - Tag: `# Feature: combined-signals-confluence, Property 2`; `@settings(max_examples=100)`
    - **Validates: Requirements 3.1, 3.3**

  - [ ]* 5.3 Write property test for disabled / no-fire degradation
    - **Property 3: Disabled / no-fire degradation**
    - Any constituent lists with the category disabled -> empty list + `0.0`, `0.0` composite contribution, no raise; and any lists where no combination fully holds -> empty list + `0.0`, composite unchanged
    - Tag: `# Feature: combined-signals-confluence, Property 3`; `@settings(max_examples=100)`
    - **Validates: Requirements 3.4, 4.1, 4.2**

  - [ ]* 5.4 Write property test for output shape
    - **Property 4: Output shape**
    - Any row and constituent lists; assert the result is a dict with exactly two entries: `combined_signals` (list of strings) and `combined_signal_score` (numeric)
    - Tag: `# Feature: combined-signals-confluence, Property 4`; `@settings(max_examples=100)`
    - **Validates: Requirements 3.2**

  - [x]* 5.5 Write unit tests mapping the Req 6 confluence scenarios
    - Both constituents fire (Req 6.1): `"DSS Bullish Crossover"` + `"Price above SMA"` -> `DSS_Cross_Plus_SMA_Position_Bull` fires, sub-score non-zero
    - Exactly one holds (Req 6.2) and neither holds (Req 6.3) -> does not fire, score `0.0`
    - A constituent disabled (Req 6.4): empty DSS list while `"Price above SMA"` present -> does not fire, score `0.0`
    - Category off (Req 6.5): `enabled=false` -> empty `combined_signals`, score `0.0`
    - Category on, confluence holds (Req 6.6): both strings present -> `DSS_Cross_Plus_SMA_Position_Bull` produces its configured score
    - Negation blocked by presence (Req 6.7): both presences hold but `"DSS Overbought"` present -> `DSS_Cross_SMA_Not_Overbought_Bull` does NOT fire, score `0.0`
    - Negation satisfied by absence (Req 6.8) and three-way confluence (Req 6.9): all three conditions hold -> fires, non-zero
    - DSS-only self-confluence (Req 6.10): `"DSS Bullish Crossover"` + `"DSS Oversold"` both present -> `DSS_Cross_From_Zone_Bull` fires, non-zero
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 6.10_

- [x] 6. Add inline flag + combination columns to the feature extractor (`vpa/ml_validation/feature_extractor.py`)
  - [x] 6.1 Compute the eight inline flag columns per row
    - Add `dss_oversold` / `dss_overbought` computed inline from `dss_osc[pos]` vs `dss_cfg.oversold_threshold` / `overbought_threshold`, guarded by the same `dss_enabled` / warmup / finite checks as the existing `dss_bullish_cross` / `dss_bearish_cross` block
    - Add `price_above_sma` / `price_below_sma` / `price_crossed_above_sma` / `price_crossed_below_sma` computed inline from `closes[pos]` vs `sma_series[pos]` (and `pos-1` prev values for the crosses), guarded by the same `pvs_enabled` / NaN checks as `compute_price_vs_sma_feature`
    - Thread all six new flags (plus the existing two cross flags) into `_extract_feature_vector` as default-0 parameters and append them to `FEATURE_COLUMNS` in the design's fixed order
    - HARD CONSTRAINT: leave the `composite_score` line byte-for-byte unchanged (SP-340 zero-regression) — the new flags are NOT folded into `composite_score`
    - _Requirements: 1.4_

  - [x] 6.2 Derive the ten `combo_*_bull` / `_bear` columns inline
    - After the flags are known for the row, compute each as `int(<AND expression>)` exactly per the design table: `combo_dss_cross_sma_pos_*`, `combo_dss_cross_sma_cross_*`, `combo_dss_zone_sma_cross_*`, `combo_dss_cross_from_zone_*`, and `combo_dss_cross_sma_not_ob_*` (the last two include the `and not dss_overbought` / `and not dss_oversold` negation)
    - Append all ten columns to `FEATURE_COLUMNS` and emit them from `_extract_feature_vector`; `composite_score` stays byte-for-byte unchanged
    - _Requirements: 2.5, 2.6, 2.7, 2.8_

  - [x] 6.3 Write unit tests for the inline flag and combination columns
    - Assert all eight flag columns and ten combination columns appear in `FEATURE_COLUMNS` and in the emitted feature vector in the fixed order
    - Assert each combination column equals the AND of its constituent flags on crafted rows (one per combination per direction, including the negation combo `combo_dss_cross_sma_not_ob_*`)
    - Assert `composite_score` is unchanged vs the pre-SP-327 baseline for a fixed input dataset (zero-regression guard)
    - _Requirements: 1.4, 2.5, 2.6, 2.7, 2.8_

- [x] 7. Add the ten `COMBO_*` SignalTypes and classification (`vpa/ml_validation/signal_analysis.py`)
  - [x] 7.1 Add `COMBO_*` SignalType members, `SIGNAL_DIRECTIONS`, and column-guarded `classify_signals` reads
    - Add the ten `COMBO_*` members (bull/bear per combination) with the exact string values from the design
    - Add `SIGNAL_DIRECTIONS` entries mapping each bull member to `UP` and each bear member to `DOWN` (Req 5.1)
    - Extend `classify_signals(df)` with a `_COMBO_COLUMN_TO_TYPE` loop doing a column-presence-guarded, `notna`-masked `== 1` read per combination column; an absent column leaves that type's list empty (Req 5.2)
    - _Requirements: 5.1, 5.2_

  - [ ]* 7.2 Write property test for classify_signals partitioning
    - **Property 5: classify_signals partitions rows by combination column**
    - Random DataFrames with injected `combo_*` columns (values in {0, 1, NaN}) and some columns absent -> assert each present column's index partition equals exactly its `notna & == 1` rows and absent columns leave the type empty
    - Tag: `# Feature: combined-signals-confluence, Property 5`; `@settings(max_examples=100)`
    - **Validates: Requirements 5.2**

  - [ ]* 7.3 Write unit test for SignalType directions and classify columns
    - Assert the ten `COMBO_*` members exist and map to the correct `UP`/`DOWN` directions in `SIGNAL_DIRECTIONS` (Req 5.1)
    - Assert `classify_signals` on a DataFrame with `combo_*` columns produces correct index lists, excludes NaN rows, and leaves absent columns empty (Req 5.2)
    - _Requirements: 5.1, 5.2_

- [x] 8. Add the five combination backtest variations (`vpa/backtesting/variations.py`)
  - [x] 8.1 Add `_make_combo_filter` and the five `StrategyVariation`s
    - Define `_COMBO_FILTER_TYPES` mapping each of the five variation names (Combo_DSS_Cross_SMA_Position, Combo_DSS_Cross_SMA_Cross, Combo_DSS_Zone_SMA_Cross, Combo_DSS_Cross_From_Zone, Combo_DSS_Cross_SMA_Not_Overbought) to the frozenset of its two `COMBO_*` SignalType members
    - Add `_make_combo_filter(allowed)` returning a `signal_filter` that admits only entries whose `signal_type` is in `allowed` and excludes every other type
    - In `build_default_variations()`, append one `StrategyVariation` per entry in `_COMBO_FILTER_TYPES` alongside the existing `DSS_Bressert_Only`; reuse the existing engine unchanged (no modify/subclass/monkeypatch)
    - _Requirements: 5.3, 5.4_

  - [x] 8.2 Write integration tests for the combination variations
    - Variation filters (Req 5.3): each of the five variations admits only its own two `COMBO_*` SignalType members and excludes every other type (including the DSS-only and price-vs-SMA baseline types)
    - Combination run (Req 5.4, 5.5): a fixture signal log (combination + non-combination entries) + price series -> `run_variation` calls `BacktestEngine().run(...)` once via its public API, only that combination's entries priced, full `MetricsResult` suite produced (total/annualised/buy-and-hold return, Sharpe, max drawdown, win rate, profit factor, avg win, avg loss, expectancy, time in market, num trades, trades/year)
    - Zero matches (Req 5.6): a log with no entries for a combination -> completes without error, `num_trades == 0`, every trade-derived metric `0.0`
    - Failure isolation (Req 5.7): a deliberately failing variation in a batch -> `VariationFailure(name, error)` recorded, other variations still run
    - Comparability (Req 5.3): the existing `DSS_Bressert_Only` and the `PRICE_ABOVE_SMA` / `PRICE_BELOW_SMA` baselines run in the same batch for comparison against the combinations
    - _Requirements: 5.3, 5.4, 5.5, 5.6, 5.7_

- [x] 9. Checkpoint - backtest path complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Final verification pass (lint, format, full suite)
  - Run `ruff check .` and `ruff format --check .` over the repo and fix any lint or formatting issues (CI enforces both; tool-written files can drop trailing newlines)
  - Run the FULL test suite with `pytest -m ""` (NOT bare `pytest`, which deselects the slow ML tests per the workspace testing rule) and fix any failures until the whole suite is green
  - _Requirements: 1.5, 2.1, 3.1, 5.1, 6.1_

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP; core implementation tasks are never optional.
- Each task references specific requirement clauses for traceability, and property-test tasks reference the design's Property numbers.
- Checkpoints (tasks 5 and 9) ensure incremental validation before the backtest layer and the final verification build on the live analyzer path.
- Property-based tests (Hypothesis, `@settings(max_examples=100)`) validate the universal confluence oracle, composite additivity, degradation, output shape, and `classify_signals` partitioning; unit/integration tests cover the Req 6 scenarios, config shape, feature columns, and the backtest pipeline.
- The live detector is a post-pass over Steps 6.3/6.4 lists; the backtest path stays separate from `MarketAnalyzer` (SP-340 rule) and `composite_score` is byte-for-byte unchanged.
- The final verification task (task 10) runs the full suite including the slow ML tests before the Jira task may be marked Done. No production deployment task is in scope for this feature.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["1.3", "1.4", "2.1"] },
    { "id": 3, "tasks": ["3.1"] },
    { "id": 4, "tasks": ["4.1"] },
    { "id": 5, "tasks": ["5.1", "5.2", "5.3", "5.4", "5.5", "6.1", "7.1"] },
    { "id": 6, "tasks": ["6.2", "7.2", "7.3", "8.1"] },
    { "id": 7, "tasks": ["6.3", "8.2"] }
  ]
}
```
