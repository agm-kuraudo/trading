<!-- Generated with GitHub Copilot in VS Code; prepared for review and handoff to Kiro. -->

# Requirements Document

## Introduction

SP-310 replaces the SP-500 scan's plain-text-only report with structured CSV and HTML reports while retaining the existing plain-text output for debugging and backward compatibility. Both formats must be generated from the same deterministic scan result so the historical record and human-readable report cannot diverge.

## Glossary

- **SP-500 Scan**: The all-shares workflow currently orchestrated by `vpa/app_all_shares.py`.
- **Scan Result**: The complete structured output of one ticker evaluation, including success, signal data, opportunity data, or failure information.
- **Report Run**: One execution of the SP-500 scan for a single report date.
- **Output Directory**: Configurable filesystem directory where date-stamped reports are written.
- **CSV Report**: Machine-readable report containing one row per scanned ticker.
- **HTML Report**: Human-readable report summarizing scan metadata, ranked signals, opportunities, and failures.
- **Plain-Text Report**: Existing `share_output_YYYYMMDD.txt` output retained for diagnostics and compatibility.

## Requirements

### Requirement 1: Complete Structured Scan Results

**User Story:** As a user, I want every ticker's scan outcome represented in the report so that failures and incomplete scans are visible.

#### Acceptance Criteria

1. The scan SHALL produce one structured result for every ticker attempted, whether analysis succeeds, produces no opportunity, or fails.
2. A successful result SHALL include the source ticker symbol, normalized report ticker, signal score, signal components, and opportunity fields when available.
3. A failed result SHALL include the source ticker symbol, failure status, and a safe human-readable error message.
4. The report data SHALL distinguish a ticker that was successfully evaluated but did not qualify from a ticker that was skipped because of an error.
5. The structured result model SHALL be independent of CSV and HTML rendering so both outputs use identical data.

### Requirement 2: CSV Report

**User Story:** As a researcher, I want a stable CSV record that can be filtered, compared, and retained over time.

#### Acceptance Criteria

1. Each report run SHALL write a date-stamped CSV file to the configured Output Directory.
2. The CSV SHALL contain one row per attempted ticker and stable columns for report date, source ticker, report ticker, status, signal score, signal components, opportunity status, drawdown percentage, momentum percentage, 52-week high, and error message.
3. CSV rows SHALL be ordered deterministically by descending signal score for successful results, followed by failed results ordered by ticker.
4. Missing numeric values SHALL use an explicit empty CSV field rather than a fabricated zero.
5. The CSV SHALL be encoded as UTF-8 with a header row and consistent newline handling.
6. Historical CSV files SHALL not be overwritten by later report dates.

### Requirement 3: HTML Report

**User Story:** As a trader, I want a readable daily report that can be shared through OneDrive.

#### Acceptance Criteria

1. Each report run SHALL write a date-stamped HTML file to the configured Output Directory.
2. The HTML SHALL display report date, scan totals, successful/failed counts, top recommendations, bottom recommendations, opportunity results, and failed tickers.
3. HTML content SHALL be generated from the same structured results used by the CSV renderer.
4. Ticker names, errors, and other dynamic values SHALL be HTML-escaped before rendering.
5. Empty result sets and disabled opportunity filters SHALL render an explicit explanatory section rather than an empty or broken table.
6. The HTML SHALL be self-contained and render without external network dependencies.

### Requirement 4: Output Configuration and Compatibility

**User Story:** As an operator, I want reports written to a configurable synchronized folder without breaking existing scheduled runs.

#### Acceptance Criteria

1. The report Output Directory SHALL be configurable, with the current `vpa/log/` location retained as the default.
2. The writer SHALL create the Output Directory when it does not exist.
3. Filenames SHALL include the report date and use stable names for CSV, HTML, and existing plain-text output.
4. The existing plain-text report SHALL continue to be produced for debugging and backward compatibility.
5. The scan SHALL remain runnable through its current entry point and SHALL not execute the scan merely because a report helper module is imported.
6. File writes SHALL use explicit UTF-8 encoding and close resources reliably, including when a write fails.

### Requirement 5: Determinism and Error Handling

**User Story:** As a maintainer, I want repeatable reports and visible partial failures so that scheduled runs are trustworthy.

#### Acceptance Criteria

1. Given the same input results and report date, CSV and HTML output ordering SHALL be deterministic.
2. A single ticker failure SHALL not abort the complete SP-500 scan.
3. Report generation SHALL complete with the successful results and recorded failures when some tickers fail.
4. The report SHALL expose the total attempted, successful, failed, and opportunity counts.
5. Report generation errors SHALL be surfaced to the caller and retained in plain-text diagnostics where possible.
6. Dynamic report values SHALL not be able to inject executable HTML or alter the report structure.

### Requirement 6: Testing and Documentation

**User Story:** As a developer, I want focused report tests so future changes do not break scheduled output or historical tracking.

#### Acceptance Criteria

1. Tests SHALL verify the structured result model and deterministic ordering.
2. Tests SHALL verify CSV headers, row contents, missing-value handling, encoding, and date-stamped filenames.
3. Tests SHALL verify HTML sections, escaping, empty states, disabled-filter output, and failure visibility.
4. Tests SHALL verify configurable output directories and directory creation using temporary paths.
5. Tests SHALL verify the existing plain-text output remains available.
6. The README SHALL document the new report formats and output configuration when the public workflow changes.
