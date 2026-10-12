# Implementation Plan: VPA Threshold Tuning & ML Re-validation (SP-313)

## Overview

This plan refactors the hardcoded VPA scoring thresholds in `vpa/app.py` into an injectable
`ScoringParams` dataclass, then builds a thin experiment layer in `vpa/ml_validation/tuning/`
that sweeps candidate thresholds, gates changes on measured improvement (Req 6, +≥3.09pp),
classifies results, and records reproducible artefacts.

The refactor is **behaviour-preserving**: a characterisation/regression test locks the current
baseline extraction output *before* any refactor (task 1), and every refactor step verifies that
`ScoringParams.default()` reproduces today's scoring exactly (Property 1). Code tasks (1–12) are
followed by manual/analysis tasks (13–17) that run the harness, apply the gate, and document
findings in the Side Projects Confluence space, and a final verification task (18).

Scope boundary: this plan does **not** tune RSI thresholds or MA-crossover thresholds.

Testing: pure-function tests are FAST (default `pytest` run); tests that re-extract features,
train a real XGBoost model, or run the full pipeline carry the `slow` marker. Tasks 13–17 are
manual/analysis tasks and have no unit tests.

## Tasks

- [x] 1. Lock current baseline feature-extraction output as a regression fixture (SAFETY NET — before any refactor)
  - Add a characterisation test that runs the current/legacy `VPAFeatureExtractor` extraction path over a fixed pinned raw-OHLCV window and snapshots the full labelled feature dataset (all 31 columns including `composite_score` and `next_day_direction`) as a stored regression fixture.
  - This fixture is the oracle that later refactor steps (3, 4, 5) and Property 1 assert against; capture it NOW so any accidental drift introduced by the refactor is caught.
  - Mark `slow` (re-extracts features over a real window).
  - _Requirements: 1.2_
  - **Property 1: Default-params behaviour preservation**

- [x] 2. Implement `ScoringParams` dataclass and validation
  - [x] 2.1 Create `vpa/ml_validation/tuning/scoring_params.py`
    - Immutable `@dataclass(frozen=True) ScoringParams` with fields and defaults: `shooting_star_spread_mult=2.0`, `shooting_star_lower_wick_mult=2.0`, `acc_dist_volume_percentile=65`, `acc_dist_test_count=3`, `period_weight_p1/p2/p3=1.0`, `vol_backed_mult_p1/p2/p3=2.0`.
    - Add `ScoringParams.default()` classmethod returning the canonical current configuration.
    - Implement `validate() -> list[str]` returning rejection messages (empty == valid): shooting-star mult `< 1` or non-positive; `acc_dist_volume_percentile` not an integer in 1..99; `acc_dist_test_count` not an integer `>= 1`; any `vol_backed_mult_pN` negative.
    - _Requirements: 2.5, 3.1, 3.2, 5.1_
  - [x]* 2.2 Write unit + Hypothesis property test for `validate()`
    - Unit: representative in-range and out-of-range examples per field.
    - **Property 5: Candidate validation biconditional** — `validate()` returns a non-empty list iff at least one field is out of range (FAST).
    - **Validates: Requirements 2.5, 3.1, 3.2, 5.1**

- [x] 3. Refactor `Candle.__init__` for injectable shooting-star multipliers
  - In `vpa/app.py`, add keyword-only params `shooting_star_spread_mult` and `shooting_star_lower_wick_mult` to `Candle.__init__`, defaulting to the existing class constants (`CONFIG_SHOOTING_STAR_UPPER_WICK_X_TIMES_BIGGER_THAN_SPREAD`, `..._BIGGER_THAN_LOWER_WICK`).
  - Update the shooting-star detection test to use the parameters instead of the class constants.
  - All existing six-positional-arg callers must remain unaffected; verify the characterisation test (task 1) is still green.
  - _Requirements: 2_
  - **Property 1: Default-params behaviour preservation**

- [x] 4. Refactor `identify_acc_or_dist` for injectable percentile and test count
  - In `vpa/app.py`, change the signature to `identify_acc_or_dist(period_three, period_one, *, volume_percentile=65, test_count=3)`.
  - Replace the hardcoded `np.percentile(volume_stats_list, [65, 90])` with `[volume_percentile, 90]` and the `>= 3` literal with `>= test_count`.
  - Keep positional back-compatibility for existing callers; verify the characterisation test (task 1) is still green.
  - _Requirements: 3_
  - **Property 1: Default-params behaviour preservation**

- [x] 5. Thread `ScoringParams` through `VPAFeatureExtractor`
  - [x] 5.1 Inject scoring params into extraction
    - Add `scoring_params: ScoringParams | None = None` to `VPAFeatureExtractor.__init__` (default `None` → `ScoringParams.default()`).
    - When constructing each `Candle`, pass `shooting_star_spread_mult` / `shooting_star_lower_wick_mult` from `scoring_params`.
    - In `_detect_signals`: pass `volume_percentile` / `test_count` to `identify_acc_or_dist`, apply `period_weight_pN` to each period's `multiple_bar` contribution, and use `vol_backed_mult_pN` in place of the hardcoded `* 2`.
    - _Requirements: 2, 3, 4, 5_
  - [x] 5.2 Write `slow` property test for default-params preservation
    - **Property 1: Default-params behaviour preservation** — `DatasetSnapshot.extract(ScoringParams.default())` reproduces the task-1 regression fixture column-for-column (`slow`).
    - **Validates: Requirements 2, 3, 4, 5 (non-regression)**
  - [x]* 5.3 Write property test for composite score totality
    - **Property 4: Composite score totality** — for any valid `ScoringParams` (including reduced `vol_backed_mult_p1/p2`), every scored bar still has a non-null `composite_score`. Keep FAST over a small synthetic window if feasible, else mark `slow`.
    - **Validates: Requirements 5.3**

- [x] 6. Add optional `end_date` to `generate_dataset` to pin the window
  - [x] 6.1 Add `end_date` parameter
    - Change `generate_dataset(days=3650, repo=None, end_date=None)`; `None` → `datetime.datetime.now().date()` (preserves current behaviour). An explicit `end_date` pins the data window for the experiment (Req 1.4).
    - _Requirements: 1.1, 1.4_
  - [x] 6.2 Write `slow` determinism/reproducibility property test
    - **Property 2: Determinism / reproducibility** — two independent extractions-and-evaluations at seed 42 (set before dataset generation and before model training) yield `Baseline_Accuracy` and mean `ML_Accuracy` equal to two decimal places. Re-extracts + re-trains → `slow`.
    - **Property 3: Baseline accuracy range** — `compute_baseline_accuracy()` ∈ [0,1] and recorded `baseline_accuracy_pct` ∈ [0,100] (FAST over a small/synthetic dataset).
    - **Validates: Requirements 1.4, 1.2**

- [x] 7. Implement `DatasetSnapshot` to pin the raw-OHLCV window and centralise seeding
  - Create `vpa/ml_validation/tuning/snapshot.py` with `@dataclass(frozen=True) DatasetSnapshot(ticker, data_start, data_end, seed=42)`.
  - Implement `extract(params, repo=None) -> pd.DataFrame`: set seed 42, run `VPAFeatureExtractor.generate_dataset` over the pinned window with `params`, return the labelled dataset. Centralises Req 1.1 seeding.
  - A snapshot is identified by `(ticker, data_start, data_end, seed)` so sweeps are apples-to-apples.
  - _Requirements: 1.1, 1.4_

- [x] 8. Implement `ChangeGate` pure decision functions
  - [x] 8.1 Create `vpa/ml_validation/tuning/gate.py`
    - `exceeds_margin(candidate_pct, baseline_pct, margin_pp) -> bool` (strict `>` for Req 3.3/4.2 per-dimension margins).
    - `should_apply_to_config(candidate_pct, in_effect_pct) -> bool` returning `(candidate_pct - in_effect_pct) >= 3.09` (Req 6.1/6.2).
    - `record_shooting_star(...)` applying the +0.5pp recording margin and the tie-break toward the candidate nearest the current value (2) (Req 2.2–2.4).
    - Return `SelectionOutcome` capturing prior/applied value, prior/new accuracy, justifying delta (Req 6.3), or "no change beneficial" (Req 2.4/3.5/4.3/5.4).
    - _Requirements: 2.2, 2.3, 2.4, 3.3, 4.2, 5.2, 6_
  - [x] 8.2 Write FAST unit + property tests for the gate
    - Unit: `should_apply_to_config` / `exceeds_margin` at and around 3.09pp and per-dimension margins; shooting-star tie-break toward value nearest 2; "no change beneficial" outcomes.
    - **Property 6: Apply-gate threshold and idempotence** — `should_apply_to_config` is `True` iff `candidate_pct - in_effect_pct >= 3.09`, and a non-clearing candidate leaves `ScoringParams` equal by dataclass equality (no-op) (FAST).
    - **Validates: Requirements 6.1, 6.2, 6.3**

- [x] 9. Implement `Classifier` pure band functions
  - [x] 9.1 Create `vpa/ml_validation/tuning/classify.py`
    - `classify_ml_vs_sp312(ml_pct)`: `increased` > 53.68, `decreased` < 47.50, else `within-band` (Req 7.4).
    - `classify_baseline_vs_sp312(base_pct)`: `increased`/`decreased`/`unchanged` vs 52.34 (Req 7.4).
    - `classify_ticker_edge(ticker_base_pct, spy_base_pct)`: `stronger`/`weaker`/`comparable` with ±3.09pp band (Req 9.4).
    - `pursue_decision(spy_ml_pct: float | None) -> PursueResult`: `pursue` when strictly > 54.0, else `do not pursue`; `None` → `no recommendation` with unavailable reason (Req 8).
    - Define single-source-of-truth constants (`SP312_BASELINE_PCT`, `SP312_ML_MEAN_PCT`, `SP312_ML_STD_PCT`, `PURSUE_ML_THRESHOLD_PCT`, `ML_BAND_LOW`, `ML_BAND_HIGH`).
    - _Requirements: 7.4, 8, 9.4_
  - [x] 9.2 Write FAST unit + property tests for classifiers
    - Unit: example cases at each boundary (47.50, 53.68, 52.34, ±3.09pp, strict > 54.0, `None` → unavailable).
    - **Property 7: Classification band partition** — each classifier returns exactly one band and selects the correct band at every boundary (FAST).
    - **Validates: Requirements 7.4, 9.4, 8**

- [x] 10. Implement `ExperimentRecord` and `ResultWriter`
  - [x] 10.1 Create `vpa/ml_validation/tuning/record.py`
    - `ExperimentRecord` with all fields from the Data Models table (ticker, data_start/end, labelled_row_count, seed, serialised `scoring_params`, baseline_accuracy_pct, ml_mean/std_accuracy_pct, skipped_folds, top5_feature_importance, realized_volatility, run_completed, error); all numeric values to at least 2dp.
    - `ResultWriter` serialising each record to a JSON artefact plus a human-readable summary, mirroring `AnalysisScript.save_outputs`.
    - Enforce Req 1.5 pre-write guard: if a run produced zero labelled rows or data is unavailable, write no partial artefact and raise a ticker-identifying error.
    - Log-and-continue on artefact write failure (after a result was successfully computed).
    - _Requirements: 1.2, 1.3, 1.5, 10.6_
  - [x]* 10.2 Write FAST unit tests for record/writer
    - Record serialisation round-trip incl. `scoring_params` flat dict and `null` + reason markers (Req 10.6); Req 1.5 pre-write guard writes no partial artefact; write-failure is logged and does not raise.
    - _Requirements: 1.2, 1.3, 1.5, 10.6_

- [x] 11. Implement multi-ticker selection helpers
  - [x] 11.1 Create `vpa/ml_validation/tuning/ticker_selection.py`
    - `realized_daily_volatility(dataset) -> float`: std of daily close-to-close returns over the window.
    - `volatility_spread_ok(vols: list[float]) -> bool`: pairwise difference `>= 10%` of the lowest selected ticker's volatility (Req 9.1).
    - _Requirements: 9.1_
  - [ ]* 11.2 Write FAST unit tests for selection helpers
    - `realized_daily_volatility` on known series; `volatility_spread_ok` pass/fail cases incl. the replacement-selection path (Req 9.5).
    - _Requirements: 9.1_

- [x] 12. Implement `SweepRunner` and wire the tuning layer together
  - [x] 12.1 Create `vpa/ml_validation/tuning/sweep.py`
    - `SweepRunner.run(snapshot, baseline, candidates) -> SweepResult`.
    - Validate each candidate with `ScoringParams.validate()`; exclude out-of-range candidates and append rejection messages (Req 2.5/3.1/3.2/5.1) before any extraction.
    - For baseline + each valid candidate, re-extract the dataset over the pinned snapshot and compute `Baseline_Accuracy` via `AnalysisScript.compute_baseline_accuracy`.
    - Record accuracy and signed `delta_pp` for every evaluated candidate, beneficial or not (Req 3.4).
    - On per-candidate failure (extraction error / zero rows), exclude from selection, append to `eval_errors`, and retain previously recorded results (Req 3.6).
    - Produce `SweepResult`/`CandidateResult` as defined in Data Models and wire `ScoringParams`, `DatasetSnapshot`, `ChangeGate`, and `ResultWriter` together into the end-to-end sweep flow.
    - _Requirements: 2.1, 3.4, 3.6, 4.1, 5.1_
  - [x]* 12.2 Write `slow` integration test for the sweep
    - End-to-end sweep over a pinned window: out-of-range candidate excluded with the sweep continuing (Req 2.5), per-candidate eval error retains prior results (Req 3.6), every evaluated candidate recorded (Req 3.4). Re-extracts features → `slow`.
    - **Property 1: Default-params behaviour preservation** and **Property 4: Composite score totality** exercised through the integration path.
    - **Validates: Requirements 2.1, 3.4, 3.6, 4.1, 5.1**

- [x] 13. (Manual / analysis — no unit tests) Run SPY re-validation
  - Run `python -m vpa.ml_validation.run_analysis --ticker SPY`.
  - Record the signed percentage-point deltas of SPY `Baseline_Accuracy` vs 52.34% and SPY mean `ML_Accuracy` vs 50.59%, and classify the movement against the SP312 band (52.34% / 50.59% ± 3.09%) using the task-9 classifiers.
  - If the run fails or SPY data is unavailable, record `run_completed = false` with an error (Req 7.2) and emit no accuracy values.
  - _Requirements: 7_

- [x] 14. (Manual / analysis — no unit tests) Apply the pursue decision from SPY ML accuracy
  - Apply `pursue_decision` to the SPY mean `ML_Accuracy`: `pursue` when strictly > 54.0%, else `do not pursue`; `None` → no recommendation + unavailable reason.
  - Record the recommendation alongside the supporting `ML_Accuracy` value (2dp).
  - _Requirements: 8_

- [x] 15. (Manual / analysis — no unit tests) Run the four threshold sweeps and apply the Req 6 gate
  - Run the shooting-star (Req 2), acc/dist percentile + test-count (Req 3), period-three weighting (Req 4), and vol_backed p1/p2 reduction (Req 5) sweeps on the pinned snapshot via `SweepRunner`.
  - Apply the Req 6 apply-gate (`should_apply_to_config`, +≥3.09pp) to decide which, if any, tuned values are written to `config.json`; for applied changes record prior/applied value, prior/new accuracy, and the justifying delta (Req 6.3); otherwise record "no change beneficial".
  - _Requirements: 2, 3, 4, 5, 6_

- [x] 16. (Manual / analysis — no unit tests) Run 3–5 individual tickers and classify edge vs SPY
  - Select 3–5 individual S&P 500 tickers whose realized daily-return volatility satisfies the Req 9.1 spread (`volatility_spread_ok`), run each through the harness, and record each ticker's `Baseline_Accuracy` / `ML_Accuracy`.
  - Classify each ticker's edge as stronger / weaker / comparable vs SPY using the ±3.09pp band (`classify_ticker_edge`).
  - Handle `< 2000` labelled rows: record a ticker-identifying error, write no accuracy for that ticker, and select a replacement ticker still satisfying the volatility spread (Req 9.5).
  - _Requirements: 9_

- [~] 17. (Manual / analysis — no unit tests) Document findings and single recommendation in Confluence
  - In the Side Projects Confluence space, document every evaluated threshold adjustment (identifier, applied?, signed accuracy delta vs baseline), the SPY re-validation ML/baseline values with signed deltas vs SP312, each individual ticker's ML_Accuracy with signed delta vs SPY, and the exact threshold values + integer seed per reported result.
  - Record exactly one of "pursue" / "do not pursue" with the supporting `ML_Accuracy` value.
  - For any unavailable value, write an explicit "unavailable + reason" marker rather than omitting it (Req 10.6).
  - _Requirements: 10_

- [~] 18. Final verification
  - Run the full suite `pytest -m ""` (529 existing + new tests) and confirm all green so the `slow` ML tests are not skipped.
  - Run `ruff check .` and `ruff format --check .` and confirm both clean (run the format check after any scripted/tool writes).
  - _Requirements: all_

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP; core implementation tasks are never optional. The Property tests guarding behaviour-preservation (5.2), reproducibility (6.2), the Req 6 apply gate (8.2), and the classification/recommendation logic (9.2) have been promoted to required (no `*`) because they protect production scoring and the ticket's conclusion; the remaining `*` test sub-tasks (2.2, 5.3, 10.2, 11.2, 12.2) stay optional.
- Tasks 13–17 are manual/analysis tasks (run the harness, apply gates, document in Confluence) and carry no unit tests, per the feature's analysis-driven nature.
- Task 1 is a safety net: it locks the current baseline extraction output BEFORE any refactor so Property 1 can assert the injectable-params change is behaviour-preserving.
- Test markers follow the repo rule: pure-function tests are FAST (default run); tests that re-extract features, train a real XGBoost model, or run the full pipeline carry the `slow` marker.
- Each task references specific requirement sub-clauses and, where applicable, the Correctness Property it validates for traceability.
- Definition of Done (SP-313): any threshold change clearing the Req 6 gate must be applied to `config.json`, the applied/retained decisions recorded, and the full results plus the single recommendation documented in Confluence. Until config + Confluence are both complete, the ticket belongs in Mostly Done.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "2.1", "9.1", "11.1"] },
    { "id": 1, "tasks": ["2.2", "3", "8.1", "9.2", "11.2"] },
    { "id": 2, "tasks": ["4", "8.2"] },
    { "id": 3, "tasks": ["5.1", "6.1"] },
    { "id": 4, "tasks": ["5.2", "5.3", "6.2", "7", "10.1"] },
    { "id": 5, "tasks": ["10.2", "12.1"] },
    { "id": 6, "tasks": ["12.2"] }
  ]
}
```
