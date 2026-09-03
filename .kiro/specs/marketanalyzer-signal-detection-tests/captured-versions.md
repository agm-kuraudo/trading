# Captured Dependency Versions (Task 1.1)

Spec: `marketanalyzer-signal-detection-tests` (SP-307)

This is a durable record of the exact dependency versions installed in the
**existing** `.venv` (interpreter: `d:\projects\trading\.venv\Scripts\python.exe`,
Python 3.12.0), captured **before** `.venv` is deleted and recreated in task 1.5.
Task 1.2 uses these versions to pin the packages in `requirements.txt`.

Captured via `python -m pip show <pkg>` against the existing `.venv`.

## Required test/runtime packages (currently absent from requirements.txt)

| Package     | Installed version | In requirements.txt before 1.2? |
|-------------|-------------------|---------------------------------|
| pytest      | 9.1.1             | No                              |
| hypothesis  | 6.165.10          | No                              |
| xgboost     | 3.4.1             | No                              |
| pytest-cov  | 7.1.0             | No                              |
| coverage    | 7.16.0            | No                              |

Notes:
- `pytest-cov` and `coverage` were **already installed** in the existing `.venv`,
  so no install step was needed to capture their versions (nothing was fabricated).
- The `pytest`, `hypothesis`, and `xgboost` versions match the values named in the
  design/tasks docs (pytest==9.1.1, hypothesis==6.165.10, xgboost==3.4.1).
- Per Requirements 10.1 and 12.4, `pytest-cov` and `coverage` must be pinned to
  these same versions in requirements.txt (no contradiction).

## Other third-party imports cross-checked against requirements.txt

An import grep across the trading project (excluding `.venv`) found these
third-party top-level imports. All except the five above are already pinned in
`requirements.txt`, so no additional additions are required for task 1.2:

| Import name | requirements.txt entry | Present before 1.2? |
|-------------|------------------------|---------------------|
| matplotlib  | matplotlib==3.9.2      | Yes                 |
| mplfinance  | mplfinance~=0.12.10b0  | Yes                 |
| numpy       | numpy==2.0.2           | Yes                 |
| pandas      | pandas==2.2.3          | Yes                 |
| requests    | requests==2.32.3       | Yes                 |
| scipy       | scipy==1.15.1          | Yes                 |
| selenium    | selenium~=4.34.0       | Yes                 |
| sklearn     | scikit-learn==1.6.1    | Yes                 |
| yfinance    | yfinance==0.2.58       | Yes                 |

Local/first-party modules (not dependencies): `vpa`, `utils`, `options_payoffs`,
`price_calc`. Standard-library modules were excluded.

**Conclusion:** The only third-party libraries imported by the trading project
that are absent from `requirements.txt` are `pytest`, `hypothesis`, and `xgboost`.
`pytest-cov` and `coverage` are tooling (not directly imported) but are required
for coverage reporting and are captured above for pinning in task 1.2.

---

# Baseline Coverage of `vpa/app_runner.py` (Task 2)

Spec: `marketanalyzer-signal-detection-tests` (SP-307)

Durable record of the **baseline** line-coverage of `vpa/app_runner.py`, measured
against the freshly rebuilt `.venv` (from task 1.5) and the EXISTING test suite,
**before** any new `detect_signals` tests are added. This value is the comparison
point for task 14.2, which must show strictly higher coverage after the new tests.

## Baseline line-coverage metric

| File                | Statements | Missed | Baseline line coverage (1 dp) |
|---------------------|-----------:|-------:|-------------------------------|
| `vpa/app_runner.py` | 395        | 68     | **82.8%**                     |

- The default `term-missing` report rounds to a whole number and displayed `83%`.
  Re-reporting the same coverage data at 1-decimal precision
  (`coverage report --precision=1`) gives the precise **82.8%** recorded here
  ((395 - 68) / 395 = 82.7848%).

## Exact command used

Run from the repository root (`d:\projects\trading`), using the freshly rebuilt
`.venv`:

```
.\.venv\Scripts\python.exe -m pytest --cov=vpa.app_runner --cov-report=term-missing --ignore=options/tests/test_price_calc.py --continue-on-collection-errors
```

Precise 1-decimal figure obtained from the same coverage data via:

```
.\.venv\Scripts\python.exe -m coverage report --precision=1 --include="*app_runner.py"
```

Notes on the command:
- The task text names `--cov=vpa/app_runner`. With the slash/path form coverage
  reported "Module vpa/app_runner was never imported / No data was collected", so
  the equivalent dotted-module form `--cov=vpa.app_runner` was used to target the
  same file (`vpa/app_runner.py`). This measures exactly the intended module.

## Files excluded for the baseline

- `options/tests/test_price_calc.py` is **excluded** (`--ignore=...`) because it
  has a known collection error (bare `from price_calc import ...`). This import is
  fixed in task 12.1. After task 12.1, this file will be **included** in the
  post-change measurement (task 14.2). Its exclusion does not affect the
  `vpa/app_runner.py` coverage number, since it exercises the options code path,
  not `app_runner`.

## Run metadata

- Date: 2026 (recorded at task-2 execution time)
- Suite result: 287 passed, 0 failures, 0 collection errors (with the one file ignored)
- Interpreter: `d:\projects\trading\.venv\Scripts\python.exe` (Python 3.12.0)
- coverage 7.16.0, pytest-cov 7.1.0, pytest 9.1.1
