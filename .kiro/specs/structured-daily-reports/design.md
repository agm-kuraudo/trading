<!-- Generated with GitHub Copilot in VS Code; prepared for review and handoff to Kiro. -->

# Design Document: Structured Daily Reports

## Overview

Refactor the SP-500 scan into a callable workflow that returns structured per-ticker results, then render those results into CSV, HTML, and the existing plain-text report. The scan's business logic remains unchanged; this change separates collection, ranking, rendering, and filesystem output so all report formats share one source of truth.

## Design Decisions

1. **Shared structured model**: Define typed report records and a report-run container rather than passing loosely shaped dictionaries between renderers.
2. **Both CSV and HTML are required**: CSV is the durable machine-readable record; HTML is the human-readable daily summary.
3. **Plain text is retained**: Continue writing the existing text report during the migration for debugging and scheduled-workflow compatibility.
4. **One row per attempted ticker**: Successful non-opportunities remain visible, and failures are represented explicitly rather than silently printed and discarded.
5. **Deterministic ordering**: Successful rows sort by descending signal score with ticker tie-breaking; failed rows sort by ticker. Opportunity rows retain their existing drawdown ordering with ticker tie-breaking.
6. **Safe HTML rendering**: Use standard-library `html.escape` and a self-contained document; do not add a template dependency for this report.
7. **Configurable output path**: Read an output directory setting from the existing configuration with `vpa/log/` as the default, preserving current behavior.
8. **Callable entry point**: Move import-time orchestration behind `main()` and small functions so tests can inject ticker lists, analyzers, dates, and output directories without network calls.

## Proposed Module Structure

```text
vpa/
  reports/
    __init__.py
    models.py
    renderers.py
    writers.py
  app_all_shares.py
```

The exact module split may be reduced if the existing project style favors fewer files, but responsibilities should remain distinct:

- `models.py`: typed `TickerScanResult`, `OpportunityResult`, and `DailyReport` structures.
- `renderers.py`: pure CSV, HTML, and plain-text rendering functions.
- `writers.py`: date-stamped path construction, directory creation, and UTF-8 file writes.
- `app_all_shares.py`: ticker loading, analyzer execution, opportunity evaluation, and CLI/script entry point.

## Data Model

```text
TickerScanResult
  source_ticker: str
  report_ticker: str
  status: "success" | "failed"
  signal_score: float | None
  signal_components: str
  opportunity_status: "qualifies" | "does_not_qualify" | "disabled" | "unavailable"
  drawdown_pct: float | None
  momentum_pct: float | None
  fifty_two_week_high: float | None
  error_message: str | None

DailyReport
  report_date: date
  results: list[TickerScanResult]
  opportunity_filter_enabled: bool
  output metadata/count properties derived from results
```

Signal components should be serialized consistently for CSV, preferably as a delimited string or JSON string with a documented convention. The renderer must not recompute signal or opportunity values.

## Workflow

```text
main()
  -> load_config()
  -> load_tickers()
  -> run_scan(tickers, analyzer_factory, opportunity_evaluator)
       -> one TickerScanResult per attempted ticker
  -> build DailyReport
  -> write CSV, HTML, and plain text
  -> return output paths / report summary
```

The analyzer's existing `process_data()` and `get_dataframe()` behavior remains the source of signal scores and opportunity evaluation. Exceptions are caught per ticker, converted to failed results, and do not stop the scan.

## Output Contract

Default filenames for report date `YYYYMMDD`:

- `share_output_YYYYMMDD.csv`
- `share_output_YYYYMMDD.html`
- `share_output_YYYYMMDD.txt`

The output directory defaults to `vpa/log/` and is configurable. CSV columns, in order:

```text
report_date,source_ticker,report_ticker,status,signal_score,signal_components,opportunity_status,drawdown_pct,momentum_pct,fifty_two_week_high,error_message
```

The HTML document contains:

1. Header with title, report date, and scan counts.
2. Top recommendations table.
3. Bottom recommendations table.
4. Opportunities table or disabled/no-opportunities state.
5. Failed tickers table when failures exist.

## Compatibility and Risks

- Existing scripts may rely on import-time execution; preserve command-line execution through `if __name__ == "__main__": main()` while removing side effects on import.
- Current ticker normalization replaces periods with hyphens; retain both source and report ticker values to avoid losing identity.
- The current report silently omits failures; adding failure rows changes report shape but improves operational visibility as required.
- The current config is loaded as a dictionary in this module; use the typed settings loader introduced by SP-308 where available, or preserve the existing loader until a compatible setting is added.
- HTML must escape exception text and ticker values.
- Atomic replacement is desirable for scheduled readers, but should not complicate the first implementation; reliable UTF-8 writes and directory creation are required.

## Testing Strategy

Use dependency injection and temporary directories. Tests should not download market data or execute the module at import time. Reuse existing opportunity fixtures and add synthetic scan results for renderer tests. Validate pure renderer output separately from orchestration and filesystem behavior.

In addition to automated tests, perform one real end-to-end run against a deliberately limited ticker set or an explicit dry-run mode. Capture the generated CSV, HTML, and plain-text paths, inspect their contents, verify that the three reports agree on the same scan results, and record the observed output in the completion notes. The real run must use normal configuration and network behavior, but must not expose credentials or overwrite historical reports.
