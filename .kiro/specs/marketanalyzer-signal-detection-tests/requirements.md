# Requirements Document

## Introduction

This feature covers work for Jira ticket **SP-307 "Improve test coverage for MarketAnalyzer signal detection"** in the trading project. It has five goals:

**Goal 1 — Regression tests for `MarketAnalyzer.detect_signals()`.** The `detect_signals()` method (in `vpa/app_runner.py`) contains complex multi-factor scoring logic across four signal categories (single-candle, trend, multiple-bar, accumulation/distribution) and currently has no direct regression tests. This goal adds deterministic unit tests using fixed data so the scoring logic can be safely refactored in future without silent behavioral drift.

**Goal 2 — Correct pytest default discovery.** Running `pytest` from the repository root currently collects 287 tests but fails with one collection error caused by `options/tests/test_price_calc.py` performing a bare `from price_calc import ...`. That import only resolves when the current working directory is inside `options/`. The functions it needs actually live in `utils/utils.py` (the sibling test `options/tests/test_implied_volatility.py` already imports them correctly from there). This goal fixes the broken import and adds pytest configuration so every `test_*.py` file is discoverable from the repository root.

**Goal 3 — Standardize test style to pytest-native.** The trading test suite is a mix of styles. Roughly twenty test files are already pytest-native (plain test functions with `hypothesis`-based property tests and bare `assert` statements), while four files still use `unittest.TestCase`: `vpa/tests/test_alpha.py`, `vpa/tests/test_execution.py`, `options/tests/test_implied_volatility.py`, and `options/tests/test_price_calc.py`. This mix is currently valid because pytest collects `unittest.TestCase` classes natively. This goal converts all four `unittest.TestCase` files to pytest-native style so the suite follows a single convention, and requires the new `detect_signals` tests to be authored pytest-native from the start.

**Goal 4 — Complete and correct `requirements.txt` test and runtime dependencies.** The `requirements.txt` file does not currently list several third-party libraries the project depends on: `pytest` (the test runner), `hypothesis` (imported by roughly fifteen test files), `xgboost` (imported by both the test suite and by production code in `vpa/ml_validation/analysis.py` and `vpa/ml_validation/walk_forward.py`), and `pytest-cov`/`coverage` (needed for the coverage reporting in Goal 1 / Requirement 10). `scikit-learn` is already listed. This goal makes `requirements.txt` complete so a fresh install into a clean environment can collect and run the full test suite.

**Goal 5 — Prune unused dependencies from `requirements.txt`.** The `requirements.txt` file currently pins a large TensorFlow/Keras machine-learning stack (`tensorflow` itself is not listed, but its transitive dependencies are: `absl-py`, `astunparse`, `flatbuffers`, `gast`, `google-pasta`, `grpcio`, `h5py`, `libclang`, `ml-dtypes`, `namex`, `opt_einsum`, `optree`, `protobuf`, `termcolor`, `wrapt`, `Werkzeug`, `Markdown`, and similar). A repository-wide search confirms that `tensorflow` and `keras` are imported nowhere under `d:\projects\trading`; they are used only by the separate MLL project (`d:\projects\MLL`), so those packages and their exclusive transitive dependencies are leftovers here. By contrast, `xgboost` and `scikit-learn` are genuinely imported by the trading project (`vpa/ml_validation/analysis.py`, `vpa/ml_validation/walk_forward.py`, and the ML-validation tests) and must be retained. This goal makes `requirements.txt` minimal — listing only packages the trading project imports directly or that are genuine transitive dependencies of a retained package — so the manifest reflects what the trading project actually uses. Goal 4 adds what is missing; Goal 5 removes what is unused; together `requirements.txt` becomes both complete and minimal.

The five goals are independent but share the outcome of a clean, fully-collecting, single-convention test suite that reports coverage and installs reproducibly from a complete and minimal manifest.

## Glossary

- **MarketAnalyzer**: The class in `vpa/app_runner.py` whose `detect_signals()` method is under test. Constructed via `MarketAnalyzer(config_path, ticker_symbol=None, log_level="INFO", fixed_df=None, log_prefix="debug_log")`. When `fixed_df` is provided, network data loading is skipped.
- **detect_signals**: The `MarketAnalyzer.detect_signals(this_candle)` method. Returns a dictionary with keys `single_candle_signals`, `single_candle_signal_score`, `trend_signals`, `trend_signal_score`, `multiple_bar_signals`, `multiple_bar_signal_score`, `acc_dist_signals`, `acc_dist_signal_score`.
- **Signal_Category**: One of the four scoring groups produced by `detect_signals`: single-candle, trend, multiple-bar, accumulation/distribution.
- **Candle**: The `Candle(time, volume, open, high, low, close)` class in `vpa/app.py` with settable `spread_percentiles`/`volume_percentiles` dictionaries and `up_bar`/`shooting_star`/`hammer`/`is_candle_pattern` properties.
- **Deterministic_Data**: Test input drawn from the existing `vpa/data/spy_data.csv` file or from synthetic fixed values, chosen so test outcomes do not depend on network access, wall-clock time, or randomness.
- **Threshold**: A numeric boundary from `vpa/config/config.json` `trading_parameters` (for example `High_Spread_Threshold` 55, `High_Volume_Threshold` 55, `Anomaly_Threshold` 20, `Signal_Bar_Count`) or an inline literal in `detect_signals` (for example the spread/volume percentile boundary of 70, and the accumulation/distribution boundaries of 65, 50, 40, 60).
- **Edge_Condition**: An input positioned exactly at, just below, or just above a Threshold, used to verify boundary behavior of the scoring logic.
- **Baseline_Coverage**: The measured code coverage of the test suite recorded before the new `detect_signals` tests are added.
- **Test_Suite**: The complete collection of `test_*.py` files across the repository, run via `pytest` from the repository root.
- **Collection_Error**: A pytest failure that occurs while importing a test module, before any test in that module runs.
- **Pytest_Configuration**: The `[tool.pytest.ini_options]` section in `pyproject.toml` (and/or a `conftest.py`) that defines discovery settings such as `testpaths` and root directory.
- **Coverage_Tooling**: The `pytest-cov` and `coverage` packages required to produce a coverage report. Neither is currently installed in `.venv`.
- **Pytest_Native_Style**: A test authoring convention using plain module-level test functions, or test classes that do NOT subclass `unittest.TestCase`, together with bare Python `assert` statements, `pytest` fixtures for setup and teardown in place of `setUp`/`tearDown`, and no `import unittest` and no `unittest.main()` block.
- **Unittest_Style_File**: A `test_*.py` module that defines one or more classes subclassing `unittest.TestCase`. As of this ticket the Unittest_Style_Files are `vpa/tests/test_alpha.py`, `vpa/tests/test_execution.py`, `options/tests/test_implied_volatility.py`, and `options/tests/test_price_calc.py`.
- **Assertion_Translation**: The mapping from `unittest.TestCase` assertion methods to equivalent pytest-native assertions: `assertEqual(a, b)` to `assert a == b`; `assertAlmostEqual(a, b)` to `assert a == pytest.approx(b)`; `assertIn(a, b)` to `assert a in b`; `assertTrue(x)` to `assert x`; `assertFalse(x)` to `assert not x`; `assertRaises(E)` to `pytest.raises(E)`; `assertIsInstance(a, T)` to `assert isinstance(a, T)`.
- **Third_Party_Dependency**: A Python library that is not part of the Python standard library and not a first-party module of this repository, imported by the Test_Suite or by the project's production code.
- **Requirements_Manifest**: The `requirements.txt` file at the repository root that pins the project's Python dependencies.
- **Clean_Environment**: A freshly created Python virtual environment containing only the packages installed from the Requirements_Manifest, with no packages carried over from `.venv` or any other pre-existing environment.
- **Trading_Project**: The Python project rooted at `d:\projects\trading`, comprising its production code and its Test_Suite, but excluding `.venv` and excluding the separate MLL project rooted at `d:\projects\MLL`.
- **Direct_Import**: An `import` or `from ... import` statement in the Trading_Project's production code or Test_Suite that names a Third_Party_Dependency (or a module of that dependency).
- **Transitive_Dependency**: A Third_Party_Dependency that no Trading_Project module imports via a Direct_Import, but that a Retained_Dependency requires in order to be installed and to function (a dependency of a dependency).
- **Retained_Dependency**: A Third_Party_Dependency that the Requirements_Manifest keeps after pruning, because the Trading_Project imports it via a Direct_Import, or because it is a Transitive_Dependency of another Retained_Dependency. `xgboost`, `scikit-learn`, `matplotlib`, `pandas`, `yfinance`, `selenium`, and `mplfinance` are Retained_Dependencies.
- **Unused_Dependency**: A Third_Party_Dependency currently listed in the Requirements_Manifest that no Trading_Project module imports via a Direct_Import and that is not a Transitive_Dependency of any Retained_Dependency.
- **TensorFlow_Stack**: The set of packages currently pinned in the Requirements_Manifest that exist there only as transitive dependencies of `tensorflow`/`keras`: `absl-py`, `astunparse`, `flatbuffers`, `gast`, `google-pasta`, `grpcio`, `h5py`, `libclang`, `ml-dtypes`, `namex`, `opt_einsum`, `optree`, `protobuf`, `termcolor`, `wrapt`, `Werkzeug`, and `Markdown`. Neither `tensorflow` nor `keras` is imported by any Trading_Project module; both are used only by the separate MLL project.
- **Fresh_Install_Verification**: The procedure of installing the packages from the Requirements_Manifest into a Clean_Environment and then collecting and running the full Test_Suite from the repository root, used to confirm that pruning removed no package the Trading_Project actually needs.

## Requirements

### Requirement 1: Single-Candle Signal Regression Tests

**User Story:** As a developer, I want deterministic tests for the single-candle scoring branch of `detect_signals`, so that I can refactor candle-level scoring without introducing silent regressions.

#### Acceptance Criteria

1. THE Test_Suite SHALL include tests that invoke `detect_signals` with Deterministic_Data and assert on the returned `single_candle_signals` list and `single_candle_signal_score` value.
2. WHEN the supplied Candle is an up bar, THE Test_Suite SHALL assert that `single_candle_signals` contains "Up Bar" and that the up-bar contribution to `single_candle_signal_score` is +1.
3. WHEN the supplied Candle is a down bar, THE Test_Suite SHALL assert that `single_candle_signals` contains "Down Bar" and that the down-bar contribution to `single_candle_signal_score` is -1.
4. WHEN the supplied Candle is an up bar whose spread percentile for a period is strictly greater than 70, THE Test_Suite SHALL assert that `single_candle_signals` contains "Wide Spread (<period>)" for that period and that the "Wide Spread" contribution to `single_candle_signal_score` is +2.5.
5. WHEN the supplied Candle is a down bar whose spread percentile for a period is strictly greater than 70, THE Test_Suite SHALL assert that `single_candle_signals` contains "Wide Spread (<period>)" for that period and that the "Wide Spread" contribution to `single_candle_signal_score` is -2.5.
6. WHEN the supplied Candle is an up bar whose spread percentile AND volume percentile for a period are both strictly greater than 70, THE Test_Suite SHALL assert that `single_candle_signals` contains "High Volume (<period>)" for that period and that the "High Volume" contribution to `single_candle_signal_score` is +2.5.
7. WHEN the supplied Candle is a down bar whose spread percentile AND volume percentile for a period are both strictly greater than 70, THE Test_Suite SHALL assert that `single_candle_signals` contains "High Volume (<period>)" for that period and that the "High Volume" contribution to `single_candle_signal_score` is -2.5.
8. IF the supplied Candle has a spread percentile for a period that is not strictly greater than 70, THEN THE Test_Suite SHALL assert that neither "Wide Spread (<period>)" nor "High Volume (<period>)" appears in `single_candle_signals` for that period.
9. WHEN the supplied Candle exhibits a shooting-star pattern, THE Test_Suite SHALL assert that `single_candle_signals` contains "Shooting Star", that "Hammer" is absent from `single_candle_signals`, and that the shooting-star contribution to `single_candle_signal_score` is -3.
10. WHEN the supplied Candle exhibits a hammer pattern, THE Test_Suite SHALL assert that `single_candle_signals` contains "Hammer", that "Shooting Star" is absent from `single_candle_signals`, and that the hammer contribution to `single_candle_signal_score` is +3.
11. WHEN `detect_signals` is invoked repeatedly with identical Deterministic_Data, THE Test_Suite SHALL assert that `single_candle_signals` and `single_candle_signal_score` are identical across every invocation.

### Requirement 2: Trend Signal Regression Tests

**User Story:** As a developer, I want deterministic tests for the trend-detection branch of `detect_signals`, so that changes to ADX-based trend scoring are caught by the Test_Suite.

#### Acceptance Criteria

1. THE Test_Suite SHALL include tests that invoke `detect_signals` with Deterministic_Data and assert on the returned `trend_signals` list and `trend_signal_score` value.
2. WHEN the `period_three` rolling window produces an ADX value (`adx_values[0]`) strictly greater than 25 with DM+ (`adx_values[2]`) strictly greater than DM- (`adx_values[3]`), THE Test_Suite SHALL assert that `trend_signals` contains "Market is trending" and "Trending Up" and that `trend_signal_score` equals +5.
3. WHEN the `period_three` rolling window produces an ADX value (`adx_values[0]`) strictly greater than 25 with DM- (`adx_values[3]`) strictly greater than DM+ (`adx_values[2]`), THE Test_Suite SHALL assert that `trend_signals` contains "Market is trending" and "Trending Down" and that `trend_signal_score` equals -5.
4. WHEN the `period_three` rolling window produces an ADX value (`adx_values[0]`) that is not strictly greater than 25, THE Test_Suite SHALL assert that `trend_signals` is empty and `trend_signal_score` equals 0.
5. IF the `period_three` rolling window contains fewer than fifteen Candles, THEN THE Test_Suite SHALL assert that invoking `detect_signals` raises a ValueError for insufficient ADX data.

### Requirement 3: Multiple-Bar Signal Regression Tests

**User Story:** As a developer, I want deterministic tests for the multiple-bar scoring branch of `detect_signals`, so that per-period bull, bear, and volume-backed scoring stays stable across changes.

#### Acceptance Criteria

1. THE Test_Suite SHALL include tests that invoke `detect_signals` with Deterministic_Data and assert on the returned `multiple_bar_signals` list and `multiple_bar_signal_score` value.
2. WHEN a period's up-bar count is greater than or equal to that period's `Signal_Bar_Count` Threshold and the period signal is not volume-backed, THE Test_Suite SHALL assert that `multiple_bar_signals` contains "Bull Signal (<period>)" for that period and that the bull contribution to `multiple_bar_signal_score` is +2.5.
3. WHEN a period's up-bar count is less than or equal to `PERIOD_ONE_LENGTH` minus that period's `Signal_Bar_Count` Threshold and the period signal is not volume-backed, THE Test_Suite SHALL assert that `multiple_bar_signals` contains "Bear Signal (<period>)" for that period and that the bear contribution to `multiple_bar_signal_score` is -2.5.
4. WHEN a period's bull condition is met and the period is volume-backed (that period's `high_spread_count` is greater than or equal to `High_Spread_Count`, its `high_volume_count` is greater than or equal to `High_Volume_Count`, and its `anomaly_count` is less than or equal to `Anomaly_Threshold`), THE Test_Suite SHALL assert that `multiple_bar_signals` contains "Bull Signal (<period>)" and "Volume Backed (<period>)" for that period and that the combined contribution to `multiple_bar_signal_score` is +5.0.
5. WHEN a period's bear condition is met and the period is volume-backed (that period's `high_spread_count` is greater than or equal to `High_Spread_Count`, its `high_volume_count` is greater than or equal to `High_Volume_Count`, and its `anomaly_count` is less than or equal to `Anomaly_Threshold`), THE Test_Suite SHALL assert that `multiple_bar_signals` contains "Bear Signal (<period>)" and "Volume Backed (<period>)" for that period and that the combined contribution to `multiple_bar_signal_score` is -5.0.
6. WHEN a period's up-bar count is above `PERIOD_ONE_LENGTH` minus that period's `Signal_Bar_Count` Threshold and below that period's `Signal_Bar_Count` Threshold, THE Test_Suite SHALL assert that neither "Bull Signal (<period>)" nor "Bear Signal (<period>)" appears for that period and that the period contributes 0 to `multiple_bar_signal_score`.
7. WHEN a period's bull or bear condition is met but at least one volume-backed sub-condition fails (that period's `high_spread_count` is below `High_Spread_Count`, or its `high_volume_count` is below `High_Volume_Count`, or its `anomaly_count` is above `Anomaly_Threshold`), THE Test_Suite SHALL assert that "Volume Backed (<period>)" is absent for that period and that the period contribution to `multiple_bar_signal_score` is the undoubled adjustment (+2.5 for bull, -2.5 for bear).

### Requirement 4: Accumulation/Distribution Signal Regression Tests

**User Story:** As a developer, I want deterministic tests for the accumulation/distribution branch of `detect_signals`, so that test-pass, test-fail, and climax scoring remain verifiable.

#### Acceptance Criteria

1. THE Test_Suite SHALL include tests that invoke `detect_signals` with Deterministic_Data and assert on the returned `acc_dist_signals` list and `acc_dist_signal_score` value.
2. WHEN `identify_acc_or_dist` reports an accumulation condition, THE Test_Suite SHALL assert that `acc_dist_signals` contains "Possible Acc" and that the accumulation contribution to `acc_dist_signal_score` is +10.
3. WHEN `identify_acc_or_dist` reports a distribution condition, THE Test_Suite SHALL assert that `acc_dist_signals` contains "Possible Dist" and that the distribution contribution to `acc_dist_signal_score` is -10.
4. IF an accumulation condition is present and either the `period_one` spread percentile is strictly greater than 65 or `is_candle_pattern()` returns True, and the `period_one` volume percentile is strictly less than 50, THEN THE Test_Suite SHALL assert that `acc_dist_signals` contains "Test Pass" and that the test-pass contribution to `acc_dist_signal_score` is +5.
5. IF a distribution condition is present and either the `period_one` spread percentile is strictly greater than 65 or `is_candle_pattern()` returns True, and the `period_one` volume percentile is strictly less than 50, THEN THE Test_Suite SHALL assert that `acc_dist_signals` contains "Test Pass" and that the test-pass contribution to `acc_dist_signal_score` is -5.
6. IF an accumulation condition is present and either the `period_one` spread percentile is strictly greater than 65 or `is_candle_pattern()` returns True, and the `period_one` volume percentile is not strictly less than 50, THEN THE Test_Suite SHALL assert that `acc_dist_signals` contains "Test Fail" and that the test-fail contribution to `acc_dist_signal_score` is -2.
7. IF a distribution condition is present and either the `period_one` spread percentile is strictly greater than 65 or `is_candle_pattern()` returns True, and the `period_one` volume percentile is not strictly less than 50, THEN THE Test_Suite SHALL assert that `acc_dist_signals` contains "Test Fail" and that the test-fail contribution to `acc_dist_signal_score` is +2.
8. IF an accumulation condition is present and the `period_two` spread percentile is strictly less than 40 and the `period_two` volume percentile is strictly greater than 60, THEN THE Test_Suite SHALL assert that `acc_dist_signals` contains "Climax" and that the climax contribution to `acc_dist_signal_score` is +10.
9. IF a distribution condition is present and the `period_two` spread percentile is strictly less than 40 and the `period_two` volume percentile is strictly greater than 60, THEN THE Test_Suite SHALL assert that `acc_dist_signals` contains "Climax" and that the climax contribution to `acc_dist_signal_score` is -10.

### Requirement 5: Threshold Edge-Condition Tests

**User Story:** As a developer, I want tests that exercise inputs positioned exactly at Threshold boundaries, so that off-by-one and boundary-comparison errors in the scoring logic are detected.

#### Definitions For This Requirement

- **One_Step**: The smallest representable increment of the input value at a Threshold. For the integer-valued percentile and bar-count inputs exercised by these tests, One_Step SHALL be 1.
- **Strict_Boundary**: A Threshold compared with a strict operator (`>` or `<`), where an input exactly equal to the Threshold does not satisfy the comparison.
- **Inclusive_Boundary**: A Threshold compared with an inclusive operator (`>=` or `<=`), where an input exactly equal to the Threshold satisfies the comparison.

#### Acceptance Criteria

1. WHEN an input value is set exactly at a Strict_Boundary used by `detect_signals`, THE Test_Suite SHALL assert that the signal governed by that Threshold is absent.
2. WHEN an input value is set exactly at an Inclusive_Boundary used by `detect_signals`, THE Test_Suite SHALL assert that the signal governed by that Threshold is present.
3. WHEN an input value is set One_Step below a Threshold, THE Test_Suite SHALL assert the signal outcome that the Threshold's comparison operator produces for a value strictly below the Threshold.
4. WHEN an input value is set One_Step above a Threshold, THE Test_Suite SHALL assert the signal outcome that the Threshold's comparison operator produces for a value strictly above the Threshold.
5. THE Test_Suite SHALL include Edge_Condition tests at, One_Step below, and One_Step above the single-candle spread/volume percentile boundary of 70 (strict `>`), asserting that the "Wide Spread"/"High Volume" signals are absent at 70 and at 69 and present at 71.
6. THE Test_Suite SHALL include Edge_Condition tests at, One_Step below, and One_Step above the `Signal_Bar_Count` boundary (inclusive `>=` for the bull condition), asserting that the "Bull Signal" entry is present when the up-bar count equals `Signal_Bar_Count`, present when it is one above, and absent when it is one below.
7. THE Test_Suite SHALL include Edge_Condition tests at, One_Step below, and One_Step above the accumulation/distribution test-pass boundaries: the `period_one` spread percentile test-candidate boundary of 65 (strict `>`) and the `period_one` volume percentile test-pass boundary of 50 (strict `<`), asserting the "Test Pass" and "Test Fail" outcomes that each strict comparison produces at, below, and above the boundary.

### Requirement 6: Deterministic Test Construction

**User Story:** As a developer, I want the `detect_signals` tests to be fully deterministic, so that they produce identical results on every run and in continuous integration.

#### Acceptance Criteria

1. THE Test_Suite SHALL construct each MarketAnalyzer under test with a non-null `fixed_df` argument, or SHALL populate the `period_one`, `period_two`, and `period_three` rolling windows directly, and SHALL pass `ticker_symbol=None`, so that the constructor's `load_data` network path is not reached.
2. THE Test_Suite SHALL source all test input from the existing `vpa/data/spy_data.csv` file or from synthetic fixed values defined within the tests.
3. WHEN the same detect_signals test is executed ten times in succession, THE Test_Suite SHALL produce identical signal lists and signal scores on every execution.
4. THE detect_signals tests SHALL derive every asserted outcome solely from the fixed input data and SHALL NOT depend on the wall-clock time, the current date, or unseeded random values.
5. WHERE a test constructs a MarketAnalyzer that opens a log file, THE Test_Suite SHALL direct that log file to a test-controlled directory and SHALL remove the directory and its log artifacts whether the test passes or fails.
6. IF any test execution reaches a network-backed market-data load path, THEN THE Test_Suite SHALL fail that test.
7. WHILE the detect_signals tests execute, THE Test_Suite SHALL make zero outbound market-data requests.

### Requirement 7: Fix Broken Test Import for Root-Level Discovery

**User Story:** As a developer, I want `options/tests/test_price_calc.py` to import its functions correctly, so that `pytest` run from the repository root collects the full Test_Suite without a Collection_Error.

#### Acceptance Criteria

1. THE `options/tests/test_price_calc.py` module SHALL import `calculate_binomial_parameters`, `calculate_volatility`, `get_asset_data`, `price_option`, and `process_data` from `utils.utils`.
2. WHEN `pytest` is run from the repository root, THE Test_Suite SHALL collect `options/tests/test_price_calc.py` without a Collection_Error.
3. THE fix SHALL preserve the existing test behavior of `options/tests/test_price_calc.py` so that its test cases continue to assert the same outcomes.
4. THE fix SHALL NOT trigger the network-backed yfinance pricing pipeline in `options/price_calc.py` at import time.

### Requirement 8: Repository-Root Pytest Discovery Configuration

**User Story:** As a developer, I want pytest discovery configured at the repository root, so that every `test_*.py` file is collected consistently regardless of the current working directory.

#### Acceptance Criteria

1. THE Pytest_Configuration SHALL be defined in `pyproject.toml` under `[tool.pytest.ini_options]`, and/or via a `conftest.py`, so that the repository root is the resolved pytest root directory.
2. WHEN `pytest` is run from the repository root, THE Test_Suite SHALL discover all `test_*.py` files across the repository's test directories.
3. WHEN `pytest` is run from the repository root, THE Test_Suite SHALL report zero Collection_Errors.
4. THE Pytest_Configuration SHALL exclude non-test directories already excluded by the project's tooling configuration (for example `.venv`, `__pycache__`, `.git`) from collection.

### Requirement 9: Existing Tests Continue To Pass

**User Story:** As a developer, I want all existing tests to keep passing after this work, so that the coverage improvement does not come at the cost of regressions.

#### Acceptance Criteria

1. WHEN the full Test_Suite is run from the repository root after the changes, THE Test_Suite SHALL report zero test failures and zero Collection_Errors.
2. THE changes SHALL preserve the behavior of every test that passed before the changes were made.

### Requirement 10: Coverage Reporting and Improvement

**User Story:** As a developer, I want a coverage report that shows measurable improvement, so that the value of the new `detect_signals` tests is demonstrable against the ticket's acceptance criteria.

#### Definitions For This Requirement

- **Line_Coverage_Metric**: The percentage of executable lines in `vpa/app_runner.py` executed during a `pytest` run, reported to one decimal place by the Coverage_Tooling.

#### Acceptance Criteria

1. THE `requirements.txt` file SHALL list `pytest-cov` and `coverage` with pinned versions.
2. THE developer SHALL record, to one decimal place, the Baseline_Coverage as the Line_Coverage_Metric for `vpa/app_runner.py` measured before the new detect_signals tests are added.
3. WHEN the Line_Coverage_Metric for `vpa/app_runner.py` is measured after the new detect_signals tests are added, THE measured value SHALL be strictly greater than the recorded Baseline_Coverage.
4. THE Test_Suite SHALL support producing the Line_Coverage_Metric for `vpa/app_runner.py` via a documented command that runs from the repository root.
5. IF installation of the Coverage_Tooling fails or the coverage measurement command cannot produce the Line_Coverage_Metric, THEN THE developer SHALL report the failure and SHALL NOT record a Baseline_Coverage or post-change coverage value from that failed run.

### Requirement 11: Standardize Test Style To Pytest-Native

**User Story:** As a developer, I want every test in the repository to follow a single pytest-native convention, so that the Test_Suite is consistent, has no `unittest` dependency, and is simpler to read and maintain.

#### Acceptance Criteria

1. THE Test_Suite SHALL adopt Pytest_Native_Style as the single target convention, in which each test is a plain module-level function or a method of a class that does not subclass `unittest.TestCase`, each assertion is a bare Python `assert` statement, and per-test setup is provided by a pytest fixture rather than a `setUp` method.
2. THE developer SHALL convert `vpa/tests/test_alpha.py` to Pytest_Native_Style, preserving every existing test's assertions and intent so that the same behaviors are verified after conversion.
3. THE developer SHALL convert `vpa/tests/test_execution.py` to Pytest_Native_Style, preserving every existing test's assertions and intent so that the same behaviors are verified after conversion.
4. THE developer SHALL convert `options/tests/test_implied_volatility.py` to Pytest_Native_Style, preserving every existing test's assertions and intent so that the same behaviors are verified after conversion.
5. THE developer SHALL convert `options/tests/test_price_calc.py` to Pytest_Native_Style, preserving every existing test's assertions and intent so that the same behaviors are verified after conversion.
6. WHEN a converted test contains a `unittest.TestCase` assertion method, THE developer SHALL replace that assertion with the equivalent pytest-native assertion defined by Assertion_Translation.
7. WHEN a Unittest_Style_File defines a `setUp` method, THE developer SHALL replace that setup with a pytest fixture that provides the same test state.
8. WHEN a Unittest_Style_File defines a `suite()` helper or an `if __name__ == "__main__"` block that runs `unittest.main()` or a `unittest` runner, THE developer SHALL remove that helper and that block during conversion.
9. WHEN the conversion is complete, THE Test_Suite SHALL contain zero `test_*.py` modules that execute `import unittest` and zero `test_*.py` modules that call `unittest.main()`.
10. THE new `detect_signals` tests SHALL be authored in Pytest_Native_Style from the outset and SHALL NOT introduce any `unittest.TestCase` subclass, `import unittest` statement, or `unittest.main()` call.
11. WHEN the full Test_Suite is run from the repository root after conversion, THE Test_Suite SHALL collect and pass every converted test with the same pass or fail outcome each converted test produced before conversion, consistent with Requirement 9.

### Requirement 12: Complete And Correct requirements.txt Dependencies

**User Story:** As a developer, I want `requirements.txt` to list every third-party library the tests and production code import, so that a fresh install into a clean environment can collect and run the full Test_Suite without missing-module failures.

#### Acceptance Criteria

1. THE Requirements_Manifest SHALL list every Third_Party_Dependency that the Test_Suite or the project's production code imports and that is currently absent from the Requirements_Manifest, and SHALL explicitly include `pytest`, `hypothesis`, `pytest-cov`, `coverage`, and `xgboost`.
2. THE Requirements_Manifest SHALL pin each dependency added under this requirement to an exact version, using the version-pinning style already used in the Requirements_Manifest.
3. THE pinned version of each dependency added under this requirement SHALL match the version of that dependency installed and used in the project's `.venv`; specifically the Requirements_Manifest SHALL pin `pytest` to `9.1.1`, `hypothesis` to `6.165.10`, and `xgboost` to `3.4.1`.
4. WHERE `pytest-cov` or `coverage` is not currently installed in the project's `.venv`, THE developer SHALL install that package into the project's `.venv`, SHALL pin it in the Requirements_Manifest to the installed version, and SHALL use that same pinned version to satisfy Requirement 10 criterion 1, so that Requirement 10 and Requirement 12 pin identical versions of `pytest-cov` and `coverage` with no contradiction.
5. WHEN the full dependency set is installed into a Clean_Environment from the Requirements_Manifest, THE Test_Suite SHALL be collectable and runnable from the repository root without any `ModuleNotFoundError`.
6. IF the Test_Suite or production code is found to import a Third_Party_Dependency that is absent from the Requirements_Manifest after this work, THEN THE developer SHALL add that dependency to the Requirements_Manifest with a pinned version.

### Requirement 13: Prune Unused Dependencies From requirements.txt

**User Story:** As a developer, I want `requirements.txt` to list only the packages the Trading_Project actually uses, so that the manifest is minimal, installs faster into a Clean_Environment, and no longer carries the leftover TensorFlow/Keras stack that belongs to the separate MLL project.

#### Acceptance Criteria

1. THE Requirements_Manifest SHALL list a package if and only if that package is imported by the Trading_Project via a Direct_Import OR is a Transitive_Dependency of a Retained_Dependency, where a Retained_Dependency is any package that satisfies this condition.
2. THE Requirements_Manifest SHALL NOT list `tensorflow` and SHALL NOT list `keras`, because no Trading_Project module imports either package via a Direct_Import.
3. THE Requirements_Manifest SHALL NOT list any package in the TensorFlow_Stack set { absl-py, astunparse, flatbuffers, gast, google-pasta, grpcio, h5py, libclang, ml-dtypes, namex, opt_einsum, optree, protobuf, termcolor, wrapt, Werkzeug, Markdown } that is neither imported by a Trading_Project module via a Direct_Import nor a Transitive_Dependency of a Retained_Dependency.
4. THE Requirements_Manifest SHALL retain `xgboost` and `scikit-learn`, because the Trading_Project imports `xgboost` via a Direct_Import in `vpa/ml_validation/analysis.py` and `vpa/ml_validation/walk_forward.py`, and imports `scikit-learn` via a Direct_Import in `vpa/ml_validation/walk_forward.py` and the ML-validation tests.
5. IF a package's classification is ambiguous because it could be a Transitive_Dependency of a Retained_Dependency such as `matplotlib`, `pandas`, `scikit-learn`, `xgboost`, `yfinance`, `selenium`, or `mplfinance`, THEN THE developer SHALL retain that package in the Requirements_Manifest rather than remove it on the basis of a missing Direct_Import alone.
6. WHEN the pruned Requirements_Manifest is installed into a Clean_Environment via Fresh_Install_Verification, THE Test_Suite SHALL collect and execute from the repository root with zero occurrences of ModuleNotFoundError, consistent with Requirement 12 criterion 5.
7. IF Fresh_Install_Verification produces one or more ModuleNotFoundError occurrences caused by a removed package, THEN THE developer SHALL restore each such package to the Requirements_Manifest with a pinned exact version and re-run Fresh_Install_Verification until zero ModuleNotFoundError occurrences remain, so that the Fresh_Install_Verification outcome governs the final dependency list.
8. WHEN both Requirement 12 and this requirement are complete, THE Requirements_Manifest SHALL list every package the Trading_Project imports via a Direct_Import together with the Transitive_Dependencies of the Retained_Dependencies, and SHALL list no package that is neither a Direct_Import nor a Transitive_Dependency of a Retained_Dependency, so that the manifest is simultaneously complete and minimal.
