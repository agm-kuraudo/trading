<!-- Generated with GitHub Copilot in VS Code; prepared for review and handoff to Kiro. -->

# Implementation Plan: Structured Daily Reports

## Overview

Implement the SP-500 structured reporting workflow with shared typed data, CSV and HTML renderers, configurable filesystem output, retained plain-text output, and focused regression coverage.

## Tasks

- [x] 0. Establish branch isolation
  - [x] 0.1 Create and verify feature branch `SP-310-structured-daily-reports` from the current `master`.
  - [x] 0.2 Confirm implementation changes are made only on the feature branch and unrelated worktree changes remain excluded.
  - _Requirements: 4.5_

- [x] 1. Define the report contract
  - [x] 1.1 Add typed models for per-ticker results and a daily report run.
  - [x] 1.2 Define stable CSV columns, HTML sections, status values, opportunity states, and filename conventions.
  - [x] 1.3 Define deterministic ordering and explicit missing/error-value behavior.
  - _Requirements: 1.1-1.5, 2.2-2.4, 3.2-3.5, 5.1-5.4_

- [x] 2. Extract the scan workflow
  - [x] 2.1 Refactor `vpa/app_all_shares.py` so importing it does not execute a full scan.
  - [x] 2.2 Extract ticker loading and per-ticker analysis into callable functions with injectable dependencies.
  - [x] 2.3 Preserve existing signal and opportunity calculations.
  - [x] 2.4 Convert per-ticker exceptions into failed structured results without aborting the scan.
  - [x] 2.5 Retain the current script/CLI entry point through `main()`.
  - _Requirements: 1.1-1.5, 4.4-4.5, 5.2-5.5_

- [x] 3. Implement CSV rendering and writing
  - [x] 3.1 Add a pure CSV renderer with the agreed stable header and field serialization.
  - [x] 3.2 Add date-stamped CSV path generation and configurable output-directory support.
  - [x] 3.3 Write UTF-8 CSV files with explicit newline handling and reliable resource cleanup.
  - [x] 3.4 Preserve empty numeric fields and failure messages without fabricating values.
  - _Requirements: 2.1-2.6, 4.1-4.3, 4.6_

- [x] 4. Implement HTML rendering and writing
  - [x] 4.1 Add a pure self-contained HTML renderer using the shared report model.
  - [x] 4.2 Render metadata, counts, top/bottom recommendations, opportunities, and failures.
  - [x] 4.3 Escape all dynamic ticker, error, and report values.
  - [x] 4.4 Render explicit empty, disabled-filter, and partial-failure states.
  - [x] 4.5 Add date-stamped HTML path generation and UTF-8 writing.
  - _Requirements: 3.1-3.6, 4.1-4.3, 5.6_

- [x] 5. Preserve and integrate plain-text output
  - [x] 5.1 Reuse the shared report model to produce the existing plain-text sections.
  - [x] 5.2 Preserve the current filename and debugging information where compatible.
  - [x] 5.3 Ensure CSV, HTML, and text are generated from one scan result.
  - _Requirements: 1.5, 4.4, 6.5_

- [x] 6. Add focused tests
  - [x] 6.1 Test model construction, status distinctions, deterministic ordering, and counts.
  - [x] 6.2 Test CSV headers, serialization, missing values, failures, encoding, and filenames.
  - [x] 6.3 Test HTML sections, escaping, empty states, disabled filters, and failures.
  - [x] 6.4 Test scan orchestration with mocked analyzers and injected ticker failures.
  - [x] 6.5 Test output-directory configuration and directory creation using temporary paths.
  - [x] 6.6 Test import safety and the retained script entry point.
  - _Requirements: 5.1-5.6, 6.1-6.5_

- [ ] 7. Documentation and quality checks
  - [x] 7.1 Update `README.md` with CSV/HTML output names, output-directory configuration, and report contents.
  - [x] 7.2 Run focused report and opportunity tests.
  - [x] 7.3 Run Ruff format and lint on changed Python files.
  - [ ] 7.4 Run the full pytest suite.
  - [x] 7.5 Perform a real end-to-end run using a limited ticker set or dry-run mode and inspect the generated CSV, HTML, and plain-text outputs.
  - [x] 7.6 Verify the three real outputs agree on report date, ticker results, ordering, counts, and failure visibility; preserve the sample output outside version control if needed.
  - [ ] 7.7 Add a completion comment to Jira `SP-310` summarizing implementation, verification, real-run output paths/results, and PR readiness.
  - [ ] 7.8 Transition Jira to Mostly Done only after verification and PR readiness; do not transition to Done without explicit user confirmation.
  - _Requirements: 4.1-4.6, 6.6_

## Notes

- Both CSV and HTML are required; plain text remains for compatibility.
- Do not conflate this work with SP-333 backtest reporting.
- Do not add network calls to tests.
- Review whether the existing configuration loader from SP-308 should supply the output directory setting or whether a narrowly scoped report setting is preferable.
