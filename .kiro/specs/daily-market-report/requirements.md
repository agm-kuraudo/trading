# Requirements Document

## Introduction

The Daily Market Report (Jira SP-356) is a single orchestrator job that produces one consolidated,
human-readable market report each day. Rather than reading text files written by other jobs, the
orchestrator runs the upstream scans in-process and builds the consolidated report from the
resulting in-memory Python objects. In one run the orchestrator:

- runs the all-shares VPA scan (`vpa/app_all_shares.py` `run_scan`), which returns a single
  in-memory daily scan result carrying both the VPA signal scores and the opportunity candidates;
- runs the SP-315 market-regime signal generator in-process
  (`vpa/ml_validation/daily_signal.py` `DailySignalGenerator(ticker=...).run()`), per asset, where
  SPY is the current primary asset;
- writes each component's own individual outputs as they are written today (the all-shares scan's
  `share_output_*` CSV/HTML/TXT, and the SP-315 signals-log CSV);
- builds and writes the Consolidated_Daily_Report with four defined sections from those in-memory
  objects, and archives a JSON snapshot of the report to a date-stamped historical archive.

Running the SP-315 generator in-process also gives that generator a scheduled home, which it does
not currently have. The feature builds on the existing `vpa/reports` module (`models.py`,
`renderers.py`, `writers.py`) and follows the project's established delivery pattern: the job runs
on the Raspberry Pi under Rundeck via a shell launcher and writes its outputs to the shared drive,
surfacing its status in the Rundeck job logs. A future database-backed source for the upstream
inputs is a possible swap but is out of scope.

## Glossary

- **Consolidated_Report_Generator**: The new orchestrator component that runs the upstream scans
  in-process, obtains the three in-memory inputs, assembles the Consolidated_Daily_Report, renders
  the report sections, and writes the report and its historical JSON snapshot. This is the system
  being specified.
- **Consolidated_Daily_Report**: The single rendered report produced for one report date, composed
  of the four defined report sections.
- **VPA_Scan_Result**: The in-memory daily Volume Price Analysis scan result returned by the
  all-shares scan (`vpa/app_all_shares.py` `run_scan`) as a typed daily-report object whose rows
  carry both signal scores and opportunity fields. It is the source of both the VPA signal view and
  the opportunity-candidate view.
- **Opportunity_Candidates**: The opportunity-candidate view derived from the VPA_Scan_Result (the
  qualifying rows produced by the drawdown/momentum filter, SP-305, `vpa/opportunities.py`). The
  Opportunity_Candidates are a view of the same VPA_Scan_Result object, not a separate input.
- **Market_Regime_Signal**: The per-asset market-regime output produced by the SP-315 generator
  (`vpa/ml_validation/daily_signal.py` `DailySignalGenerator`). For each configured asset, the
  Market_Regime_Signal provides zero or more market-regime signal records, each record carrying the
  asset identifier, a signal_type, an adjusted_direction, and a confidence_level. An asset with no
  fired records represents "no high-conviction signal" for that asset. SPY is the current primary
  asset, but the signal is not limited to SPY and is expected to cover additional indexes,
  commodities, and shares over time.
- **Signal_Record**: One fired market-regime signal in the Market_Regime_Signal for an asset,
  carrying the asset identifier, signal_type (e.g. "distribution", "strong_bearish"),
  adjusted_direction (e.g. "BUY"), and confidence_level (one of "High", "Medium-High", "Low-Medium",
  "Low").
- **Report_Section**: One of the four named parts of the Consolidated_Daily_Report: the Market
  Regime section, the Top VPA Signals section, the Opportunities section, and the Daily Summary
  section.
- **Historical_Snapshot**: A JSON file persisting the data of one Consolidated_Daily_Report, stored
  in the historical archive under a date-based file name.
- **Historical_Archive**: The directory in which Historical_Snapshot files are retained across days.
- **Shared_Drive**: The shared-drive destination (the `VPA_SHARE_DIR` share directory, default
  `/mnt/data/my_share`) to which the launcher delivers the Consolidated_Daily_Report so that the
  report is accessible from the user's day-to-day computer. This is the current delivery target; a
  future copy of report data to a database is out of scope.
- **Configured_Assets**: The externally configured list of assets for which the
  Consolidated_Report_Generator runs the SP-315 market-regime signal generator. The list is
  supplied by configuration, supports an arbitrary number (N) of assets, and defaults to a single
  entry containing the current primary asset (SPY). Adding or removing assets is a configuration
  change, not a code change.
- **Report_Date**: The calendar date the report is generated for, used to stamp the report and its
  Historical_Snapshot file name.
- **Report_Status**: The outcome of a report-generation run (success or failure), reported to the
  Rundeck job logs.
- **Rundeck_Log**: The log stream of the Rundeck job that runs the orchestrator on the Raspberry Pi.
- **Missing_Input**: An upstream in-memory input that is absent because the upstream component
  produced no object (for example, the component raised an error).
- **Empty_Input**: An upstream in-memory input that is present but contains no signal rows, no
  opportunity candidates, or no fired market-regime records.

## Requirements

### Requirement 1: Orchestrate the upstream scans and produce a single consolidated daily report

**User Story:** As a trader and consumer of the VPA system outputs, I want one orchestrator job to run the daily scans and consolidate their outputs into a single report, so that I can quickly identify actionable opportunities each morning without manually running or reviewing multiple jobs.

#### Acceptance Criteria

1. WHEN the Consolidated_Report_Generator is run, THE Consolidated_Report_Generator SHALL run the upstream scans in-process and produce exactly one Consolidated_Daily_Report for the Report_Date in the same run.
2. WHEN the Consolidated_Report_Generator produces the Consolidated_Daily_Report, THE Consolidated_Report_Generator SHALL include all four Report_Sections and no other sections, ordered as the Market Regime section, the Top VPA Signals section, the Opportunities section, and the Daily Summary section.
3. THE Consolidated_Report_Generator SHALL render the Consolidated_Daily_Report using the existing `vpa/reports` rendering and writing components.
4. WHEN the Consolidated_Report_Generator writes the Consolidated_Daily_Report, THE Consolidated_Report_Generator SHALL display the Report_Date in the rendered report output in ISO 8601 (YYYY-MM-DD) form.
5. WHEN the Consolidated_Daily_Report is produced, THE Consolidated_Report_Generator SHALL deliver the rendered Consolidated_Daily_Report to the Shared_Drive so that the Consolidated_Daily_Report is accessible from the user's day-to-day computer.
6. WHEN the run produces outputs in addition to the Consolidated_Daily_Report, THE Consolidated_Report_Generator SHALL deliver the Consolidated_Daily_Report specifically to the Shared_Drive rather than only the most recently written output file.
7. IF report generation cannot produce the Consolidated_Daily_Report, THEN THE Consolidated_Report_Generator SHALL not write a partial Consolidated_Daily_Report and SHALL report a failure Report_Status to the Rundeck_Log indicating generation did not complete.

### Requirement 2: Obtain the three in-memory inputs from the upstream components

**User Story:** As a trader, I want the report to draw from every daily signal source, so that the report is a single source of truth for the day's market opportunities.

#### Acceptance Criteria

1. WHEN the Consolidated_Report_Generator assembles the Consolidated_Daily_Report, THE Consolidated_Report_Generator SHALL obtain the VPA_Scan_Result by running the all-shares VPA scan in-process.
2. WHEN the Consolidated_Report_Generator assembles the Consolidated_Daily_Report, THE Consolidated_Report_Generator SHALL obtain the Opportunity_Candidates as the opportunity-candidate view derived from the same VPA_Scan_Result.
3. WHEN the Consolidated_Report_Generator assembles the Consolidated_Daily_Report, THE Consolidated_Report_Generator SHALL obtain the Market_Regime_Signal by running the SP-315 market-regime signal generator in-process for each asset in the Configured_Assets.
4. THE Consolidated_Report_Generator SHALL run the SP-315 market-regime signal generator for each asset in the Configured_Assets and SHALL support an arbitrary number (N) of Configured_Assets without code changes, where the default Configured_Assets list contains the current primary asset (SPY).
5. WHEN an input is a Missing_Input or an Empty_Input, THE Consolidated_Report_Generator SHALL treat that input as obtained and continue assembling the Consolidated_Daily_Report.
6. WHEN the Consolidated_Report_Generator has obtained the VPA_Scan_Result, the Opportunity_Candidates, and the Market_Regime_Signal, THE Consolidated_Report_Generator SHALL populate the Market Regime section from the Market_Regime_Signal, the Top VPA Signals section from the VPA_Scan_Result, and the Opportunities section from the Opportunity_Candidates.

### Requirement 3: Market Regime section

**User Story:** As a trader, I want the report to show each asset's fired market-regime signals, so that I can read the day's opportunities in the context of the current market direction and conviction.

#### Acceptance Criteria

1. WHEN the Market_Regime_Signal is present and an asset has one or more fired Signal_Records, THE Consolidated_Report_Generator SHALL display in the Market Regime section, for that asset, the asset identifier together with each fired Signal_Record's signal_type, adjusted_direction, and confidence_level.
2. WHEN the Consolidated_Report_Generator displays more than one fired Signal_Record for an asset in the Market Regime section, THE Consolidated_Report_Generator SHALL order those Signal_Records by confidence_level from highest to lowest, with "High" first, matching the SP-315 generator's own ordering.
3. WHEN the Market_Regime_Signal is present and contains more than one asset with one or more fired Signal_Records, THE Consolidated_Report_Generator SHALL display the fired Signal_Records of every such asset in the Market Regime section.
4. WHEN the Market_Regime_Signal is present and a configured asset has no fired Signal_Records, THE Consolidated_Report_Generator SHALL display in the Market Regime section, for that asset, the asset identifier together with a no-high-conviction-signal indication.
5. IF the Market_Regime_Signal is a Missing_Input or an Empty_Input, THEN THE Consolidated_Report_Generator SHALL render the Market Regime section containing a placeholder indicating the market-regime signal is unavailable and SHALL display no asset Signal_Record.

### Requirement 4: Top VPA Signals section

**User Story:** As a trader, I want the report to list the strongest VPA signals, so that I can see the highest-conviction tickers without scanning the full output.

#### Acceptance Criteria

1. WHEN the VPA_Scan_Result contains one or more signal rows, THE Consolidated_Report_Generator SHALL include in the Top VPA Signals section at most the 5 signal tickers with the highest signal score.
2. WHEN the Consolidated_Report_Generator lists signal tickers in the Top VPA Signals section, THE Consolidated_Report_Generator SHALL order the listed tickers by signal score from highest to lowest.
3. WHEN two or more listed tickers have an equal signal score, THE Consolidated_Report_Generator SHALL order those equally-scored tickers alphabetically by ticker symbol in ascending order.
4. IF the VPA_Scan_Result is a Missing_Input or an Empty_Input, THEN THE Consolidated_Report_Generator SHALL render the Top VPA Signals section with a placeholder indicating no VPA signals are available.

### Requirement 5: Opportunities section

**User Story:** As a trader, I want the report to list the day's opportunity candidates, so that I can act on tickers that meet the drawdown and momentum criteria.

#### Acceptance Criteria

1. WHEN the Opportunity_Candidates contain one or more opportunity candidates, THE Consolidated_Report_Generator SHALL list every opportunity ticker from the Opportunity_Candidates in the Opportunities section in a deterministic order.
2. IF the Opportunity_Candidates are a Missing_Input or an Empty_Input, THEN THE Consolidated_Report_Generator SHALL render the Opportunities section with a placeholder indicating no opportunities are available.
3. WHEN the Consolidated_Report_Generator lists an opportunity ticker in the Opportunities section, THE Consolidated_Report_Generator SHALL display for that ticker its drawdown value and its momentum value from the Opportunity_Candidates.

### Requirement 6: Daily Summary section

**User Story:** As a trader, I want a one-line summary of the day's actionable items, so that I can gauge the day at a glance before reading the detail sections.

#### Acceptance Criteria

1. WHEN the Consolidated_Report_Generator has populated the Market Regime, Top VPA Signals, and Opportunities sections, THE Consolidated_Report_Generator SHALL include in the Daily Summary section a count of actionable opportunities equal to the non-negative integer number of opportunity tickers listed in the Opportunities section.
2. WHEN the Consolidated_Report_Generator populates the Daily Summary section, THE Consolidated_Report_Generator SHALL include, for the primary asset, the adjusted_direction and confidence_level of that asset's highest-confidence fired Signal_Record or a no-high-conviction-signal indication when that asset has no fired Signal_Record, together with the count of signal tickers listed in the Top VPA Signals section.
3. IF one or two of the three inputs are a Missing_Input or an Empty_Input, THEN THE Consolidated_Report_Generator SHALL report in the Daily Summary section a zero count for each section whose input is unavailable and the corresponding values for each section whose input is available.
4. IF all three inputs are a Missing_Input or an Empty_Input, THEN THE Consolidated_Report_Generator SHALL render the Daily Summary section reporting zero actionable opportunities, zero VPA signals, and the market-regime-unavailable placeholder.

### Requirement 7: Historical JSON snapshot archival

**User Story:** As a trader and analyst, I want every report archived as a JSON snapshot, so that I have a historical record for future performance analysis.

#### Acceptance Criteria

1. WHEN the Consolidated_Report_Generator produces a Consolidated_Daily_Report, THE Consolidated_Report_Generator SHALL write exactly one Historical_Snapshot in valid JSON format to the Historical_Archive.
2. WHEN the Consolidated_Report_Generator writes a Historical_Snapshot, THE Consolidated_Report_Generator SHALL name the Historical_Snapshot file using the Report_Date formatted as YYYY-MM-DD.
3. WHEN the Consolidated_Report_Generator writes a Historical_Snapshot, THE Consolidated_Report_Generator SHALL record in the Historical_Snapshot the data of all four Report_Sections and the Report_Date.
4. THE Consolidated_Report_Generator SHALL write the Historical_Snapshot as an automatic step of report generation without a separate manual action.
5. WHERE a Historical_Snapshot file for the Report_Date already exists in the Historical_Archive, THE Consolidated_Report_Generator SHALL replace the full contents of the existing Historical_Snapshot file for that Report_Date with the newly generated Historical_Snapshot.
6. FOR ALL Historical_Snapshot files written, reading the Historical_Snapshot back into report data SHALL reproduce the four Report_Sections and the Report_Date recorded when the Historical_Snapshot was written, with no field added, dropped, or altered (round-trip property).
7. IF the Consolidated_Report_Generator cannot complete writing the Historical_Snapshot to the Historical_Archive, THEN THE Consolidated_Report_Generator SHALL leave any pre-existing Historical_Snapshot file for that Report_Date unchanged and SHALL surface an error indicating the archival failure.

### Requirement 8: Graceful handling of missing or empty inputs

**User Story:** As a trader, I want the report to be produced even when a signal source fails, so that an outage in one upstream component does not deprive me of the rest of the report.

#### Acceptance Criteria

1. IF one or two of the three inputs are a Missing_Input or an Empty_Input, THEN THE Consolidated_Report_Generator SHALL still produce exactly one Consolidated_Daily_Report containing all four Report_Sections, populating each Report_Section whose input is available from that input and rendering each Report_Section whose input is a Missing_Input or an Empty_Input with its unavailable-input placeholder.
2. IF all three inputs are a Missing_Input or an Empty_Input, THEN THE Consolidated_Report_Generator SHALL produce exactly one Consolidated_Daily_Report containing all four Report_Sections, with each Report_Section rendered using its unavailable-input placeholder.
3. WHEN the Consolidated_Report_Generator produces the Consolidated_Daily_Report after encountering one or more inputs that are a Missing_Input or an Empty_Input, THE Consolidated_Report_Generator SHALL complete report generation with a success Report_Status.

### Requirement 9: Error logging

**User Story:** As an operator of the Raspberry Pi automation, I want report-generation errors logged, so that I can diagnose why a report was incomplete or absent.

#### Acceptance Criteria

1. WHEN the Consolidated_Report_Generator encounters a Missing_Input or an Empty_Input, THE Consolidated_Report_Generator SHALL log a message that identifies the affected input and indicates whether the condition was a Missing_Input or an Empty_Input.
2. IF the Consolidated_Report_Generator fails to obtain an input because the upstream component raised an error, THEN THE Consolidated_Report_Generator SHALL log an error entry that identifies the affected input and states the reason the upstream component failed.
3. IF the Consolidated_Report_Generator fails to write the Consolidated_Daily_Report or the Historical_Snapshot, THEN THE Consolidated_Report_Generator SHALL log an error entry that identifies the failed write target and states the reason the write failed.
4. WHEN more than one input is affected by a Missing_Input, an Empty_Input, or an upstream-component error in a single report-generation run, THE Consolidated_Report_Generator SHALL log a separate entry for each affected input.

### Requirement 10: Rundeck-visible orchestrator exit status

**User Story:** As an operator, I want the orchestrator job's status visible in the Rundeck job logs, so that a monitored daily job reflects whether the report was produced.

#### Acceptance Criteria

1. WHEN the Consolidated_Report_Generator run completes, THE Consolidated_Report_Generator SHALL emit exactly one terminal Report_Status to the Rundeck_Log.
2. WHEN the Consolidated_Report_Generator produces the Consolidated_Daily_Report, THE Consolidated_Report_Generator SHALL emit to the Rundeck_Log a message confirming the Consolidated_Daily_Report was produced for the Report_Date with a success Report_Status and SHALL exit with a process exit status indicating success.
3. WHEN the Consolidated_Report_Generator produces the Consolidated_Daily_Report after one or more upstream components failed, THE Consolidated_Report_Generator SHALL treat the run as a success Report_Status and SHALL exit with a process exit status indicating success.
4. IF the Consolidated_Report_Generator cannot produce the Consolidated_Daily_Report, THEN THE Consolidated_Report_Generator SHALL emit a failure Report_Status to the Rundeck_Log and SHALL exit with a process exit status indicating failure.
