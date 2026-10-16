# Implementation Plan: DSS and DSS/SMA Combo Signal Classification

## Overview

SP-359 makes `DailySignalGenerator` a first-class producer and classifier of DSS crossover signals and the ten DSS/SMA combo signals. The work mirrors the already-shipped `VPAFeatureExtractor.generate_dataset` DSS/zone/combo logic inside `DailySignalGenerator.run`, extends `classify_last_row` to recognise the DSS and combo columns on the latest candle, adds default confidence levels to `CONFIDENCE_MAP`, regenerates SPY's `ticker_signals.json` entry, and locks the behaviour in with property-based and example tests.

The plan builds incrementally: first the daily-run precompute and per-row derivation (so the feature columns exist), then classification, then confidence mapping and config, then wiring verified by the model-based equivalence tests. All tests are FAST and run under `pytest -m ""`.

## Tasks

- [x] 1. Add DSS precompute to the daily run
  - In `vpa/ml_validation/daily_signal.py`, add the DSS precompute block to `DailySignalGenerator.run` before the per-row loop, mirroring `generate_dataset` Step 3b
  - Read DSS config from `extractor._config.dss_bressert`; copy the `_valid_period` / `_valid_threshold` / `dss_enabled` gating verbatim from `generate_dataset`
  - When enabled, call `vpa.dss_bressert.calculate_dss_bressert` once over the whole frame and compute `dss_warmup = stochastic_period + smoothing_period + trigger_period - 2`; when disabled, leave `dss_osc`/`dss_trig` as `None` and do not call `calculate_dss_bressert`
  - _Requirements: 1.1, 1.2, 1.5, 2.4_

- [x] 2. Derive per-row DSS crossover, zone, and combo columns in the daily run
  - [x] 2.1 Surface the four price-vs-SMA integer flags in the per-row loop
    - Expose `price_above_sma`, `price_below_sma`, `price_crossed_above_sma`, `price_crossed_below_sma` as integer variables in the loop body (mirroring `generate_dataset` Step 9c), alongside the existing `price_vs_sma_signal_score`
    - _Requirements: 2.3_

  - [x] 2.2 Compute DSS crossover flags per row
    - Inside the per-row loop, compute `dss_bullish_cross` / `dss_bearish_cross` gated by `dss_enabled`, `pos >= dss_warmup`, `pos > 0`, and `np.isfinite(...)` on the osc/trigger at `pos` and `pos - 1` (mirror `generate_dataset` Step 9); default to 0 otherwise
    - _Requirements: 1.3, 1.4, 1.6_

  - [x] 2.3 Compute DSS zone flags per row
    - Compute `dss_oversold` / `dss_overbought` gated by `dss_enabled`, `pos >= dss_warmup`, and `np.isfinite(osc)` (no `pos > 0` requirement), comparing the oscillator to `oversold_threshold` / `overbought_threshold` (mirror Step 9a); default to 0 otherwise
    - _Requirements: 2.1, 2.2_

  - [x] 2.4 Compute the ten combo columns per row
    - Compute each of the ten `combo_*` columns as `int(<AND expression>)` of the crossover, zone, and price-vs-SMA flags per the Combo_Expressions (mirror Step 9d)
    - _Requirements: 2.3, 2.4_

  - [x] 2.5 Pass the eighteen flags into the feature vector
    - Extend the existing `extractor._extract_feature_vector(...)` call in the loop to pass the two DSS crossover flags, two zone flags, four price-vs-SMA flags, and ten combo columns as keyword arguments so they appear in `result_df`
    - _Requirements: 1.7, 2.5_

  - [-]* 2.6 Write property test: daily run reproduces the feature extractor's columns
    - **Property 1: Daily run reproduces the feature extractor's DSS, zone, and combo columns**
    - Generate OHLCV frames (≥40 rows) and a valid DSS config; monkeypatch yfinance download; assert every emitted row's four DSS and ten combo columns equal `generate_dataset`'s for identical input
    - **Validates: Requirements 1.1, 1.3, 1.4, 2.1, 2.3, 2.6**

  - [x]* 2.7 Write property test: DSS disabled zeroes every DSS and combo column
    - **Property 2: DSS disabled zeroes every DSS and combo column**
    - Assert all four DSS and ten combo columns are 0 for every row when `DSS_Enabled` is false, and that `calculate_dss_bressert` is never called (spy/patch)
    - **Validates: Requirements 1.5, 2.4**

  - [x]* 2.8 Write property test: pre-warm-up rows carry no DSS or combo signal
    - **Property 3: Pre-warm-up rows carry no DSS or combo signal**
    - Assert every row at positional index `< dss_warmup` (and index 0 for crossover columns) has all four DSS and ten combo columns equal 0
    - **Validates: Requirements 1.6, 2.2**

  - [x]* 2.9 Write property test: DSS and combo columns are always 0 or 1 integers
    - **Property 4: DSS and combo columns are always 0 or 1 integers**
    - Assert every value in the four DSS and ten combo columns is an integer equal to 0 or 1, for enabled and disabled configs
    - **Validates: Requirements 1.7, 2.5**

  - [x]* 2.10 Write example tests for daily-run column derivation
    - Over a crafted frame, assert `dss_bullish_cross`/`dss_bearish_cross` match the crossover logic post-warm-up, are 0 pre-warm-up, and 0 when disabled (Req 7.9)
    - Assert all ten combo columns match the Combo_Expressions, are 0 pre-warm-up, and 0 when disabled (Req 7.10)
    - _Requirements: 7.9, 7.10_

- [x] 3. Checkpoint - daily-run feature columns
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Classify DSS and combo columns on the latest candle
  - [x] 4.1 Extend `classify_last_row` with DSS crossover and combo classification
    - Import `_COMBO_COLUMN_TO_TYPE` from `signal_analysis.py`; after the existing composite/acc-dist/price-vs-SMA logic, add `dss_bullish_cross`/`dss_bearish_cross` classification and loop over `_COMBO_COLUMN_TO_TYPE`, reusing the `col in df.columns` guard, `_is_valid_numeric`, and `== 1` test
    - Leave the early empty-frame guard and all existing classifications untouched
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [-]* 4.2 Write property test: type classified iff final-row column equals 1
    - **Property 5: A DSS or combo type is classified exactly when its final-row column equals 1**
    - Generate final-row cell values across NaN / ints / floats / non-numeric strings / absent column; assert inclusion iff present and coerces to 1, no error otherwise
    - **Validates: Requirements 3.1, 3.2, 3.5, 3.6, 4.1, 4.4**

  - [x]* 4.3 Write property test: daily combo classification agrees with `classify_signals`
    - **Property 6: Daily combo classification agrees with `classify_signals`**
    - Assert the combo `SignalType` set from `classify_last_row` equals the set whose `classify_signals` matched-index list contains the final row's index
    - **Validates: Requirements 4.2**

  - [x]* 4.4 Write property test: adding DSS/combo columns does not disturb other classifications
    - **Property 7: Adding DSS and combo columns does not disturb other classifications**
    - Assert core and price-vs-SMA membership is identical with/without DSS and combo columns, and DSS membership is unaffected by combo columns
    - **Validates: Requirements 3.8, 4.6**

  - [x]* 4.5 Write example tests for classification edge cases
    - final-row `dss_bullish_cross == 1` → contains `DSS_BULLISH`; `dss_bearish_cross == 1` → contains `DSS_BEARISH` (Req 7.1, 7.2)
    - both DSS columns absent → neither type, no error (Req 7.3); final DSS value NaN/≠1 → absent (Req 7.4)
    - parametrised: each combo column == 1 → its `SignalType` present (Req 7.5); combo column absent or NaN/≠1 → absent, no error (Req 7.6)
    - `classify_last_row(pd.DataFrame())` returns `set()` without raising (Req 3.7, 4.5)
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

- [x] 5. Checkpoint - classification
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Add default confidence levels for DSS and combo types
  - [x] 6.1 Extend `CONFIDENCE_MAP`
    - Add `DSS_BULLISH` / `DSS_BEARISH` entries set to `"Medium-High"` and an entry for each of the ten combo `SignalType`s set to `"Medium-High"` in the module-level `CONFIDENCE_MAP` in `daily_signal.py`
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [-]* 6.2 Write unit tests for `CONFIDENCE_MAP` contents
    - Assert `DSS_BULLISH`/`DSS_BEARISH` rank strictly above `"Low"` in `CONFIDENCE_ORDER`; assert each of the ten combo types has an entry in `CONFIDENCE_ORDER` equal to `"Medium-High"`
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [x]* 6.3 Write property test: default-path records use mapped confidence, BUY, hold 10
    - **Property 8: Default-path DSS and combo records use the mapped confidence, BUY, hold 10**
    - For DSS/combo types with no matching config rule, assert `build_signal_records` uses the `CONFIDENCE_MAP` confidence, `adjusted_direction == "BUY"`, `suggested_hold_days == 10`
    - **Validates: Requirements 5.5**

  - [x]* 6.4 Write property test: matching rule overrides, NONE omits
    - **Property 9: A matching rule overrides direction, confidence, and hold days (and NONE omits)**
    - Generate config rules; assert the rule's direction/confidence/hold are applied when direction ≠ `"NONE"`, and the signal is omitted when `"NONE"`
    - **Validates: Requirements 5.6, 5.7**

  - [x]* 6.5 Write property test: records ordered by confidence, High first, unknown last
    - **Property 10: Records are ordered by confidence, High first, unknown last**
    - Assert returned records are ordered per `CONFIDENCE_ORDER` with unknown confidence levels sorted last
    - **Validates: Requirements 5.8**

  - [x]* 6.6 Write example tests for `build_signal_records` with DSS/combo types
    - No matching rule → record uses `CONFIDENCE_MAP` confidence (Req 7.7)
    - Matching rule → record uses the rule's `adjusted_direction`; `NONE` rule → record omitted (Req 7.8)
    - _Requirements: 7.7, 7.8_

- [x] 7. Regenerate SPY config entry with DSS and combo rules
  - [x] 7.1 Add DSS and combo rules to the SPY entry in `ticker_signals.json`
    - In `vpa/config/ticker_signals.json`, add exactly one `dss_bullish` rule, one `dss_bearish` rule, and one rule per combo column name to the SPY object, following the SP-322 generator schema (`adjusted_direction` plus `confidence_level`/`suggested_hold_days` when not `"NONE"`; bare `{"adjusted_direction": "NONE"}` when disabled)
    - Leave existing SPY non-DSS/non-combo rules and the entire AAPL entry byte-for-byte unchanged; keep the file valid JSON
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

  - [-]* 7.2 Write SPY config schema and regression tests
    - Load `ticker_signals.json`; assert SPY has exactly one `dss_bullish`, one `dss_bearish`, and one rule per combo column name; assert each rule's `adjusted_direction` ∈ {`"BUY"`, `"SELL"`, `"NONE"`} with valid `confidence_level` + int `suggested_hold_days >= 1` when not `"NONE"`
    - Assert the file parses as valid JSON and the pre-existing SPY non-DSS/non-combo rules and the whole AAPL entry are unchanged
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

- [x] 8. Final checkpoint - full suite, lint, and format
  - Run `ruff check .` and `ruff format --check .` clean, then `pytest -m ""` green (Req 7.11, 8.3, 8.4, 8.5)
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional (test tasks) and can be skipped for a faster MVP, though the property and example tests are the mechanism that locks in model-based equivalence with `generate_dataset` / `classify_signals`.
- Each task references specific requirements (and, for test tasks, the design correctness property) for traceability.
- The daily run deliberately mirrors `generate_dataset` rather than sharing a helper (see design "mirror, don't share"); equivalence is enforced by Property 1 (task 2.6).
- `build_signal_records` needs no code change; its behaviour is verified by tasks 6.3–6.6.
- Deployment to the Raspberry Pi and the Jira traceability/Done gates (Req 8) are process steps outside this coding task list.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2.1", "6.1", "7.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "6.2", "7.2"] },
    { "id": 3, "tasks": ["2.4", "6.3", "6.4", "6.5", "6.6"] },
    { "id": 4, "tasks": ["2.5"] },
    { "id": 5, "tasks": ["2.6", "2.7", "2.8", "2.9", "2.10", "4.1"] },
    { "id": 6, "tasks": ["4.2", "4.3", "4.4", "4.5"] }
  ]
}
```
