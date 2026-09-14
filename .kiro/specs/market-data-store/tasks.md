# Implementation Plan: Market Data Store (SP-349)

## Overview

This plan builds a persistent, TimescaleDB-backed OHLCV store for the trading project
(Python throughout: pytest + hypothesis are already dependencies). It sequences work so
that **pure, locally-testable logic comes first** (dependency, connection helper,
normalisation, repository), followed by the verify/bootstrap and backfill scripts, then
consumer migration and the full property-based test suite — all of which can be built
and unit/integration-tested **locally** (against a local Postgres/TimescaleDB or a
mocked connection) with no dependency on the Pi.

The final section (**Infrastructure Migration, Task 12**) is an operator/deploy task
that is **DESTRUCTIVE**, touches the **shared** `my_postgres` server, and is **BLOCKED
on Betfair ticket SP-352**. It cannot be completed by code alone and must not run during
normal task execution. The store code and its tests are deliberately independent of that
migration — only the Pi deployment/verification is blocked on SP-352.

> **Convention:** all test tasks are required — the user promoted them, so no optional
> tasks remain. Every task in this plan is core and must be implemented. Each task cites
> the requirement clauses it satisfies.

## Tasks

- [x] 1. Add the psycopg2 dependency
  - Add `psycopg2-binary` to `requirements.txt` with a pinned version (matching Betfair usage).
  - Confirm `pandas`, `yfinance`, `hypothesis`, `pytest`, `pytest-cov` are already present; do not duplicate.
  - _Requirements: 9.3_

- [x] 2. Create the `vpa/market_data` package and DB connection helper
  - [x] 2.1 Scaffold the package
    - Create `vpa/market_data/__init__.py`.
    - _Requirements: 9.1_

  - [x] 2.2 Implement `vpa/market_data/db.py` (mirrors Betfair `verify_db.py`)
    - Define `REQUIRED_DB_KEYS = ["DB_HOST","DB_PORT","DB_NAME","DB_USER","DB_PWD"]` and `CONNECT_TIMEOUT_S = 10`.
    - `_read_db_config(env_path=None)` reads `DB_*` from `.env`; missing/empty become `""` so validation can report all.
    - `validate_env(config, required_keys)` returns the list of missing/empty required keys.
    - `connect(config=None)` opens a `psycopg2` connection with `connect_timeout=10`; `DB_NAME` points at the dedicated `market_data` database (NOT `bf_trader`); `DB_HOST` defaults to `my_postgres`.
    - `connect_maintenance(config=None)` opens an **autocommit** connection to the maintenance DB (`postgres`), used only for `CREATE DATABASE`.
    - _Requirements: 7.1, 7.2, 9.2_

  - [x] 2.3 Write unit tests for `validate_env` and config reading
    - Assert all missing keys reported when `.env` empty; none when complete; empty values treated as missing.
    - _Requirements: 7.1, 7.3_

- [x] 3. Implement centralised ingestion/normalisation (`vpa/market_data/ohlcv_ingest.py`)
  - [x] 3.1 Implement `normalise_yf_download(raw)` (pure, no network)
    - `reset_index()`, flatten a MultiIndex via `columns.get_level_values(0)`, case-insensitively rename to canonical names, `dropna(subset=[Open,High,Low,Close,Volume])`, `sort_values("Date")`, return exactly `CANONICAL_COLUMNS = [Date,Open,High,Low,Close,Volume]`.
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 3.2 Implement `to_store_rows(df, ticker, interval, source, adjusted)`
    - Map canonical rows to `(ticker, interval, ts, open, high, low, close, volume, adjusted, source)`; map `Date` to `ts` as a UTC bar-open timestamp (daily = midnight UTC).
    - _Requirements: 1.4, 4.5_

  - [x] 3.3 Implement `fetch_yf(ticker, interval, start, end)`
    - Thin `yf.download(auto_adjust=True, progress=False)` wrapper delegating to `normalise_yf_download`.
    - _Requirements: 4.1_

  - [x] 3.4 Write unit tests for `normalise_yf_download`
    - Cover MultiIndex input, flat input, case-insensitive rename, dropna, ascending sort, exact output columns.
    - _Requirements: 4.1, 4.2_

  - [x] 3.5 Write unit tests for `to_store_rows`
    - Assert `Date -> ts` UTC bar-open mapping (daily = midnight UTC) and tuple shape/order.
    - _Requirements: 1.4, 4.5_

- [x] 4. Implement the repository (`vpa/market_data/repository.py`)
  - [x] 4.1 Implement `MarketDataRepository.__init__` and `upsert_bars`
    - Constructor takes `conn_factory=connect`.
    - `upsert_bars(df, ticker, interval, source="yfinance", adjusted=True)` converts via `to_store_rows`, runs the `ON CONFLICT (ticker, interval, ts) DO UPDATE` SQL, commits, returns `{"inserted": n, "updated": m}` (use `xmax=0` to distinguish insert vs update).
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.4_

  - [x] 4.2 Implement `get_ohlcv` (offline read)
    - `SELECT ts,open,high,low,close,volume ... WHERE ticker/interval AND ts in [start,end] ORDER BY ts`; return canonical `Date,O,H,L,C,V` DataFrame ordered by `Date`; perform no network I/O.
    - _Requirements: 3.1_

  - [x] 4.3 Implement `load_ohlcv` (read-through, fetch only missing tail)
    - Read offline first via `get_ohlcv`; compute `expected_last`; if store missing/incomplete, `fetch_yf` only the missing tail, drop the incomplete final bar, `upsert_bars` (idempotent), re-read merged range.
    - Use `utils.utils.trading_days_between(start, end)` for daily gap detection.
    - _Requirements: 3.2, 3.3, 5.3_

  - [x] 4.4 Implement `export_ohlcv` (scoped CSV/Parquet)
    - Write the scoped range to CSV or Parquet at `path` (fmt-driven), return `path`; no standing full-history file.
    - _Requirements: 3.5, 3.6_

  - [x] 4.5 Write integration test: idempotency / append
    - Upsert the same bars twice against a test DB (or mocked conn); assert identical row set, no duplicates, and `inserted/updated` counts.
    - _Requirements: 2.2, 2.3, 2.4_

  - [x] 4.6 Write integration test: offline read performs no network I/O
    - Patch `yf.download` to raise if called; assert `get_ohlcv` and `export_ohlcv` succeed without invoking it.
    - _Requirements: 3.1, 3.6_

- [~] 5. Checkpoint — pure logic + repository verified
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Implement the verify/bootstrap script (`scripts/verify_market_data_db.py`)
  - [x] 6.1 Implement `verify_market_data_db(env_path=None)`
    - Read config + `validate_env`; if missing, return `{reachable:false, missing_config:...}` without connecting.
    - Step 1 (maintenance connection, autocommit): `SELECT 1 FROM pg_database WHERE datname='market_data'`; if absent run `CREATE DATABASE market_data` (never inside a transaction, never `IF NOT EXISTS`).
    - Step 2 (connection to `market_data`): run idempotent DDL — `CREATE SCHEMA/TABLE/INDEX IF NOT EXISTS` (exact SP-324 §7 columns + PK `(ticker,interval,ts)` + `ix_ohlcv_ticker_interval_ts`).
    - Return structured result: `reachable`, `missing_config`, `db_ready`, `schema_ready`, `created`, `error`.
    - _Requirements: 7.1, 7.2, 7.5, 7.6, 7.8, 1.1, 1.2, 1.3, 1.7_

  - [x] 6.2 Add TimescaleDB provisioning to the DDL
    - `CREATE EXTENSION IF NOT EXISTS timescaledb`; `create_hypertable('market_data.ohlcv','ts',if_not_exists=>TRUE)`; `ALTER TABLE ... SET (timescaledb.compress, compress_segmentby='ticker, interval')`; `add_compression_policy('market_data.ohlcv', INTERVAL '30 days')`.
    - Track created objects in `created` (`extension`,`hypertable`,`compression_policy`) so re-runs report `[]`.
    - _Requirements: 7.7, 8.1, 8.2, 8.3, 8.4_

  - [x] 6.3 Implement `main()` with exit codes
    - Print result; exit 2 on missing config, 1 on unreachable, 0 on success.
    - _Requirements: 7.3, 7.4, 7.9_

  - [x] 6.4 Write integration test: bootstrap idempotency (incl. Timescale)
    - Run twice against a Timescale-capable test DB; assert second run `created == []`, `ohlcv` still a hypertable on `ts`, exactly one compression policy.
    - _Requirements: 7.6, 7.7, 8.2, 8.3_

- [x] 7. Implement the backfill script (`scripts/backfill_market_data.py`)
  - [x] 7.1 Implement backfill CLI
    - Parse `--ticker`/`--interval`; `yf.download(period="max", auto_adjust=True, progress=False)`; `normalise_yf_download`; `upsert_bars` (idempotent); print result.
    - Document the invocation `python scripts/backfill_market_data.py --ticker SPY --interval 1d`.
    - _Requirements: 6.1, 6.2, 6.3_

  - [x] 7.2 Write backfill acceptance test for SPY
    - Backfill SPY `1d`, then read it back offline via `get_ohlcv`; assert non-empty, ordered, and idempotent on re-run.
    - _Requirements: 6.2, 6.3_

- [x] 8. Migrate consumers to the repository
  - [x] 8.1 Route `utils.utils.get_live_data_from_yfinance` through the Normaliser
    - Delegate its flatten/rename to `ohlcv_ingest.normalise_yf_download` (single source of truth); remove the duplicated logic.
    - _Requirements: 4.4_

  - [x] 8.2 Migrate `VPAFeatureExtractor.generate_dataset`
    - Source bars from `repo.load_ohlcv(ticker,"1d",start,end)`; preserve the 2000-row minimum check raising `InsufficientDataError`; keep the `Date,Open,High,Low,Close,Volume` columns.
    - _Requirements: 5.1, 4.4_

  - [x] 8.3 Migrate `MarketAnalyzer.load_data`
    - Replace `yf.download` with `repo.load_ohlcv(ticker,"1d",start,end)` (read-through); preserve the existing downstream column set/ordering.
    - _Requirements: 5.2, 4.4_

  - [x] 8.4 Migrate the all-shares scan (`vpa/app_all_shares.py`)
    - Build each `MarketAnalyzer` to read per-ticker via `repo.load_ohlcv`, so each run persists that day's bars idempotently.
    - _Requirements: 5.3_

  - [x] 8.5 Wire backtesting to scoped export
    - Add on-demand `repo.export_ohlcv(...)` so ML/feature generation and backtests read offline with no standing full-history file.
    - _Requirements: 5.4, 3.5, 3.6_

  - [x] 8.6 Write migration regression tests
    - Assert `generate_dataset` still raises `InsufficientDataError` under 2000 rows; assert migrated consumers do not call `yf.download` directly (patched to raise) when the store is warm.
    - _Requirements: 5.1, 5.2, 5.3_

- [~] 9. Checkpoint — scripts + consumer migration verified
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Property-based tests for the five correctness properties (hypothesis)
  - [x] 10.1 Property test — idempotency / PK invariant
    - **Property 1: Idempotency (PK invariant)** — `upsert_bars(B); upsert_bars(B)` yields the same rows as a single upsert, with no duplicate `(ticker, interval, ts)`.
    - **Validates: Requirements 11.1, 2.2, 2.3**

  - [x] 10.2 Property test — round-trip
    - **Property 2: Round-trip** — bars upserted then read via `get_ohlcv` equal `normalise_yf_download(input)` within float tolerance for the same ticker/interval/range.
    - **Validates: Requirements 11.2, 3.1**

  - [x] 10.3 Property test — offline read (no network I/O)
    - **Property 3: Offline read** — with `yf.download` patched to raise, `get_ohlcv` and `export_ohlcv` are never network-bound.
    - **Validates: Requirements 11.3, 3.1, 3.6**

  - [x] 10.4 Property test — read-through completeness
    - **Property 4: Read-through completeness** — `load_ohlcv` returns a contiguous set of trading-day bars (checked against `utils.utils.trading_days_between(start, end)`) and fetches only the missing tail (no full re-download when a prefix is covered).
    - **Validates: Requirements 11.4, 3.2, 3.3**

  - [x] 10.5 Property test — bootstrap idempotency incl. Timescale objects
    - **Property 5: Bootstrap idempotency (incl. Timescale)** — on an already-provisioned state, `verify_market_data_db` creates nothing (`created == []`), keeps `ohlcv` a hypertable on `ts`, and adds no duplicate compression policy.
    - **Validates: Requirements 11.5, 7.6, 7.7, 8.2, 8.3**

- [~] 11. Final checkpoint — full store buildable and tested locally
  - Ensure all unit, integration, and property-based tests pass locally (against a local Postgres/TimescaleDB or a mocked connection). At this point the entire store code is complete and verified **without** the Pi rebuild; only the shared-server deployment/verification below remains.
  - Ensure all tests pass, ask the user if questions arise.

---

## ⚠ 12. Infrastructure Migration — OPERATOR / DEPLOY TASK (DESTRUCTIVE, SHARED RESOURCE)

> **This task cannot be completed by code alone and MUST NOT run during normal task
> execution.** It is DESTRUCTIVE (drops the shared `my_postgres` server's databases),
> touches a resource shared with the Betfair project, and requires **explicit operator
> go-ahead at execution time**.
>
> **BLOCKED on Betfair ticket SP-352**, which must be completed first. SP-352 adds
> `bf.quality_run` and `bf.quality_match_result` to `bf_trader_py/build/sql/create_database.sql`
> and to `verify_db.py`'s required tables/DDL, and switches the `my_postgres` image in
> `bf_trader_py/build/postgres_build.sh` to a `timescale/timescaledb` arm64 tag
> (PG16-compatible). Until SP-352 is done, the rebuild would silently drop those two
> live tables — so the rebuild SHALL NOT proceed.
>
> **The trading store code (Tasks 1–11) is NOT blocked on SP-352** — it can be fully
> built and unit/integration/property-tested locally. Only the Pi deployment and its
> post-rebuild verification depend on SP-352.

- [~] 12.1 Confirm SP-352 complete and obtain operator go-ahead (operator action)
  - Verify SP-352 has landed (image swap in `postgres_build.sh`; `quality_*` tables in `create_database.sql` + `verify_db.py`).
  - Obtain explicit operator confirmation to proceed with the destructive, shared-resource rebuild. Do not proceed without it.
  - _Requirements: 10.1, 10.2, 10.3_

- [~] 12.2 Rebuild `my_postgres` on the TimescaleDB image (operator action, DESTRUCTIVE)
  - On the Pi, run `postgres_build.sh` to recreate the container on the Timescale arm64 image; this DROPS the server databases (acceptable per operator — Betfair data disposable). Preserve/recreate `my_trading_network` and `my_pgadmin` (the script already does this).
  - _Requirements: 10.1, 10.2_

- [~] 12.3 Restore both schemas post-rebuild (operator action)
  - Run Betfair `scripts/verify_db.py` to recreate all six `bf` tables (original four plus reconciled `bf.quality_run` and `bf.quality_match_result`).
  - Run trading `scripts/verify_market_data_db.py` to create the `market_data` database + schema + `ohlcv` hypertable + compression.
  - _Requirements: 10.4, 10.5_

- [~] 12.4 Post-rebuild verification on the Pi (operator action)
  - Confirm `CREATE EXTENSION timescaledb` succeeds; `market_data.ohlcv` is a hypertable; a smoke SPY backfill followed by an offline read works; Betfair capture still connects.
  - _Requirements: 10.6_

## Notes

- All test tasks were promoted to required — no optional tasks remain; every task is core and must be implemented.
- Each task references specific requirement clauses for traceability.
- Checkpoints (Tasks 5, 9, 11) ensure incremental validation.
- Property tests (Task 10) validate the five universal correctness properties from the design; unit/integration tests validate specific examples and edge cases.
- **Tasks 1–11 are coding tasks doable now and locally** (local Postgres/TimescaleDB or mocked connection); the store is not blocked on the Pi.
- **Task 12 is operator/deploy work**: DESTRUCTIVE, shared-resource, BLOCKED on Betfair SP-352, and requires explicit operator go-ahead. It cannot be completed by a coding agent.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "2.1"] },
    { "id": 1, "tasks": ["2.2"] },
    { "id": 2, "tasks": ["2.3", "3.1", "3.2"] },
    { "id": 3, "tasks": ["3.3", "3.4", "3.5", "4.1"] },
    { "id": 4, "tasks": ["4.2", "4.3", "4.4", "6.1"] },
    { "id": 5, "tasks": ["4.5", "4.6", "6.2", "7.1"] },
    { "id": 6, "tasks": ["6.3", "6.4", "7.2", "8.1"] },
    { "id": 7, "tasks": ["8.2", "8.3", "8.5"] },
    { "id": 8, "tasks": ["8.4", "8.6"] },
    { "id": 9, "tasks": ["10.1", "10.2", "10.3", "10.4", "10.5"] },
    { "id": 10, "tasks": ["12.1"] },
    { "id": 11, "tasks": ["12.2"] },
    { "id": 12, "tasks": ["12.3"] },
    { "id": 13, "tasks": ["12.4"] }
  ]
}
```
