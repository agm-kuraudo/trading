# Requirements Document

## Introduction

This feature replaces the Selenium/Firefox-based forex data retrieval in the VPA (Volume Price Analysis) trading application with a browserless approach that downloads Dukascopy binary feed files directly from `data.forexsb.com` and aggregates them into daily bars client-side.

The current implementation (`vpa/app_forex.py` plus the `vpa/forex_auto/` page-object package) drives a headless Firefox browser via geckodriver to `forexsb.com/historical-forex-data`, waits for an in-browser CSV export of `GBPUSD_D1.csv`, saves it to a Downloads folder, and reads it with pandas before handing a DataFrame to `MarketAnalyzer`. This is fragile for scheduled automation on a Raspberry Pi because it depends on geckodriver and Firefox being installed and stable.

Investigation confirmed the forexsb browser UI generates its CSV in-browser from a gzipped binary Dukascopy feed available at a predictable, unauthenticated URL. Daily (D1) data is not stored server-side, so the replacement downloads intraday M30 data and aggregates it to daily bars, matching the site's own client-side logic. A stdlib-only proof of concept (urllib, gzip, struct) plus pandas produced 5,017 daily GBPUSD bars with volume in the exact DataFrame shape `MarketAnalyzer` expects, using only dependencies already present in `requirements.txt`.

This work is tracked by Jira ticket **SP-309** ("Replace Selenium forex scraping with API or direct download") in the `trading` project, fixVersion "Trading Bot - VPA 0.5", label "trading". The code lives in `d:\projects\trading` (not `bf_trader_py`).

## Glossary

- **VPA_Forex_App**: The forex entry point (`vpa/app_forex.py`) that retrieves GBPUSD data and runs the VPA analysis. Referred to here as the target system for the retrieval and integration requirements.
- **Forex_Data_Retriever**: The new browserless component that downloads the Dukascopy binary feed and produces a daily bar DataFrame. Replaces the Selenium-driven download in the VPA_Forex_App.
- **Feed_Decoder**: The logic within the Forex_Data_Retriever that decodes the gzipped binary feed into intraday records.
- **Daily_Aggregator**: The logic within the Forex_Data_Retriever that resamples intraday records into daily (D1) bars.
- **MarketAnalyzer**: The existing downstream analysis class (`vpa/app_runner.py`) that accepts a `fixed_df` DataFrame, sorts by "Date", and produces a trade signal.
- **Dukascopy_Feed**: The gzipped binary data file at `https://data.forexsb.com/datafeed/data/dukascopy/{SYMBOL}{PERIOD}.lb.gz` (no API key, no authentication).
- **Symbol_Metadata**: Per-symbol scaling info (priceScale, volumeScale, digits) from `https://data.forexsb.com/datafeed/info/premium.json.gz`. For GBPUSD: priceScale=100000, volumeScale=1, digits=5.
- **Analysis_DataFrame**: A pandas DataFrame with columns exactly `["Date", "Open", "High", "Low", "Close", "Volume"]`, where "Date" is a datetime dtype, passed to MarketAnalyzer as `fixed_df`.
- **M30**: The 30-minute intraday period. The Dukascopy_Feed URL uses period `30` (`GBPUSD30.lb.gz`).
- **D1**: The daily period produced by aggregating M30 records.
- **Long_Period_SMA**: The longest simple moving average window configured for MarketAnalyzer, which sets the minimum number of daily bars required for full analysis.
- **Rundeck_Job**: The scheduled job (`vpa/jobs/Daily_VPA_Check_-_Forex_-_GBP_USD.yaml`) that runs `vpa/scripts/start_vpa_forex.sh` on the Raspberry Pi at 09:30 on weekdays.
- **Raspberry_Pi**: The always-on ARM Linux deployment target that runs the scheduled forex check.

## Requirements

### Requirement 1: Browserless forex data retrieval

**User Story:** As a trading bot operator, I want forex data retrieved without a browser, so that the scheduled forex check does not depend on geckodriver or Firefox.

#### Acceptance Criteria

1. THE Forex_Data_Retriever SHALL retrieve GBPUSD price data without invoking Selenium, a web browser, or a browser driver.
2. THE Forex_Data_Retriever SHALL retrieve GBPUSD price data using only the Python standard library (urllib, gzip, struct, pathlib) and pandas.
3. WHEN GBPUSD data is requested, THE Forex_Data_Retriever SHALL download the Dukascopy_Feed for the M30 period from `https://data.forexsb.com/datafeed/data/dukascopy/GBPUSD30.lb.gz`.
4. THE Forex_Data_Retriever SHALL obtain the GBPUSD priceScale and volumeScale from the Symbol_Metadata source.
5. IF the Symbol_Metadata source is unavailable or does not contain a priceScale and volumeScale for the requested symbol, THEN THE Forex_Data_Retriever SHALL abort retrieval and raise an error indicating the symbol metadata is missing.

### Requirement 2: Decode the binary feed

**User Story:** As a developer, I want the gzipped binary feed decoded into price records, so that intraday bars can be produced from the raw Dukascopy data.

#### Acceptance Criteria

1. WHEN a gzipped Dukascopy_Feed is retrieved, THE Feed_Decoder SHALL decompress the feed before decoding.
2. THE Feed_Decoder SHALL detect the record size as either 24 bytes (time, open, high, low, close, volume) or 28 bytes (adds a spread field), based on the decompressed buffer length.
3. IF the decompressed buffer length is not an exact multiple of a supported record size (24 or 28 bytes), THEN THE Feed_Decoder SHALL raise an error identifying the record-size mismatch and SHALL NOT emit any price records.
4. IF the decompressed buffer length is zero bytes, THEN THE Feed_Decoder SHALL produce an empty set of price records without raising an error.
5. THE Feed_Decoder SHALL decode each record as little-endian Int32 fields.
6. THE Feed_Decoder SHALL compute each record timestamp as `946684800000 + (time_field * 60000)` milliseconds since the Unix epoch.
7. THE Feed_Decoder SHALL compute each open, high, low, and close price as the corresponding Int32 field divided by the GBPUSD priceScale.
8. THE Feed_Decoder SHALL compute each volume as the ceiling of the volume Int32 field divided by the GBPUSD volumeScale.

### Requirement 3: Aggregate intraday records into daily bars

**User Story:** As a trading bot operator, I want daily GBPUSD bars with volume, so that the VPA analysis receives the same daily data it consumes today.

#### Acceptance Criteria

1. THE Daily_Aggregator SHALL aggregate decoded M30 records into D1 bars grouped by calendar day (UTC).
2. WHEN aggregating a calendar day, THE Daily_Aggregator SHALL set Open to the first record's open, High to the maximum high, Low to the minimum low, Close to the last record's close, and Volume to the sum of record volumes.
3. THE Daily_Aggregator SHALL emit D1 bars in ascending chronological order by date.
4. WHEN invoked with an empty set of decoded records, THE Daily_Aggregator SHALL produce zero daily bars without raising an error.
5. THE Daily_Aggregator SHALL produce daily bars current to the most recent day available in the Dukascopy_Feed.

### Requirement 4: Preserve the MarketAnalyzer integration contract

**User Story:** As a developer, I want the retriever to produce the same DataFrame format the VPA_Forex_App already produces, so that MarketAnalyzer and all downstream analysis remain unchanged.

#### Acceptance Criteria

1. THE Forex_Data_Retriever SHALL produce an Analysis_DataFrame with columns in the exact order `["Date", "Open", "High", "Low", "Close", "Volume"]`.
2. THE Forex_Data_Retriever SHALL set the "Date" column to a pandas datetime dtype and the Open, High, Low, Close, and Volume columns to a numeric dtype.
3. WHEN the Analysis_DataFrame is produced, THE VPA_Forex_App SHALL pass it to MarketAnalyzer as the `fixed_df` argument with `ticker_symbol="GBPUSD"`.
4. WHEN the trade signal is 15 or greater, THE VPA_Forex_App SHALL log "BUY Recommendation".
5. WHEN the trade signal is -15 or less, THE VPA_Forex_App SHALL log "SELL Recommendation".
6. WHEN the trade signal is greater than -15 and less than 15, THE VPA_Forex_App SHALL log "DO NOT TRADE".
7. THE VPA_Forex_App SHALL preserve the existing MarketAnalyzer logging behavior and the `graph_intervals` call.

### Requirement 5: Sufficient data for downstream analysis

**User Story:** As a trading bot operator, I want enough daily bars retrieved for the analysis window, so that the moving-average logic runs on complete data.

#### Acceptance Criteria

1. WHEN daily bars are requested for MarketAnalyzer analysis, THE Forex_Data_Retriever SHALL return a set of D1 bars whose count is equal to or greater than the number of periods in the Long_Period_SMA window.
2. IF the count of available D1 bars is fewer than the number of periods in the Long_Period_SMA window, THEN THE Forex_Data_Retriever SHALL raise an error indicating insufficient D1 bars and SHALL NOT return a partial D1 bar set to MarketAnalyzer.

### Requirement 6: Error handling for retrieval failures

**User Story:** As a trading bot operator, I want retrieval failures surfaced clearly, so that the scheduled job fails loudly rather than analyzing bad data.

#### Acceptance Criteria

1. IF the Dukascopy_Feed request fails due to a network error, THEN THE Forex_Data_Retriever SHALL raise an error describing the network failure and SHALL NOT return forex data to the caller.
2. IF the Dukascopy_Feed request returns a non-200 HTTP status, THEN THE Forex_Data_Retriever SHALL raise an error including the returned status code and SHALL NOT return forex data to the caller.
3. IF the decompressed feed contains zero records, THEN THE Forex_Data_Retriever SHALL raise an error indicating an empty feed.
4. IF the retrieved feed cannot be decompressed, THEN THE Forex_Data_Retriever SHALL raise an error indicating a decompression failure.

### Requirement 7: Cross-platform operation

**User Story:** As a developer, I want the retriever to run on both Windows and the Raspberry Pi, so that development and production use the same code path.

#### Acceptance Criteria

1. THE Forex_Data_Retriever SHALL execute on Windows and on Linux/ARM from a single identical source codebase with no platform-specific code branches.
2. WHEN the Forex_Data_Retriever constructs a filesystem path, THE Forex_Data_Retriever SHALL build it using OS-independent path handling.
3. THE Forex_Data_Retriever SHALL retrieve data without reading from or writing to the hardcoded `/home/mypi/Downloads` directory.

### Requirement 8: Symbol configurability

**User Story:** As a developer, I want the symbol to be parameterizable, so that the retriever can be reused for symbols beyond GBPUSD without editing hardcoded values.

#### Acceptance Criteria

1. THE Forex_Data_Retriever SHALL accept the symbol as a parameter consisting of a 6-character currency pair code, treating the value case-insensitively.
2. WHERE no symbol is specified, THE Forex_Data_Retriever SHALL default to GBPUSD.
3. WHEN a supported symbol is specified, THE Forex_Data_Retriever SHALL derive the Dukascopy_Feed URL and the Symbol_Metadata scaling values for that symbol.
4. IF the specified symbol does not match the required 6-character currency pair format, THEN THE Forex_Data_Retriever SHALL reject the request before any retrieval attempt and raise an error indicating the symbol format is invalid.

### Requirement 9: Testability of decode and aggregation logic

**User Story:** As a developer, I want the decode and aggregation logic to be unit and property testable, so that correctness can be verified without network access.

#### Acceptance Criteria

1. WHEN the Feed_Decoder is invoked with a given input byte buffer, THE Feed_Decoder SHALL produce identical output across repeated invocations with that same input.
2. WHEN the Daily_Aggregator is invoked with a given set of decoded records, THE Daily_Aggregator SHALL produce daily bars identical in count, ordering, and per-bar field values across repeated invocations with that same input.
3. THE Feed_Decoder and Daily_Aggregator SHALL be invocable in tests without performing any network request.
4. FOR ALL sets of valid intraday records, THE Daily_Aggregator SHALL set each daily bar's total Volume equal to the arithmetic sum of the Volume values of the source records assigned to that bar's calendar day.

### Requirement 10: Removal of the Selenium implementation

**User Story:** As a maintainer, I want the old Selenium code and dependency removed, so that the project no longer carries an unused browser-automation stack.

#### Acceptance Criteria

1. THE VPA_Forex_App SHALL retrieve forex data through the Forex_Data_Retriever without importing any Selenium module.
2. WHEN the Forex_Data_Retriever is in use as the sole forex-data source, THE trading project SHALL remove the `vpa/forex_auto/` page-object package in its entirety.
3. THE trading project SHALL remove the `selenium` dependency from `requirements.txt`.

### Requirement 11: Deployment and verification on the Raspberry Pi

**User Story:** As a trading bot operator, I want the replacement verified on the Pi via the existing scheduled job, so that the ticket is only Done when the automation works end-to-end in production.

#### Acceptance Criteria

1. THE VPA_Forex_App SHALL run on the Raspberry_Pi via the existing Rundeck_Job and `vpa/scripts/start_vpa_forex.sh` without geckodriver or Firefox installed.
2. WHEN the VPA_Forex_App runs on the Raspberry_Pi using live GBPUSD data, THE VPA_Forex_App SHALL produce a trade-signal log entry.
3. WHILE the replacement is complete but not yet deployed and verified on the Raspberry_Pi, THE SP-309 ticket SHALL remain in the Mostly Done column rather than Done.
