# Implementation Plan: MarketAnalyzer Signal Detection Tests (SP-307)

## Overview

This plan implements the test-and-tooling work for Jira **SP-307**. The code under test (`MarketAnalyzer.detect_signals()` in `vpa/app_runner.py` and its collaborators in `vpa/app.py`) MUST NOT be modified — all tasks produce test artifacts, tooling configuration, and dependency/environment fixes only.

Sequencing is grounded in the design: get the environment and dependencies correct first (so the suite can run), capture the baseline coverage before adding new `detect_signals` tests, build the shared `conftest.py` scaffolding, then the per-category tests, the pytest config and import fix, the four `unittest`->pytest conversions, and finally the full-suite/coverage/clean-install verification.

## Tasks

- [x] 1. Rebuild the environment and correct `requirements.txt` against a clean `.venv` (foundation first)
  - [x] 1.1 Capture currently-installed dependency versions from the existing `.venv` BEFORE removing it
    - Read exact installed versions of `pytest`, `hypothesis`, `xgboost`, `pytest-cov`, and `coverage` from the existing `.venv`
    - If `pytest-cov` and/or `coverage` are absent from the existing `.venv`, install them into it first so their versions can be captured (do not fabricate a version if install fails — report it)
    - Also capture the versions of any other third-party libraries imported by the test suite or production code that are absent from `requirements.txt`
    - Record all captured versions so the pinning information survives once `.venv` is deleted in task 1.5
    - _Requirements: 12.3, 12.4, 10.1_

  - [x] 1.2 Complete `requirements.txt` (add missing) using the captured versions
    - Append, in the existing `==` pinning style, every third-party library the test suite or production code imports but that is currently absent from `requirements.txt`
    - Explicitly add `pytest`, `hypothesis`, `pytest-cov`, `coverage`, and `xgboost`, each pinned to the version captured in task 1.1 (e.g. `pytest==9.1.1`, `hypothesis==6.165.10`, `xgboost==3.4.1`)
    - Use identical `pytest-cov`/`coverage` pins to satisfy both Requirement 10.1 and Requirement 12.4 (no contradiction)
    - Grep the test suite and `vpa/ml_validation/*` for third-party imports and confirm each is represented in the manifest
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.6, 10.1_

  - [x] 1.3 Prune unused dependencies (remove) from `requirements.txt`
    - Applied AFTER 1.2's additions and BEFORE recreating `.venv` (task 1.5), so the fresh install already excludes the unused packages
    - Remove the unused TensorFlow/Keras stack packages that no trading module imports via a Direct_Import and that are not transitive deps of a retained package: `absl-py`, `astunparse`, `flatbuffers`, `gast`, `google-pasta`, `grpcio`, `h5py`, `libclang`, `ml-dtypes`, `namex`, `opt_einsum`, `optree`, `protobuf`, `termcolor`, `wrapt`, `Werkzeug`, `Markdown`
    - Explicitly retain `xgboost` and `scikit-learn` (imported by `vpa/ml_validation/*`); do NOT remove `tensorflow`/`keras` (they are not top-level lines in the manifest anyway)
    - Apply the retain-on-ambiguity rule: keep any package that could be a Transitive_Dependency of a Retained_Dependency (`matplotlib`, `pandas`, `scikit-learn`, `xgboost`, `yfinance`, `selenium`, `mplfinance`) rather than removing it on a missing Direct_Import alone
    - The fresh-install verification in task 1.6 governs the final result: any removal that breaks an import is restored pinned and re-verified
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5_

  - [x] 1.4 Clean up stale `venv` -> `.venv` references and remove the unused `.idea/` folder
    - Remove the entire `.idea/` folder from the repo via `git rm -r .idea` (11 files are git-tracked, so a filesystem delete alone is insufficient). This supersedes the previously-planned surgical edits (run-config SDK_HOME, .iml excludeFolder, misc.xml Black component).
    - Add `.idea/` to the repository-root `.gitignore` so the folder does not return (.gitignore does not currently list it).
    - Repoint the activation lines in `vpa/scripts/start_vpa.sh`, `vpa/scripts/start_vpa_all_shares.sh`, `vpa/scripts/start_vpa_forex.sh` to `source /usr/local/trading/.venv/bin/activate`.
    - Grep for the old `venv` name (outside `.venv/`) in the shell scripts and confirm zero matches remain.
    - _Requirements: (user-directed stale-venv cleanup — no numbered AC)_

  - [x] 1.5 Recreate `.venv` fresh and install only from the corrected `requirements.txt`
    - Remove the existing `.venv` directory and create a new virtual environment in its place
    - Install ONLY from the corrected-and-pruned `requirements.txt` (no ad-hoc packages), so the fresh install already excludes the packages removed in task 1.3
    - Note this is a destructive, one-time environment rebuild that reinstalls heavy dependencies (e.g. `xgboost`, `scikit-learn`)
    - _Requirements: 12.5_

  - [x] 1.6 Verify `requirements.txt` is complete AND minimal against the fresh `.venv`
    - Collect and run the full suite from the repository root using the freshly recreated `.venv`
    - Assert zero `ModuleNotFoundError` — this is the governing check for BOTH the additions (R12) and the removals (R13)
    - If any third-party import is missing (an addition gap), add it to `requirements.txt` pinned to its installed version and reinstall into `.venv`
    - If a removed package causes a `ModuleNotFoundError` (an over-prune), restore it to `requirements.txt` pinned to its exact version and reinstall, then re-verify until zero `ModuleNotFoundError` remain
    - This is the early verification that the requirements list is right (folds in the former clean-install check)
    - _Requirements: 12.5, 12.6, 13.6, 13.7_

- [x] 2. Record baseline coverage of `vpa/app_runner.py` (BEFORE adding new detect_signals tests)
  - Run `pytest --cov=vpa/app_runner --cov-report=term-missing` from the repository root against the existing suite, using the freshly rebuilt `.venv` from task 1.5
  - Record, to one decimal place, the baseline line-coverage metric for `vpa/app_runner.py`
  - If the coverage command cannot produce the metric, report the failure and do not record a baseline value
  - Store the recorded baseline in the tasks notes / spec for later comparison
  - _Requirements: 10.2, 10.4, 10.5_

- [x] 3. Build shared test scaffolding in `vpa/tests/conftest.py` (Area A)
  - [x] 3.1 Implement builder helper functions
    - `make_candle(*, up, volume, spread, upper_wick, lower_wick, time)` deriving OHLC so `up_bar`, `spread`, wicks, and pattern flags (shooting-star / hammer / avoid accidental LLD) are exactly as requested
    - `set_percentiles(candle, *, spread, volume)` assigning `spread_percentiles` THEN `volume_percentiles` (order matters for the anomaly-map setter), keyed on all three period names
    - `populate_windows(analyzer, period_one, period_two, period_three)` writing into `analyzer._MarketAnalyzer__deque_dictionary[...]` via the mangled name, respecting each deque `maxlen`
    - `make_minimal_df(rows=250)` and `load_spy_slice(n)` (reads first `n` rows of `vpa/data/spy_data.csv`) for the `fixed_df`/ADX path
    - _Requirements: 6.1, 6.2_

  - [x] 3.2 Implement hermeticity and construction fixtures
    - `no_network(monkeypatch)`: monkeypatch `vpa.app_runner.yf.download` to raise `AssertionError("network access attempted")`; autouse in new test modules
    - `null_logger(monkeypatch)`: monkeypatch `vpa.app_runner.DebugLog` with a no-file stand-in whose `.log(message, level="DEBUG")` is a no-op; autouse in new test modules; document the delete-based fallback in a `try/finally` for any real-logger path
    - `analyzer_factory(no_network, null_logger)`: returns `build(*, fixed_df=None, config_path=DEFAULT_CONFIG)` constructing `MarketAnalyzer` with `ticker_symbol=None` and the real `vpa/config/config.json`
    - `populated_analyzer(analyzer_factory)`: analyzer with three windows pre-filled with a neutral baseline candle set
    - _Requirements: 6.1, 6.4, 6.5, 6.6, 6.7_

- [x] 4. Checkpoint - verify scaffolding runs and the suite still collects
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Single-candle regression tests (Area B) — `vpa/tests/test_detect_signals_single_candle.py`
  - [x] 5.1 Implement up/down bar and pattern example tests
    - Assert `single_candle_signals` and `single_candle_signal_score` for up bar ("Up Bar", +1) and down bar ("Down Bar", -1)
    - Assert shooting star ("Shooting Star", -3, "Hammer" absent) and hammer ("Hammer", +3, "Shooting Star" absent)
    - Author pytest-native (no `unittest`); use `pytest.approx` for fractional scores
    - _Requirements: 1.1, 1.2, 1.3, 1.9, 1.10, 11.10_

  - [x] 5.2 Implement wide-spread / high-volume example tests
    - Up bar spread percentile > 70 -> "Wide Spread (<period>)" (+2.5); down bar -> (-2.5)
    - Both spread AND volume percentile > 70 -> "High Volume (<period>)" (+2.5 up / -2.5 down)
    - Spread percentile not strictly > 70 -> neither "Wide Spread" nor "High Volume" present for that period
    - _Requirements: 1.4, 1.5, 1.6, 1.7, 1.8_

  - [x]* 5.3 Write property test for wide-spread / high-volume 70 boundary
    - **Property 2: Wide-spread / high-volume presence tracks the 70 boundary**
    - **Validates: Requirements 1.4, 1.6, 1.8, 5.5**

- [x] 6. Trend regression tests (Area B) — `vpa/tests/test_detect_signals_trend.py`
  - [x] 6.1 Implement trend example tests
    - Assert `trend_signals` / `trend_signal_score` for trending up ("Market is trending" + "Trending Up", +5), trending down ("Trending Down", -5), and not-trending (empty, 0)
    - Use `load_spy_slice` and/or synthetic candle sequences engineered so `adx_values[0]`, `[2]`, `[3]` satisfy each branch
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 6.2 Implement ADX-insufficiency error test
    - With `period_three` holding fewer than 15 candles, assert `detect_signals` raises `ValueError` (matching the insufficient-ADX message) via `pytest.raises`
    - _Requirements: 2.5_

- [x] 7. Multiple-bar regression tests (Area B) — `vpa/tests/test_detect_signals_multiple_bar.py`
  - [x] 7.1 Implement bull/bear and neutral-band example tests
    - Bull: up-bar count >= `Signal_Bar_Count` (not volume-backed) -> "Bull Signal (<period>)" (+2.5)
    - Bear: up-bar count <= `PERIOD_ONE_LENGTH` - `Signal_Bar_Count` (not volume-backed) -> "Bear Signal (<period>)" (-2.5)
    - Neutral band -> neither signal present, contributes 0
    - _Requirements: 3.1, 3.2, 3.3, 3.6_

  - [x] 7.2 Implement volume-backed and sub-condition-failure tests
    - Volume-backed bull/bear (high_spread_count >= High_Spread_Count, high_volume_count >= High_Volume_Count, anomaly_count <= Anomaly_Threshold) -> "Volume Backed (<period>)" + doubled score (+5.0 / -5.0)
    - At least one volume sub-condition fails -> "Volume Backed" absent, undoubled contribution (+2.5 / -2.5)
    - _Requirements: 3.4, 3.5, 3.7_

  - [x]* 7.3 Write property test for bull-signal Signal_Bar_Count boundary
    - **Property 3: Bull-signal presence tracks the `Signal_Bar_Count` boundary**
    - **Validates: Requirements 3.2, 5.6**

- [x] 8. Accumulation/distribution regression tests (Area B) — `vpa/tests/test_detect_signals_acc_dist.py`
  - [x] 8.1 Implement Acc/Dist base condition tests
    - Force accumulation via period_three volume/close percentiles and `period_one[-1].close` relative to price percentiles -> "Possible Acc" (+10)
    - Force distribution -> "Possible Dist" (-10)
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 8.2 Implement Test Pass / Test Fail tests
    - Acc/Dist candidate (spread percentile period_one > 65 OR `is_candle_pattern()`) with volume percentile period_one < 50 -> "Test Pass" (+5 Acc / -5 Dist)
    - Same candidate with volume percentile not < 50 -> "Test Fail" (-2 Acc / +2 Dist)
    - _Requirements: 4.4, 4.5, 4.6, 4.7_

  - [x] 8.3 Implement Climax tests
    - Acc/Dist condition with period_two spread percentile < 40 AND period_two volume percentile > 60 -> "Climax" (+10 Acc / -10 Dist)
    - _Requirements: 4.8, 4.9_

  - [x]* 8.4 Write property test for Acc/Dist Test Pass 65 and 50 boundaries
    - **Property 4: Acc/Dist "Test Pass" presence tracks the 65 and 50 boundaries**
    - **Validates: Requirements 4.4, 4.5, 4.6, 4.7, 5.7**

- [x] 9. Threshold edge-condition tests (Area D) — `vpa/tests/test_detect_signals_thresholds.py`
  - [x] 9.1 Implement spread/volume percentile 70 edge triples
    - "Wide Spread"/"High Volume" absent at 70, absent at 69, present at 71 (strict `>`)
    - _Requirements: 5.1, 5.3, 5.4, 5.5_

  - [x] 9.2 Implement `Signal_Bar_Count` inclusive-boundary edge triples
    - "Bull Signal" present when up-bar count equals `Signal_Bar_Count`, present one above, absent one below (inclusive `>=`)
    - _Requirements: 5.2, 5.6_

  - [x] 9.3 Implement Acc/Dist test-pass boundary edge triples
    - With an acc/dist condition fixed, assert "Test Pass"/"Test Fail" outcomes at/below/above the period_one spread 65 (strict `>`) and period_one volume 50 (strict `<`) boundaries
    - _Requirements: 5.7_

- [x] 10. Determinism test (Area E) — `vpa/tests/test_detect_signals_determinism.py`
  - [x] 10.1 Implement repeated-invocation equality example test
    - Invoke `detect_signals` ten times with identical fixed data; assert all four signal lists and all four scores are identical every time
    - _Requirements: 1.11, 6.3_

  - [x]* 10.2 Write property test for determinism / idempotence
    - **Property 1: `detect_signals` is deterministic and idempotent**
    - **Validates: Requirements 1.11, 6.3**

- [x] 11. Checkpoint - ensure new detect_signals tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Fix broken import and configure root-level pytest discovery (Area C)
  - [x] 12.1 Fix the broken import in `options/tests/test_price_calc.py`
    - Replace `from price_calc import (...)` with `from utils.utils import calculate_binomial_parameters, calculate_volatility, get_asset_data, price_option, process_data`
    - Preserve existing test behavior; ensure no yfinance pricing pipeline runs at import time
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [x] 12.2 Add repository-root pytest configuration to `pyproject.toml`
    - Add `[tool.pytest.ini_options]` with `testpaths = ["vpa/tests", "options/tests"]` and `norecursedirs` mirroring the Ruff exclude list plus cache dirs (`.venv`, `__pycache__`, `.git`, `.hypothesis`, `ml_validation_output`, `test_data`, `.ruff_cache`, `.pytest_cache`)
    - Ensure the repo root resolves as the pytest rootdir and discovery is CWD-independent
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

- [x] 13. Convert the four `unittest.TestCase` files to pytest-native style (Area E)
  - [x] 13.1 Convert `vpa/tests/test_alpha.py`
    - Replace `setUp` with a pytest fixture (deque dict + `spy_data.csv` load); translate `assertEqual`/`assertTrue`/`assertIn`/`assertIsNotNone`/`assertRaises` per the Assertion_Translation map; remove `suite()` and the `__main__` runner
    - Preserve the same ADX vector expectations, data source (including `"Adj Close"`), and intent
    - _Requirements: 11.1, 11.2, 11.6, 11.7, 11.8, 11.9, 11.11_

  - [x] 13.2 Convert `vpa/tests/test_execution.py`
    - Translate `assertEqual` -> `==`; remove `__main__`/`unittest.main()`; no `setUp` present
    - _Requirements: 11.1, 11.3, 11.6, 11.8, 11.9, 11.11_

  - [x] 13.3 Convert `options/tests/test_implied_volatility.py`
    - Translate `assertAlmostEqual(a, b, places=2)` -> `assert a == pytest.approx(b, abs=1e-2)`; remove `__main__`/`unittest.main()`
    - _Requirements: 11.1, 11.4, 11.6, 11.8, 11.9, 11.11_

  - [x] 13.4 Convert `options/tests/test_price_calc.py`
    - Replace `setUp` (constants + `sample_data`) with a pytest fixture; translate `assertIsInstance`/`assertFalse`/`assertIn`/`assertGreater`/`assertLess`/`assertAlmostEqual` per the map; remove `__main__`/`unittest.main()` (import fix already applied in 12.1)
    - _Requirements: 11.1, 11.5, 11.6, 11.7, 11.8, 11.9, 11.11_

  - [x]* 13.5 Static check for zero remaining unittest usage
    - Verify zero `test_*.py` modules `import unittest` and zero call `unittest.main()`
    - _Requirements: 11.9_

- [x] 14. Full-suite, coverage, and clean-install verification
  - [x] 14.1 Run the full suite from the repository root
    - Run `pytest` from the repo root; assert zero test failures and zero collection errors; confirm previously passing tests still pass
    - _Requirements: 8.3, 9.1, 9.2, 11.11_

  - [x] 14.2 Measure post-change coverage vs baseline
    - Run `pytest --cov=vpa/app_runner --cov-report=term-missing` from the repo root; record the post-change line-coverage of `vpa/app_runner.py` to one decimal place
    - Assert the post-change value is strictly greater than the recorded baseline from task 2
    - If the coverage command cannot produce the metric, report the failure and record no value
    - _Requirements: 10.3, 10.4, 10.5_

- [x] 15. Final checkpoint - ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks (property tests and the static unittest-usage check) and can be skipped for a faster MVP.
- The code under test (`detect_signals` and its collaborators) MUST NOT be modified — every task produces test artifacts, tooling config, dependency, or environment fixes only.
- The environment is rebuilt from scratch first (tasks 1.1–1.6): installed versions are captured, `requirements.txt` is completed (missing deps added) and pruned (unused TensorFlow/Keras-stack deps removed), stale venv references are cleaned (the `.idea/` folder is removed wholesale via `git rm -r .idea` and added to `.gitignore` since PyCharm is no longer used, and the shell-script activation lines are repointed to `.venv`), `.venv` is recreated fresh from the corrected-and-pruned manifest, and the requirements list is verified against that clean install — all before any coverage or test work. Tasks 1.1 -> 1.2 -> 1.3 -> 1.4 -> 1.5 -> 1.6 are strictly sequential (each depends on the prior); in particular pruning (1.3) is applied to the manifest before the fresh `.venv` recreate (1.5) so the clean install already excludes the unused packages.
- The manifest ends up both complete AND minimal: task 1.2 adds every missing import, task 1.3 removes the unused TensorFlow/Keras stack, and task 1.6's fresh-install run governs the final list for both — restoring any over-pruned package (pinned) until zero `ModuleNotFoundError` remain.
- Task 1.5 is a destructive, one-time environment rebuild (it deletes and recreates `.venv`, reinstalling heavy deps like `xgboost`/`scikit-learn`).
- Baseline coverage (task 2) MUST be recorded against the freshly rebuilt `.venv` and before any new `detect_signals` test is added, so the post-change comparison in task 14.2 is meaningful.
- Each of the four correctness properties is implemented by exactly one property-based test sub-task (5.3, 7.3, 8.4, 10.2), annotated with its property number and the requirements clause it validates.
- Percentile assignment order is always spread-then-volume (the `Candle` volume setter reads spread percentiles to build the anomaly map).
- All new tests and all conversions are pytest-native: no `unittest.TestCase`, no `import unittest`, no `unittest.main()`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["1.3"] },
    { "id": 3, "tasks": ["1.4"] },
    { "id": 4, "tasks": ["1.5"] },
    { "id": 5, "tasks": ["1.6"] },
    { "id": 6, "tasks": ["2"] },
    { "id": 7, "tasks": ["3.1", "3.2"] },
    { "id": 8, "tasks": ["5.1", "5.2", "6.1", "6.2", "7.1", "7.2", "8.1", "8.2", "8.3", "9.1", "9.2", "9.3", "10.1", "12.1", "12.2", "13.1", "13.2", "13.3", "13.4"] },
    { "id": 9, "tasks": ["5.3", "7.3", "8.4", "10.2", "13.5"] },
    { "id": 10, "tasks": ["14.1"] },
    { "id": 11, "tasks": ["14.2"] }
  ]
}
```
