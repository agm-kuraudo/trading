# Bugfix Requirements Document

## Introduction

The allowance-aware IG intraday backfill (`scripts/ig_backfill.py`, delivered by SP-379)
does not actually deepen stored history. Its native backfill loop (`_backfill_native`)
repeatedly fetches the *same* most-recent window on every batch, so it burns weekly IG
historical-data allowance on duplicate bars and never seeds the intended depth
(~2 years). This was discovered during the first real backfill run for SP-350 (Jira
ticket SP-382).

The root cause is that `IGClient.fetch_prices(epic, resolution, num_points)` only
implements IG's most-recent-N endpoint (`GET /prices/{epic}/{resolution}/{num_points}`).
There is no date cursor and no backward pagination. `_backfill_native` calls
`fetch_prices` with a fixed `this_batch` each iteration and never advances a cursor, so
every batch requests the same most-recent window, re-upserting identical bars and
decrementing the allowance each pass. The `fetched < this_batch` early-stop never trips
because a full batch is always returned.

Evidence from the live Pi run (15 Oct 2026):

- `1h, 2y`: inserted=382, updated=3118, points_used=3500, remaining_allowance=4775, deferred=0
- `4h, 2y`: inserted=470, updated=410, points_used=880, remaining_allowance=3892, deferred=0

Resulting store depth (should be ~2 years):

- `1h`: 500 rows, earliest 2026-09-16 (~1 month), latest 2026-10-15
- `4h`: 502 rows, earliest 2026-06-24 (~4 months), latest 2026-10-15

`points_used=3500` with only `inserted=382` and `updated=3118` is the tell: ~500 recent
bars were fetched ~7 times over (all upserting the same rows), consuming allowance each
pass. `deferred=0` is misleading — it means "spent the planned points", not "reached the
target depth".

Impact / blast radius:

- `1h`/`4h` on the Pi are only ~1-4 months deep, not 2 years (allowance partly wasted).
- Running the `15m` backfill as-is would waste allowance the same way.
- SP-381 (multi-instrument backfill) is built on this same CLI and would inherit the flaw.
- Grow-forward (keeping the store current) is unaffected — it only moves forward and
  works correctly.

The fix direction is to add a date-range historical-prices fetch to `IGClient` (IG offers
`/prices/{epic}/{resolution}/{startDate}/{endDate}` and the older
`/prices/{epic}/{resolution}?startdate=...&enddate=...` form) and change the backfill
loop to page backward through successive older dated windows (newest -> oldest) until the
target depth or the allowance floor is reached, upserting each window once. The fix must
stay allowance-aware (`plan_backfill` / `SAFETY_FLOOR`) and idempotent.

## Bug Analysis

### Current Behavior (Defect)

When a native IG backfill runs, the loop re-requests the most-recent window every batch
rather than walking backward through older history.

1.1 WHEN a native backfill (`_backfill_native`) runs for more than one batch THEN the system re-fetches the same most-recent window on each batch instead of advancing to older history
1.2 WHEN successive batches re-fetch the same window THEN the system re-upserts the identical already-stored bars (reported as `updated`) and consumes IG allowance (`points_used`) on each duplicate pass
1.3 WHEN the requested depth exceeds the most-recent window size THEN the system never reaches the target history depth (earliest stored timestamp stays ~1 month / ~4 months back instead of ~`years` back) yet still reports `deferred=0`
1.4 WHEN `_backfill_native` loops THEN the `fetched < this_batch` early-stop never trips, because the most-recent-N endpoint always returns a full batch, so the loop only ends on budget/floor exhaustion
1.5 WHEN a backfill is requested THEN the only data-retrieval path available is `IGClient.fetch_prices(epic, resolution, num_points)`, which calls the most-recent-N endpoint only and offers no date cursor or backward pagination

### Expected Behavior (Correct)

2.1 WHEN a native backfill runs for more than one batch THEN the system SHALL advance a date cursor so each batch fetches an older dated window than the previous one (newest -> oldest)
2.2 WHEN the backfill pages backward THEN the system SHALL upsert each dated window once, so `points_used` roughly equals the number of distinct bars seeded (no duplicate-fetch allowance waste)
2.3 WHEN a backfill for `years` of history completes within budget THEN the system SHALL seed the store to approximately `years` back (earliest stored timestamp is ~`years` back, not ~1 month)
2.4 WHEN there is no deeper history available (an older window returns no further bars) THEN the system SHALL stop paging backward and report completion rather than looping on an empty/duplicate window
2.5 WHEN the backfill needs dated windows THEN `IGClient` SHALL support a dated historical-prices fetch (a from/to window) in addition to the existing most-recent-N fetch
2.6 WHEN the backward-paging loop runs THEN the system SHALL remain allowance-aware, stopping before the live remaining allowance would fall below `SAFETY_FLOOR` and reporting the untouched remainder as `deferred`

### Unchanged Behavior (Regression Prevention)

3.1 WHEN bars are normalised and upserted THEN the system SHALL CONTINUE TO flow IG bars through `normalise_ig_prices` -> `MarketDataRepository.upsert_bars` tagged `source="ig"`, `adjusted=False`, idempotent on the `(ticker, interval, ts)` PK
3.2 WHEN an overlapping window is pulled again THEN the system SHALL CONTINUE TO insert no new rows (idempotent re-pull), so a run remains resumable across weeks
3.3 WHEN the grow-forward job keeps the store current THEN the system SHALL CONTINUE TO move forward and work correctly, unaffected by the backfill change
3.4 WHEN a `4h` backfill runs and native `HOUR_4` is unsupported for the epic THEN the system SHALL CONTINUE TO derive `4h` bars from the stored `1h` series via `resample_1h_to_4h`, spending zero extra IG allowance
3.5 WHEN an IG `snapshotTime` is parsed (including the two dated-window timestamp forms) THEN the system SHALL CONTINUE TO parse it via the SP-379 multi-format parser (`IG_SNAPSHOT_FMTS`), failing loudly on an unknown format
3.6 WHEN the allowance budget for a run is computed THEN the system SHALL CONTINUE TO use `plan_backfill` and never drive `remainingAllowance` below `SAFETY_FLOOR`
3.7 WHEN the `15m` backfill is run incrementally across weeks THEN the system SHALL CONTINUE TO spend down toward `SAFETY_FLOOR` per run and report the `deferred` remainder for the next week to resume
