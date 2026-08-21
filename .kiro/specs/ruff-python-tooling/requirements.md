# Requirements Document

## Introduction

Add Ruff as the standard Python linter and formatter across both Python projects in the workspace (bf_trader_py and trading). Ruff provides an equivalent experience to Biome for JS/TS — a single fast tool that handles both linting and formatting. The configuration should be consistent across projects, live in `pyproject.toml`, and work on both Windows and Linux (x64 and ARM). An initial formatting pass must bring existing code into compliance so that all projects start from a clean baseline.

## Glossary

- **Ruff**: A fast Python linter and formatter written in Rust, configured via `pyproject.toml`
- **Project**: One of the two Python codebases: bf_trader_py or trading
- **Configuration_File**: The `pyproject.toml` file at the root of each Project containing Ruff settings
- **Lint_Check**: The command `ruff check .` which analyses Python source files for code quality issues
- **Format_Check**: The command `ruff format --check .` which verifies files match the configured style
- **CI_Pipeline**: The GitHub Actions workflow that runs automated checks on push and pull request events
- **Virtual_Environment**: The project-local `.venv` directory containing installed Python packages

## Requirements

### Requirement 1: Ruff Configuration File

**User Story:** As a developer, I want a `pyproject.toml` with Ruff configuration at the root of each Python project, so that linting and formatting rules are defined consistently and checked in to version control.

#### Acceptance Criteria

1. THE Configuration_File named `pyproject.toml` SHALL exist at the root directory of each Project
2. THE Configuration_File SHALL contain a `[tool.ruff]` section with line-length set to 120
3. THE Configuration_File SHALL contain a `[tool.ruff.format]` section with quote-style set to double
4. THE Configuration_File SHALL contain a `[tool.ruff.lint]` section with a `select` key that enables the rule sets: E (pycodestyle errors), F (Pyflakes), I (isort), UP (pyupgrade), and B (flake8-bugbear)
5. WHEN a Project already contains dependency metadata (a `requirements.txt` file or a `[project.dependencies]` section in `pyproject.toml`), THE Configuration_File SHALL preserve that existing metadata and only add or update `[tool.ruff]` related sections
6. THE Configuration_File SHALL contain an `exclude` key within `[tool.ruff]` that excludes `.venv`, `__pycache__`, `.git`, and `.hypothesis` directories
7. THE Configuration_File SHALL contain a `target-version` key within `[tool.ruff]` set to `"py311"`

### Requirement 2: Consistent Configuration Across Projects

**User Story:** As a developer, I want the same Ruff rules applied across all Python projects, so that code style and quality are uniform regardless of which project I am working in.

#### Acceptance Criteria

1. THE Configuration_File in each Project SHALL use identical values for line-length, quote-style, lint rule selection, target-version, and excluded directories, where line-length is a single numeric value consistent across all projects, quote-style is one of "single" or "double" consistent across all projects, target-version is a single Python version string consistent across all projects, and lint rule selection is an identical set of enabled and disabled rule codes across all projects
2. IF a Project contains project-specific paths that require exclusion (e.g. build artifacts, data directories), THEN THE Configuration_File SHALL include those paths in the exclude list in addition to the common exclusions shared by all projects
3. THE Configuration_File SHALL use an isort configuration that sets `known-first-party` to the top-level importable package name or names defined within that Project
4. WHEN any shared configuration value (line-length, quote-style, lint rule selection, target-version, or common exclusions) differs between any two Project Configuration_Files, THE Configuration_File SHALL be considered non-conformant

### Requirement 3: Initial Format Pass

**User Story:** As a developer, I want all existing Python source files formatted by Ruff on initial setup, so that the codebase starts from a clean baseline and future diffs only contain meaningful changes.

#### Acceptance Criteria

1. WHEN Ruff is configured for a Project, THE Developer SHALL run `ruff format .` before running `ruff check . --fix`, so that formatting is applied first and lint fixes operate on consistently formatted code
2. WHEN Ruff is configured for a Project, THE Developer SHALL run `ruff check . --fix` to auto-fix all safe lint violations in that Project
3. AFTER the initial format pass (both `ruff format .` and `ruff check . --fix` have completed), THE command `ruff check .` SHALL exit with code 0 and produce no error output on each Project
4. AFTER the initial format pass, THE command `ruff format --check .` SHALL exit with code 0 and produce no output indicating differences on each Project
5. THE initial format pass SHALL be committed as a single dedicated commit per Project with the message format `SP-323: apply Ruff formatting to <project-name>`

### Requirement 4: CI Integration

**User Story:** As a developer, I want Ruff checks to run automatically in CI, so that formatting and lint regressions are caught before code is merged.

#### Acceptance Criteria

1. WHEN a push to the main branch or a pull request targeting the main branch occurs on either Project repository (bf_trader_py or trading), THE CI_Pipeline SHALL run `ruff check .` and `ruff format --check .`
2. IF the Lint_Check or Format_Check fails, THEN THE CI_Pipeline SHALL report a non-zero exit code and fail the workflow
3. THE CI_Pipeline SHALL install Ruff using a pinned version (e.g. `ruff==0.8.x`) to ensure reproducible builds
4. THE CI_Pipeline Ruff checks SHALL complete within 2 minutes of execution start
5. WHEN the trading Project does not have an existing `.github/workflows` directory, THE CI_Pipeline setup SHALL create the directory and workflow file
6. THE CI_Pipeline SHALL use the same Configuration_File (`pyproject.toml`) as the local development environment to prevent configuration drift between CI and local checks

### Requirement 5: Platform Compatibility

**User Story:** As a developer, I want Ruff to work on both Windows and Linux across x64 and ARM architectures, so that I can develop and run checks on any of my machines.

#### Acceptance Criteria

1. THE Configuration_File SHALL use forward-slash path separators in all exclude patterns to ensure cross-platform compatibility
2. THE Ruff installation via `pip install ruff` SHALL succeed on Windows x64, Linux x64, and Linux ARM64 platforms without additional configuration or compilation steps
3. WHEN Ruff is installed via pip into a Virtual_Environment on any supported platform, THE commands `ruff check .` and `ruff format --check .` SHALL produce identical results given the same source files and Configuration_File
4. THE Configuration_File SHALL NOT contain any platform-specific settings or conditional logic

### Requirement 6: Developer Workflow Integration

**User Story:** As a developer, I want to run Ruff locally from my virtual environment, so that I can check and fix issues before pushing code.

#### Acceptance Criteria

1. THE Ruff package SHALL be listed as a development dependency with a pinned version in each Project's dependency file (requirements.txt or pyproject.toml dev dependencies)
2. WHEN a developer runs `ruff check .` from the Project root, THE Lint_Check SHALL use the configuration from the local Configuration_File and exit with code 0 if no violations are found or a non-zero code if violations exist
3. WHEN a developer runs `ruff format .` from the Project root, THE formatter SHALL use the configuration from the local Configuration_File and modify files in-place to match the configured style
4. WHEN a developer runs `ruff check . --fix`, THE Lint_Check SHALL auto-fix all safe fixes without modifying unsafe fixes
5. IF no Configuration_File exists in the Project root or any parent directory, THEN Ruff SHALL use its built-in defaults and report a warning to the developer
