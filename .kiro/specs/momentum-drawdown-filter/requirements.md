# Requirements Document

## Introduction

The Momentum/Drawdown Filter is a new screener that surfaces potential bargain opportunities from the SP-500 daily scan. It identifies shares that exhibit positive short-term momentum while trading 20% or more below their 52-week high — suggesting a broader trend reversal may be underway. The filter runs as part of the existing `app_all_shares.py` scan and outputs a separate "Opportunities" section in the daily report file.

## Glossary

- **Drawdown_Filter**: The module responsible for calculating 52-week highs, momentum, and applying the drawdown threshold to identify opportunity candidates.
- **Daily_Report**: The plain-text output file written to `vpa/log/share_output_YYYYMMDD.txt` containing scan results.
- **Fifty_Two_Week_High**: The highest closing price observed for a ticker within the most recent 252 trading days of available data.
- **Momentum**: The rate of change of the closing price over a configurable look-back period, expressed as a percentage. Positive momentum means the current close is higher than the close N days ago.
- **Drawdown_Percentage**: The percentage decline of the current closing price relative to the Fifty_Two_Week_High, calculated as `((current_close - fifty_two_week_high) / fifty_two_week_high) * 100`.
- **Drawdown_Threshold**: The configurable minimum drawdown percentage (default 20%) a ticker must exceed to qualify as an opportunity.
- **Momentum_Period**: The configurable look-back period in trading days used to calculate rate of change (default 20 days).
- **Opportunities_List**: The filtered subset of tickers that satisfy both the drawdown threshold and positive momentum criteria.
- **Scanner**: The `app_all_shares.py` script that iterates over SP-500 tickers and orchestrates analysis.

## Requirements

### Requirement 1: Fetch Sufficient Historical Data

**User Story:** As a trader, I want the system to fetch at least 252 trading days of price history, so that a full 52-week high can be calculated accurately.

#### Acceptance Criteria

1. WHEN the Drawdown_Filter is enabled, THE Scanner SHALL request at least 365 calendar days of historical data from the data provider for each ticker.
2. IF the data provider returns fewer than 252 trading days for a ticker, THEN THE Drawdown_Filter SHALL exclude that ticker from the Opportunities_List and log a warning identifying the ticker and the number of rows received.
3. WHEN the Drawdown_Filter is disabled via configuration, THE Scanner SHALL use the existing data window logic without modification.

### Requirement 2: Calculate 52-Week High

**User Story:** As a trader, I want the system to determine the 52-week high for each ticker, so that I can understand how far the current price has fallen from its peak.

#### Acceptance Criteria

1. WHEN sufficient historical data is available, THE Drawdown_Filter SHALL compute the Fifty_Two_Week_High as the maximum closing price within the most recent 252 trading days.
2. THE Drawdown_Filter SHALL compute the Drawdown_Percentage using the formula `((current_close - fifty_two_week_high) / fifty_two_week_high) * 100`.
3. THE Drawdown_Filter SHALL use only the closing price column for both the Fifty_Two_Week_High and current price calculations.

### Requirement 3: Calculate Short-Term Momentum

**User Story:** As a trader, I want the system to calculate short-term momentum for each ticker, so that I can identify shares with recent upward price movement.

#### Acceptance Criteria

1. THE Drawdown_Filter SHALL calculate Momentum as the percentage rate of change over the configured Momentum_Period using the formula `((current_close - close_n_days_ago) / close_n_days_ago) * 100`.
2. WHEN fewer than Momentum_Period trading days are available after warm-up, THE Drawdown_Filter SHALL exclude that ticker from the Opportunities_List.
3. THE Drawdown_Filter SHALL use the default Momentum_Period of 20 trading days when no configuration override is provided.

### Requirement 4: Apply Filter Criteria

**User Story:** As a trader, I want the system to flag shares meeting both drawdown and momentum criteria, so that I see only genuine bargain-with-momentum opportunities.

#### Acceptance Criteria

1. THE Drawdown_Filter SHALL include a ticker in the Opportunities_List only when the Drawdown_Percentage is less than or equal to the negative Drawdown_Threshold (price is at least threshold percent below peak) AND the Momentum is strictly greater than zero.
2. THE Drawdown_Filter SHALL use a default Drawdown_Threshold of 20 percent when no configuration override is provided.
3. WHEN no tickers satisfy both filter criteria, THE Drawdown_Filter SHALL produce an empty Opportunities_List.

### Requirement 5: Output Opportunities in Daily Report

**User Story:** As a trader, I want the opportunities listed in the daily report, so that I can review them alongside existing scan results.

#### Acceptance Criteria

1. WHEN the Opportunities_List is not empty, THE Daily_Report SHALL include a section titled "Opportunities" containing each qualifying ticker, its Drawdown_Percentage, and its Momentum value.
2. THE Daily_Report SHALL sort the Opportunities section by Drawdown_Percentage in ascending order (largest drawdown first).
3. WHEN the Opportunities_List is empty, THE Daily_Report SHALL include the "Opportunities" section header followed by a line stating "No opportunities found".
4. THE Daily_Report SHALL append the Opportunities section after the existing Top 5 and Bottom 5 sections.

### Requirement 6: Configuration

**User Story:** As a trader, I want to configure filter parameters via the existing config file, so that I can tune thresholds without modifying code.

#### Acceptance Criteria

1. THE Scanner SHALL read Drawdown_Filter settings from a `drawdown_filter` section in the JSON configuration file.
2. WHERE the `drawdown_filter` section is absent from the configuration file, THE Drawdown_Filter SHALL use default values: enabled=true, drawdown_threshold=20, momentum_period=20, data_days=365.
3. WHEN `drawdown_filter.enabled` is set to false, THE Drawdown_Filter SHALL skip all filter calculations and produce an Opportunities section containing the line "Opportunities: disabled" in the Daily_Report to maintain consistent report structure.
4. IF `drawdown_filter.momentum_period` is less than 1, THEN THE Drawdown_Filter SHALL log a warning and use the default value of 20.
5. IF `drawdown_filter.drawdown_threshold` is less than 0 or greater than 100, THEN THE Drawdown_Filter SHALL log a warning and use the default value of 20.

### Requirement 7: Data Window Coordination

**User Story:** As a trader, I want the data fetch window to accommodate both the MA crossover and drawdown filter requirements, so that both features receive sufficient data.

#### Acceptance Criteria

1. WHEN both the Drawdown_Filter and MA crossover are enabled, THE Scanner SHALL request historical data using the larger of the two configured data_days values.
2. WHEN only the Drawdown_Filter is enabled, THE Scanner SHALL request historical data using the Drawdown_Filter data_days value.
3. WHEN only the MA crossover is enabled, THE Scanner SHALL continue using the MA crossover data_days value.
4. IF the data provider returns fewer rows than required by either enabled feature despite requesting the larger data window, THEN THE Scanner SHALL disable the affected feature for that ticker, log a warning, and continue processing.
