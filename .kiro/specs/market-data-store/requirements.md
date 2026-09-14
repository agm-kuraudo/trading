# Requirements Document

## Introduction

SP-349 delivers a persistent market-data store so that OHLCV bars are **captured and
accumulated over time** in a dedicated PostgreSQL `market_data` database, rather than
re-fetched from yfinance on every run. yfinance becomes an ingestion source *behind*
the store; the VPA scan, feature-generation, and backtesting paths read from the store
and run fully offline. This is the BUILD following the SP-324 storage-strategy spike —
the technology (PostgreSQL + TimescaleDB) and the `market_data.ohlcv` schema are
already decided in the design and are not re-litigated here.

These requirements are **derived from** the approved design (`design.md`) and are kept
consistent with every decision already made there. They introduce no new technology
choices. Where relevant they reference the blocking Betfair schema-drift reconciliation
follow-up ticket (referred to here as SP-352), on which the destructive infrastructure
rebuild depends.

## Glossary

- **OHLCV**: A market-data bar carrying Open, High, Low, Close, and Volume values for a
  ticker over one interval of time.
- **Bar-open ts (UTC)**: The `ts` column — the bar's OPEN time expressed in UTC. Daily
  bars use midnight UTC of the trading day; intraday intervals (later) use the bar-open
  instant.
- **Hypertable**: A TimescaleDB table transparently partitioned on a time column
  (here `market_data.ohlcv` partitioned on `ts`), enabling time-series compression and
  chunk management.
- **Read-through**: A read that returns stored bars and, only when the store is
  stale/incomplete, fetches and persists just the missing tail from yfinance before
  returning the merged range.
- **Backfill**: A one-off seed of the deepest available yfinance history for a
  ticker+interval into the store.
- **Idempotent upsert**: An insert that uses `ON CONFLICT (ticker, interval, ts)` so
  that re-ingesting the same bar updates the existing row rather than creating a
  duplicate; re-running produces no additional rows.
- **Market_Data_Store**: The system under specification — the dedicated `market_data`
  database, its `market_data.ohlcv` hypertable, the repository/ingestion layer, and the
  verify/bootstrap and backfill scripts.
- **Repository**: `MarketDataRepository` — the data-access layer exposing
  `upsert_bars`, `get_ohlcv`, `load_ohlcv`, and `export_ohlcv`.
- **Bootstrap_Script**: `scripts/verify_market_data_db.py` — verifies and idempotently
  provisions the database, schema, table, index, and TimescaleDB objects.
- **Normaliser**: `ohlcv_ingest.normalise_yf_download` — the single canonical yfinance
  flatten/rename/dropna/sort routine.

## Requirements

### Requirement 1: Persistent OHLCV Store

**User Story:** As a trading-system operator, I want OHLCV bars persisted and
accumulated over time in a dedicated database, so that I own a proprietary dataset that
grows deeper than the yfinance lookback window and is decoupled from Betfair.

#### Acceptance Criteria

1. THE Market_Data_Store SHALL persist OHLCV bars in a dedicated `market_data`
   PostgreSQL database on the shared `my_postgres` server, separate from the Betfair
   `bf_trader` database.
2. THE Market_Data_Store SHALL store bars in a `market_data.ohlcv` table whose primary
   key is `(ticker, interval, ts)`.
3. THE Market_Data_Store SHALL define the `market_data.ohlcv` columns exactly as
   specified in SP-324 §7: `ticker TEXT`, `interval TEXT`, `ts TIMESTAMPTZ`,
   `open DOUBLE PRECISION`, `high DOUBLE PRECISION`, `low DOUBLE PRECISION`,
   `close DOUBLE PRECISION`, `volume DOUBLE PRECISION`, `adjusted BOOLEAN DEFAULT TRUE`,
   `source TEXT DEFAULT 'yfinance'`, and `ingested_at TIMESTAMPTZ DEFAULT now()`.
4. THE Market_Data_Store SHALL store `ts` as the bar-open time in UTC, using midnight
   UTC of the trading day for daily bars.
5. WHERE bars are captured over successive runs, THE Market_Data_Store SHALL retain
   previously captured bars so that the stored history accumulates over time.
6. THE Market_Data_Store SHALL accept the `interval` value `'1d'` and SHALL accept the
   additional values `'15m'`, `'1h'`, and `'4h'` without any structural schema change.
7. THE Market_Data_Store SHALL create an index
   `ix_ohlcv_ticker_interval_ts` on `market_data.ohlcv (ticker, interval, ts)`.

### Requirement 2: Idempotent Incremental Append

**User Story:** As a scheduled-job owner, I want re-running the same day to be safe, so
that repeated or overlapping runs never create duplicate bars.

#### Acceptance Criteria

1. WHEN bars are ingested via `upsert_bars`, THE Repository SHALL insert them using
   `ON CONFLICT (ticker, interval, ts) DO UPDATE`.
2. WHEN a bar with an existing `(ticker, interval, ts)` is re-ingested, THE Repository
   SHALL update the existing row rather than create a duplicate row.
3. WHEN the same set of bars is ingested twice, THE Repository SHALL leave the stored
   row count unchanged after the second ingestion.
4. WHEN `upsert_bars` completes, THE Repository SHALL return the count of inserted rows
   and the count of updated rows.

### Requirement 3: Repository / Data-Access Layer

**User Story:** As a consumer developer, I want a thin repository over the store, so
that I can read bars offline and let reads transparently top up the store from
yfinance.

#### Acceptance Criteria

1. WHEN `get_ohlcv(ticker, interval, start, end)` is called, THE Repository SHALL
   return the stored bars for the range as a canonical `Date, Open, High, Low, Close,
   Volume` DataFrame ordered by `Date`, without performing any network I/O.
2. WHEN `load_ohlcv(ticker, interval, start, end)` is called, THE Repository SHALL
   return bars from the store and, WHILE the store is stale or incomplete for the
   range, SHALL fetch and persist only the missing tail from yfinance before returning
   the merged range.
3. WHEN `load_ohlcv` determines the store already covers a prefix of the requested
   range, THE Repository SHALL fetch only the missing tail rather than re-downloading
   the full range.
4. WHEN `upsert_bars(df, ticker, interval)` is called, THE Repository SHALL persist the
   canonical DataFrame rows idempotently as defined in Requirement 2.
5. WHEN `export_ohlcv(ticker, interval, start, end, path, fmt)` is called, THE
   Repository SHALL write the scoped range to a CSV or Parquet file at `path` and SHALL
   return that path.
6. THE Repository SHALL NOT maintain a standing full-history flat-file copy; export
   SHALL be scoped to the requested range only.

### Requirement 4: Centralised yfinance Normalisation

**User Story:** As a maintainer, I want a single canonical yfinance normalisation
routine, so that the duplicated flatten/rename/dropna/sort logic across the codebase is
replaced by one source of truth.

#### Acceptance Criteria

1. THE Normaliser SHALL flatten a MultiIndex yfinance download to single-level columns,
   case-insensitively rename to the canonical names, drop rows with missing OHLCV
   values, and sort ascending by `Date`.
2. WHEN `normalise_yf_download(raw)` returns, THE Normaliser SHALL produce a DataFrame
   containing exactly the columns `Date, Open, High, Low, Close, Volume`.
3. THE Normaliser SHALL perform normalisation without any network I/O.
4. THE Market_Data_Store SHALL route `utils.utils.get_live_data_from_yfinance`,
   `MarketAnalyzer.load_data`, and `VPAFeatureExtractor.generate_dataset` through the
   Normaliser so that the previously duplicated normalisation logic is removed.
5. WHEN mapping canonical rows to store rows, THE Normaliser SHALL map `Date` to `ts`
   as a UTC bar-open timestamp.

### Requirement 5: Consumer Migration to the Store

**User Story:** As a system architect, I want all bar consumers to read from the
repository instead of calling yfinance directly, so that the scan, feature generation,
and backtesting paths run offline against the accumulated store.

#### Acceptance Criteria

1. WHEN `VPAFeatureExtractor.generate_dataset` obtains bars, THE Market_Data_Store SHALL
   source them from the Repository, and THE feature extractor SHALL preserve its
   2000-row minimum check, raising `InsufficientDataError` when fewer than 2000 rows are
   available.
2. WHEN `MarketAnalyzer.load_data` obtains bars, THE Market_Data_Store SHALL source them
   from the Repository via read-through, preserving the existing downstream column set.
3. WHEN the all-shares scan runs, THE Market_Data_Store SHALL source each ticker's bars
   from the Repository via read-through so that each run persists that day's bars
   idempotently.
4. WHEN the backtesting engine requires bars, THE Market_Data_Store SHALL provide them
   via a scoped `export_ohlcv`, and THE backtesting engine SHALL read offline without
   performing network I/O.

### Requirement 6: Backfill Deepest History

**User Story:** As an operator, I want to seed the deepest available history per
ticker, so that the store starts with maximum depth and later reads are mostly offline.

#### Acceptance Criteria

1. WHEN the backfill script is run for a ticker and interval, THE Market_Data_Store
   SHALL fetch the deepest available yfinance history, normalise it, and upsert it into
   the store.
2. WHEN the backfill script is re-run for the same ticker and interval, THE
   Market_Data_Store SHALL upsert idempotently, adding no duplicate bars.
3. THE Market_Data_Store SHALL provide a documented backfill invocation
   (`python scripts/backfill_market_data.py --ticker SPY --interval 1d`) and SHALL be
   exercised for at least the `SPY` ticker as acceptance evidence.

### Requirement 7: Verify / Bootstrap Script

**User Story:** As an operator, I want an idempotent verify/bootstrap script that
mirrors Betfair's convention, so that first-run provisioning and repeated health checks
behave predictably and fail loudly.

#### Acceptance Criteria

1. THE Bootstrap_Script SHALL read the `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and
   `DB_PWD` keys from `.env`, with `DB_NAME` pointing at the dedicated `market_data`
   database.
2. WHEN opening a connection, THE Bootstrap_Script SHALL use `psycopg2` with a
   `connect_timeout` of 10 seconds, mirroring Betfair's `verify_db.py` convention.
3. IF required DB configuration keys are missing or empty, THEN THE Bootstrap_Script
   SHALL report the missing keys, SHALL NOT attempt a connection, and SHALL exit with
   code 2.
4. IF the database server is unreachable within the connect timeout, THEN THE
   Bootstrap_Script SHALL report the failure and SHALL exit with code 1.
5. IF the dedicated `market_data` database is absent, THEN THE Bootstrap_Script SHALL
   create it via a maintenance-database connection in autocommit mode, because
   `CREATE DATABASE` cannot run inside a transaction.
6. WHEN the dedicated database is present, THE Bootstrap_Script SHALL ensure the
   `market_data` schema, the `ohlcv` table, and the `ix_ohlcv_ticker_interval_ts` index
   exist, creating each only if absent.
7. WHEN provisioning the store, THE Bootstrap_Script SHALL enable the `timescaledb`
   extension, convert `market_data.ohlcv` to a hypertable on `ts`, configure native
   compression segmented by `ticker, interval`, and add a compression policy for chunks
   older than 30 days.
8. WHEN provisioning completes, THE Bootstrap_Script SHALL return a structured result
   reporting reachability, missing configuration, database readiness, schema readiness,
   the list of objects created, and any error.
9. WHEN provisioning succeeds, THE Bootstrap_Script SHALL exit with code 0.

### Requirement 8: TimescaleDB Enablement

**User Story:** As a data owner, I want TimescaleDB enabled at provisioning time, so
that the store gains time-series compression on the Pi's constrained disk without a
later migration.

#### Acceptance Criteria

1. THE Market_Data_Store SHALL enable the `timescaledb` extension in the dedicated
   `market_data` database.
2. THE Market_Data_Store SHALL configure `market_data.ohlcv` as a hypertable
   partitioned on `ts`.
3. THE Market_Data_Store SHALL enable native columnar compression on
   `market_data.ohlcv`, segmented by `ticker, interval`, for chunks older than 30 days.
4. THE Market_Data_Store SHALL preserve the SP-324 §7 primary key `(ticker, interval,
   ts)` unchanged, relying on `ts` already being part of the key for hypertable
   compatibility.

### Requirement 9: Cross-Platform Support and Dependencies

**User Story:** As a developer working on both the Pi and Windows, I want the store to
run on both platforms, so that development and production behave identically.

#### Acceptance Criteria

1. THE Market_Data_Store SHALL run on ARM Linux (the Raspberry Pi capture host) and on
   Windows x64 (developer machines).
2. THE Market_Data_Store SHALL resolve `DB_HOST=my_postgres` via Docker DNS on the Pi
   and via a hosts-file mapping of `my_postgres` to `127.0.0.1` on Windows, matching the
   Betfair convention.
3. THE Market_Data_Store SHALL add `psycopg2` (pinned `psycopg2-binary`, matching
   Betfair usage) to `requirements.txt`.

### Requirement 10: Infrastructure Migration Prerequisite (my_postgres → TimescaleDB)

**User Story:** As an operator, I want the shared `my_postgres` container rebuilt on a
TimescaleDB-capable image safely, so that the store can be provisioned without silently
losing Betfair's live tables.

#### Acceptance Criteria

1. THE Market_Data_Store SHALL require the `my_postgres` container (defined in
   `bf_trader_py/build/postgres_build.sh`) to be rebuilt on a `timescale/timescaledb`
   arm64 image compatible with PostgreSQL 16, via a one-line image change in that
   script.
2. THE infrastructure rebuild SHALL be treated as a destructive, shared-resource step
   that drops the server's databases, and IF the operator has not given explicit
   go-ahead, THEN the rebuild SHALL NOT proceed.
3. THE infrastructure rebuild SHALL be blocked on the Betfair schema-drift
   reconciliation follow-up ticket (SP-352), which adds `bf.quality_run` and
   `bf.quality_match_result` to `create_database.sql` and to `verify_db.py`'s required
   tables, and switches the image in `postgres_build.sh`; the rebuild SHALL NOT proceed
   until SP-352 is complete.
4. WHEN the rebuild is complete, THE Market_Data_Store SHALL restore the Betfair schema
   by running `scripts/verify_db.py`, recreating all six `bf` tables (the original four
   plus the reconciled `bf.quality_run` and `bf.quality_match_result`).
5. WHEN the rebuild is complete, THE Market_Data_Store SHALL restore the trading schema
   by running `scripts/verify_market_data_db.py` to create the dedicated `market_data`
   database, schema, `ohlcv` hypertable, and compression.
6. WHEN post-rebuild verification is performed, THE Market_Data_Store SHALL confirm that
   `CREATE EXTENSION timescaledb` succeeds, that `market_data.ohlcv` is a hypertable,
   that a smoke SPY backfill followed by an offline read works, and that Betfair capture
   still connects.

### Requirement 11: Correctness Properties (Property-Based Testing)

**User Story:** As a quality owner, I want the store's core invariants expressed as
testable properties, so that property-based tests validate correctness across many
generated inputs.

#### Acceptance Criteria

1. FOR ALL sets of bars, upserting the set twice SHALL yield the same stored rows as
   upserting it once, with no duplicate `(ticker, interval, ts)` (idempotency / PK
   invariant).
2. FOR ALL normalised bar sets, reading back via `get_ohlcv` over the same
   ticker/interval/range SHALL equal the normalised input within float tolerance
   (round-trip).
3. WHEN `get_ohlcv` or `export_ohlcv` is invoked, THE Repository SHALL perform no
   network I/O (offline read), verifiable by asserting a patched `yf.download` is never
   called.
4. FOR ALL requested ranges, `load_ohlcv` SHALL return a contiguous set of trading-day
   bars — with no missing days the source could provide, checked against
   `utils.utils.trading_days_between(start, end)` — while fetching only the missing tail
   (read-through completeness).
5. FOR ALL already-provisioned states, running `verify_market_data_db` SHALL be a no-op
   that creates nothing (`created == []`), keeps `market_data.ohlcv` a hypertable on
   `ts`, and adds no duplicate compression policy (bootstrap idempotency including
   Timescale objects).
