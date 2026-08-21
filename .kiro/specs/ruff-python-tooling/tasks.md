# Implementation Plan: Ruff Python Tooling

## Overview

Configure Ruff as the standard Python linter and formatter across both bf_trader_py and trading projects. This involves creating `pyproject.toml` configuration files, adding GitHub Actions CI workflows, pinning the development dependency, and running an initial format pass to bring existing code into compliance.

## Tasks

- [x] 1. Configure Ruff for the trading project
  - [x] 1.1 Create `pyproject.toml` with Ruff configuration at `d:\projects\trading\pyproject.toml`
    - Add `[tool.ruff]` section with `line-length = 120`, `target-version = "py311"`, and `exclude` list
    - Add `[tool.ruff.format]` section with `quote-style = "double"`
    - Add `[tool.ruff.lint]` section with `select = ["E", "F", "I", "UP", "B"]`
    - Add `[tool.ruff.lint.isort]` section with `known-first-party = ["ig", "options", "utils", "vpa"]`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6, 1.7, 2.1, 2.2, 2.3_

  - [x] 1.2 Add Ruff as a pinned development dependency in `d:\projects\trading\requirements.txt`
    - Append `ruff==0.8.6` to the file
    - Preserve all existing dependency entries
    - Install into the project's local `.venv` (activate with `.venv\Scripts\activate` on Windows or `source .venv/bin/activate` on Linux, then `pip install ruff==0.8.6`). The `requirements.txt` entry ensures reproducibility, but the actual installation is local to the venv.
    - _Requirements: 6.1, 1.5_

- [x] 2. Configure Ruff for the bf_trader_py project
  - [x] 2.1 Create `pyproject.toml` with Ruff configuration at `d:\projects\bf_trader_py\pyproject.toml`
    - Add `[tool.ruff]` section with `line-length = 120`, `target-version = "py311"`, and `exclude` list (including project-specific: `build`, `certs`, `log`)
    - Add `[tool.ruff.format]` section with `quote-style = "double"`
    - Add `[tool.ruff.lint]` section with `select = ["E", "F", "I", "UP", "B"]`
    - Add `[tool.ruff.lint.isort]` section with `known-first-party = ["api", "betfair", "charts", "config", "decorators", "logic", "output", "scripts", "tests", "web"]`
    - Ensure core settings (line-length, target-version, quote-style, select) are identical to the trading project configuration
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6, 1.7, 2.1, 2.2, 2.3, 2.4_

  - [x] 2.2 Add Ruff as a pinned development dependency in `d:\projects\bf_trader_py\build\requirements.txt`
    - Append `ruff==0.8.6` to the file
    - Preserve all existing dependency entries
    - Install into the project's local `.venv` (activate with `.venv\Scripts\activate` on Windows or `source .venv/bin/activate` on Linux, then `pip install ruff==0.8.6`). The `requirements.txt` entry ensures reproducibility, but the actual installation is local to the venv.
    - _Requirements: 6.1, 1.5_

- [x] 3. Checkpoint - Verify configuration
  - Ensure both `pyproject.toml` files exist and contain correct settings.
  - Run `ruff check --show-settings` in each project root to confirm Ruff reads the correct configuration.
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Create GitHub Actions CI workflows
  - [x] 4.1 Create CI workflow for the trading project at `d:\projects\trading\.github\workflows\ruff.yml`
    - Create the `.github/workflows/` directory (does not exist yet)
    - Define workflow triggered on push to `master` and pull requests targeting `master`
    - Include steps: checkout, setup Python 3.11, install `ruff==0.8.6`, run `ruff check .`, run `ruff format --check .`
    - Set `timeout-minutes: 2`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [x] 4.2 Create CI workflow for the bf_trader_py project at `d:\projects\bf_trader_py\.github\workflows\ruff.yml`
    - Add workflow file alongside existing `qodana_code_quality.yml`
    - Define workflow triggered on push to `main` and pull requests targeting `main`
    - Include steps: checkout, setup Python 3.11, install `ruff==0.8.6`, run `ruff check .`, run `ruff format --check .`
    - Set `timeout-minutes: 2`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.6_

- [x] 5. Run initial format pass on the trading project
  - [x] 5.1 Apply Ruff formatting and lint fixes to the trading project
    - Activate the virtual environment (`.venv\Scripts\activate` on Windows or `source .venv/bin/activate` on Linux) before running Ruff commands
    - Run `ruff format .` from the project root to format all Python files
    - Run `ruff check . --fix` to auto-fix all safe lint violations
    - Verify `ruff check .` exits with code 0
    - Verify `ruff format --check .` exits with code 0
    - Commit changes with message `SP-323: apply Ruff formatting to trading`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 6.2, 6.3, 6.4_

- [x] 6. Run initial format pass on the bf_trader_py project
  - [x] 6.1 Apply Ruff formatting and lint fixes to the bf_trader_py project
    - Activate the virtual environment (`.venv\Scripts\activate` on Windows or `source .venv/bin/activate` on Linux) before running Ruff commands
    - Run `ruff format .` from the project root to format all Python files
    - Run `ruff check . --fix` to auto-fix all safe lint violations
    - Verify `ruff check .` exits with code 0
    - Verify `ruff format --check .` exits with code 0
    - Commit changes with message `SP-323: apply Ruff formatting to bf_trader_py`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 6.2, 6.3, 6.4_

- [x] 7. Final checkpoint - Verify full compliance
  - Confirm both projects pass `ruff check .` and `ruff format --check .` with exit code 0.
  - Confirm CI workflow files are syntactically valid YAML.
  - Confirm configuration uses forward-slash path separators in exclude patterns for cross-platform compatibility.
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 5.1, 5.3, 5.4_

## Notes

- No property-based tests are included — this feature is purely configuration and tooling with no testable pure functions.
- Each project is self-contained with its own `pyproject.toml` and CI workflow.
- Core settings must be identical across both projects; only `known-first-party` and project-specific exclusions may differ.
- The format pass must be run in order: `ruff format .` first, then `ruff check . --fix`.
- Ruff version 0.8.6 is pinned in both dependency files and CI to prevent drift.
- Checkpoints ensure incremental validation.
- Platform compatibility is inherent to Ruff's pip distribution (pre-built wheels for Windows x64, Linux x64, Linux ARM64).
- Ruff is installed per-project in the local `.venv` virtual environment, not globally. This keeps each project isolated and ensures the pinned version is used.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1"] },
    { "id": 1, "tasks": ["1.2", "2.2", "4.1", "4.2"] },
    { "id": 2, "tasks": ["5.1", "6.1"] }
  ]
}
```
