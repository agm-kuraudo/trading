# Implementation Plan: IG Intraday OHLCV Ingestion + Allowance-Aware Backfill (SP-379)

## Overview

This plan builds IG intraday (`15m` / `1h` / `4h`) OHLCV ingestion for the US 500
spread-bet instrument and lands it in the SP-349 `market_data.ohlcv` store (Python
throughout; `4h` is the SP-379 scope addition — native IG `HOUR_4` if the epic supports
it, otherwise derived by resampling the stored `1h` series;
`pandas` / `psycopg2` / `requests` are the stack, and `pytest` + `hypothesis` are
already dependencies). It sequences work so **pure, locally-testable logic comes first**
(read-only IG client, mid-price normalisation, allowance planning), then the
session-aware repository read-through, then the allowance-aware backfill CLI, the
yfinance intraday fix, and the grow-forward job (entrypoint + Rundeck wiring). Property
and unit tests sit next to the code they cover, and the suite stays hermetic — no live
IG calls — via a new `no_ig_network` guard mirroring the existing `no_network` fixture.

The build is **strictly read-only** against IG (session login + `GET /prices` only; no
deal/order/position surface). IG bars are stored as **mid-price** under the epic ticker
`IX.D.SPTRD.DAILY.IP` with `source="ig"`, `adjusted=FALSE`, coexisting with the
yfinance `SPY` baseline without either overwriting the other.

The final section (**Pi Deployment, Task 10**) is an operator/deploy task group that is
the Definition of Done for this deployable work: the ticket stays in **Mostly Done**
until `source="ig"` bars are verified in the Pi `my_postgres` store. The `pi-access`
steering is **read-only by default** — the write/deploy actions on the Pi require
explicit operator go-ahead at execution time.

> **Convention:** test sub-tasks are marked optional with `*` per the workflow; core
> implementation and the deployment steps are never optional. Each task cites the
> requirement clauses it satisfies, and each property test names the design Property it
> validates.

## Tasks

- [x] 1. Confirm the `requests` dependency and scaffold the IG client module
  - Confirm `requests` is available in `requirements.txt` (it is a transitive dependency via yfinance); if it is not a direct dependency, add it pinned — no exotic new package.
  - Confirm `pandas`, `hypothesis`, `pytest` are already present; do not duplicate.
  - Create `vpa/market_data/ig_client.py` with module-level constants `IG_LIVE_KEYS`, `IG_DEMO_KEYS`, `IG_LIVE_BASE`, `IG_DEMO_BASE`, `SESSION_TTL_S = 12 * 60 * 60`.
  - _Requirements: 1.4, 6.3_

- [x] 2. Implement IG credentials + read-only IG client (`vpa/market_data/ig_client.py`)
  - [x] 2.1 Implement `read_ig_config` and `validate_ig_env`
    - `read_ig_config(demo, env_path=None)` reads `IG_API_KEY`/`IG_USER_ID`/`IG_PWD` (live) or `IG_DEMO_*` (demo) from `.env` via the existing `vpa.market_data.db._parse_env_file`; missing/empty become `""`. No new dependency, no hardcoded secrets.
    - `validate_ig_env(config, required_keys)` returns the full subset of missing/empty required keys (mirrors `db.validate_env`).
    - _Requirements: 1.4, 1.5_

  - [ ]* 2.2 Write unit tests for config reading and validation
    - Assert all missing keys reported when `.env` is empty; none when complete; empty values treated as missing; demo flag selects the `IG_DEMO_*` key set.
    - _Requirements: 1.4, 1.5_

  - [x] 2.3 Implement `IGClient.__init__` and `login`
    - Constructor signature `__init__(self, *, demo=False, env_path=None, http=requests)` with the `http` transport injectable for hermetic tests; select base URL by `demo`.
    - `login()` validates env first (raise/report on missing keys, no HTTP), then `POST {base}/session` (Version 2) with `X-IG-API-KEY` header + `{identifier, password}`; capture `CST` + `X-SECURITY-TOKEN` from response headers; hold the session with expiry `now + SESSION_TTL_S` (reset-on-use). Raise `IGAuthError` on non-200, holding no tokens.
    - _Requirements: 1.1, 1.5, 1.6_

  - [x] 2.4 Implement `fetch_prices`
    - `fetch_prices(epic, resolution, num_points)` ensures a valid (non-expired) session, re-logging in on expiry; `GET {base}/prices/{epic}/{resolution}/{num_points}` with auth headers + `Version: 2`; return `{"prices": [...], "allowance": {...}}` parsed from JSON. Read-only; `resolution` in `{MINUTE_15, HOUR}`.
    - Do NOT add any deal/order/position method or import — the read-only guarantee is structural (by omission).
    - _Requirements: 1.2, 1.3_

  - [ ]* 2.5 Write unit tests for `login`/`fetch_prices` against a mocked HTTP transport
    - `login` captures tokens from mocked response headers; non-200 raises `IGAuthError` with no tokens held; `fetch_prices` builds the right URL/headers and parses `prices` + `allowance`.
    - Assert the read-only surface: `IGClient` has no attribute/method that places, amends, or closes a deal/order/position.
    - _Requirements: 1.1, 1.2, 1.3, 1.6_

  - [ ]* 2.6 Property test — read-only surface
    - **Property 7: Read-only surface** — `IGClient` exposes only `login` and `fetch_prices` and has no deal/order/position attribute or method.
    - **Validates: Requirements 1.3**

- [x] 3. Implement IG normalisation to canonical mid-price OHLCV (`vpa/market_data/ig_ingest.py`)
  - [x] 3.1 Implement `_mid` and `normalise_ig_prices`
    - Add constants `IG_RESOLUTION = {"15m": "MINUTE_15", "1h": "HOUR"}` and `IG_SNAPSHOT_FMT = "%Y:%m:%d-%H:%M:%S"`.
    - `_mid(field)` returns `(bid + ask) / 2` for one IG OHLC field object; raise if both bid and ask are None.
    - `normalise_ig_prices(raw)` is pure (no network): for each bar in `raw["prices"]`, parse `snapshotTime` into a tz-aware UTC `Date`, set `Open/High/Low/Close` from `_mid(openPrice/highPrice/lowPrice/closePrice)`, set `Volume` from `lastTradedVolume`; then `dropna` on OHLCV, `sort_values("Date")`, and return exactly `ohlcv_ingest.CANONICAL_COLUMNS` in order.
    - Reuse `ohlcv_ingest.to_store_rows` for the store mapping (no change to `to_store_rows` required); the output contract mirrors `normalise_yf_download` so IG rows flow through the same `upsert_bars` path tagged `source="ig"`, `adjusted=FALSE`.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [ ]* 3.2 Write unit tests for `_mid` and `normalise_ig_prices`
    - `_mid` on representative bid/ask field objects; `normalise_ig_prices` on a representative IG payload: mid computation per field, UTC `snapshotTime` parse, `lastTradedVolume` -> Volume, dropna of partial bars, ascending sort, exact `CANONICAL_COLUMNS`.
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [ ]* 3.3 Property test — mid is bracketed
    - **Property 1: Mid is bracketed** — for arbitrary bid/ask, `_mid(field)` lies in `[min(bid, ask), max(bid, ask)]`; with `bid == ask` it equals both.
    - **Validates: Requirements 2.2**

  - [ ]* 3.4 Property test — canonical output shape
    - **Property 2: Canonical output shape** — `normalise_ig_prices(raw)` returns exactly `CANONICAL_COLUMNS` in order, sorted ascending by `Date`, with no NaN in any OHLCV column.
    - **Validates: Requirements 2.1, 2.3**

  - [ ]* 3.5 Property test — UTC bar-open
    - **Property 3: UTC bar-open** — every normalised `ts` is tz-aware UTC and equals the bar-open instant parsed from `snapshotTime`; no naive timestamp survives normalisation.
    - **Validates: Requirements 2.4**

  - [x] 3.6 Implement 4h native-probe + resample-from-1h (`vpa/market_data/ig_ingest.py`)
    - Add `"4h": "HOUR_4"` to `IG_RESOLUTION` (used only when the native probe succeeds). Reference IG's documented resolution enum including `HOUR_4` (IG Labs: https://labs.ig.com/reference/prices-epic-resolution-numpoints.html); SP-342 validated only `MINUTE_15`/`HOUR` for this epic, so `HOUR_4` support is unknown until probed.
    - `probe_hour4(client, epic)` issues one small read-only `GET /prices` for `HOUR_4` via the injected transport and returns `True` iff IG returns usable OHLC + volume (non-empty, mid-computable, with `lastTradedVolume`); `False`/empty -> derive path.
    - `resample_1h_to_4h(df_1h)` is pure (no network): group the ascending `1h` series into fixed 4-hour windows aligned to the session; for each non-empty window emit `Open` = first `1h` Open, `High` = max High, `Low` = min Low, `Close` = last `1h` Close, `Volume` = sum Volume, `Date` = the first `1h` bar's bar-open ts (UTC); return exactly `ohlcv_ingest.CANONICAL_COLUMNS`.
    - Either path flows through `MarketDataRepository.upsert_bars(df, epic, "4h", source="ig", adjusted=False)`. Native path spends allowance like `1h`; derived path spends ZERO extra allowance (reads the stored `1h` series, requires `1h` present first).
    - _Requirements: 2.6, 3.5_

  - [ ]* 3.7 Property test — 4h resample integrity
    - **Property 9: 4h resample integrity** — for an arbitrary contiguous `1h` series, each derived `4h` bar has `Open`=first, `High`=max, `Low`=min, `Close`=last, `Volume`=sum over its fixed 4-hour window, labelled by the bar-open ts in UTC; derived (and native) `4h` rows carry `source="ig"`, `interval="4h"`, `adjusted=FALSE`. Assert `probe_hour4` falls back to the derive path when the mocked transport returns empty/unsupported `HOUR_4`.
    - **Validates: Requirements 2.6, 3.5, 5.4**

- [x] 4. Implement allowance-aware planning (`vpa/market_data/ig_ingest.py`)
  - [x] 4.1 Implement `AllowanceState` and `plan_backfill`
    - Add constants `WEEKLY_ALLOWANCE = 10_000` and `SAFETY_FLOOR = 500`.
    - `AllowanceState` dataclass carries `remaining` (`allowance.remainingAllowance`) and `expiry_s` (`allowance.allowanceExpiry`).
    - `plan_backfill(target_points, batch_points, state)` computes `budget = max(0, state.remaining - SAFETY_FLOOR)`, `this_run = min(target_points, budget)`, `batches = ceil(this_run / batch_points)`, and returns `{"this_run": ..., "batches": ..., "deferred": target_points - this_run}` so a run never spends below the floor and reports deferred points.
    - _Requirements: 3.1, 3.2, 3.3_

  - [ ]* 4.2 Write unit tests for `plan_backfill` budget maths
    - Cover: ample allowance (this_run == target), tight allowance (this_run clamped to budget), remaining at/below floor (this_run == 0, all deferred), and batch count rounding.
    - _Requirements: 3.1, 3.2, 3.3_

  - [ ]* 4.3 Property test — allowance never over-spent
    - **Property 5: Allowance never over-spent** — `plan_backfill(...).this_run` satisfies `0 <= this_run <= target_points` and `this_run <= max(0, remaining - SAFETY_FLOOR)`.
    - **Validates: Requirements 3.1, 3.2, 3.3**

- [x] 5. Checkpoint — read-only client, normalisation, and allowance planning verified
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Make intraday read-through session-aware (`vpa/market_data/repository.py` edit)
  - [x] 6.1 Implement session-aware `_expected_last` for intraday
    - Add `INTRADAY_MINUTES = {"15m": 15, "1h": 60}`. Keep the `1d` branch and the non-intraday fallback unchanged.
    - For `15m`/`1h`, return the open time of the last COMPLETED session bar on/before `end`, floored to the interval grid within the US 500 trading session (weekday, excluding the ~1h daily break); return `None` when `[start, end]` contains no session time, so no tail fetch triggers. Keep it monotonic in `end`.
    - _Requirements: 5.1_

  - [x] 6.2 Wire `_drop_incomplete_final_bar` and an injectable intraday tail fetcher
    - Wire `_drop_incomplete_final_bar` to drop the in-progress final intraday bar before persisting (daily stays a no-op). Give `MarketDataRepository` an injectable intraday tail fetcher (defaulting to an IG-backed `fetch_prices` adapter) so `load_ohlcv`'s read-through fetches the missing tail from IG for `source="ig"` tickers while the daily path keeps using `fetch_yf`. One read-through algorithm; only the tail fetcher differs by source.
    - _Requirements: 5.2_

  - [ ]* 6.3 Write repository intraday tests
    - `_expected_last` for `15m`/`1h` returns the last completed session bar (not `end`), `None` for a weekend-only range, and is monotonic in `end`; read-through fetches only the missing tail via the injected fetcher (asserted with a fake that records calls) and drops the incomplete final bar.
    - _Requirements: 5.1, 5.2_

  - [ ]* 6.4 Property test — session-aware expectation
    - **Property 6: Session-aware expectation** — intraday `_expected_last` returns the last completed session bar-open on/before `end` (never `end` mid-bar or out-of-hours), `None` for a no-session range, and is monotonic in `end`.
    - **Validates: Requirements 5.1**

  - [ ]* 6.5 Property test — idempotent ingestion
    - **Property 4: Idempotent ingestion** — upserting the same IG bars twice changes the row count by zero, and re-pulling an overlapping backfill window inserts no new rows (PK invariant on `(ticker, interval, ts)`).
    - **Validates: Requirements 3.4, 5.2**

- [x] 7. Implement the allowance-aware IG backfill CLI (`scripts/ig_backfill.py`)
  - [x] 7.1 Implement the backfill CLI
    - Parse `--epic`/`--interval`/`--years` (interval in `15m`/`1h`/`4h`). `IGClient.login()`, then loop `fetch_prices` in batches: before each fetch call `plan_backfill` and re-check the live `allowance.remainingAllowance` after each batch, stopping early (reporting `deferred`) if remaining would fall below `SAFETY_FLOOR`. Each batch: `normalise_ig_prices` -> `MarketDataRepository.upsert_bars(df, epic, interval, source="ig", adjusted=False)` (idempotent). Print `{inserted, updated, points_used, remaining_allowance, deferred}`.
    - 1h deep: ~2 yrs (~3,500 points) seeds in a single within-budget run. 15m: seed incrementally across successive weekly runs; resumability comes free from the idempotent PK (re-pulling an overlap inserts nothing new).
    - 4h: call `probe_hour4` first — if native `HOUR_4` is supported, pull `4h` like `1h` (spends allowance like `1h`, ~small); otherwise derive `4h` from the already-stored `1h` series via `resample_1h_to_4h` and upsert, spending ZERO extra IG allowance (requires `1h` seeded first).
    - Document the invocations: `python scripts/ig_backfill.py --epic IX.D.SPTRD.DAILY.IP --interval 1h --years 2`, `... --interval 15m --years 2`, and `... --interval 4h --years 2`.
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [ ]* 7.2 Write backfill tests against the mocked IG transport
    - Drive the loop with a fake `http` returning scripted `prices` + `allowance`; assert it stops before breaching `SAFETY_FLOOR`, reports `deferred`, upserts idempotently on a re-run over an overlapping window, and never issues a live call (`no_ig_network` active).
    - _Requirements: 3.2, 3.4_

- [x] 8. Fix the yfinance intraday baseline (`scripts/backfill_market_data.py` edit)
  - [x] 8.1 Use a bounded period for intraday
    - For intraday `1h`, request `period="730d"` instead of `period="max"` (which returns EMPTY for `1h` per SP-342). Leave the daily path unchanged; keep yfinance `1h` rows tagged `source="yfinance"` under ticker `SPY` so they coexist with IG rows.
    - _Requirements: 4.1, 4.2_

  - [ ]* 8.2 Write a regression test for the intraday period
    - Patch `yf.download` to record its `period` kwarg; assert the intraday `1h` path requests `"730d"` (not `"max"`) and the daily path is unchanged.
    - _Requirements: 4.1_

  - [ ]* 8.3 Property test — source isolation
    - **Property 8: Source isolation** — IG rows (`source="ig"`, ticker = epic) and yfinance baseline rows (`source="yfinance"`, ticker = `SPY`) never overwrite each other.
    - **Validates: Requirements 2.5, 4.2**

- [x] 9. Implement the grow-forward job and Rundeck wiring
  - [x] 9.1 Implement `vpa/scripts/grow_forward_intraday.py`
    - Define `EPIC = "IX.D.SPTRD.DAILY.IP"` and `INTERVALS = ["15m", "1h", "4h"]`. `grow_forward(epic=EPIC, intervals=INTERVALS, repo=None, now=None)` reads-through `MarketDataRepository.load_ohlcv` over a recent window per interval so only the missing tail is fetched from IG and upserted idempotently; return a per-interval summary `{interval: {fetched, inserted, updated}}`; exit non-zero on failure so Rundeck surfaces it. Document `python -m vpa.scripts.grow_forward_intraday`.
    - 4h handling: if native `HOUR_4` is supported, grow `4h` forward exactly like `15m`/`1h` (read-through tail fetch). If `4h` is DERIVED, do NOT make a separate IG call for it — after the `1h` tail is refreshed, recompute/upsert the affected `4h` bars from the freshly-updated `1h` tail via `resample_1h_to_4h` (idempotent on the `(ticker, interval, ts)` PK, zero extra allowance). Grow `1h` before `4h` in the derived path.
    - _Requirements: 5.2, 5.3, 5.4_

  - [x] 9.2 Add the Rundeck shell entrypoint `vpa/scripts/start_grow_forward_intraday.sh`
    - Mirror `start_vpa_all_shares.sh`: activate the venv, `cd /usr/local/trading`, run the module, propagate the exit code.
    - _Requirements: 5.3_

  - [x] 9.3 Add the Rundeck job definition `vpa/jobs/Grow_Forward_Intraday_IG.yaml`
    - Model it on the CONFIRMED-CURRENT export shape (the checked-in `vpa/jobs/*.yaml` exports have been re-exported and verified current): a single-item YAML list whose entry carries `name`, `id`, `uuid`, `description`, `loglevel`, `defaultTab: nodes`, `executionEnabled: true`, `nodeFilterEditable: false`, `plugins: {ExecutionLifecycle: {}}`, `scheduleEnabled`, a `schedule` block (`month: '*'`, `time: {hour, minute, seconds}`, `weekday: {day}`, `year: '*'`), and a `sequence.commands[].scriptfile` pointing at `/usr/local/trading/vpa/scripts/start_grow_forward_intraday.sh` with `keepgoing: false` and `strategy: node-first`.
    - Use `weekday.day: '2,3,4,5,6'` (Mon–Fri, the observed weekday-job convention) with an **hourly, all-day** cadence (`hour: '*'`, `minute: '0'`) and `timeZone: UTC` pinned. All-day (not just the US cash session) is required so the IG source's out-of-hours bars stay current rather than backfilling in a burst each morning; the ~1h 21:00–22:00 UTC break just yields an empty run.
    - NOTE: the yaml is a VERSIONED SNAPSHOT committed to the repo, NOT a deploy source — Rundeck keeps jobs in its own internal DB, so the job is installed via the Rundeck UI/API (Task 12.3) and the yaml re-exported to keep the record current.
    - _Requirements: 5.3_

  - [ ]* 9.4 Write a smoke test for `grow_forward`
    - With a stubbed repo/injected IG fetcher (no live calls), assert `grow_forward` iterates both intervals, returns the per-interval summary, and exits non-zero when a fetch raises.
    - _Requirements: 5.2, 5.3_

- [x] 10. Add the hermetic IG network guard (`vpa/tests/conftest.py` edit)
  - Add a `no_ig_network` guard mirroring the existing `no_network` fixture: monkeypatch the real IG HTTP transport to raise `AssertionError("IG network access attempted")`, so no test can reach live IG. Apply it to the IG test modules (`test_ig_client.py`, `test_ig_ingest.py`, `test_repository_intraday.py`).
  - _Requirements: 6.1_

- [x] 11. Checkpoint — quality gate (lint, format, full suite)
  - Run `ruff check .` and `ruff format --check .`; fix anything flagged (`ruff check --fix .`, `ruff format .`). A common trip-up: files written by tooling can lose the trailing newline or drift from ruff's style — run the format check, not just the tests.
  - Then run the FULL suite `pytest -m ""` (includes the slow ML tests) and confirm green. This gate MUST pass before any push / PR open-or-merge / marking the ticket Done.
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 6.2, 6.3_

---

## 🚀 12. Pi Deployment — OPERATOR / DEPLOY TASK (Definition of Done)

> **This task group is the Definition of Done for this deployable work and CANNOT be
> completed by code alone.** Per the ticket-standards DoD, SP-379 stays in **Mostly
> Done** until `source="ig"` bars are verified in the Pi `my_postgres` store — code
> being merged is not sufficient.
>
> The `pi-access` steering is **READ-ONLY by default**: SSH diagnostics are fine, but
> the write/deploy actions below (editing the Pi `.env`, pulling the latest code on
> the Pi, installing/scheduling the Rundeck job) require **explicit operator
> go-ahead at execution time**. Do not perform them without it.
>
> **Dev-vs-prod split (allowed):** development, the test suite, and the initial deep 1h
> backfill may run from the dev machine against the shared Pi store. Only the recurring
> grow-forward job must run on the Pi.

- [x] 12.1 Place live `IG_*` credentials in the Pi `.env` (operator action)
  - Add `IG_API_KEY` / `IG_USER_ID` / `IG_PWD` to the Pi's gitignored `.env` (never committed). Requires operator go-ahead (write action on the Pi).
  - _Requirements: 7.1_

- [x] 12.2 Pull the latest code on the Pi (operator action)
  - On the Pi: `cd /usr/local/trading && git pull` on `master`. This project is NOT containerised (unlike `bf_trader_py`): `/usr/local/trading` is a plain git checkout with a project `.venv`, and the Rundeck jobs run the venv Python scripts directly (there is no app Dockerfile/compose; the only containers on the Pi are `my_postgres`/`my_pgadmin`, which are the data store, not this app). SP-379 added no new dependencies (`requests`/`pandas`/`hypothesis`/`pytest` were already pinned), so no venv reinstall is needed — but if a future change touches `requirements.txt`, run `/usr/local/trading/.venv/bin/pip install -r requirements.txt`. Requires operator go-ahead (write action on the Pi).
  - _Requirements: 7.2_

- [x] 12.3 Install and schedule the grow-forward Rundeck job on the Pi (operator action)
  - Rundeck is CONFIRMED live on the Pi (direct systemd install, `rundeckd` 5.10.0, HTTP port 4440 — not a container). Create/schedule the `Grow Forward Intraday IG` job via the Rundeck UI/API (jobs live in Rundeck's own internal DB; committing the yaml does not schedule it) on an **hourly, all-day Mon–Fri, UTC** schedule (covers out-of-hours), then re-export the job yaml into `vpa/jobs/Grow_Forward_Intraday_IG.yaml` as the versioned record. DONE: job installed with id/uuid `39c82681-9730-4105-b0f4-4293b26cc229`, `hour: '*'`, `timeZone: UTC`, and the repo yaml re-exported to match. Requires operator go-ahead.
  - _Requirements: 5.3, 7.3_

- [x] 12.4 Verify `source="ig"` bars land in the Pi store (operator action)
  - After the grow-forward job runs on the Pi, confirm `15m`/`1h` rows with `source='ig'` are present in the Pi `my_postgres` store via a read-only `psql` SELECT of row counts and the latest `ts`. Add a completion comment on SP-379 noting the deploy was done and verified, then move the ticket from Mostly Done to Done. VERIFIED (15 Oct 2026): a read-only SELECT on the Pi `my_postgres` store shows `source='ig'` bars for all three intervals — 15m (475 rows, latest 2026-10-15 08:45 UTC), 1h (118 rows, latest 08:00 UTC), 4h (32 rows, derived, latest 08:00 UTC) — current to the latest completed session hour, confirming the hourly grow-forward job keeps the store current after the snapshotTime-format fix. SP-379 moved to Done.
  - _Requirements: 7.4, 7.5_

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP; core implementation and the deployment steps are never optional.
- Each task references specific requirement clauses for traceability; each property test names the design Property (1–9) it validates.
- Checkpoints (Tasks 5, 11) ensure incremental validation; Task 11 is the explicit lint/format/full-suite quality gate that must pass before any push / PR / marking Done.
- Tasks 1–11 are coding/config tasks doable locally (mocked IG transport + local/mocked Postgres); the ingestion is not blocked on the Pi.
- Task 12 is operator/deploy work: the `pi-access` steering is read-only by default, so the write/deploy actions require explicit operator go-ahead, and the ticket stays in Mostly Done until `source="ig"` bars are verified on the Pi.

### Out of scope / deferred (NOT in SP-379)

- **Storing IG BID/ASK series and the implied spread.** SP-379 stores **mid-price only**
  per OHLC field (design Decision #2). Capturing the raw bid/ask (as separate rows or a
  second source tag) and the implied spread is a DEFERRED future enhancement — revisit
  only if fill-accuracy matters for execution. No implementation task is created for it
  here; this note exists so the idea is not lost.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["2.1"] },
    { "id": 1, "tasks": ["2.2", "2.3", "3.1", "4.1"] },
    { "id": 2, "tasks": ["2.4", "3.2", "3.3", "3.4", "3.5", "4.2", "4.3"] },
    { "id": 3, "tasks": ["2.5", "2.6", "3.6", "6.1", "7.1", "8.1"] },
    { "id": 4, "tasks": ["3.7", "6.2", "7.2", "8.2", "8.3", "9.1"] },
    { "id": 5, "tasks": ["6.3", "6.4", "6.5", "9.2", "9.3", "9.4"] },
    { "id": 6, "tasks": ["12.1"] },
    { "id": 7, "tasks": ["12.2"] },
    { "id": 8, "tasks": ["12.3"] },
    { "id": 9, "tasks": ["12.4"] }
  ]
}
```
