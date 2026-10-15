"""Bug-condition exploration test for the IG backfill backward-paging defect (SP-382).

This module encodes **Property 1 (Bug Condition - Backward Paging Deepens History)**
from the ``ig-backfill-paging-fix`` bugfix spec. It drives
``scripts.ig_backfill._backfill_native`` with a fake ``IGClient`` and a fake repo and
asserts the EXPECTED (fixed) behaviour: under the bug condition
(``target_points > batch_points`` with budget for more than one batch) a correct loop
MUST page backward through strictly-older dated windows, upserting each window exactly
once so ``points_used`` roughly equals the number of distinct bars seeded.

**This test is expected to FAIL on the UNFIXED ``_backfill_native``** - the failure
confirms the bug exists (the loop re-fetches the same most-recent window every batch via
``fetch_prices`` and never advances a date cursor). When the backward-paging fix lands
(the new ``IGClient.fetch_prices_range`` + a date-cursor loop) this same test will PASS,
validating the fix (tasks.md task 3.4). Do NOT "fix" this test or the code to make it
pass at this stage - the failing counterexamples ARE the deliverable for task 1.

Hermeticity mirrors ``test_ig_client.py``: the ``no_ig_network`` guard is applied at
module scope and a temporary ``.env`` is passed to any real ``IGClient`` via ``env_path``
so the real project ``.env`` is never read. The ``_backfill_native`` tests here inject a
fully fake client/repo, so no real IG object or network is touched regardless.

_Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5 (bug condition);
Requirements 2.1, 2.2, 2.3, 2.4 (expected behaviour the fix must satisfy)._
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.ig_backfill import DEFAULT_BATCH_POINTS, _backfill_native
from vpa.market_data.ig_ingest import SAFETY_FLOOR

pytestmark = pytest.mark.usefixtures("no_ig_network")


# ---------------------------------------------------------------------------
# Fakes - a most-recent-N IG client and a recording repo
# ---------------------------------------------------------------------------

# A fixed, deterministic universe of distinct 1h bars, newest-first. This stands in
# for the "true" available history on IG. The real most-recent-N endpoint always
# returns the newest N of these, so without a date cursor every batch sees the same
# newest slice. BUG_UNIVERSE_DEPTH deliberately exceeds a single batch so a correct
# loop MUST page backward to seed the full depth.
BUG_UNIVERSE_DEPTH = 1_500
_UNIVERSE_END = pd.Timestamp("2026-10-15 00:00:00", tz="UTC")


def _bar_at(ts: pd.Timestamp) -> dict:
    """Build one IG ``/prices`` bar dict for bar-open ``ts`` (mid-computable OHLC)."""
    # IG_SNAPSHOT_FMTS[1] - the slash-space form seen live on the Pi.
    snapshot = ts.strftime("%Y/%m/%d %H:%M:%S")
    price = {"bid": 100.0, "ask": 100.2}
    return {
        "snapshotTime": snapshot,
        "openPrice": price,
        "highPrice": {"bid": 100.5, "ask": 100.7},
        "lowPrice": {"bid": 99.5, "ask": 99.7},
        "closePrice": price,
        "lastTradedVolume": 1_000,
    }


def _universe_newest_first() -> list[dict]:
    """Return the full fake universe of distinct 1h bars, newest-first."""
    return [_bar_at(_UNIVERSE_END - pd.Timedelta(hours=i)) for i in range(BUG_UNIVERSE_DEPTH)]


class FakeMostRecentNClient:
    """A fake ``IGClient`` that implements IG's real most-recent-N semantics.

    ``fetch_prices(epic, resolution, num_points)`` always returns the newest
    ``num_points`` bars from a fixed universe (newest-first), recording every call -
    exactly how the live endpoint behaves. Because there is no date cursor, every batch
    the unfixed loop issues sees the SAME newest window.

    If the fixed code calls the (not-yet-implemented) dated fetch, this fake records it
    too and serves the correct strictly-older window, so the SAME test validates the fix
    once it lands.
    """

    def __init__(self, universe: list[dict], allowance_remaining: int):
        self._universe = universe  # newest-first
        self._allowance_remaining = allowance_remaining
        self.fetch_calls: list[dict] = []
        self.range_calls: list[dict] = []

    def _allowance(self) -> dict:
        return {"remainingAllowance": self._allowance_remaining, "allowanceExpiry": 60}

    def fetch_prices(self, epic: str, resolution: str, num_points: int) -> dict:
        """Most-recent-N: always the newest ``num_points`` bars (no date cursor)."""
        self.fetch_calls.append({"epic": epic, "resolution": resolution, "num_points": num_points})
        window = self._universe[: max(0, num_points)]
        # Spending one point per returned bar (mirrors IG).
        self._allowance_remaining = max(0, self._allowance_remaining - len(window))
        return {"prices": window, "allowance": self._allowance()}

    def fetch_prices_range(self, epic: str, resolution: str, start, end) -> dict:
        """Dated window ``[start, end)`` - the backward-paging path the fix adds.

        Present so the SAME test exercises the fixed loop. Returns the slice of the
        universe strictly older than ``end`` (newest-first), empty when history runs out.
        """
        start = pd.Timestamp(start)
        end = pd.Timestamp(end)
        self.range_calls.append({"epic": epic, "resolution": resolution, "start": start, "end": end})
        window = [b for b in self._universe if start <= pd.Timestamp(b["snapshotTime"].replace("/", "-")) < end]
        self._allowance_remaining = max(0, self._allowance_remaining - len(window))
        return {"prices": window, "allowance": self._allowance()}


class RecordingRepo:
    """A fake ``MarketDataRepository`` recording every upsert and simulating the PK.

    Idempotent on ``(ticker, interval, Date)``: a bar seen before counts as ``updated``,
    a new bar counts as ``inserted`` - the real ``upsert_bars`` contract. Records the set
    of distinct timestamps ever stored so the test can compare distinct bars seeded
    against ``points_used``.
    """

    def __init__(self):
        self.upsert_calls: list[dict] = []
        self._seen_ts: set[pd.Timestamp] = set()

    def upsert_bars(self, df: pd.DataFrame, ticker: str, interval: str, *, source: str, adjusted: bool) -> dict:
        self.upsert_calls.append(
            {
                "ticker": ticker,
                "interval": interval,
                "source": source,
                "adjusted": adjusted,
                "dates": list(pd.to_datetime(df["Date"], utc=True)),
            }
        )
        inserted = 0
        updated = 0
        for ts in pd.to_datetime(df["Date"], utc=True):
            if ts in self._seen_ts:
                updated += 1
            else:
                self._seen_ts.add(ts)
                inserted += 1
        return {"inserted": inserted, "updated": updated}

    @property
    def distinct_bars(self) -> int:
        return len(self._seen_ts)

    @property
    def oldest_ts(self) -> pd.Timestamp | None:
        return min(self._seen_ts) if self._seen_ts else None


# ---------------------------------------------------------------------------
# Property 1: Bug Condition - Backward Paging Deepens History
# ---------------------------------------------------------------------------

# Concrete bug-condition case: target depth exceeds one batch AND there is budget for
# more than one batch, so isBugCondition holds and a correct loop MUST page backward.
_BATCH_POINTS = DEFAULT_BATCH_POINTS  # 500
_TARGET_POINTS = 1_500  # 3 batches' worth
_ALLOWANCE_REMAINING = 9_900  # budget = 9_900 - SAFETY_FLOOR = 9_400 > one batch
_EPIC = "IX.D.SPTRD.DAILY.IP"
_RESOLUTION = "HOUR"


def _run_native():
    """Drive ``_backfill_native`` for the concrete bug-condition case; return parts."""
    client = FakeMostRecentNClient(_universe_newest_first(), _ALLOWANCE_REMAINING)
    repo = RecordingRepo()
    summary = _backfill_native(
        client,
        repo,
        _EPIC,
        "1h",
        _RESOLUTION,
        _TARGET_POINTS,
        _BATCH_POINTS,
    )
    return client, repo, summary


def test_bug_condition_is_satisfied_by_the_scenario():
    """Sanity: this scenario really is a bug condition (needs backward paging).

    ``target_points > batch_points`` and the planned budget (``remaining - SAFETY_FLOOR``)
    exceeds one batch, so a correct ``_backfill_native`` MUST advance a date cursor.
    """
    assert _TARGET_POINTS > _BATCH_POINTS
    assert (_ALLOWANCE_REMAINING - SAFETY_FLOOR) > _BATCH_POINTS


def test_backfill_pages_backward_through_strictly_older_windows():
    """Property 1: each successive batch fetches a STRICTLY OLDER dated window.

    EXPECTED behaviour (fixed loop): the loop advances a date cursor so each batch's
    requested window is older than the previous one (newest -> oldest).

    FAILS on the UNFIXED loop - counterexample (b): the unfixed code never requests a
    dated window at all (``fetch_prices_range`` is never called); it re-issues the same
    most-recent-N ``fetch_prices`` every batch, so there is no cursor to advance and the
    second batch's window equals the first.

    _Validates: Requirements 2.1_
    """
    client, _repo, _summary = _run_native()

    # A correct loop pages backward via dated windows (more than one batch here).
    assert len(client.range_calls) >= 2, (
        "unfixed loop never requested a dated window: "
        f"range_calls={client.range_calls!r}, fetch_calls={client.fetch_calls!r}"
    )
    # Each successive requested window must be strictly older than the last.
    ends = [c["end"] for c in client.range_calls]
    for earlier, later in zip(ends, ends[1:], strict=False):
        assert (
            later < earlier
        ), f"second batch window did not advance backward (no cursor advance): window ends = {ends!r}"


def test_each_window_upserted_once_no_duplicate_waste():
    """Property 1: each dated window is upserted ONCE; points_used ~= distinct bars.

    EXPECTED behaviour (fixed loop): distinct bars seeded roughly equals ``points_used``,
    because each window is fetched and upserted exactly once (no duplicate-fetch waste).

    FAILS on the UNFIXED loop - counterexample (a): every batch re-fetches the identical
    newest window, so the repo re-upserts the SAME bars (``updated`` grows while distinct
    bars stay flat) and ``points_used`` far exceeds the distinct bars seeded.

    _Validates: Requirements 2.2_
    """
    _client, repo, summary = _run_native()

    distinct = repo.distinct_bars
    # No duplicate-fetch waste: spent points track distinct bars seeded (within a batch).
    assert summary["points_used"] <= distinct + _BATCH_POINTS, (
        f"points_used={summary['points_used']} far exceeds distinct bars seeded "
        f"({distinct}) - duplicate-window re-fetching detected"
    )
    # Across all upsert calls, no timestamp is upserted more than once (each window once).
    all_dates: list[pd.Timestamp] = []
    for call in repo.upsert_calls:
        all_dates.extend(call["dates"])
    assert len(all_dates) == len(set(all_dates)), (
        "a bar was upserted more than once (duplicate windows): "
        f"{len(all_dates)} upserted vs {len(set(all_dates))} distinct"
    )


def test_store_seeded_to_requested_depth_despite_deferred_zero():
    """Property 1: oldest stored bar reaches ~requested depth; deferred=0 means done.

    EXPECTED behaviour (fixed loop): the oldest upserted timestamp reaches approximately
    the requested depth (``target_points`` bars back from newest).

    FAILS on the UNFIXED loop - counterexample (c): the run reports ``deferred=0``
    ("spent the planned points") while the oldest upserted bar is only one batch deep,
    far short of the requested depth.

    _Validates: Requirements 2.3_
    """
    _client, repo, summary = _run_native()

    assert repo.oldest_ts is not None
    requested_depth_ts = _UNIVERSE_END - pd.Timedelta(hours=_TARGET_POINTS - 1)
    # Allow a one-batch slack; the point is the store reaches ~target depth, not ~1 batch.
    tolerance = pd.Timedelta(hours=_BATCH_POINTS)
    assert repo.oldest_ts <= requested_depth_ts + tolerance, (
        f"oldest stored bar {repo.oldest_ts} is far short of the requested depth "
        f"{requested_depth_ts} even though deferred={summary['deferred']}"
    )


def test_loop_stops_on_empty_older_window_not_only_on_budget():
    """Property 1: the loop can terminate by exhausting history (empty older window).

    EXPECTED behaviour (fixed loop): paging backward reaches the end of available history
    and stops because a dated window returns no further bars - reaching the full universe
    depth within the generous budget.

    FAILS on the UNFIXED loop - counterexample (d): the most-recent-N endpoint always
    returns a full batch, so ``fetched < this_batch`` never trips; the loop only ends on
    budget/floor exhaustion and can never terminate on an empty older window. The store
    therefore never reaches the full universe depth.

    _Validates: Requirements 2.4_
    """
    _client, repo, _summary = _run_native()

    # With budget for the whole universe, a backward-paging loop seeds (nearly) all of it.
    assert repo.distinct_bars >= BUG_UNIVERSE_DEPTH - _BATCH_POINTS, (
        f"only {repo.distinct_bars} distinct bars seeded of {BUG_UNIVERSE_DEPTH} available "
        "- the loop never paged backward to exhaust history"
    )
