"""Unit, property-based and integration coverage for the IG backward-paging fix (SP-382, task 4).

This module adds the task-4 coverage described in the ``ig-backfill-paging-fix`` design
("Testing Strategy": Unit Tests, Property-Based Tests, Integration Tests). It is ADDITIVE
to the task-1 exploration tests (``test_ig_backfill.py``) and the task-2 preservation
tests (``test_ig_backfill_preservation.py``) - it does not weaken or replace them. It
exercises the FIXED ``scripts.ig_backfill`` code (the dated ``IGClient.fetch_prices_range``
plus the date-cursor ``_backfill_native`` loop).

Three layers (all hermetic, no ``slow`` marker):

- **Unit** - ``_backfill_native`` cursor math: each batch's requested ``end`` equals the
  previous window's oldest ``snapshotTime``; the loop stops on an empty older window; the
  no-progress guard prevents an infinite loop when the cursor cannot move back.
- **Property-based (Hypothesis)** - random descending window sequences upsert each bar
  once and reach the generated depth; random ``AllowanceState`` values never drive
  ``remaining`` below ``SAFETY_FLOOR`` with a consistent ``deferred``; overlapping re-pulls
  are idempotent (no new inserts on overlap).
- **Integration (fake client + fake repo)** - full ``backfill(epic, "1h", years)`` pages
  backward across several windows, seeds ~target depth, stays above the floor, and reports
  ``deferred=0`` only when end-of-history / target depth is actually reached;
  ``backfill(epic, "4h", years)`` with native ``HOUR_4`` unsupported derives from the
  stored ``1h`` series (zero IG allowance spent); resumability - a second run over an
  overlapping range inserts no new rows.

Hermeticity mirrors ``test_ig_client.py``: the ``no_ig_network`` guard is applied at module
scope so any accidental real transport use fails loudly. The ``_backfill_native`` /
``backfill`` paths here inject fully fake client/repo objects (the integration tests
monkeypatch ``scripts.ig_backfill.IGClient`` / ``MarketDataRepository`` with the shared
fakes), so no real IG object, network, or store is touched. No real project ``.env`` is
read. Shared fakes live in ``vpa.tests.ig_backfill_fakes`` (reused here to stay DRY without
disturbing the task-1/task-2 modules' own local fakes).

_Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.6, 3.1, 3.2, 3.4._
"""

from __future__ import annotations

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import scripts.ig_backfill as ig_backfill
import vpa.market_data.ohlcv_ingest as ohlcv_ingest
from scripts.ig_backfill import (
    DEFAULT_BATCH_POINTS,
    _backfill_native,
    backfill,
)
from vpa.market_data.ig_ingest import SAFETY_FLOOR, resample_1h_to_4h
from vpa.tests.ig_backfill_fakes import (
    TRUE_BARS_PER_DAY,
    UNIVERSE_END,
    FakeDatedClient,
    RecordingRepo,
    bar_at,
    cadence_step,
    density_step,
    universe_newest_first,
)

pytestmark = pytest.mark.usefixtures("no_ig_network")


_EPIC = "IX.D.SPTRD.DAILY.IP"
_RESOLUTION = "HOUR"
_BATCH_POINTS = DEFAULT_BATCH_POINTS  # 500


# ---------------------------------------------------------------------------
# Unit: _backfill_native cursor math
# ---------------------------------------------------------------------------


def test_cursor_end_equals_previous_window_oldest_snapshot():
    """Unit: each batch's requested ``end`` equals the previous window's oldest bar.

    The fixed loop walks a date cursor backward: after upserting a window it advances the
    cursor to the OLDEST ``snapshotTime`` seen, so the NEXT dated fetch requests
    ``end == that oldest timestamp``. This pins the cursor arithmetic directly - for every
    adjacent pair of range calls, the later call's ``end`` equals the oldest bar returned
    by the earlier call's window.

    _Validates: Requirements 2.1, 2.6_
    """
    client = FakeDatedClient(universe_newest_first(1_500), allowance_remaining=9_900)
    repo = RecordingRepo()

    _backfill_native(client, repo, _EPIC, "1h", _RESOLUTION, 1_500, _BATCH_POINTS)

    # More than one dated window was requested (the run needed to page backward).
    assert len(client.range_calls) >= 2

    # For each adjacent pair, the next window's end == the oldest bar in the prior window.
    for prior, nxt in zip(client.range_calls, client.range_calls[1:], strict=False):
        prior_start, prior_end = prior["start"], prior["end"]
        oldest_in_prior = min(
            pd.Timestamp(b["snapshotTime"].replace("/", "-"), tz="UTC")
            for b in client._universe
            if prior_start <= pd.Timestamp(b["snapshotTime"].replace("/", "-"), tz="UTC") < prior_end
        )
        # Cursor is kept tz-naive UTC in the loop; compare on the same wall clock.
        assert (
            pd.Timestamp(nxt["end"]).tz_convert("UTC") == oldest_in_prior
        ), f"batch end {nxt['end']} != previous window oldest snapshot {oldest_in_prior}"


def test_loop_stops_on_empty_older_window():
    """Unit: paging stops (reports completion) when an older window returns no bars.

    With budget far exceeding the whole 300-bar universe, the fixed loop pages backward
    until a dated window older than the oldest bar comes back EMPTY. At that point it sets
    ``remaining = 0`` and breaks, so ``deferred == 0`` and the store holds the entire
    universe - it stopped on end-of-history, not on budget.

    _Validates: Requirements 2.4_
    """
    depth = 300
    client = FakeDatedClient(universe_newest_first(depth), allowance_remaining=9_900)
    repo = RecordingRepo()

    summary = _backfill_native(client, repo, _EPIC, "1h", _RESOLUTION, 2_000, _BATCH_POINTS)

    # The whole universe is seeded and the run reports completion (not a budget stop).
    assert repo.distinct_bars() == depth
    assert summary["deferred"] == 0
    # The last dated window requested returned no bars (end-of-history signal).
    last = client.range_calls[-1]
    tail = [
        b
        for b in client._universe
        if last["start"] <= pd.Timestamp(b["snapshotTime"].replace("/", "-"), tz="UTC") < last["end"]
    ]
    assert tail == []


def test_no_progress_guard_prevents_infinite_loop():
    """Unit: the no-progress guard breaks when the cursor cannot move backward.

    If a dated window keeps returning the SAME newest bar (so the oldest ``snapshotTime``
    never moves the cursor back), a naive loop would spin forever. The guard detects
    ``oldest >= cursor`` and breaks. Here a pathological client always returns a single
    fixed bar at ``UNIVERSE_END`` regardless of the requested window; the loop must still
    terminate and return a summary rather than hang.

    _Validates: Requirements 2.1, 2.6_
    """

    class StuckClient(FakeDatedClient):
        def fetch_prices_range(self, epic, resolution, start, end):
            self.range_calls.append({"epic": epic, "resolution": resolution, "start": start, "end": end})
            # Always the same newest bar - the oldest ts never moves the cursor back.
            self._allowance_remaining = max(0, self._allowance_remaining - 1)
            return {"prices": [bar_at(UNIVERSE_END)], "allowance": self._allowance()}

    client = StuckClient(universe_newest_first(1_500), allowance_remaining=9_900)
    repo = RecordingRepo()

    summary = _backfill_native(client, repo, _EPIC, "1h", _RESOLUTION, 1_500, _BATCH_POINTS)

    # Terminated (no hang) with a well-formed summary; only the one fixed bar was stored.
    assert set(summary) == {"inserted", "updated", "points_used", "remaining_allowance", "deferred"}
    assert repo.distinct_bars() == 1
    # The guard tripped quickly rather than issuing an unbounded number of fetches.
    assert len(client.range_calls) <= 3


# ---------------------------------------------------------------------------
# Property-based (Hypothesis)
# ---------------------------------------------------------------------------

# Built once and shared by the allowance-floor property so each generated example does
# not rebuild a large bar list. Larger than any point total the property's budget could
# ever pull, so the fetch never runs dry and the allowance guard is the only stopping
# condition exercised. Spaced at the 1h session cadence so a dated window sized for
# ``this_batch`` points returns ~``this_batch`` bars (matching real session-gapped IG
# history), making the per-batch allowance spend track the loop's own budgeting.
_ALLOWANCE_PROPERTY_UNIVERSE = universe_newest_first(6_000, step=cadence_step("1h"))


@settings(max_examples=40, deadline=None)
@given(
    depth=st.integers(min_value=1, max_value=1_600),
    batch_points=st.sampled_from([100, 250, 500]),
)
def test_property_descending_windows_upsert_each_bar_once_and_reach_depth(depth, batch_points):
    """Property: paging backward upserts each bar exactly once and reaches full depth.

    For a randomly-sized descending universe (``depth`` hourly bars) with ample budget,
    the fixed loop pages backward through strictly-older dated windows until history is
    exhausted. Each bar is upserted exactly once (no duplicate-fetch waste), so the sum of
    upserted timestamps across all calls has no repeats, and the oldest stored bar reaches
    the generated depth (the universe's oldest bar).

    _Validates: Requirements 2.1, 2.2, 2.3, 2.4_
    """
    step = cadence_step("1h")
    universe = universe_newest_first(depth, step=step)
    client = FakeDatedClient(universe, allowance_remaining=9_900)
    repo = RecordingRepo()

    # Target larger than the universe so end-of-history (not the target) is the stop.
    target_points = depth + batch_points + 10
    _backfill_native(client, repo, _EPIC, "1h", _RESOLUTION, target_points, batch_points)

    # Every bar upserted exactly once across all upsert calls (no duplicate waste).
    all_dates: list[pd.Timestamp] = []
    for call in repo.upsert_calls:
        all_dates.extend(call["dates"])
    assert len(all_dates) == len(set(all_dates))

    # The whole universe was seeded and the oldest stored bar reaches the generated depth
    # (the oldest bar actually present in the universe - the fake serialises bar times to
    # whole seconds, so compare against that true oldest rather than the raw cadence math).
    assert repo.distinct_bars() == depth
    expected_oldest = min(pd.Timestamp(b["snapshotTime"].replace("/", "-"), tz="UTC") for b in universe)
    assert repo.oldest_ts() == expected_oldest


@settings(max_examples=40, deadline=None)
@given(
    remaining=st.integers(min_value=0, max_value=5_000),
    target_points=st.integers(min_value=0, max_value=4_000),
    batch_points=st.sampled_from([100, 250, 500, 1_000]),
)
def test_property_fixed_loop_never_drives_remaining_below_floor(remaining, target_points, batch_points):
    """Property: the FIXED paging loop keeps live ``remaining`` at/above the floor.

    For arbitrary ``AllowanceState`` / target / batch sizes the fixed backward-paging loop
    stays allowance-aware: its in-loop fetches never drive the live remaining allowance
    below ``SAFETY_FLOOR``, and it always reports a non-negative ``deferred`` no greater
    than the target. (The one-time 1-point allowance probe before the loop may spend a
    single point at the exact boundary - ``remaining == SAFETY_FLOOR`` with no in-loop
    headroom - exactly as pinned in the task-2 preservation suite, so the general lower
    bound is ``SAFETY_FLOOR - 1`` and tightens to ``SAFETY_FLOOR`` whenever a real in-loop
    fetch actually ran.)

    A generous universe (larger than any point total the generated budget could pull)
    stands in for IG's history so the fetch never runs dry - isolating the allowance guard
    as the only stopping condition under test.

    _Validates: Requirements 2.6, 3.6, 3.7_
    """
    client = FakeDatedClient(_ALLOWANCE_PROPERTY_UNIVERSE, remaining)
    repo = RecordingRepo()

    summary = _backfill_native(client, repo, _EPIC, "1h", _RESOLUTION, target_points, batch_points)

    remaining_allowance = summary["remaining_allowance"]
    assert remaining_allowance is not None

    if remaining >= SAFETY_FLOOR:
        assert remaining_allowance >= SAFETY_FLOOR - 1
        if summary["points_used"] > 0:
            assert remaining_allowance >= SAFETY_FLOOR
    else:
        assert remaining_allowance <= remaining
        assert summary["deferred"] == target_points

    assert 0 <= summary["deferred"] <= target_points
    assert summary["points_used"] >= 0


@settings(max_examples=30, deadline=None)
@given(
    depth=st.integers(min_value=1, max_value=1_200),
    batch_points=st.sampled_from([250, 500]),
)
def test_property_overlapping_re_pull_is_idempotent(depth, batch_points):
    """Property: a second paging run over the same range inserts no new rows.

    Running the fixed loop twice against a SHARED repo over an overlapping range seeds the
    universe on the first run and, because the ``(ticker, interval, ts)`` PK is idempotent,
    re-pulls the SAME bars on the second run as all-updates (zero new inserts, no growth in
    distinct stored bars). This is what makes a run resumable across weeks.

    _Validates: Requirements 3.2_
    """
    repo = RecordingRepo()
    target_points = depth + batch_points + 10
    step = cadence_step("1h")

    first = _backfill_native(
        FakeDatedClient(universe_newest_first(depth, step=step), allowance_remaining=9_900),
        repo,
        _EPIC,
        "1h",
        _RESOLUTION,
        target_points,
        batch_points,
    )
    seeded = repo.distinct_bars()
    assert first["inserted"] == seeded
    assert seeded == depth

    second = _backfill_native(
        FakeDatedClient(universe_newest_first(depth, step=step), allowance_remaining=9_900),
        repo,
        _EPIC,
        "1h",
        _RESOLUTION,
        target_points,
        batch_points,
    )
    # Overlap re-pull: nothing new inserted, every seen bar an update, depth unchanged.
    assert second["inserted"] == 0
    assert second["updated"] >= 1
    assert repo.distinct_bars() == depth


# ---------------------------------------------------------------------------
# Allowance-safety regression (SP-382): REALISTIC-density windows
# ---------------------------------------------------------------------------
#
# These are the KEY regression tests. The earlier hermetic fakes spaced the universe at
# ``cadence_step`` (``365.25 / BARS_PER_YEAR``), so a window the loop sized for
# ``this_batch`` points returned EXACTLY ``this_batch`` bars - which masked the real bug
# (an undersized ``BARS_PER_YEAR`` oversized every dated window, and because IG debits one
# allowance point per bar RETURNED, each window cost far more than ``this_batch`` points,
# breaching the floor). Here the fake universe is spaced at the MEASURED demo-IG density
# (``density_step`` / ``TRUE_BARS_PER_DAY``), INDEPENDENT of ``BARS_PER_YEAR``, so a
# mismatch between the loop's assumed density and reality makes a window return MORE bars
# than the loop budgeted - exactly the live failure - and we assert the floor is never
# breached regardless.


def _oversized_universe(depth: int, oversize: float) -> list[dict]:
    """Return a universe whose density is ``oversize``x what the loop's window math assumes.

    The loop sizes a window from ``BARS_PER_YEAR`` expecting ~``this_batch`` bars; spacing
    the fake universe ``oversize`` times DENSER than that assumption means a window the loop
    thinks holds ``this_batch`` bars actually returns ~``oversize * this_batch`` bars - the
    density-undercount failure mode. Spaced from the loop-matched ``cadence_step`` divided
    by ``oversize`` so the oversize factor is explicit and does not depend on the measured
    constant staying equal to ``BARS_PER_YEAR``.
    """
    return universe_newest_first(depth, step=cadence_step("1h") / oversize)


def test_regression_dense_windows_never_breach_floor_even_when_oversized():
    """Regression (SP-382): windows returning MANY more bars than this_batch stay above floor.

    This is the exact failure that slipped through: a dated window sized for ``this_batch``
    points returns far MORE bars (because real density outran the loop's assumption), and IG
    debits one point per returned bar, so the window overspends. With a universe spaced ~3.6x
    DENSER than the loop assumes (the measured undercount ratio) and a budget tight enough
    that the OLD guard - which only reserved a flat ``this_batch`` - would have breached the
    floor, the fixed loop MUST still leave ``remaining_allowance >= SAFETY_FLOOR``.

    _Validates: Requirements 2.6_
    """
    oversize = 3.6  # the measured density undercount ratio (6260 / 1750)
    # Budget tight enough that one flat-this_batch step looks affordable but a 3.6x-dense
    # window would blow past the floor under the OLD guard (which reserved only this_batch).
    allowance = SAFETY_FLOOR + 1_200
    client = FakeDatedClient(_oversized_universe(5_000, oversize), allowance_remaining=allowance)
    repo = RecordingRepo()

    summary = _backfill_native(client, repo, _EPIC, "1h", _RESOLUTION, 4_000, _BATCH_POINTS)

    # The core guarantee: the floor is never breached, even though each window returned
    # ~3.6x the bars the loop budgeted for (the fixed guard reserves a worst-case window
    # cost and debits the ACTUAL bars returned).
    assert summary["remaining_allowance"] >= SAFETY_FLOOR
    # And it genuinely fetched a dense window (more bars than a single budgeted batch),
    # proving the assertion is not vacuous.
    assert summary["points_used"] > _BATCH_POINTS


@settings(max_examples=40, deadline=None)
@given(
    oversize=st.floats(min_value=1.0, max_value=3.6),
    remaining=st.integers(min_value=SAFETY_FLOOR, max_value=6_000),
    batch_points=st.sampled_from([100, 250, 500, 1_000]),
)
def test_property_realistic_density_never_breaches_floor(oversize, remaining, batch_points):
    """Property (SP-382): for any density over-run, the loop never drops below the floor.

    Generates universes spaced from 1x up to 3.6x DENSER than the loop's window math assumes
    (so each dated window returns up to the measured-undercount ratio more bars than the loop
    budgeted, and IG debits one point per returned bar) across a range of starting allowances
    and batch sizes. The fixed floor-safe guard - which reserves a realistic worst-case window
    cost (``WINDOW_COST_SAFETY_FACTOR`` x ``this_batch``, calibrated to that 3.6x measured
    mismatch) before each fetch and debits the ACTUAL bars returned - must keep the live
    ``remaining_allowance`` at or above ``SAFETY_FLOOR`` for every IN-LOOP fetch. This is the
    universal form of the exact failure the demo run hit (remaining driven to 147, below the
    500 floor).

    The sole sub-floor case is the one-time 1-point allowance probe before the loop: when the
    run STARTS at exactly ``remaining == SAFETY_FLOOR`` the probe spends the single point,
    leaving ``SAFETY_FLOOR - 1`` (the same boundary pinned in the task-2 preservation suite).
    So the general lower bound is ``SAFETY_FLOOR - 1``, tightening to ``SAFETY_FLOOR`` whenever
    a real in-loop fetch actually ran (``points_used > 0``).

    _Validates: Requirements 2.6_
    """
    universe = _oversized_universe(8_000, oversize)
    client = FakeDatedClient(universe, allowance_remaining=remaining)
    repo = RecordingRepo()

    summary = _backfill_native(client, repo, _EPIC, "1h", _RESOLUTION, 4_000, batch_points)

    assert summary["remaining_allowance"] >= SAFETY_FLOOR - 1
    if summary["points_used"] > 0:
        assert summary["remaining_allowance"] >= SAFETY_FLOOR


def test_fake_universe_density_matches_measured_ground_truth():
    """Guard: the realistic-density fake really packs ~17 bars per calendar day.

    Anchors the regression fakes to the SP-382 measurement (120 bars over 7 calendar days
    ~= 17.14 bars/day). A 7-day slice of a ``density_step`` universe must contain ~120 bars,
    so if the fake ever silently drifts back to the loop-matched (bug-masking) cadence this
    guard fails loudly.
    """
    universe = universe_newest_first(1_000, step=density_step("1h"))
    end = UNIVERSE_END
    start = end - pd.Timedelta(days=7)
    in_window = [b for b in universe if start <= pd.Timestamp(b["snapshotTime"].replace("/", "-"), tz="UTC") < end]
    # ~17.14 bars/day * 7 days = ~120; allow a small rounding band.
    assert abs(len(in_window) - round(TRUE_BARS_PER_DAY * 7)) <= 2


# ---------------------------------------------------------------------------
# Integration: full backfill(epic, interval, years) with injected fakes
# ---------------------------------------------------------------------------


def _install_fakes(monkeypatch, client, repo):
    """Monkeypatch ``backfill``'s internally-constructed client/repo with fakes.

    ``backfill`` builds ``IGClient()`` and ``MarketDataRepository()`` itself, so the
    integration tests swap those names in the ``scripts.ig_backfill`` namespace for the
    injected fakes (keeping the run network-free and store-free end to end).
    """
    monkeypatch.setattr(ig_backfill, "IGClient", lambda *a, **k: client)
    monkeypatch.setattr(ig_backfill, "MarketDataRepository", lambda *a, **k: repo)


def _stored_1h_from_universe(depth: int) -> pd.DataFrame:
    """Build a canonical stored ``1h`` DataFrame of ``depth`` ascending hourly bars."""
    rows = []
    for i in range(depth):
        ts = UNIVERSE_END - pd.Timedelta(hours=i)
        rows.append({"Date": ts, "Open": 100.1, "High": 100.6, "Low": 99.6, "Close": 100.1, "Volume": 1_000.0})
    df = pd.DataFrame(rows, columns=ohlcv_ingest.CANONICAL_COLUMNS)
    return df.sort_values("Date").reset_index(drop=True)


def test_integration_1h_backfill_pages_backward_and_seeds_target_depth(monkeypatch):
    """Integration: ``backfill(epic, "1h", years)`` pages backward and seeds ~target depth.

    With a universe deeper than the target and ample allowance, the full ``backfill`` entry
    point pages backward across several dated windows, seeds roughly the target depth
    (``BARS_PER_YEAR["1h"] * years`` bars), stays above the floor, and reports
    ``deferred=0`` because the target depth was actually reached.

    _Validates: Requirements 2.1, 2.2, 2.3, 2.6_
    """
    years = 1
    target = ig_backfill.BARS_PER_YEAR["1h"] * years  # 1,750
    step = cadence_step("1h")
    # Universe deeper than the target so the stop is the target, not end-of-history.
    client = FakeDatedClient(universe_newest_first(target + 600, step=step), allowance_remaining=9_900)
    repo = RecordingRepo()
    _install_fakes(monkeypatch, client, repo)

    summary = backfill(_EPIC, "1h", years)

    # Paged backward across several windows (not a single most-recent-N fetch).
    assert len(client.range_calls) >= 3
    # Seeded ~target depth (within one batch) and stayed above the floor.
    assert repo.distinct_bars(_EPIC, "1h") >= target - _BATCH_POINTS
    assert summary["remaining_allowance"] >= SAFETY_FLOOR
    # Target depth reached -> deferred reports completion.
    assert summary["deferred"] == 0
    oldest = repo.oldest_ts(_EPIC, "1h")
    requested_depth_ts = UNIVERSE_END - step * (target - 1)
    assert oldest <= requested_depth_ts + step * _BATCH_POINTS


def test_integration_1h_backfill_stops_above_floor_short_of_target_on_tight_budget(monkeypatch):
    """Integration: a tight budget stops the run above the floor and short of target depth.

    When the allowance budget cannot cover the target depth, the run spends down toward the
    floor and stops BEFORE breaching it (``remaining_allowance >= SAFETY_FLOOR``), seeding
    fewer than the target bars - the budget-limited stop path (Req 2.6). A run can only reach
    the full target depth when the budget actually covers it, and the floor is never breached
    regardless; the resumability test confirms a later run picks up the remainder over the
    idempotent PK.

    _Validates: Requirements 2.3, 2.6_
    """
    years = 2
    target = ig_backfill.BARS_PER_YEAR["1h"] * years  # 3,500
    step = cadence_step("1h")
    # Tight budget: only ~1,000 points spendable above the floor - far short of 3,500.
    client = FakeDatedClient(universe_newest_first(target + 1_000, step=step), allowance_remaining=SAFETY_FLOOR + 1_000)
    repo = RecordingRepo()
    _install_fakes(monkeypatch, client, repo)

    summary = backfill(_EPIC, "1h", years)

    # Stopped at/above the floor, short of the full target (budget-limited, not done).
    assert summary["remaining_allowance"] >= SAFETY_FLOOR
    assert repo.distinct_bars(_EPIC, "1h") < target
    # Only ~the spendable budget was consumed (no duplicate-window waste).
    assert summary["points_used"] <= 1_000 + _BATCH_POINTS


def test_integration_4h_derives_from_stored_1h_with_zero_allowance(monkeypatch):
    """Integration: ``backfill(epic, "4h", years)`` derives from stored ``1h`` (zero allowance).

    With native ``HOUR_4`` unsupported (the probe returns empty), the full ``backfill``
    entry point reads the stored ``1h`` series via ``get_ohlcv`` and resamples it to ``4h``
    through ``resample_1h_to_4h``, upserting the derived bars once and spending ZERO IG
    allowance (``points_used=0``). The derived bar count equals the pure resampler's output.

    _Validates: Requirements 3.1, 3.4_
    """
    stored_1h = _stored_1h_from_universe(200)
    client = FakeDatedClient([], allowance_remaining=9_900, probe_supported=False)
    repo = RecordingRepo(stored_1h=stored_1h)
    _install_fakes(monkeypatch, client, repo)

    summary = backfill(_EPIC, "4h", 1)

    expected_4h = resample_1h_to_4h(stored_1h)
    assert summary["points_used"] == 0
    assert summary["remaining_allowance"] is None
    assert summary["deferred"] == 0
    assert summary["inserted"] == len(expected_4h)
    # Only the native HOUR_4 probe hit the client; no deeper native pull, no dated windows.
    assert [c["resolution"] for c in client.fetch_calls] == ["HOUR_4"]
    assert client.range_calls == []
    # The 1h series was read and exactly one 4h upsert was written.
    assert len(repo.get_ohlcv_calls) == 1
    assert repo.get_ohlcv_calls[0]["interval"] == "1h"
    assert repo.distinct_bars(_EPIC, "4h") == len(expected_4h)


def test_integration_resumability_second_run_inserts_no_new_rows(monkeypatch):
    """Integration: a second full ``backfill`` over an overlapping range inserts nothing new.

    Running ``backfill(epic, "1h", years)`` twice against a SHARED fake repo seeds the
    history on the first run and, because the PK is idempotent, re-pulls the same overlap on
    the second run as all-updates (zero new inserts, unchanged depth) - confirming
    week-to-week resumability.

    _Validates: Requirements 3.2_
    """
    years = 1
    target = ig_backfill.BARS_PER_YEAR["1h"] * years
    # Universe == target depth so the first run seeds the WHOLE universe (reaching both
    # target depth and end-of-history), making the second run a pure overlap re-pull.
    # (With the SP-382 density correction a window now costs ~this_batch, so the loop
    # stops precisely at target depth; a universe DEEPER than target would leave an
    # un-seeded gap below target that a second run would legitimately fill as new inserts,
    # which is correct resume-to-depth behaviour but not the pure-overlap idempotency this
    # test pins. Sizing the universe to the target keeps the overlap exact.)
    depth = target
    step = cadence_step("1h")
    repo = RecordingRepo()

    _install_fakes(monkeypatch, FakeDatedClient(universe_newest_first(depth, step=step), 9_900), repo)
    first = backfill(_EPIC, "1h", years)
    seeded = repo.distinct_bars(_EPIC, "1h")
    assert first["inserted"] == seeded
    assert seeded > 0

    _install_fakes(monkeypatch, FakeDatedClient(universe_newest_first(depth, step=step), 9_900), repo)
    second = backfill(_EPIC, "1h", years)

    assert second["inserted"] == 0
    assert second["updated"] >= 1
    assert repo.distinct_bars(_EPIC, "1h") == seeded
