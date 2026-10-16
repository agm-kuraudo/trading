# Implementation Plan: Daily Market Report

## Overview

Build the in-memory orchestrator and its supporting `vpa/reports/` layer bottom-up: first the
pure, property-testable core (frozen dataclasses + JSON round-trip, the builder, the renderer,
the snapshot writer), then the two I/O-at-the-edges pieces that invoke heavy upstream code via
dependency injection (the per-asset regime wrapper and the orchestrator entrypoint), and finally
the delivery wiring (shell launcher + Rundeck job). Each step builds on the previous one and ends
with the orchestrator wiring everything together, so no module is left orphaned.

Property-based tests (hypothesis, minimum 100 iterations each) cover the seven correctness
properties from the design and sit next to the code they validate. The orchestrator and regime
wrapper are tested with injected fakes and MUST NOT touch yfinance or the network. All tests are
fast (no `slow` marker).

## Tasks

- [x] 1. Create consolidated data models and JSON serialization
  - [x] 1.1 Define the frozen dataclasses and section models
    - Create `vpa/reports/consolidated_models.py` with `RegimeSignalEntry`, `RegimeAssetEntry`
      (incl. `no_high_conviction` property), `MarketRegimeSection` (incl. `available` property),
      `VpaSignal`, `TopVpaSignalsSection`, `Opportunity`, `OpportunitiesSection`,
      `DailySummarySection`, and `ConsolidatedReport`
    - Match the existing `@dataclass(frozen=True)` style in `vpa/reports/models.py`
    - _Requirements: 3.1, 3.4, 4.1, 5.3, 6.1, 6.2, 1.2_
  - [x] 1.2 Implement `to_dict` / `from_dict` and JSON round-trip helpers
    - Add pure `to_dict(report) -> dict` and `from_dict(data) -> ConsolidatedReport` matching the
      snapshot schema (`schema_version`, `report_date` as ISO 8601, asset-keyed `market_regime`
      with `available` flag, the three other sections)
    - `report_date` written via `date.isoformat()` and parsed via `date.fromisoformat`
    - _Requirements: 7.3, 7.6_
  - [x] 1.3 Write property test for snapshot round-trip
    - **Property 1: Snapshot round-trip is identity**
    - **Validates: Requirements 7.1, 7.3, 7.6**
    - Hypothesis strategy builds arbitrary `ConsolidatedReport` values (random regime assets with
      random signal entries, random VPA signals / opportunities, arbitrary dates); assert
      `from_dict(to_dict(r)) == r` and `from_dict(json.loads(json.dumps(to_dict(r)))) == r`
    - Minimum 100 iterations; tag `# Feature: daily-market-report, Property 1: ...`

- [x] 2. Implement the pure consolidated builder
  - [x] 2.1 Implement `build_consolidated_report`
    - Create `vpa/reports/consolidated_builder.py` with
      `build_consolidated_report(report_date, scan_result, regime_result)` producing exactly one
      `ConsolidatedReport` with all four sections in fixed order (Market Regime, Top VPA Signals,
      Opportunities, Daily Summary) and no others
    - Top VPA Signals: take at most first 5 of `scan_result.successful_results` (already ordered);
      `None`/empty -> empty section placeholder
    - Opportunities: list every ticker from `scan_result.opportunities` with drawdown and momentum
      (already ordered); `None`/empty -> empty section placeholder
    - Market Regime: one `RegimeAssetEntry` per configured asset from the `RegimeAssetResult`
      tuple (present records High-first, empty -> no-high-conviction, missing -> unavailable)
    - Daily Summary: opportunity count, VPA signal count, and the primary asset's
      highest-confidence direction/confidence (or no-high-conviction)
    - Pure, no I/O
    - _Requirements: 1.1, 1.2, 2.2, 2.5, 2.6, 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.3, 6.1, 6.2, 6.3, 6.4, 8.1, 8.2, 8.3_
  - [x] 2.2 Write property test for Top VPA Signals ordering and cap
    - **Property 2: Top VPA Signals ordering and cap**
    - **Validates: Requirements 4.1, 4.2, 4.3**
    - Generate random `DailyReport`s; assert section length <= 5, score descending with
      alphabetical tie-break, and every listed score >= every omitted score
    - Minimum 100 iterations; tag `# Feature: daily-market-report, Property 2: ...`
  - [x] 2.3 Write property test for Opportunities ordering
    - **Property 3: Opportunities ordering is deterministic and total**
    - **Validates: Requirements 2.2, 5.1, 5.3**
    - Generate random `DailyReport`s with rows permuted; assert same membership as
      `.opportunities`, stable deterministic order under permutation, each carrying drawdown and
      momentum
    - Minimum 100 iterations; tag `# Feature: daily-market-report, Property 3: ...`
  - [x] 2.4 Write property test for the four-sections invariant
    - **Property 4: Report always has the four sections in order**
    - **Validates: Requirements 1.1, 1.2, 8.1, 8.2**
    - Generate scan result as present/missing/empty and regime assets as present/empty/missing;
      assert the four sections always exist in order and the builder always returns a report
    - Minimum 100 iterations; tag `# Feature: daily-market-report, Property 4: ...`
  - [x] 2.5 Write property test for Daily Summary consistency
    - **Property 5: Daily Summary is consistent with the rendered sections**
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4**
    - Assert summary counts equal section lengths, primary-asset direction/confidence equal that
      asset's highest-confidence record (or the no-high-conviction indication), and zero counts
      for unavailable sections
    - Minimum 100 iterations; tag `# Feature: daily-market-report, Property 5: ...`
  - [x] 2.6 Write property test for graceful degradation
    - **Property 6: Graceful degradation never fails and never fabricates**
    - **Validates: Requirements 2.5, 3.5, 4.4, 5.2, 8.1, 8.2, 8.3, 10.3**
    - For any subset of inputs missing/empty (incl. per-asset regime failure), assert the builder
      still returns a report, renders each unavailable section/asset with its placeholder, and
      displays nothing it did not receive
    - Minimum 100 iterations; tag `# Feature: daily-market-report, Property 6: ...`

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement the consolidated renderer
  - [x] 4.1 Implement `render_consolidated_text`
    - Create `vpa/reports/consolidated_renderer.py` with
      `render_consolidated_text(report) -> str` following the `render_plain_text` style (header +
      sectioned lines, trailing newline)
    - Display `Report_Date` as ISO 8601 `YYYY-MM-DD`; render all four sections with their
      placeholders when unavailable (regime missing/empty, no VPA signals, no opportunities,
      summary zero/placeholder)
    - _Requirements: 1.2, 1.3, 1.4, 3.1, 3.2, 3.3, 3.4, 3.5, 4.4, 5.2, 6.4_
  - [ ]* 4.2 Write unit tests for the renderer
    - Assert `Report_Date` rendered as ISO 8601; each placeholder string present when a section or
      regime asset is unavailable; present records rendered High-first
    - _Requirements: 1.4, 3.3, 3.4, 3.5, 4.4, 5.2, 6.4_

- [x] 5. Implement the JSON snapshot writer
  - [x] 5.1 Implement snapshot path, write, and read-back
    - Create `vpa/reports/snapshot_writer.py` with `snapshot_path(archive_dir, report_date)`
      (`<archive_dir>/<YYYY-MM-DD>.json`), `write_snapshot(report, archive_dir)` and
      `read_snapshot(path)`
    - `write_snapshot` reuses `to_dict`/`from_dict`, creates parent dirs
      (`mkdir(parents=True)`), writes exactly one file, and is atomic/overwrite-safe via temp-file
      + `os.replace`; a failed serialise/write leaves any pre-existing dated file unchanged and
      surfaces the error; `encoding="utf-8"`
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.7_
  - [ ]* 5.2 Write unit tests for the snapshot writer
    - File named `YYYY-MM-DD.json` (7.2); exactly one file written (7.1); re-running the same date
      fully replaces contents (7.5); a simulated temp-write/replace failure leaves a pre-existing
      file unchanged and surfaces the error (7.7)
    - _Requirements: 7.1, 7.2, 7.5, 7.7_

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement the asset-neutral regime wrapper
  - [x] 7.1 Implement `collect_regime` with per-asset isolation
    - Create `vpa/reports/regime.py` with `RegimeAssetState` enum, `RegimeAssetResult` dataclass,
      and `collect_regime(assets, *, output_dir, lookback_days=200, generator_factory=DailySignalGenerator)`
    - Per asset: build `generator_factory(output_dir=..., lookback_days=..., ticker=asset)` and
      call `.run()`; non-empty -> `PRESENT`, empty -> `EMPTY`, `InsufficientDataError`/any
      exception -> `MISSING` with the reason captured in `detail` and logged
    - `generator_factory` is injectable; exactly one `RegimeAssetResult` returned per configured
      asset; iterates an arbitrary N of assets with no code change
    - Not a file reader; uses `logging.getLogger(__name__)`
    - _Requirements: 2.3, 2.4, 2.5, 8.1, 9.1, 9.2, 9.4_
  - [x] 7.2 Write property test for Market Regime per-asset shape
    - **Property 7: Market Regime reflects each configured asset exactly once**
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
    - Generate per-asset regime results mixing present/empty/missing over arbitrary N; assert each
      configured asset appears exactly once, present records High-first, empty assets show
      no-high-conviction, missing assets show the unavailable placeholder
    - Minimum 100 iterations; tag `# Feature: daily-market-report, Property 7: ...`
  - [ ]* 7.3 Write unit tests for the regime wrapper with an injected fake generator
    - Inject a fake `generator_factory` (never touches yfinance/network); assert `.run()` invoked
      per configured asset, one failing asset does not stop the others, and each failure yields one
      log entry naming the affected asset
    - _Requirements: 2.3, 8.1, 9.1, 9.2, 9.4_

- [x] 8. Implement the orchestrator entrypoint and wire everything together
  - [x] 8.1 Implement config resolution and input acquisition
    - Create `vpa/reports/daily_market_report.py` with `main(argv=None) -> int`
    - Resolve `Report_Date` (Pi local date, overridable via arg/env), `Configured_Assets` (from a
      `vpa/config/config.json` key with optional env override, default `["SPY"]`), and the
      `Historical_Archive` directory from config/env
    - Run `run_scan(...)` inside `try/except`; on failure log the reason and pass
      `scan_result = None` (VPA scan input Missing). Run the regime wrapper per configured asset
    - _Requirements: 2.1, 2.3, 2.4, 2.5, 9.1, 9.2, 9.4_
  - [x] 8.2 Wire build -> render -> write outputs and emit terminal status
    - Call `write_reports(report, output_dir)` for the all-shares scan's individual outputs
    - Call `build_consolidated_report(...)`, then `render_consolidated_text(...)` and write the
      rendered report to `vpa/log/consolidated_report_YYYYMMDD.txt` (known, stable name), then
      `write_snapshot(...)`
    - Write report/snapshot only after a successful build (no partial report on build failure);
      emit exactly one terminal `Report_Status` (stdout success / stderr failure) and return the
      matching exit code (0 for produced incl. degraded, non-zero only when no report at all); log
      an error naming the failed write target on a write failure
    - _Requirements: 1.1, 1.3, 1.5, 1.6, 1.7, 2.6, 9.3, 10.1, 10.2, 10.3, 10.4_
  - [x] 8.3 Write orchestrator unit tests with injected fakes
    - Inject a fake scan function and fake regime generator (no yfinance/network): happy path
      returns 0 and prints one success line; injected scan failure plus a failing regime asset
      still returns 0 with a report produced; injected build/write failure returns non-zero, prints
      one failure line, and writes no partial report; assert `write_reports` invoked and `.run()`
      invoked per configured asset
    - _Requirements: 1.3, 1.7, 2.1, 2.3, 7.4, 10.1, 10.2, 10.3, 10.4_

- [x] 9. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Add the delivery launcher and Rundeck job
  - [x] 10.1 Create the shell launcher
    - Create `vpa/scripts/start_daily_market_report.sh` following
      `start_vpa_all_shares.sh`: activate the venv, ensure `/usr/local/trading` on `PYTHONPATH`,
      run `python -m vpa.reports.daily_market_report`, copy the specific
      `vpa/log/consolidated_report_YYYYMMDD.txt` to `$VPA_SHARE_DIR` (default `/mnt/data/my_share`)
      by its known name, and `exit $?` so the orchestrator's exit status is the Rundeck status
    - _Requirements: 1.5, 1.6, 10.2, 10.4_
  - [x] 10.2 Create the Rundeck job definition
    - Create `vpa/jobs/Daily_Market_Report.yaml` following the existing job pattern (single
      `scriptfile` command, daily schedule, `keepgoing: false`, `node-first`) pointing at the new
      launcher
    - _Requirements: 10.1, 10.2, 10.4_

- [x] 11. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass (`& "d:\projects\trading\.venv\Scripts\python.exe" -m pytest`), ask the
    user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP.
- Each task references specific requirements for traceability.
- Checkpoints ensure incremental validation.
- Property tests validate the seven universal correctness properties (hypothesis, minimum 100
  iterations each), tagged `# Feature: daily-market-report, Property <n>: <text>`.
- Unit tests validate specific examples and edge cases; the orchestrator and regime wrapper use
  injected fakes and MUST NOT touch yfinance or the network.
- All tests are fast (no `slow` marker).
- Jira: SP-356 ("Daily Market Report", Trading Bot 0.7).

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "7.1"] },
    { "id": 2, "tasks": ["1.3", "2.1", "7.2", "7.3"] },
    { "id": 3, "tasks": ["2.2", "2.3", "2.4", "2.5", "2.6", "4.1", "5.1"] },
    { "id": 4, "tasks": ["4.2", "5.2", "8.1"] },
    { "id": 5, "tasks": ["8.2", "10.1", "10.2"] },
    { "id": 6, "tasks": ["8.3"] }
  ]
}
```
