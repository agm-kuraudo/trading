# Implementation Plan: Replace Selenium Forex Scraping

## Overview

This plan implements the browserless forex retriever described in the design as a new
`vpa/forex_data/` package, then rewires `vpa/app_forex.py` to use it, removes the old
Selenium stack, and finishes with a Pi deployment/verification step.

Tasks are ordered so the pure, network-free logic (errors, decoder, aggregator) and its
property tests come first, followed by the network layer, the orchestrator, the app_forex
rewrite, the Selenium removal, and finally deployment. Each task references the requirement
numbers and (where relevant) the design correctness properties it implements.

Implementation language is **Python** (per the design). Tests use **pytest + hypothesis**
(already in `requirements.txt`). Property tests carry the tag comment:
`# Feature: replace-selenium-forex-scraping, Property {number}: {property_text}` and run
with `@settings(max_examples=100)` or higher.

## Tasks

- [x] 1. Create the `vpa/forex_data/` package skeleton and typed error hierarchy
  - [x] 1.1 Create the package files and error hierarchy
    - Create `vpa/forex_data/__init__.py` (exports added in a later task) and `vpa/forex_data/errors.py`
    - In `errors.py` define the base `ForexRetrievalError` and subclasses: `InvalidSymbolError`, `SymbolMetadataError`, `FeedNetworkError`, `FeedHTTPError` (stores `status_code`), `FeedDecodeError`, `EmptyFeedError`, `InsufficientDataError`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 1.5, 5.2, 8.4_

- [x] 2. Implement the pure feed decoder
  - [x] 2.1 Implement `Record` dataclass and `decode_feed` in `vpa/forex_data/decoder.py`
    - Add `RECORD_SIZES = (28, 24)` and `EPOCH_BASE_MS = 946684800000`
    - Define `@dataclass(frozen=True) Record(timestamp_ms, open, high, low, close, volume)`
    - `decode_feed(raw_gz_bytes, price_scale, volume_scale)`: gunzip (raise `FeedDecodeError` on failure); empty buffer → `[]`; detect record size (28 first, then 24, else raise `FeedDecodeError`); unpack leading six fields as little-endian Int32 (`"<6i"`), read/ignore trailing spread on 28-byte records
    - Compute `timestamp_ms = EPOCH_BASE_MS + time_field*60000`, O/H/L/C = `field/price_scale`, `volume = ceil((volume_int32 or 1)/volume_scale)`; return records in file order
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8_

  - [x] 2.2 Add test helper `encode_records(records, size)` in the forex_data test module
    - Build synthetic little-endian Int32 `.lb` buffers at record size 24 or 28 and gzip them, so decode round-trip tests can generate valid inputs
    - _Requirements: 9.3_

  - [x] 2.3 Write property test for decode round-trip
    - **Property 1: Decode round-trip recovers field values**
    - **Validates: Requirements 2.1, 2.2, 2.5, 2.6, 2.7, 2.8**
    - Generators: lists of Int32 field tuples; record size ∈ {24, 28}; positive `price_scale`, `volume_scale`; assert timestamp/price/volume derivations, order, and count

  - [x] 2.4 Write property test for malformed buffer length rejection
    - **Property 2: Malformed buffer length is rejected**
    - **Validates: Requirements 2.3**
    - Generators: byte buffers with length > 0 and not divisible by 24 or 28; assert `FeedDecodeError` and no records emitted

  - [x]* 2.5 Write unit test for zero-length buffer
    - Gzipped empty buffer decodes to `[]` with no error
    - _Requirements: 2.4_

- [x] 3. Implement the pure daily aggregator
  - [x] 3.1 Implement `aggregate_to_daily` in `vpa/forex_data/aggregator.py`
    - Add `DAILY_COLUMNS = ["Date", "Open", "High", "Low", "Close", "Volume"]`
    - Build a DataFrame from records, convert `timestamp_ms` → UTC `DatetimeIndex`, `resample("1D")` with `Open=first, High=max, Low=min, Close=last, Volume=sum`, `dropna()`, reset index to tz-naive `Date`
    - Reorder to `DAILY_COLUMNS` sorted ascending by `Date`; empty input → empty DataFrame with correct columns/dtypes (no error)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2_

  - [x] 3.2 Write property test for per-day OHLCV aggregation
    - **Property 3: Daily aggregation computes correct per-day OHLCV**
    - **Validates: Requirements 3.1, 3.2, 3.5**
    - Generators: lists of records spanning multiple UTC days; assert one bar per distinct UTC day with correct O/H/L/C and most-recent day present as last bar

  - [x]* 3.3 Write property test for ascending chronological order
    - **Property 4: Daily bars are in ascending chronological order**
    - **Validates: Requirements 3.3**
    - Generators: lists of records with unordered timestamps; assert `Date` column strictly increasing

  - [x] 3.4 Write property test for volume preservation
    - **Property 5: Volume is preserved under aggregation**
    - **Validates: Requirements 3.2, 9.4**
    - Generators: lists of records with arbitrary volumes; assert per-day Volume equals sum of source volumes for that day and total equals grand sum

  - [x]* 3.5 Write property test for output DataFrame shape invariant
    - **Property 6: Output DataFrame shape is invariant**
    - **Validates: Requirements 3.4, 4.1, 4.2**
    - Generators: lists of records including the empty set; assert exact column order, tz-naive datetime `Date`, numeric O/H/L/C/V dtypes

  - [x]* 3.6 Write unit test for empty aggregation
    - Empty record list → empty DataFrame with correct columns/dtypes and no error
    - _Requirements: 3.4_

- [x] 4. Add cross-cutting determinism property test for the pure functions
  - [x]* 4.1 Write property test for decode/aggregation determinism
    - **Property 9: Decode and aggregation are deterministic**
    - **Validates: Requirements 9.1, 9.2**
    - Invoke `decode_feed` twice on the same buffer and `aggregate_to_daily` twice on the same records; assert identical results
    - _Requirements: 9.1, 9.2_

- [x] 5. Checkpoint - pure logic complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Implement the network layer
  - [x] 6.1 Implement `fetch_symbol_metadata` and `fetch_feed` in `vpa/forex_data/feed.py`
    - `fetch_symbol_metadata(url=premium.json.gz)`: GET + gunzip + `json.loads`, return full dict; map `URLError`/socket → `FeedNetworkError`, `HTTPError.code` → `FeedHTTPError`, gunzip/json failure → `FeedDecodeError`
    - `fetch_feed(symbol, period=30, base_url=...)`: GET `{base_url}/{SYMBOL}{period}.lb.gz` with `Referer: https://data.forexsb.com/data-app` header, return raw gzipped bytes; map `URLError`/socket → `FeedNetworkError`, non-200 → `FeedHTTPError` carrying `.code`
    - Use `urllib.request` only; return no data on failure
    - _Requirements: 1.2, 1.3, 1.4, 6.1, 6.2_

  - [x]* 6.2 Write mocked unit tests for the network layer error mapping
    - Monkeypatch `urllib` to raise `URLError` → `FeedNetworkError`; `HTTPError(code=404)` → `FeedHTTPError` carrying 404; assert no data returned on failure
    - _Requirements: 6.1, 6.2_

- [x] 7. Implement the orchestrator
  - [x] 7.1 Implement `Forex_Data_Retriever` and `get_daily_dataframe` in `vpa/forex_data/retriever.py`
    - Constants `SYMBOL_LENGTH = 6`, `DEFAULT_SYMBOL = "GBPUSD"`, `M30_PERIOD = 30`
    - `Forex_Data_Retriever(min_bars=200)` with per-instance metadata cache
    - `get_daily_dataframe(symbol=DEFAULT_SYMBOL)`: validate symbol (strip, exactly 6 alpha, uppercase, case-insensitive) → `InvalidSymbolError` before any fetch; fetch+cache metadata and look up per-symbol `priceScale`/`volumeScale` (missing → `SymbolMetadataError`); fetch M30 feed; `decode_feed`; `aggregate_to_daily`; zero records/bars → `EmptyFeedError`; `< min_bars` → `InsufficientDataError` (return nothing); else return Analysis_DataFrame
    - Add module-level `get_daily_dataframe(symbol=DEFAULT_SYMBOL, min_bars=200)` convenience wrapper
    - _Requirements: 1.4, 1.5, 5.1, 5.2, 6.3, 8.1, 8.2, 8.3, 8.4_

  - [x] 7.2 Wire package exports in `vpa/forex_data/__init__.py`
    - Export `Forex_Data_Retriever` and `get_daily_dataframe` (and the error types) so callers use `from vpa.forex_data import get_daily_dataframe`
    - _Requirements: 4.3, 8.2_

  - [x]* 7.3 Write property test for symbol normalization and URL derivation
    - **Property 7: Symbol normalization and URL derivation**
    - **Validates: Requirements 1.3, 8.1, 8.3**
    - Generators: 6-letter strings in mixed case; assert normalization to uppercase and derived URL `.../dukascopy/{UPPER}30.lb.gz`

  - [x]* 7.4 Write property test for invalid symbol rejection
    - **Property 8: Invalid symbols are rejected before any retrieval**
    - **Validates: Requirements 8.4**
    - Generators: strings not exactly 6 alpha chars; assert `InvalidSymbolError` and that no metadata/feed fetch occurs (assert mocks not called)

  - [x]* 7.5 Write unit test for metadata lookup and default symbol
    - Sample metadata dict → correct GBPUSD scales; missing symbol → `SymbolMetadataError`; no-arg `get_daily_dataframe()` targets GBPUSD
    - _Requirements: 1.4, 1.5, 8.2_

  - [x] 7.6 Write unit test for a non-GBPUSD pair (multi-pair support)
    - Using injected metadata + synthetic bytes for a pair with a different `priceScale` (e.g. USDJPY), assert prices decode using that pair's scale and the derived URL uses the pair symbol — closes the PoC gap where only GBPUSD was verified
    - _Requirements: 8.1, 8.3, 2.7_

  - [x] 7.7 Write unit tests for sufficiency boundary and orchestrator error mapping
    - Exactly 200 daily bars passes; 199 raises `InsufficientDataError` and returns nothing; mocked `fetch_feed` raising `URLError` → `FeedNetworkError`; `HTTPError(404)` → `FeedHTTPError` carrying 404; non-gzip bytes → `FeedDecodeError`; zero-record feed → `EmptyFeedError`
    - Inject via monkeypatching `fetch_feed`/`fetch_symbol_metadata` — no network
    - _Requirements: 5.1, 5.2, 6.1, 6.2, 6.3, 6.4, 9.3_

- [x] 8. Checkpoint - retriever complete offline
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Rewrite `vpa/app_forex.py` to use the retriever
  - [x] 9.1 Replace the Selenium block with the browserless retriever call
    - Remove all `selenium` imports and the geckodriver/Firefox/download-folder logic
    - Call `my_df = get_daily_dataframe(symbol="GBPUSD")` passing the full daily history (do NOT `.tail(51)`) so the long-period SMA (200) stays enabled
    - Preserve `MarketAnalyzer(config_path=..., log_level="INFO", fixed_df=my_df, ticker_symbol="GBPUSD", log_prefix="GBPUSD")`, `process_data()`, `graph_intervals()`, and the BUY (`>= 15`) / SELL (`<= -15`) / DO NOT TRADE thresholds
    - _Requirements: 4.3, 4.4, 4.5, 4.6, 4.7, 10.1, 7.1, 7.2, 7.3_

  - [x] 9.2 Write signal-threshold and wiring tests for app_forex
    - With a stubbed `MarketAnalyzer`, `trade_signal` of 15/−15/0 logs BUY/SELL/DO NOT TRADE, and boundaries 14/−14 log DO NOT TRADE; with a mocked retriever returning a synthetic df, assert `MarketAnalyzer(fixed_df=..., ticker_symbol="GBPUSD")` is constructed and `process_data()`/`graph_intervals()` are called
    - _Requirements: 4.3, 4.4, 4.5, 4.6, 4.7_

- [x] 10. Remove the Selenium implementation and dependency
  - [x] 10.1 Delete `vpa/forex_auto/` and drop `selenium` from `requirements.txt`
    - Remove the `vpa/forex_auto/` package (e.g. `base_page.py`, `forex_home_page.py`) in its entirety and delete the `selenium` line from `requirements.txt`
    - _Requirements: 10.2, 10.3_

  - [x]* 10.2 Write no-Selenium and cross-platform smoke tests
    - Assert importing `vpa.forex_data` and `vpa.app_forex` pulls in no `selenium` module; assert `vpa/forex_auto/` no longer exists and `selenium` is absent from `requirements.txt`; assert the retriever source has no `sys.platform`/`os.name` branches, no hardcoded path separators (pathlib only), and no reference to `/home/mypi/Downloads`
    - _Requirements: 1.1, 7.1, 7.2, 7.3, 10.1, 10.2, 10.3_

- [x] 11. Final checkpoint - full suite green
  - Ensure all tests pass, ask the user if questions arise.

- [~] 12. Deploy and verify on the Raspberry Pi (RUNS ON THE PI — not a code task)
  - **This is the definition of done (Requirement 11) and the one task that is not a pure code/test change.** It runs on the Pi; see the `pi-access` steering for how to reach it. Keep SP-309 in **Mostly Done** until this completes.
  - Pull latest on the Pi and ensure the venv reflects the updated `requirements.txt` (selenium removed); confirm geckodriver/Firefox are not required
  - Run the scheduled job via the `Rundeck_Job` / `vpa/scripts/start_vpa_forex.sh` (or `python app_forex.py`) against live GBPUSD data and confirm a trade-signal log entry is produced
  - Once verified, move SP-309 to Done with a completion comment noting the deploy was done and verified
  - _Requirements: 11.1, 11.2, 11.3_

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP; they are still included in the dependency graph.
- Each task references specific requirements (and design properties where relevant) for traceability.
- Property tests validate the 9 universal correctness properties from the design; unit/example tests cover metadata lookup, error mapping, the sufficiency boundary, signal thresholds, multi-pair decoding, and no-Selenium/cross-platform checks.
- Task 12 is the only non-code task and must run on the Pi; the ticket stays in Mostly Done until it is deployed and verified there.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "3.1"] },
    { "id": 2, "tasks": ["2.2", "2.5", "3.2", "3.3", "3.4", "3.5", "3.6", "4.1"] },
    { "id": 3, "tasks": ["2.3", "2.4", "6.1"] },
    { "id": 4, "tasks": ["6.2", "7.1"] },
    { "id": 5, "tasks": ["7.2", "7.3", "7.4", "7.5", "7.6", "7.7"] },
    { "id": 6, "tasks": ["9.1"] },
    { "id": 7, "tasks": ["9.2", "10.1"] },
    { "id": 8, "tasks": ["10.2"] }
  ]
}
```
