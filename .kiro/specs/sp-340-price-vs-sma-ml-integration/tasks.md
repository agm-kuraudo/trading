# Implementation Plan: SP-340 — Price vs SMA ML Integration

## Overview

This plan integrates the live SP-326 price vs SMA signal into the ML feature-extraction and signal-analysis path as a standalone, independently backtestable signal (Option B). The work follows the approved design: inline reimplementation in `VPAFeatureExtractor` (never calling `MarketAnalyzer` in production), a byte-for-byte unchanged `composite_score`, two new feature columns inserted after `rsi_signal_score` (31 → 33), two new `SignalType` members with sign-based classification, daily-signal wiring, and stale feature-count corrections.

Tasks are ordered so each builds on the previous: feature-extractor columns and inline scoring first (with their tests), then signal_analysis, then daily_signal, then stale-count corrections and the slow fixture regeneration, then the verification gate. All four modules live under `d:\projects\trading`: `vpa/ml_validation/feature_extractor.py`, `vpa/ml_validation/signal_analysis.py`, `vpa/ml_validation/daily_signal.py`, with tests under `vpa/tests/` and `vpa/tests/ml_validation/`.

Note (per repo workflow): the Jira ticket SP-340 cannot move to Done until the final verification gate (task 9) passes.

## Tasks

- [x] 1. Add price vs SMA feature columns and inline scoring to `VPAFeatureExtractor`
  - [x] 1.1 Insert the two new entries into `FEATURE_COLUMNS` (31 → 33)
    - In `vpa/ml_validation/feature_extractor.py`, add `"price_vs_sma_value"` and `"price_vs_sma_signal_score"` to `FEATURE_COLUMNS` immediately AFTER `"rsi_signal_score"` and before `"dss_bullish_cross"` (design §1.1)
    - Keep DSS / `composite_score` / `up_bar_current` at the tail in their existing order
    - _Requirements: 2.1, 2.2_

  - [x] 1.2 Thread the two values into `_extract_feature_vector` and emit them in order
    - Add optional params `price_vs_sma_value: float = 50.0` and `price_vs_sma_signal_score: float = 0.0` to `_extract_feature_vector`, mirroring `dss_bullish_cross` / `dss_bearish_cross` (design §1.5)
    - Insert the two keys into the emitted `feature_vector` dict at the same relative position as in `FEATURE_COLUMNS` so dict insertion order matches (design §1.1)
    - _Requirements: 2.3, 2.4_

  - [x] 1.3 Precompute the SMA series and compute position + optional crossover score in `generate_dataset`
    - Read config via `self._config.price_vs_sma`; precompute `sma_series` over `df["Close"]` with `rolling(window=period, min_periods=period).mean().tolist()` before the row loop, gated on `enabled`, mirroring the DSS precompute (design §1.2)
    - In the loop (which has `pos`), compute the position-based score (`close > sma` → `+scores.above`; `close < sma` → `-scores.below`; equal → `0.0`) and, when `detect_crossover` and `pos > 0` with non-NaN previous close/SMA, add `+cross_above` / `-cross_below`; pass both values into `_extract_feature_vector` (design §1.3, §1.6)
    - Guard warm-up / disabled / NaN with `pd.isna` → score `0.0`, value sentinel `50.0`
    - _Requirements: 2.5, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12_

  - [x] 1.4 Verify the `composite_score` line is byte-for-byte unchanged
    - Confirm the composite line remains `single_candle_score + trend_score + multiple_bar_score + acc_dist_score + rsi_signal_score` and that `price_vs_sma_signal_score` is NOT added (hard zero-regression constraint, design §1.4)
    - _Requirements: 4.1, 4.2, 4.3_

  - [ ]* 1.5 Write unit/example tests for extractor position and crossover scoring
    - In `vpa/tests/ml_validation/test_feature_extractor.py`: position above (`+scores.above`), below (`-scores.below`), equal (`0.0`); warm-up (< period closes) → `0.0`; `enabled=false` → `0.0`; crossover on cross-above (`+position +cross_above`) and cross-below (`-position -cross_below`); crossover off → position-only; first-row (`pos == 0`) / NaN-previous → no crossover term
    - _Requirements: 3.2, 3.3, 3.4, 3.5, 3.6, 3.8, 3.9, 3.10, 3.11, 3.12_

  - [ ]* 1.6 Write unit tests for `FEATURE_COLUMNS` structure
    - Assert both new names present; `len(VPAFeatureExtractor.FEATURE_COLUMNS) == 33`; emitted feature-vector dict key order matches `FEATURE_COLUMNS` for the two keys
    - _Requirements: 2.1, 2.2, 2.4_

  - [ ]* 1.7 Write property test P1 — SMA value equals reference rolling mean
    - `# Feature: sp-340-price-vs-sma-ml-integration, Property 1: For all close-price series and valid periods, emitted price_vs_sma_value equals pandas rolling(window=period, min_periods=period).mean() within float tolerance`
    - Hypothesis, ≥100 iterations; generate random float close series and random `period`
    - _Requirements: 3.1, 3.2_

  - [ ]* 1.8 Write property test P2 — combined score equals the MarketAnalyzer oracle
    - `# Feature: sp-340-price-vs-sma-ml-integration, Property 2: For all close series and configs, the extractor combined score equals MarketAnalyzer.detect_price_vs_sma_signals for the same row/config`
    - Hypothesis, ≥100 iterations; instantiate `MarketAnalyzer` ONLY in the test as an oracle (temp config + prepared `SMA_price_vs` column, following `vpa/tests/test_price_vs_sma.py`); production code must never import/call `MarketAnalyzer`
    - _Requirements: 3.3, 3.4, 3.5, 3.7, 3.8, 3.9, 3.10, 3.12_

  - [ ]* 1.9 Write property test P3 — crossover disabled yields position-only score
    - `# Feature: sp-340-price-vs-sma-ml-integration, Property 3: For all close series, the score with detect_crossover=false equals the position-only score; toggling the flag changes the score only by the crossover term`
    - Hypothesis, ≥100 iterations
    - _Requirements: 3.11_

  - [ ]* 1.10 Write property test P4 — composite score invariant under price-vs-SMA config
    - `# Feature: sp-340-price-vs-sma-ml-integration, Property 4: For all rows and all pairs of price_vs_sma configs (enabled/disabled, crossover on/off), composite_score is identical and equals the five-term sum`
    - Hypothesis, ≥100 iterations
    - _Requirements: 4.1, 4.2, 4.3_

  - [ ]* 1.11 Write composite-score baseline regression test
    - Capture `composite_score` for a fixed input dataset and assert it matches the captured baseline, proving the composite is byte-for-byte unchanged after the feature is added (design Testing Strategy)
    - _Requirements: 8.2_

- [ ] 2. Checkpoint — Ensure extractor tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 3. Register price vs SMA as a backtestable signal in `signal_analysis`
  - [ ] 3.1 Add `SignalType` members and `SIGNAL_DIRECTIONS` entries
    - In `vpa/ml_validation/signal_analysis.py`, add `SignalType.PRICE_ABOVE_SMA = "price_above_sma"` and `SignalType.PRICE_BELOW_SMA = "price_below_sma"`; map `PRICE_ABOVE_SMA → SignalDirection.UP` and `PRICE_BELOW_SMA → SignalDirection.DOWN` in `SIGNAL_DIRECTIONS` (design §2.1)
    - _Requirements: 5.1, 5.2, 5.3_

  - [ ] 3.2 Add column-guarded, NaN-safe classification in `classify_signals`
    - Follow the `if "dss_bullish_cross" in df.columns:` pattern: guard on `"price_vs_sma_signal_score" in df.columns`, build a `notna()` mask, match positive → `PRICE_ABOVE_SMA`, negative → `PRICE_BELOW_SMA`; `0`/NaN → neither; column absent → both lists stay empty (design §2.2)
    - _Requirements: 5.4, 5.5, 5.6, 5.7_

  - [ ]* 3.3 Write unit tests for signal_analysis members and classification
    - Assert both members exist and their `SIGNAL_DIRECTIONS` are UP/DOWN; assert column-absent → both match lists empty
    - _Requirements: 5.1, 5.2, 5.3, 5.6_

  - [ ]* 3.4 Write property test P5 — classify_signals partitions rows by score sign
    - `# Feature: sp-340-price-vs-sma-ml-integration, Property 5: For all feature DataFrames with price_vs_sma_signal_score, classify_signals returns PRICE_ABOVE_SMA exactly for non-NaN strictly-positive rows, PRICE_BELOW_SMA exactly for non-NaN strictly-negative rows, and neither for zero/NaN`
    - Hypothesis, ≥100 iterations; generate DataFrames with injected scores including zeros and NaNs
    - _Requirements: 5.4, 5.5, 5.7_

- [ ] 4. Wire price vs SMA into `daily_signal`
  - [ ] 4.1 Add `CONFIDENCE_MAP` entries for both new signal types
    - In `vpa/ml_validation/daily_signal.py`, add `SignalType.PRICE_ABOVE_SMA: "Low"` and `SignalType.PRICE_BELOW_SMA: "Low"` (labels drawn from `CONFIDENCE_ORDER`) (design §3.1)
    - _Requirements: 6.1, 6.2_

  - [ ] 4.2 Wire `classify_last_row` using the existing `_is_valid_numeric` guard
    - Read `last_row.get("price_vs_sma_signal_score")`; if `_is_valid_numeric`, add `PRICE_ABOVE_SMA` when `> 0`, `PRICE_BELOW_SMA` when `< 0`; absent/NaN/0 → add neither (design §3.2)
    - _Requirements: 6.3, 6.4, 6.5_

  - [ ] 4.3 Update daily_signal's inline extractor loop to precompute and pass the SMA series
    - In the `DailySignalGenerator` inline loop, precompute the SMA series over its `df["Close"]` and compute the per-row score with the §1.3 logic using its own positional index, passing `price_vs_sma_value` / `price_vs_sma_signal_score` into `_extract_feature_vector` so the daily path actually fires (design §3.3)
    - _Requirements: 6.3, 6.4_

  - [ ]* 4.4 Write unit tests for daily_signal wiring
    - Assert `CONFIDENCE_MAP` has both keys with labels in `CONFIDENCE_ORDER`; assert the inline daily loop precomputes the series and `classify_last_row` returns the expected member for crafted positive / negative / zero last rows
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [ ]* 4.5 Write property test P6 — classify_last_row reflects the last row's score sign
    - `# Feature: sp-340-price-vs-sma-ml-integration, Property 6: For all feature DataFrames, classify_last_row includes PRICE_ABOVE_SMA iff the last row score is non-NaN and strictly positive, PRICE_BELOW_SMA iff non-NaN strictly negative, and neither when absent/NaN/zero`
    - Hypothesis, ≥100 iterations; include the absent-column case
    - _Requirements: 6.3, 6.4, 6.5_

- [ ] 5. Checkpoint — Ensure signal_analysis and daily_signal tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Correct stale feature-count references (audit to 33)
  - [ ] 6.1 Correct counts in `feature_extractor.py`
    - Update the `_extract_feature_vector` docstring "29 feature columns" → 33; the `generate_dataset` docstring "27 feature columns" → 33; the `FEATURE_COLUMNS` leading comment "31-feature vector" → 33 (design §Stale feature-count audit)
    - _Requirements: 7.1, 7.2_

  - [ ] 6.2 Correct counts in `test_integration.py`
    - In `vpa/tests/ml_validation/test_integration.py`, change the importance-report assertion `assert len(df) == 31` → `== 33` (prefer `len(VPAFeatureExtractor.FEATURE_COLUMNS)`) and assert `{"price_vs_sma_value", "price_vs_sma_signal_score"} <= set(df["feature_name"])`; update the "All 27 feature columns" comment to 33
    - _Requirements: 7.3, 7.4_

  - [ ] 6.3 Correct remaining stale-count prose discovered in the audit
    - Update the `analysis.py` "27 feature columns" comment to 33 (code derives columns dynamically); update the "31 features" docstring prose in `test_feature_extraction_characterisation.py` and `test_scoring_params_preservation.py`; correct any other hardcoded raw-count literals/comments found, preferring `len(VPAFeatureExtractor.FEATURE_COLUMNS)` over literals where practical (design §Stale feature-count audit)
    - _Requirements: 7.5_

- [ ] 7. Regenerate the characterisation fixture (slow)
  - [ ] 7.1 Regenerate the committed characterisation fixture and verify the composite column is unchanged
    - Run with `REGEN_VPA_CHARACTERISATION_FIXTURE=1` to regenerate the fixture consumed by `test_feature_extraction_characterisation.py` / `test_scoring_params_preservation.py`; review the regenerated fixture to confirm only the two new columns were added and that the `composite_score` column values are identical to the prior fixture (design §1.1, §Fixture regeneration)
    - _Requirements: 2.4, 4.3, 8.2_

- [ ] 8. Checkpoint — Ensure the fast suite passes with the regenerated fixture
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 9. Verification gate (run in order; required before SP-340 moves to Done)
  - Run `ruff check .` (lint clean), then `ruff format --check .` (formatting clean), then `pytest -m ""` (the FULL suite including slow ML tests — NOT bare `pytest`), all green, per the repo testing rules
  - Fix any violations surfaced (`ruff check --fix .` / `ruff format .`) and re-run the gate until clean
  - _Requirements: 8.1, 8.3, 8.4, 8.5_

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP; core implementation tasks are never optional.
- Each task references specific requirement sub-clauses for traceability.
- Property tests use Hypothesis at ≥100 iterations and are tagged `# Feature: sp-340-price-vs-sma-ml-integration, Property N: <text>`; each maps to one design correctness property (P1–P6).
- Property 2 uses `MarketAnalyzer` ONLY as a test oracle; production code must never import or call it.
- The `composite_score` line must remain byte-for-byte unchanged (task 1.4) — the hard zero-regression constraint.
- The final gate must run `pytest -m ""`, not bare `pytest`, so the slow ML tests are not silently skipped.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["1.3"] },
    { "id": 3, "tasks": ["1.4", "1.5", "1.6", "1.7", "1.8", "1.9", "1.10", "1.11"] },
    { "id": 4, "tasks": ["3.1"] },
    { "id": 5, "tasks": ["3.2"] },
    { "id": 6, "tasks": ["3.3", "3.4", "4.1"] },
    { "id": 7, "tasks": ["4.2"] },
    { "id": 8, "tasks": ["4.3"] },
    { "id": 9, "tasks": ["4.4", "4.5"] },
    { "id": 10, "tasks": ["6.1", "6.2", "6.3"] },
    { "id": 11, "tasks": ["7.1"] }
  ]
}
```
