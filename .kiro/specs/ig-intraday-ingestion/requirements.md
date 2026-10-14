# Requirements Document

## Introduction

SP-379 is the BUILD that implements the data-ingestion decision made by the SP-342
spike: pull intraday OHLCV (`15m` / `1h` / `4h`) for the manually-traded **US 500**
spread-bet instrument from the **IG REST API**, normalise it to the canonical OHLCV shape, and land
it in the SP-349 `market_data.ohlcv` store. It adds an allowance-aware backfill that
seeds history within IG's 10,000-points/week budget, a grow-forward maintenance job that
keeps the store current, a yfinance intraday baseline fix, and session-aware intraday
read-through. This is the data enabler for the 0.7 intraday spine and blocks SP-350
(multi-timeframe VPA analysis).

These requirements are **derived from** the approved design (`design.md`) and are kept
consistent with every decision already made there. The source, instrument, intervals,
and storage are already decided by SP-342 and SP-349 and are not re-litigated here, with
the single exception of the `4h` interval — the SP-379 scope addition sourced from native
IG `HOUR_4` if the epic supports it, otherwise derived by resampling the stored `1h`
series. The build is **strictly read-only** against IG: session login plus `GET /prices`
only; no
deal/order/position functionality is in scope. Where the design's Correctness Properties
reference requirement IDs, those IDs match the numbering below so the cross-references
stay valid.

## Glossary

- **OHLCV**: A market-data bar carrying Open, High, Low, Close, and Volume values for a
  ticker over one interval of time.
- **Bar-open ts (UTC)**: The `ts` column — the bar's OPEN time expressed in UTC, derived
  for IG bars from the IG `snapshotTime`.
- **Intervals**: The three intraday bar sizes SP-379 ingests — `15m` and `1h` (pulled
  natively from IG per SP-342) and `4h` (the SP-379 scope addition: native IG `HOUR_4` if
  the epic supports it, otherwise derived by resampling the stored `1h` series).
- **4h resample**: Deriving a `4h` bar from the stored `1h` series over a fixed 4-hour
  grid aligned to the session: `Open` = first `1h` Open, `High` = max, `Low` = min,
  `Close` = last `1h` Close, `Volume` = sum, labelled by the bar-OPEN ts in UTC. Used when
  native IG `HOUR_4` is unsupported; costs zero extra IG allowance.
- **Mid-price**: `(bid + ask) / 2` computed per OHLC field from an IG price object; the
  price value SP-379 stores by default.
- **Epic**: The IG instrument identifier `IX.D.SPTRD.DAILY.IP` ("US 500", SPREADBET,
  GBP); used as the `ticker` tag for IG bars so they never collide with the yfinance
  `SPY` baseline.
- **IG_Client**: `vpa/market_data/ig_client.py` — the read-only IG REST client exposing
  `login` (session) and `fetch_prices` (`GET /prices`) only.
- **IG_Normaliser**: `vpa/market_data/ig_ingest.normalise_ig_prices` — maps an IG
  `/prices` payload to the canonical `Date, Open, High, Low, Close, Volume` DataFrame
  using mid-price.
- **Weekly allowance**: IG's historical-data budget of 10,000 points per week
  (`allowanceExpiry` ~604800s); a point corresponds to one fetched bar.
- **SAFETY_FLOOR**: The minimum remaining allowance (default 500) a run must leave
  unspent so an over-pull cannot lock the account out of historical data for the week.
- **Repository**: `MarketDataRepository` (SP-349) — exposes `upsert_bars`, `get_ohlcv`,
  `load_ohlcv`, `export_ohlcv`, and the `_expected_last` /
  `_drop_incomplete_final_bar` hooks.
- **Read-through**: A read that returns stored bars and, only when the store is
  stale/incomplete for the range, fetches and persists just the missing tail before
  returning the merged range.
- **Idempotent upsert**: An insert using `ON CONFLICT (ticker, interval, ts) DO UPDATE`
  so re-ingesting the same bar updates the existing row rather than creating a duplicate.
- **Grow_Forward_Job**: The scheduled maintenance job
  (`vpa/scripts/grow_forward_intraday.py` plus its shell entrypoint and Rundeck
  definition) that keeps `15m`, `1h`, and `4h` bars current on the Pi.
- **IG_Ingestion**: The system under specification — the IG client, IG normalisation,
  allowance-aware backfill, grow-forward job, yfinance intraday fix, and session-aware
  intraday read-through that together land `source="ig"` intraday bars in the store.

## Requirements

### Requirement 1: Read-Only IG Client

**User Story:** As a trading-system operator, I want a read-only IG REST client that
authenticates and fetches historical prices, so that intraday US 500 data can be
ingested without exposing any order or position capability.

#### Acceptance Criteria

1. WHEN `IG_Client.login` is called with valid credentials, THE IG_Client SHALL perform
   a `POST /session` (Version 2) request, capture the `CST` and `X-SECURITY-TOKEN`
   headers, and hold the session with an expiry of 12 hours reset on use.
2. WHEN `IG_Client.fetch_prices(epic, resolution, num_points)` is called with a valid
   session, THE IG_Client SHALL perform a `GET /prices/{epic}/{resolution}/{num_points}`
   request and return the parsed `prices` bars together with the `allowance` block.
3. THE IG_Client SHALL expose only session login and historical price retrieval and
   SHALL NOT implement or import any deal, order, or position endpoint.
4. THE IG_Client SHALL read the live credentials `IG_API_KEY`, `IG_USER_ID`, and
   `IG_PWD`, or the demo credentials `IG_DEMO_API_KEY`, `IG_DEMO_USER_ID`, and
   `IG_DEMO_PWD`, from `.env` via the existing `_parse_env_file` without adding a new
   dependency and without hardcoding any secret.
5. IF any required IG credential key is missing or empty, THEN THE IG_Client SHALL
   report the full set of missing keys and SHALL NOT perform any HTTP request.
6. IF `POST /session` returns a non-200 response, THEN THE IG_Client SHALL raise
   `IGAuthError` and SHALL hold no session tokens.

### Requirement 2: IG Normalisation to Canonical Mid-Price OHLCV

**User Story:** As a maintainer, I want IG price payloads normalised to the canonical
OHLCV shape, so that IG bars flow through the same store-mapping and upsert path as
yfinance bars.

#### Acceptance Criteria

1. WHEN `normalise_ig_prices(raw)` is called, THE IG_Normaliser SHALL map each IG bar's
   bid/ask OHLC fields to the canonical columns `Date, Open, High, Low, Close, Volume`
   and SHALL return a DataFrame containing exactly those columns.
2. THE IG_Normaliser SHALL store the mid-price `(bid + ask) / 2`, computed per OHLC
   field, as the Open, High, Low, and Close values by default.
3. WHEN mapping an IG bar, THE IG_Normaliser SHALL set `Volume` from `lastTradedVolume`,
   drop rows with any missing OHLCV value, and sort the result ascending by `Date`.
4. WHEN mapping an IG bar, THE IG_Normaliser SHALL parse the IG `snapshotTime` into a
   timezone-aware UTC bar-open timestamp used as the stored `ts`.
5. WHEN IG bars are persisted, THE IG_Ingestion SHALL tag them with `source="ig"` and
   `adjusted=FALSE`.
6. WHEN producing `4h` bars, THE IG_Ingestion SHALL first probe IG's `HOUR_4` resolution
   for the epic, and IF `HOUR_4` returns usable OHLC and volume THEN THE IG_Ingestion
   SHALL fetch `4h` natively on the same path as `15m`/`1h`, ELSE THE IG_Ingestion SHALL
   derive each `4h` bar by resampling the stored `1h` series over a fixed 4-hour grid
   aligned to the session such that `Open` is the first `1h` bar's Open, `High` is the
   window maximum High, `Low` is the window minimum Low, `Close` is the last `1h` bar's
   Close, and `Volume` is the sum of the window's Volume, labelling each `4h` bar by its
   bar-open timestamp in UTC; and in either path THE IG_Ingestion SHALL store the bars
   with `source="ig"`, `interval="4h"`, and `adjusted=FALSE`.

### Requirement 3: Allowance-Aware Backfill

**User Story:** As an operator, I want the IG backfill to respect the weekly allowance,
so that seeding history never exhausts IG's historical-data budget and remains resumable
across weeks.

#### Acceptance Criteria

1. WHEN planning a backfill run, THE IG_Ingestion SHALL respect IG's 10,000-points-per-
   week allowance by deriving the per-run point budget from the latest
   `allowance.remainingAllowance`.
2. WHEN the planned or observed remaining allowance would fall below `SAFETY_FLOOR`, THE
   IG_Ingestion SHALL stop before issuing a fetch that would breach the floor and SHALL
   report the deferred points.
3. WHERE the target interval is `1h`, THE IG_Ingestion SHALL seed approximately two years
   (~3,500 points) in a single within-budget run, and WHERE the target interval is `15m`,
   THE IG_Ingestion SHALL seed incrementally across successive weekly runs within budget.
4. WHEN a backfill window overlaps bars already stored, THE IG_Ingestion SHALL upsert
   idempotently so that a resumed run adds no duplicate bars.
5. WHEN seeding `4h` history, IF native `HOUR_4` is supported for the epic THEN THE
   IG_Ingestion SHALL spend IG allowance for the `4h` pull in the same allowance-aware
   manner as `1h`, ELSE THE IG_Ingestion SHALL derive `4h` from the already-stored `1h`
   series without issuing any additional IG request and therefore SHALL spend zero extra
   allowance, requiring the `1h` series to be present first.

### Requirement 4: yfinance Intraday Baseline Fix

**User Story:** As a maintainer, I want the yfinance intraday backfill fixed to use a
bounded period, so that a free 1h baseline remains available alongside the IG data for
cross-checking.

#### Acceptance Criteria

1. WHEN the yfinance intraday backfill fetches `1h` bars, THE IG_Ingestion SHALL request
   `period="730d"` rather than `period="max"`, because `period="max"` returns an empty
   result for `1h` per SP-342.
2. WHEN yfinance `1h` baseline bars are stored, THE IG_Ingestion SHALL tag them with
   `source="yfinance"` and ticker `SPY` so that they coexist with the IG rows without
   either source overwriting the other.

### Requirement 5: Grow-Forward Maintenance and Intraday Read-Through

**User Story:** As a scheduled-job owner, I want intraday reads to detect gaps correctly
and a scheduled job to keep the store current, so that new 15m, 1h, and 4h bars land
automatically without storing partial bars.

#### Acceptance Criteria

1. WHEN `_expected_last(interval, start, end)` is called for an intraday interval, THE
   Repository SHALL return the open time of the last completed session bar on or before
   `end`, and SHALL return no expected-last when the range contains no session time.
2. WHEN the grow-forward job runs for `15m` and `1h`, THE Repository SHALL land new bars
   idempotently via `load_ohlcv` read-through, fetching only the missing tail and
   dropping the incomplete in-progress final bar before persisting.
3. THE IG_Ingestion SHALL provide a scheduled grow-forward job defined as a Rundeck job
   on the Pi, mirroring the existing `vpa/jobs/*.yaml` job definitions.
4. WHEN the grow-forward job maintains `4h`, IF native `HOUR_4` is supported THEN THE
   Repository SHALL grow `4h` forward via the same read-through tail fetch as `15m`/`1h`,
   ELSE THE IG_Ingestion SHALL recompute and upsert the affected `4h` bars by resampling
   the freshly-updated `1h` tail without issuing an additional IG request, idempotently
   and after the `1h` tail has been refreshed.

### Requirement 6: Testing and Quality

**User Story:** As a quality owner, I want the IG ingestion covered by hermetic unit and
property tests that keep the suite clean, so that correctness is validated without any
live IG calls.

#### Acceptance Criteria

1. THE IG_Ingestion unit tests SHALL mock the IG HTTP layer so that the test suite makes
   no live IG calls, adding an IG equivalent of the existing `no_network` guard.
2. THE IG_Ingestion SHALL provide hypothesis property tests covering mid-price,
   normalisation output shape, allowance planning, and idempotent ingestion.
3. WHEN the quality checks are run, THE IG_Ingestion SHALL pass `ruff check` and
   `ruff format --check` cleanly and SHALL pass the full `pytest -m ""` suite.

### Requirement 7: Deployment to the Pi (Definition of Done)

**User Story:** As an operator, I want the ingestion deployed and verified on the
Raspberry Pi, so that intraday IG bars accumulate in production rather than only on a
developer machine.

#### Acceptance Criteria

1. THE IG_Ingestion SHALL require the live `IG_*` credentials to be present in the Pi's
   gitignored `.env` before the grow-forward job runs in production.
2. WHEN deploying, THE IG_Ingestion SHALL be pulled onto the Pi and the container rebuilt
   via the project's deploy mechanism before the ticket moves to Done.
3. WHEN deployed, THE Grow_Forward_Job SHALL be installed, scheduled, and running on the
   Pi.
4. WHEN the grow-forward job has run on the Pi, THE IG_Ingestion SHALL have landed bars
   with `source="ig"` in the Pi `my_postgres` store, verifiable by a read-only SELECT of
   row counts and the latest `ts`.
5. WHILE the ingestion code is complete but not yet deployed and verified on the Pi, THE
   IG_Ingestion SHALL remain in Mostly Done rather than Done.

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid
executions of a system — essentially, a formal statement about what the system should
do. Properties serve as the bridge between human-readable specifications and
machine-verifiable correctness guarantees.*

### Property 1: Mid is bracketed

For any IG OHLC field, the mid-price lies within `[min(bid, ask), max(bid, ask)]`, and
when `bid == ask` it equals both.

**Validates: Requirements 2.2**

### Property 2: Canonical output shape

For any IG `/prices` payload, `normalise_ig_prices` returns exactly the canonical
columns in order, sorted ascending by `Date`, with no missing value in any OHLCV column.

**Validates: Requirements 2.1, 2.3**

### Property 3: UTC bar-open

For any normalised IG bar, the stored `ts` is a timezone-aware UTC timestamp equal to the
bar-open instant parsed from `snapshotTime`, with no naive timestamp reaching the store.

**Validates: Requirements 2.4**

### Property 4: Idempotent ingestion

For any set of IG bars, upserting the set twice changes the stored row count by zero, and
re-pulling an overlapping backfill window inserts no new rows.

**Validates: Requirements 3.4, 5.2**

### Property 5: Allowance never over-spent

For any backfill plan, the planned run satisfies `0 <= this_run <= target_points` and
`this_run <= max(0, remaining - SAFETY_FLOOR)`, so a run never drives the remaining
allowance below `SAFETY_FLOOR`.

**Validates: Requirements 3.1, 3.2, 3.3**

### Property 6: Session-aware expectation

For any intraday range, `_expected_last` returns the last completed session bar-open on
or before `end` (never `end` itself mid-bar or out-of-hours) and no expected-last for a
range containing no session time, and is monotonic in `end`.

**Validates: Requirements 5.1**

### Property 7: Read-only surface

For any usage of `IGClient`, the client exposes only session login and historical price
retrieval and has no attribute or method that places, amends, or closes a
deal/order/position.

**Validates: Requirements 1.3**

### Property 8: Source isolation

For any combination of IG rows (`source="ig"`, ticker = epic) and yfinance baseline rows
(`source="yfinance"`, ticker = `SPY`), neither source overwrites the other.

**Validates: Requirements 2.5, 4.2**

### Property 9: 4h resample integrity

For any contiguous `1h` series, a derived `4h` bar's `Open` equals the first `1h` bar's
Open, `High` equals the window maximum High, `Low` equals the window minimum Low, `Close`
equals the last `1h` bar's Close, and `Volume` equals the sum of the window's Volume, over
its fixed 4-hour window labelled by the bar-open timestamp in UTC; and whether sourced
natively (`HOUR_4`) or derived, every `4h` bar carries `source="ig"`, `interval="4h"`, and
`adjusted=FALSE`.

**Validates: Requirements 2.6, 3.5, 5.4**
