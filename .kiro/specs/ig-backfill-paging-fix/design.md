# IG Backfill Backward-Paging Fix Bugfix Design

## Overview

The allowance-aware IG intraday backfill (`scripts/ig_backfill.py`, SP-379) does not
deepen stored history. Its native loop (`_backfill_native`) calls
`IGClient.fetch_prices(epic, resolution, num_points)` — IG's *most-recent-N* endpoint
(`GET /prices/{epic}/{resolution}/{num_points}`) — once per batch with a fixed
`this_batch` and no date cursor. Every batch therefore requests the *same* newest
window, re-upserting identical bars (counted as `updated`) and decrementing the weekly
allowance on each duplicate pass. The `fetched < this_batch` early-stop never trips
because the most-recent-N endpoint always returns a full batch, so the loop only ends on
budget/floor exhaustion and the store never reaches the intended ~2-year depth (SP-382).

The fix has two parts:

1. **Add a dated historical-prices fetch to `IGClient`** — a from/to window fetch
   alongside the existing most-recent-N `fetch_prices`. IG offers two shapes: the newer
   path form `GET /prices/{epic}/{resolution}/{startDate}/{endDate}`
   ([IG Labs — new dates form](https://labs.ig.com/reference/prices-epic-dates-new.html),
   dates `yyyy-MM-dd HH:mm:ss`) and the older query-string form
   `GET /prices/{epic}/{resolution}?startdate=...&enddate=...`
   ([IG Labs — old dates form](https://labs.ig.com/reference/prices-epic-dates-old.html),
   dates `yyyy:MM:dd-HH:mm:ss`). Content was rephrased for compliance with licensing
   restrictions. These two date formats correspond exactly to the two
   `IG_SNAPSHOT_FMTS` the SP-379 parser already handles, so parsing of the returned
   `snapshotTime` values needs no new format.

2. **Make `_backfill_native` page backward** — walk a date cursor from newest to oldest,
   fetching one dated window per batch (each strictly older than the last) and upserting
   it once, until the target depth is reached, no deeper history is returned, or the
   allowance floor would be breached. The loop stays allowance-aware (`plan_backfill` /
   `SAFETY_FLOOR`) and idempotent (upsert on the `(ticker, interval, ts)` PK), so a run
   is resumable across weeks.

The fix is deliberately targeted: the `4h` derive-from-`1h` path
(`_backfill_4h` / `resample_1h_to_4h`), the grow-forward job, the
`normalise_ig_prices` -> `upsert_bars` pipeline, and the SP-379 multi-format
`snapshotTime` parser (`IG_SNAPSHOT_FMTS`) are all preserved unchanged.

## Glossary

- **Bug_Condition (C)**: A native backfill run that needs more than one batch of history
  — i.e. the target depth exceeds a single IG window. Under C the current loop re-fetches
  the newest window every batch instead of advancing backward through older history.
- **Property (P)**: The desired behavior under C — each successive batch fetches a
  strictly *older* dated window (newest -> oldest), each window is upserted once, and the
  store is seeded to approximately the requested depth while staying above `SAFETY_FLOOR`.
- **Preservation**: Behavior that must stay unchanged for inputs where C does not hold —
  the single-window / most-recent-N fetch, the `4h` derive-from-`1h` path, grow-forward,
  the `normalise_ig_prices` -> `upsert_bars` pipeline, idempotent re-pulls, allowance
  planning, and the `IG_SNAPSHOT_FMTS` parser.
- **`IGClient.fetch_prices(epic, resolution, num_points)`**: The existing read-only
  most-recent-N fetch in `vpa/market_data/ig_client.py` (`GET /prices/{epic}/{resolution}/{num_points}`).
- **`IGClient.fetch_prices_range(epic, resolution, start, end)`**: The NEW dated-window
  fetch to be added to `vpa/market_data/ig_client.py` (the from/to historical-prices fetch).
- **`_backfill_native(...)`**: The loop in `scripts/ig_backfill.py` that currently
  re-fetches the newest window each batch; to be changed to page backward by date.
- **`plan_backfill` / `AllowanceState` / `SAFETY_FLOOR`**: The SP-379 allowance planner
  and its 500-point floor in `vpa/market_data/ig_ingest.py`.
- **`IG_SNAPSHOT_FMTS`**: The SP-379 tuple of known `snapshotTime` formats parsed in
  order by `_parse_snapshot_time` (fails loudly on an unknown shape).
- **date cursor**: The upper bound (`end`) of the next dated window to fetch; it moves
  backward in time each batch to the oldest bar seen in the previous window.

## Bug Details

### Bug Condition

The bug manifests when a native backfill (`_backfill_native`) runs for more than one
batch — i.e. the requested depth exceeds a single IG window. The loop calls
`client.fetch_prices(epic, resolution, this_batch)` each iteration with no date cursor,
so IG returns the *same* most-recent window every time. The function is therefore
re-fetching already-stored bars (reported as `updated`), consuming allowance
(`points_used`) on each duplicate pass, and never advancing to older history. The
`fetched < this_batch` early-stop never fires because the most-recent-N endpoint always
returns a full batch.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type BackfillRun { epic, resolution, target_points, batch_points, allowance }
  OUTPUT: boolean

  // The run needs to page backward (more than one window of depth) AND there is
  // budget for more than one batch, so a correct implementation MUST advance a date
  // cursor. The defective loop does not — it re-fetches the newest window every batch.
  RETURN input.target_points > input.batch_points
         AND plannedBudget(input.allowance) > input.batch_points
         AND secondBatchWindow(input) == firstBatchWindow(input)   // windows do not advance
END FUNCTION
```

Where `secondBatchWindow(input) == firstBatchWindow(input)` captures the defect: on the
unfixed code the second batch requests the identical newest window as the first.

### Examples

- **1h / 2y (live Pi, 15 Oct 2026)**: reported `inserted=382, updated=3118,
  points_used=3500, deferred=0`. `points_used=3500` with `updated=3118` means ~500 recent
  bars were fetched ~7× over, all re-upserting the same rows. Expected: ~3,500 *distinct*
  bars seeded back ~2 years; actual store depth only ~1 month (earliest 2026-09-16).
- **4h / 2y (live Pi)**: `inserted=470, updated=410, points_used=880`; store only ~4
  months deep (earliest 2026-06-24) instead of ~2 years.
- **Any `target_points > batch_points`**: the loop spends budget down to the floor on
  duplicate windows and reports `deferred=0` ("spent the planned points"), misleadingly
  implying success while depth is far short of target.
- **Edge — no deeper history**: when an older window legitimately returns no further
  bars, the correct behavior is to stop paging and report completion; the current loop
  cannot reach this case because it never pages backward.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- The existing most-recent-N fetch `IGClient.fetch_prices(epic, resolution, num_points)`
  continues to build `GET /prices/{epic}/{resolution}/{num_points}` and parse
  `{prices, allowance}` exactly as before (grow-forward depends on it).
- The `normalise_ig_prices` -> `MarketDataRepository.upsert_bars` path stays intact: IG
  bars flow through tagged `source="ig"`, `adjusted=False`, idempotent on the
  `(ticker, interval, ts)` PK, so an overlapping re-pull inserts no new rows.
- The `4h` derive-from-`1h` path (`_backfill_4h` -> `resample_1h_to_4h`) is unchanged and
  spends zero extra IG allowance when native `HOUR_4` is unsupported.
- The grow-forward job is unaffected (it only moves forward).
- `snapshotTime` parsing stays on the SP-379 multi-format parser `IG_SNAPSHOT_FMTS`,
  failing loudly on an unknown format.
- Allowance planning stays on `plan_backfill` / `SAFETY_FLOOR`; a run never drives
  `remainingAllowance` below the floor and reports the untouched remainder as `deferred`.
- The read-only client surface is preserved (login + price reads only; no
  deal/order/position methods) — the new fetch is another read-only `GET /prices` form.

**Scope:**
All inputs that do NOT satisfy the bug condition should be unaffected by this fix. This
includes:
- Single-window / most-recent-N fetches where `target_points <= batch_points`.
- The `4h` derive path (no native pull at all).
- Grow-forward and any other caller of `fetch_prices`.
- Allowance-exhausted runs (`plan_backfill` already returns no budget).

**Note:** The expected correct behavior under the bug condition is defined in the
Correctness Properties section (Property 1); this section focuses on what must NOT change.

## Hypothesized Root Cause

Based on the bug description and the code read, the cause is well understood (this is a
design/omission bug, not a mystery):

1. **No dated fetch on the client (primary cause)**: `IGClient` implements only the
   most-recent-N endpoint. There is no from/to fetch, so `_backfill_native` has no way to
   request an *older* window.

2. **No date cursor in the loop**: `_backfill_native` calls `fetch_prices` with a fixed
   `this_batch` each iteration and never advances a cursor, so every batch targets the
   newest window. The requested count changes the *size* of the newest window, never its
   *position* in time.

3. **Early-stop can't fire**: the `fetched < this_batch` stop assumes a shrinking window
   at the frontier of available history; with most-recent-N a full batch is always
   returned, so the loop only ends on budget/floor exhaustion — never on "reached the end
   of history".

4. **Misleading completion signal**: `deferred=0` means "spent the planned points", not
   "reached target depth", masking the shortfall.

## Correctness Properties

Property 1: Bug Condition - Backward Paging Deepens History

_For any_ native backfill run where the bug condition holds (`isBugCondition` returns
true — the target depth exceeds one window and there is budget for more than one batch),
the fixed `_backfill_native` SHALL advance a date cursor so each successive batch fetches
a strictly older dated window than the previous one (newest -> oldest), upsert each window
exactly once (so `points_used` roughly equals the number of distinct bars seeded, with no
duplicate-fetch allowance waste), seed the store to approximately the requested depth, and
stop paging when an older window returns no further bars (reporting completion rather than
looping on an empty/duplicate window).

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**

Property 2: Preservation - Non-Paging Behavior Unchanged

_For any_ input where the bug condition does NOT hold (`isBugCondition` returns false —
single-window runs, the `4h` derive path, grow-forward, or an allowance-exhausted run),
the fixed code SHALL produce the same observable result as the original: bars still flow
`normalise_ig_prices` -> `upsert_bars` tagged `source="ig"`, `adjusted=False`, idempotent
on the PK; the `4h` series is still derived from stored `1h` via `resample_1h_to_4h` with
zero extra allowance; `snapshotTime` is still parsed via `IG_SNAPSHOT_FMTS`; and allowance
planning still uses `plan_backfill` and never drops `remainingAllowance` below
`SAFETY_FLOOR`, reporting the untouched remainder as `deferred`.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7**

## Fix Implementation

### Changes Required

Assuming the root cause analysis is correct, two files change.

**File**: `vpa/market_data/ig_client.py`

**New method**: `IGClient.fetch_prices_range(epic, resolution, start, end)`

1. **Add a dated historical-prices fetch**: a new read-only method that ensures a valid
   session (reset-on-use, mirroring `fetch_prices`), builds the auth headers
   (`X-IG-API-KEY` / `CST` / `X-SECURITY-TOKEN`), and performs a single dated `GET`.
   It uses the client's already-configured base URL exactly as `fetch_prices` does
   (`self._base`, i.e. `IG_DEMO_BASE` when the client was constructed with `demo=True`,
   otherwise `IG_LIVE_BASE`) — the demo/live selection is made once at construction
   (`IGClient(demo=...)` -> `read_ig_config(demo, env_path)` + base URL) and
   `fetch_prices_range` introduces no new way of choosing the base URL.
   - **Primary (new) form**: `GET {base}/prices/{epic}/{resolution}/{startDate}/{endDate}`
     with dates formatted `yyyy-MM-dd HH:mm:ss` and `Version: 3`
     ([IG Labs — new dates form](https://labs.ig.com/reference/prices-epic-dates-new.html)).
   - **Fallback (older) form**: `GET {base}/prices/{epic}/{resolution}?startdate=...&enddate=...`
     with dates formatted `yyyy:MM:dd-HH:mm:ss` and `Version: 2`
     ([IG Labs — old dates form](https://labs.ig.com/reference/prices-epic-dates-old.html)).
     Used only if the primary form is unavailable for the account/epic (e.g. a 404/400),
     keeping the client resilient without changing the caller contract.
   - Content was rephrased for compliance with licensing restrictions.
2. **Accept tz-aware UTC `pd.Timestamp` bounds** (`start`, `end`) and format them to the
   endpoint's date string. The two IG date forms map 1:1 onto the two existing
   `IG_SNAPSHOT_FMTS`, so no new timestamp format is introduced anywhere.
3. **Return the same shape** as `fetch_prices`: `{"prices": [...], "allowance": {...}}`,
   so the normaliser and allowance planner consume it unchanged.
4. **Non-200 handling** mirrors `fetch_prices` (raise `IGAuthError` on failure of the
   chosen form), and a successful fetch resets the session expiry (reset-on-use).
5. **Keep the read-only surface guarantee**: the method is another `GET /prices` form and
   adds no deal/order/position capability. NOTE: `test_ig_client.py` currently asserts the
   public surface is exactly `{"login", "fetch_prices"}`; that assertion must be updated to
   `{"login", "fetch_prices", "fetch_prices_range"}` (still read-only — no forbidden
   `deal`/`order`/`position`/`otc`/`trade` tokens appear in the new name).

**File**: `scripts/ig_backfill.py`

**Function**: `_backfill_native`

1. **Introduce a date cursor**: start the cursor at "now" (UTC) and, each batch, fetch the
   dated window `[cursor - window_span, cursor)` via `client.fetch_prices_range`, where
   `window_span` is sized from `this_batch` and the interval's approximate bar size
   (reuse the `BARS_PER_YEAR` cadence already in the script to convert a point budget into
   a time span). The probe request that primes the allowance stays as a small
   most-recent-N `fetch_prices` call.
2. **Advance the cursor backward**: after upserting a window, set the next cursor to the
   oldest `snapshotTime` seen in that window (parsed via the existing normaliser /
   `IG_SNAPSHOT_FMTS`), guaranteeing each subsequent window is strictly older. If a window
   returns bars but the oldest timestamp does not move the cursor back (no progress), stop
   to avoid an infinite loop.
3. **Stop on end-of-history**: when a dated window returns an empty `prices` list (no
   deeper history), set `remaining = 0` and break, reporting completion — replacing the
   `fetched < this_batch` heuristic that cannot fire for dated windows.
4. **Keep the allowance guards**: continue to call `plan_backfill` before each batch, clamp
   `this_batch` to `plan["this_run"]`, skip a fetch that would drive live `remaining` below
   `SAFETY_FLOOR`, re-read the live `allowance` after each batch, and break at the floor —
   reporting the untouched remainder as `deferred`.
5. **Preserve the upsert path and idempotency**: each window still goes through
   `normalise_ig_prices` -> `repo.upsert_bars(..., source="ig", adjusted=False)`; an
   overlapping re-pull inserts no new rows, so a run stays resumable across weeks.
6. **Leave `_backfill_4h`, `_target_points`, `_allowance_state`, `backfill`, and the CLI
   untouched** except for the loop internals of `_backfill_native` (the `4h` derive path
   and grow-forward are explicitly preserved).

### Allowance-Safe Windowing (SP-382 demo-validation follow-up)

A demo-environment validation run proved the backward-paging mechanism itself is correct
(`points_used` ~= distinct bars seeded, ratio ~1.0), but exposed a second, independent
defect: the loop was **not allowance-safe**. It overspent and breached `SAFETY_FLOOR`
(observed: live `remaining` driven to 147, below the 500 floor; an earlier live run hit a
`403 exceeded-account-historical-data-allowance`). Three linked causes and their fixes:

1. **Corrected per-year bar density (`BARS_PER_YEAR`)**. Ground truth measured live on
   demo IG for epic `IX.D.SPTRD.DAILY.IP` at `HOUR` resolution: a **7-calendar-day dated
   window returned 120 bars** => ~17.1 bars/calendar day => `120 / 7 * 365.25` ≈ **6,260
   1h bars/year** (the session is nearly 24x5). The old `BARS_PER_YEAR["1h"] = 1,750`
   undercounted true density by ~3.6x. `BARS_PER_YEAR` is corrected to the measured values
   — `1h = 6,260`, `15m = 25,040` (~4x), `4h = 1,565` (~1/4) — scaled consistently, with
   the `7d -> 120 bars` measurement documented in a code comment so the basis is traceable.
   Because `_target_points` also uses `BARS_PER_YEAR`, this intentionally changes the
   target-points for a given `years`: 2 years of `1h` is now ~12,520 bars, not ~3,500. That
   is correct — the earlier figure reflected the undercount, not real history depth.

2. **Window sized so EXPECTED bars ≈ `this_batch`**. `_window_span` converts a point
   budget to a calendar width via `365.25d * (this_batch / BARS_PER_YEAR[interval])`. With
   the corrected density a 500-bar `1h` window spans ~29 calendar days, which at the
   measured ~17 bars/day returns ~500 bars — so one window costs ~`this_batch` allowance
   points (IG debits one point per bar RETURNED), instead of the ~3.6x overspend the old
   constant caused (a ~104-day window returning ~1,700–3,000+ bars).

3. **Floor-safe guard on ACTUAL bars, with worst-case headroom**. The old pre-fetch guard
   `if state.remaining - this_batch < SAFETY_FLOOR: break` only subtracted the budgeted
   `this_batch`, so it could not see a heavier real window coming. The fixed loop instead:
   - **Before each fetch**, clamps `this_batch` to the largest size whose realistic
     worst-case cost still protects the floor:
     `affordable = (state.remaining - SAFETY_FLOOR) / WINDOW_COST_SAFETY_FACTOR`; if
     `affordable <= 0` it defers the rest. `WINDOW_COST_SAFETY_FACTOR = 4.0` is calibrated
     to the measured ~3.6x historical mismatch (covers it with margin); now that
     `BARS_PER_YEAR` matches reality, residual over-run is only ordinary session-density
     variance, well inside this headroom.
   - **After each fetch**, debits `points_used` by the ACTUAL bars returned and re-reads
     the live `allowance.remainingAllowance`, breaking if it has reached the floor. So the
     guard never relies on the estimate alone — the live allowance is the authority and
     `plan_backfill` / `SAFETY_FLOOR` remain the budget authority.

4. **Corrected deferred/remaining accounting**. `remaining` tracks progress toward target
   DEPTH by the DISTINCT (newly inserted) bars each window seeds, not a flat `this_batch`.
   Re-pulled overlaps (updates) do not deepen history and a dense window may seed many more
   distinct bars than `this_batch`, so decrementing by `result["inserted"]` keeps
   `remaining` an honest "distinct bars still to seed". Consequently `deferred` is
   meaningful and `deferred == 0` genuinely means target depth (or the end-of-history
   break) was reached rather than merely "spent the planned points". The single-window /
   most-recent-N fallback path keeps the original flat `remaining -= this_batch` step
   (each most-recent-N batch is a full window), preserving that path's pinned behaviour.
   The summary dict keys are unchanged: `{inserted, updated, points_used,
   remaining_allowance, deferred}`.

## Testing Strategy

### Validation Approach

Two phases. First, surface counterexamples that demonstrate the bug on the *unfixed*
loop (duplicate-window re-fetching). Then verify the fixed loop pages backward correctly
and that non-paging behavior is unchanged. All tests are hermetic: `IGClient` takes an
injectable `http` transport (tests inject a fake scripted transport), and every IG test
module opts into the `no_ig_network` guard at module scope
(`pytestmark = pytest.mark.usefixtures("no_ig_network")`) so a forgotten injection fails
with `AssertionError("IG network access attempted")` rather than hitting live IG. No test
reads the real project `.env` (a temp `.env` is passed via `env_path`), mirroring the
existing `test_ig_client.py` conventions.

Repo conventions apply before any push / PR / marking Done: `ruff check .` and
`ruff format --check .` clean, then the full suite `pytest -m ""` green (bare `pytest`
deselects the `slow` marker). The new tests carry no `slow` marker — they are fast,
mocked, and network-free.

**Live-API smoke verification uses the IG DEMO environment first.** The hermetic
unit/property/integration tests above never touch the network (`no_ig_network` guard), so
they are unaffected by this note. However, any *ad-hoc* live-API smoke check of the dated
`fetch_prices_range` — confirming the real IG endpoint accepts the dated form and returns
the expected shape — SHOULD be run against the IG **demo** environment first by
constructing the client with `demo=True` (`IGClient(demo=True)`), which selects the
`IG_DEMO_*` credentials and the `IG_DEMO_BASE` (`https://demo-api.ig.com/gateway/deal`)
base URL. The demo account carries its own historical-data allowance, separate from the
live weekly allowance, so exploratory manual verification does not consume the live budget
that the real Pi backfill depends on. Only the actual Pi backfill that seeds ~2 years runs
against the live account (that is the real goal).

New/edited test modules:
- `vpa/tests/test_ig_client.py` (edit) — add `fetch_prices_range` unit tests; update the
  read-only-surface assertion to include `fetch_prices_range`.
- `vpa/tests/test_ig_backfill.py` (new) — exercise `_backfill_native` backward paging
  against a fake `IGClient`/transport and a fake/in-memory repo, plus the `4h` derive and
  allowance-floor preservation cases.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug on the UNFIXED code and
confirm the root cause (the loop never advances a date cursor; windows repeat).

**Test Plan**: Drive `_backfill_native` with a fake client whose `fetch_prices` records
every call and always returns the same newest window (the real most-recent-N behavior),
and a fake repo that records upserts. Assert against the *current* loop to capture the
defect, then re-point the assertions at the fixed loop.

**Test Cases**:
1. **Repeated-window counterexample**: with `target_points > batch_points`, assert that
   on the unfixed loop every fetch requests the identical newest window and the repo sees
   the same bars re-upserted each batch (`updated` grows, `inserted` stays flat) — will
   fail against the fixed loop, which fetches distinct older windows.
2. **No-cursor-advance counterexample**: assert the second batch's requested window equals
   the first on unfixed code (demonstrates the missing cursor).
3. **False `deferred=0` counterexample**: assert the unfixed run reports `deferred=0` while
   the oldest upserted timestamp is far short of the requested depth.
4. **Edge — end-of-history unreachable**: assert the unfixed loop never terminates via an
   empty older window (it only stops on budget/floor).

**Expected Counterexamples**:
- Duplicate newest-window fetches each batch; `points_used` far exceeds distinct bars.
- Possible causes confirmed: no dated client fetch, no date cursor, dead early-stop.

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed loop pages
backward and seeds the requested depth.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := backfillNative_fixed(input)
  ASSERT eachBatchWindowStrictlyOlderThanPrevious(input)
  ASSERT eachWindowUpsertedOnce(input)          // no duplicate-fetch waste
  ASSERT oldestStoredTs(result) ≈ requestedDepth(input)
  ASSERT stopsWhenOlderWindowEmpty(input)
  ASSERT result.remaining_allowance >= SAFETY_FLOOR
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed code
produces the same result as the original.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT backfillNative_original(input) == backfillNative_fixed(input)   // single-window
  ASSERT backfill4h_original(input)     == backfill4h_fixed(input)       // derive path
  ASSERT snapshotParsing_original       == snapshotParsing_fixed         // IG_SNAPSHOT_FMTS
  ASSERT allowancePlanning_original     == allowancePlanning_fixed       // plan_backfill/floor
END FOR
```

**Testing Approach**: Property-based testing (Hypothesis, already used in the repo under
`.hypothesis/`) suits preservation checking: generate many fake window sequences and
allowance states and assert the invariants hold across the input domain, catching edge
cases unit tests miss. Preservation is strongest when the fixed and original behaviors are
compared on the same generated inputs for the non-bug branches.

**Test Plan**: Observe behavior on the UNFIXED code first for the single-window fetch, the
`4h` derive path, and allowance planning, then write tests (example-based and
property-based) that pin that behavior and re-run them against the fixed code.

**Test Cases**:
1. **Single-window preservation**: `target_points <= batch_points` fetches one window and
   upserts once; identical before and after the fix.
2. **`4h` derive preservation**: with native `HOUR_4` unsupported, `_backfill_4h` reads
   stored `1h` and resamples via `resample_1h_to_4h`, `points_used=0`; unchanged.
3. **Idempotent re-pull preservation**: re-running over an overlapping window inserts no
   new rows (idempotent on the PK), so a run stays resumable.
4. **Allowance-floor preservation**: a run stops before `remaining` would fall below
   `SAFETY_FLOOR` and reports the remainder as `deferred`; unchanged by the fix.
5. **`snapshotTime` parsing preservation**: both dated-window date forms map onto the two
   `IG_SNAPSHOT_FMTS`; an unknown shape still raises `ValueError` loudly.

### Unit Tests

- `IGClient.fetch_prices_range` builds the correct new-form URL
  (`/prices/{epic}/{resolution}/{startDate}/{endDate}`, `Version: 3`), formats the dates
  `yyyy-MM-dd HH:mm:ss`, sends the auth headers, parses `{prices, allowance}`, and raises
  `IGAuthError` on non-200 — all against a fake transport.
- `fetch_prices_range` falls back to the older query-string form
  (`?startdate=...&enddate=...`, `Version: 2`, dates `yyyy:MM:dd-HH:mm:ss`) when the new
  form is unavailable (fake transport returns the unavailable status for the new form).
- `fetch_prices_range` auto-logs-in when the session is absent/expired (reset-on-use).
- Updated read-only-surface assertion: public methods are exactly
  `{"login", "fetch_prices", "fetch_prices_range"}`; no deal/order/position tokens.
- `_backfill_native` cursor math: each batch's requested `end` equals the previous
  window's oldest `snapshotTime`; the loop stops on an empty older window; the no-progress
  guard prevents an infinite loop when the cursor fails to move back.

### Property-Based Tests

- Generate random descending window sequences and assert the fixed loop upserts each bar
  once and the oldest stored timestamp reaches the generated depth (no duplicate waste).
- Generate random `AllowanceState` values and assert the loop never drives `remaining`
  below `SAFETY_FLOOR` and reports a consistent `deferred` remainder (`plan_backfill`
  invariants preserved).
- Generate overlapping window re-pulls and assert idempotency (no new inserts on overlap).

### Allowance-Safety Regression — Realistic-Density Windows (SP-382)

The demo-validation bug slipped through because the hermetic fakes spaced the universe at
the loop-matched `cadence_step` (`365.25 / BARS_PER_YEAR`), so a window the loop sized for
`this_batch` points returned EXACTLY `this_batch` bars — masking the density mismatch and
the overspend. The fakes are strengthened so this cannot recur:

- A ground-truth density anchor `TRUE_BARS_PER_DAY` (= `120 / 7`, the measured demo
  figure) and a `density_step` generator space a fake universe at the REAL session
  density, INDEPENDENT of the production `BARS_PER_YEAR` constant. A window the loop sizes
  from `BARS_PER_YEAR` therefore returns a realistic bar count; if `BARS_PER_YEAR` ever
  drifts from the measurement, the fake returns more/fewer bars than the loop budgeted —
  reproducing the exact allowance-safety failure rather than hiding it. A guard test
  (`test_fake_universe_density_matches_measured_ground_truth`) asserts a 7-day slice holds
  ~120 bars so the fake cannot silently revert to the bug-masking cadence.
- A deterministic regression (`test_regression_dense_windows_never_breach_floor_...`)
  drives `_backfill_native` against a universe ~3.6x denser than the loop assumes (the
  measured undercount ratio) with a budget tight enough that the OLD flat-`this_batch`
  guard would have breached the floor, and asserts `remaining_allowance >= SAFETY_FLOOR`
  while still fetching a genuinely dense window (`points_used > batch_points`).
- A Hypothesis property (`test_property_realistic_density_never_breaches_floor`) sweeps the
  oversize factor across `[1.0, 3.6]`, starting allowance, and batch size, asserting the
  in-loop fetches never drive the live `remaining_allowance` below `SAFETY_FLOOR` (the sole
  sub-floor case being the one-time 1-point allowance probe at the exact
  `remaining == SAFETY_FLOOR` boundary, the same bound pinned by the preservation suite).

**Pinned-value changes.** No existing test pinned the old `BARS_PER_YEAR` numbers directly,
so no numeric assertion needed weakening. One integration test
(`test_integration_resumability_second_run_inserts_no_new_rows`) previously used a universe
DEEPER than the target (`depth = target + 400`); with the density correction the loop now
stops precisely at target depth, so a deeper universe would leave an un-seeded gap below
target that the second run would correctly fill as new inserts. The test's universe is
resized to `depth = target` so the first run seeds the whole universe (reaching both target
depth and end-of-history) and the second run is a pure overlap re-pull inserting nothing —
preserving the idempotent-resumability guarantee the test exists to pin, without masking the
(correct) new stop-at-target-depth behaviour.

### Integration Tests

- Full `backfill(epic, "1h", years)` flow against a fake client + in-memory/fake repo:
  pages backward across several windows, seeds to ~target depth, stays above the floor,
  reports `deferred=0` only when end-of-history or target depth is actually reached.
- `backfill(epic, "4h", years)` with native `HOUR_4` unsupported derives from the stored
  `1h` series end-to-end (zero IG allowance spent), unchanged by the fix.
- Resumability: run the loop twice over an overlapping range and assert the second run
  inserts no new rows (idempotent PK), confirming week-to-week resume.
