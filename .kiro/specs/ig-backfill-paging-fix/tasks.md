# Implementation Plan

## Overview

This plan fixes the IG backfill backward-paging defect (SP-382) using the exploratory
bugfix workflow: write a failing bug-condition test first, pin preservation behavior,
apply the two-part fix (`IGClient.fetch_prices_range` + a date-cursor `_backfill_native`),
then re-verify the same tests. Code and spec live in `d:\projects\trading`. All tests are
hermetic (injectable fake transport, `no_ig_network` module guard, temp `.env`) and carry
no `slow` marker.

## Tasks

- [x] 1. Write bug condition exploration test (BEFORE implementing the fix)
  - **Property 1: Bug Condition** - Backward Paging Deepens History
  - **CRITICAL**: This test MUST FAIL on the unfixed `_backfill_native` loop - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails** - the failure is the expected outcome at this stage
  - **NOTE**: This test encodes the expected behavior (date cursor advances newest -> oldest, each window upserted once); it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the loop never advances a date cursor and re-fetches the same most-recent window every batch
  - **Scoped PBT Approach**: Scope the property to concrete bug-condition cases - `target_points > batch_points` with budget for more than one batch (`plannedBudget(allowance) > batch_points`), so a correct loop MUST page backward
  - Add `vpa/tests/test_ig_backfill.py` (new, hermetic): drive `_backfill_native` with a fake `IGClient` whose fetch records every call and always returns the same newest window (real most-recent-N behavior), and a fake repo that records upserts
  - Apply the `no_ig_network` guard at module scope (`pytestmark = pytest.mark.usefixtures("no_ig_network")`) and pass a temp `.env` via `env_path` so the real project `.env` is never read, mirroring `test_ig_client.py` conventions
  - Encode the Bug Condition from design (`isBugCondition`): assert that, on a correct loop, each successive batch requests a strictly older dated window and each window is upserted exactly once (`points_used` ≈ distinct bars seeded)
  - Capture the counterexamples the UNFIXED loop produces: (a) every fetch requests the identical newest window; (b) the second batch's requested window equals the first (no cursor advance); (c) the run reports `deferred=0` while the oldest upserted timestamp is far short of the requested depth; (d) the loop never terminates via an empty older window (only on budget/floor)
  - Run the test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (this is correct - it proves the bug exists)
  - Document counterexamples found (e.g. "all 7 batches fetched the identical newest window; `updated` grows while `inserted` stays flat; `points_used=3500` for ~500 distinct bars")
  - Mark task complete when the test is written, run, and the failure is documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

- [x] 2. Write preservation property tests (BEFORE implementing the fix)
  - **Property 2: Preservation** - Non-Paging Behavior Unchanged
  - **IMPORTANT**: Follow the observation-first methodology - run the UNFIXED code for non-bug-condition inputs, record the actual outputs, then write tests that pin those observed outputs
  - Non-bug-condition inputs (where `isBugCondition` returns false): single-window runs (`target_points <= batch_points`), the `4h` derive path, grow-forward, and allowance-exhausted runs
  - Observe on UNFIXED code and pin with example + property-based tests (Hypothesis, already used in the repo under `.hypothesis/`):
    - Single-window preservation: `target_points <= batch_points` fetches one window and upserts once; identical before and after the fix
    - `4h` derive preservation: with native `HOUR_4` unsupported, `_backfill_4h` reads stored `1h` and resamples via `resample_1h_to_4h`, `points_used=0`; unchanged
    - Idempotent re-pull preservation: re-running over an overlapping window inserts no new rows (idempotent on the `(ticker, interval, ts)` PK), so a run stays resumable across weeks
    - Allowance-floor preservation: generate random `AllowanceState` values and assert the loop never drives live `remaining` below `SAFETY_FLOOR` and reports the untouched remainder as `deferred` (`plan_backfill` invariants preserved)
    - `snapshotTime` parsing preservation: both dated-window date forms map onto the two existing `IG_SNAPSHOT_FMTS`; an unknown shape still raises loudly (no new timestamp format introduced)
  - Keep all tests hermetic: injectable fake transport, `no_ig_network` module guard, temp `.env` via `env_path`; no `slow` marker (fast, mocked, network-free)
  - Run the tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms the baseline behavior to preserve)
  - Mark task complete when the tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

- [x] 3. Fix the backward-paging IG backfill

  - [x] 3.1 Add `IGClient.fetch_prices_range` dated-window fetch
    - In `vpa/market_data/ig_client.py`, add a new read-only method `fetch_prices_range(epic, resolution, start, end)` that ensures a valid session (reset-on-use, mirroring `fetch_prices`) and builds the auth headers (`X-IG-API-KEY` / `CST` / `X-SECURITY-TOKEN`)
    - Primary (new) form: `GET {base}/prices/{epic}/{resolution}/{startDate}/{endDate}` with dates formatted `yyyy-MM-dd HH:mm:ss` and `Version: 3`
    - Fallback (older) form: `GET {base}/prices/{epic}/{resolution}?startdate=...&enddate=...` with dates formatted `yyyy:MM:dd-HH:mm:ss` and `Version: 2`, used only when the primary form is unavailable for the account/epic (e.g. 404/400)
    - Accept tz-aware UTC `pd.Timestamp` bounds (`start`, `end`) and format them to the endpoint's date string; the two IG date forms map 1:1 onto the two existing `IG_SNAPSHOT_FMTS`, so introduce no new timestamp format
    - Return the same shape as `fetch_prices` (`{"prices": [...], "allowance": {...}}`); mirror `fetch_prices` non-200 handling (raise `IGAuthError` on failure of the chosen form) and reset session expiry on success
    - Keep the read-only surface guarantee: the new name adds no deal/order/position capability
    - _Bug_Condition: isBugCondition(input) - target_points > batch_points AND plannedBudget > batch_points (needs dated windows)_
    - _Expected_Behavior: expectedBehavior(result) - IGClient supports a dated from/to fetch returning {prices, allowance} unchanged (design Fix Implementation, ig_client.py)_
    - _Preservation: most-recent-N fetch_prices and read-only surface unchanged (design Preservation Requirements)_
    - _Requirements: 2.5_

  - [x] 3.2 Update the read-only-surface assertion in `test_ig_client.py`
    - In `vpa/tests/test_ig_client.py`, change the public-surface assertion from `{"login", "fetch_prices"}` to `{"login", "fetch_prices", "fetch_prices_range"}`
    - Confirm the forbidden-token check still passes (no `deal`/`order`/`position`/`otc`/`trade` tokens in the new name)
    - Add `fetch_prices_range` unit tests against the fake transport: builds the correct new-form URL (`/prices/{epic}/{resolution}/{startDate}/{endDate}`, `Version: 3`, dates `yyyy-MM-dd HH:mm:ss`), sends auth headers, parses `{prices, allowance}`, raises `IGAuthError` on non-200; falls back to the older query-string form (`?startdate=...&enddate=...`, `Version: 2`, dates `yyyy:MM:dd-HH:mm:ss`) when the new form is unavailable; auto-logs-in when the session is absent/expired (reset-on-use)
    - _Bug_Condition: isBugCondition(input) - run needs dated windows_
    - _Expected_Behavior: expectedBehavior(result) - public surface is exactly {login, fetch_prices, fetch_prices_range}, still read-only_
    - _Preservation: read-only client surface preserved (design Preservation Requirements; Requirement 1.3-era guarantee)_
    - _Requirements: 2.5_

  - [x] 3.3 Change `_backfill_native` to page backward by date cursor
    - In `scripts/ig_backfill.py`, introduce a date cursor starting at "now" (UTC); each batch fetch the dated window `[cursor - window_span, cursor)` via `client.fetch_prices_range`, sizing `window_span` from `this_batch` and the interval's approximate bar size (reuse the `BARS_PER_YEAR` cadence to convert a point budget into a time span). Keep the small most-recent-N `fetch_prices` probe that primes the allowance
    - Advance the cursor backward after upserting a window: set the next cursor to the oldest `snapshotTime` seen in that window (parsed via the existing normaliser / `IG_SNAPSHOT_FMTS`), guaranteeing each subsequent window is strictly older
    - No-progress guard: if a window returns bars but the oldest timestamp does not move the cursor back, stop to avoid an infinite loop
    - Stop on end-of-history: when a dated window returns an empty `prices` list, set `remaining = 0` and break, reporting completion - replacing the `fetched < this_batch` heuristic that cannot fire for dated windows
    - Keep the allowance guards: call `plan_backfill` before each batch, clamp `this_batch` to `plan["this_run"]`, skip a fetch that would drive live `remaining` below `SAFETY_FLOOR`, re-read the live `allowance` after each batch, break at the floor, and report the untouched remainder as `deferred`
    - Preserve the upsert path and idempotency: each window still flows `normalise_ig_prices` -> `repo.upsert_bars(..., source="ig", adjusted=False)` on the `(ticker, interval, ts)` PK, so an overlapping re-pull inserts no new rows and a run stays resumable
    - Leave `_backfill_4h`, `_target_points`, `_allowance_state`, `backfill`, and the CLI untouched except for the `_backfill_native` loop internals (preserve the `4h` derive path and grow-forward)
    - _Bug_Condition: isBugCondition(input) - target_points > batch_points AND plannedBudget > batch_points AND secondBatchWindow == firstBatchWindow on unfixed code_
    - _Expected_Behavior: expectedBehavior(result) - each batch fetches a strictly older window, each upserted once, store seeded ~requested depth, stop on empty older window, remaining_allowance >= SAFETY_FLOOR (design Correctness Property 1)_
    - _Preservation: 4h derive path, grow-forward, upsert pipeline, allowance planning, IG_SNAPSHOT_FMTS all unchanged (design Preservation Requirements)_
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6_

  - [x] 3.4 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Backward Paging Deepens History
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior; when it passes it confirms each batch fetches a strictly older window, each window is upserted once, the oldest stored timestamp reaches ~requested depth, the loop stops on an empty older window, and `remaining_allowance >= SAFETY_FLOOR`
    - Run the bug condition exploration test from step 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms the bug is fixed)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6_

  - [x] 3.5 Verify preservation tests still pass
    - **Property 2: Preservation** - Non-Paging Behavior Unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run the preservation property/example tests from step 2 (single-window, `4h` derive, idempotent re-pull, allowance-floor, `snapshotTime` parsing)
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Confirm all non-bug-condition behavior is unchanged after the fix
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

- [x] 4. Add unit, property-based, and integration coverage
  - Unit: `_backfill_native` cursor math - each batch's requested `end` equals the previous window's oldest `snapshotTime`; the loop stops on an empty older window; the no-progress guard prevents an infinite loop when the cursor fails to move back
  - Property-based (Hypothesis): generate random descending window sequences and assert the fixed loop upserts each bar once and the oldest stored timestamp reaches the generated depth (no duplicate waste); generate random `AllowanceState` values and assert the loop never drives `remaining` below `SAFETY_FLOOR` with a consistent `deferred`; generate overlapping re-pulls and assert idempotency (no new inserts on overlap)
  - Integration (fake client + in-memory/fake repo): full `backfill(epic, "1h", years)` pages backward across several windows, seeds to ~target depth, stays above the floor, and reports `deferred=0` only when end-of-history or target depth is actually reached; `backfill(epic, "4h", years)` with native `HOUR_4` unsupported derives from the stored `1h` series end-to-end (zero IG allowance spent); resumability - run the loop twice over an overlapping range and assert the second run inserts no new rows
  - Keep all tests hermetic (injectable fake transport, `no_ig_network` module guard, temp `.env`); no `slow` marker
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6, 3.1, 3.2, 3.4_

- [-] 5. Checkpoint - verification, repo gates, and Pi deployment
  - Ensure all tests pass; ask the user if questions arise
  - Run `ruff check .` and `ruff format --check .` clean (auto-fix with `ruff check --fix .` / `ruff format .` if needed), then run the FULL suite `pytest -m ""` green (bare `pytest` deselects the `slow` marker, so use `-m ""` before any push / PR / marking Done)
  - **DEMO-first smoke verification**: before the final live-Pi backfill, any ad-hoc smoke test of `fetch_prices_range` against the real IG API MUST be run against the IG **demo** environment by constructing the client with `demo=True` (`IGClient(demo=True)`) - this uses the `IG_DEMO_*` credentials and the `IG_DEMO_BASE` (`https://demo-api.ig.com/gateway/deal`) base URL. The demo account has its own historical-data allowance, separate from the live weekly allowance, so exploratory manual verification does not consume the live budget the real backfill needs. The hermetic unit/property/integration tests (tasks 1-4) remain network-free (`no_ig_network`) and are unaffected by this step
  - **Deployment (Definition of Done)**: this fix changes code that runs on the always-on Raspberry Pi, so merging is not sufficient - deploy and verify on the Pi. Pull the latest changes on the Pi and rebuild the container via the project's build/deploy scripts, then re-run the `1h` and `4h` backfill (and `15m` as applicable) to seed ~2 years and confirm the store now reaches ~`years` depth (earliest stored timestamp ~2 years back, not ~1 month) with `points_used` ≈ distinct bars seeded. NOTE: the actual Pi backfill that seeds ~2 years still runs against the **live** account (that is the real goal) - only the exploratory manual smoke check above uses demo
  - While the code is complete but not yet deployed/verified on the Pi, the SP-382 ticket belongs in **Mostly Done**, not Done; move it to Done only after the deploy is verified, and note the verified deploy in the completion comment
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

## Task Dependency Graph

```
1 (bug condition exploration test, fails on unfixed code)
2 (preservation tests, pass on unfixed code)
        │
        ▼
3 Fix (requires 1 and 2 observed on unfixed code first)
  3.1 add IGClient.fetch_prices_range
        │
        ▼
  3.2 update test_ig_client.py surface + fetch_prices_range unit tests   (depends on 3.1)
  3.3 change _backfill_native to page backward by date cursor            (depends on 3.1)
        │
        ▼
  3.4 verify task 1 test now PASSES                                      (depends on 3.3)
  3.5 verify task 2 tests still PASS                                     (depends on 3.3)
        │
        ▼
4 unit / property-based / integration coverage                          (depends on 3.1, 3.3)
        │
        ▼
5 checkpoint: ruff + pytest -m "" green, then Pi deploy & verify         (depends on all)
```

Task 1 and Task 2 are independent of each other and are both prerequisites for Task 3
(they must be observed on the unfixed code first). Tasks 3.2 and 3.3 both depend on 3.1.
Tasks 3.4 and 3.5 depend on 3.3. Task 4 depends on the fix (3.1, 3.3). Task 5 depends on
everything.

```json
{
  "waves": [
    { "wave": 1, "tasks": ["1", "2"], "dependsOn": [] },
    { "wave": 2, "tasks": ["3.1"], "dependsOn": ["1", "2"] },
    { "wave": 3, "tasks": ["3.2", "3.3"], "dependsOn": ["3.1"] },
    { "wave": 4, "tasks": ["3.4", "3.5"], "dependsOn": ["3.3"] },
    { "wave": 5, "tasks": ["4"], "dependsOn": ["3.1", "3.3"] },
    { "wave": 6, "tasks": ["5"], "dependsOn": ["3.2", "3.4", "3.5", "4"] }
  ]
}
```

## Notes

- Workflow order is mandatory: the Property 1 exploration test (Task 1) MUST be written and
  seen to FAIL on the unfixed loop, and the Property 2 preservation tests (Task 2) MUST be
  seen to PASS on the unfixed loop, BEFORE the fix in Task 3.
- Tasks 3.4 and 3.5 re-run the SAME tests from Tasks 1 and 2 - do not author new tests there.
- Fast iteration uses bare `pytest` (deselects `slow`); the final gate in Task 5 MUST use
  `pytest -m ""` so no tests are silently skipped, after `ruff check .` and
  `ruff format --check .` are clean.
- Definition of Done for deployable work: SP-382 touches code that runs on the Raspberry Pi,
  so it stays in **Mostly Done** until the fix is deployed and verified on the Pi (re-run the
  `1h`/`4h` backfill to seed ~2 years). Record the verified deploy in the completion comment
  before moving the ticket to Done.
