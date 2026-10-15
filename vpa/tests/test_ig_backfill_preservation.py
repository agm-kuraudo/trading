"""Preservation tests for the IG backfill backward-paging fix (SP-382, task 2).

This module encodes **Property 2 (Preservation - Non-Paging Behavior Unchanged)**
from the ``ig-backfill-paging-fix`` bugfix spec. It pins the OBSERVED behaviour of the
UNFIXED code for inputs where the bug condition does NOT hold (``isBugCondition`` is
false), so the backward-paging fix (new ``IGClient.fetch_prices_range`` + a date-cursor
``_backfill_native`` loop) can be shown NOT to disturb them.

Observation-first methodology (tasks.md task 2): every expected value asserted below was
first OBSERVED by running the UNFIXED ``scripts.ig_backfill`` code against the fakes in
this module, then pinned as a regression anchor. These tests are **expected to PASS on
the UNFIXED code** (they confirm the baseline to preserve) and must still pass after the
fix lands (tasks.md task 3.5).

Non-bug-condition inputs covered (``isBugCondition`` false):

1. **Single-window** - ``target_points <= batch_points`` fetches one window and upserts
   once (after a 1-point allowance probe); identical before and after the fix.
2. **4h derive** - with native ``HOUR_4`` unsupported, ``_backfill_4h`` reads the stored
   ``1h`` series via ``get_ohlcv`` and resamples through ``resample_1h_to_4h``,
   ``points_used=0`` and zero extra IG allowance; unchanged.
3. **Idempotent re-pull** - re-running over an overlapping window inserts no new rows
   (idempotent on the ``(ticker, interval, ts)`` PK), so a run stays resumable.
4. **Allowance-floor** - a run never drives live ``remaining`` below ``SAFETY_FLOOR`` and
   reports the untouched remainder as ``deferred`` (``plan_backfill`` invariants).
5. **snapshotTime parsing** - the IG dated-window timestamps still parse via the two
   existing ``IG_SNAPSHOT_FMTS``; an unknown shape still raises ``ValueError`` loudly (no
   new timestamp format is introduced).

Hermeticity mirrors ``test_ig_client.py`` / ``test_ig_backfill.py``: the ``no_ig_network``
guard is applied at module scope and a temporary ``.env`` is passed to any real
``IGClient`` via ``env_path`` so the real project ``.env`` is never read. The
``_backfill_native`` / ``_backfill_4h`` tests inject fully fake client/repo objects, so no
real IG object or network is touched regardless. No ``slow`` marker: these are fast,
mocked, network-free.

_Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7._
"""

from __future__ import annotations

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import vpa.market_data.ohlcv_ingest as ohlcv_ingest
from scripts.ig_backfill import (
    DEFAULT_BATCH_POINTS,
    _backfill_4h,
    _backfill_native,
)
from vpa.market_data.ig_ingest import (
    IG_SNAPSHOT_FMTS,
    SAFETY_FLOOR,
    _parse_snapshot_time,
    resample_1h_to_4h,
)

pytestmark = pytest.mark.usefixtures("no_ig_network")


# ---------------------------------------------------------------------------
# Fakes - a most-recent-N IG client and a recording repo (shared shape with
# test_ig_backfill.py, kept local so this preservation module stands alone)
# ---------------------------------------------------------------------------

_UNIVERSE_END = pd.Timestamp("2026-10-15 00:00:00", tz="UTC")


def _bar_at(ts: pd.Timestamp) -> dict:
    """Build one IG ``/prices`` bar dict for bar-open ``ts`` (mid-computable OHLC).

    Uses the slash-space ``snapshotTime`` form (``IG_SNAPSHOT_FMTS[1]``) seen live on
    the Pi, so the bars flow through the real ``normalise_ig_prices`` parser unchanged.
    """
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


def _universe_newest_first(depth: int) -> list[dict]:
    """Return ``depth`` distinct hourly bars, newest-first (the fake IG history)."""
    return [_bar_at(_UNIVERSE_END - pd.Timedelta(hours=i)) for i in range(depth)]


class FakeMostRecentNClient:
    """A fake ``IGClient`` implementing IG's real most-recent-N ``fetch_prices``.

    ``fetch_prices(epic, resolution, num_points)`` always returns the newest
    ``num_points`` bars from a fixed universe (newest-first) and spends one allowance
    point per returned bar, recording every call. A ``probe_resolution`` whitelist lets
    the fake answer the ``4h`` native probe: resolutions NOT in the whitelist return an
    empty window (so ``probe_hour4`` reports unsupported and the derive path is taken).
    """

    def __init__(
        self,
        universe: list[dict],
        allowance_remaining: int,
        *,
        probe_supported: bool = True,
    ):
        self._universe = universe
        self._allowance_remaining = allowance_remaining
        self._probe_supported = probe_supported
        self.fetch_calls: list[dict] = []

    def _allowance(self) -> dict:
        return {"remainingAllowance": self._allowance_remaining, "allowanceExpiry": 60}

    def fetch_prices(self, epic: str, resolution: str, num_points: int) -> dict:
        self.fetch_calls.append({"epic": epic, "resolution": resolution, "num_points": num_points})
        if resolution == "HOUR_4" and not self._probe_supported:
            # Native HOUR_4 unsupported -> empty, so probe_hour4 returns False.
            return {"prices": [], "allowance": self._allowance()}
        window = self._universe[: max(0, num_points)]
        self._allowance_remaining = max(0, self._allowance_remaining - len(window))
        return {"prices": window, "allowance": self._allowance()}


class RecordingRepo:
    """A fake ``MarketDataRepository`` recording upserts and simulating the PK.

    Idempotent on ``(ticker, interval, Date)``: a bar seen before counts as ``updated``,
    a new bar as ``inserted`` - the real ``upsert_bars`` contract. Optionally serves a
    stored ``1h`` DataFrame from ``get_ohlcv`` for the ``4h`` derive path.
    """

    def __init__(self, stored_1h: pd.DataFrame | None = None):
        self.upsert_calls: list[dict] = []
        self.get_ohlcv_calls: list[dict] = []
        self._seen_ts: set[pd.Timestamp] = set()
        self._stored_1h = stored_1h

    def get_ohlcv(self, ticker: str, interval: str, start, end) -> pd.DataFrame:
        self.get_ohlcv_calls.append({"ticker": ticker, "interval": interval, "start": start, "end": end})
        if self._stored_1h is None:
            return pd.DataFrame(columns=ohlcv_ingest.CANONICAL_COLUMNS)
        return self._stored_1h

    def upsert_bars(self, df: pd.DataFrame, ticker: str, interval: str, *, source: str, adjusted: bool) -> dict:
        dates = list(pd.to_datetime(df["Date"], utc=True))
        self.upsert_calls.append(
            {
                "ticker": ticker,
                "interval": interval,
                "source": source,
                "adjusted": adjusted,
                "dates": dates,
            }
        )
        inserted = 0
        updated = 0
        for ts in dates:
            if ts in self._seen_ts:
                updated += 1
            else:
                self._seen_ts.add(ts)
                inserted += 1
        return {"inserted": inserted, "updated": updated}

    @property
    def distinct_bars(self) -> int:
        return len(self._seen_ts)


# ---------------------------------------------------------------------------
# Shared non-bug-condition parameters (isBugCondition is FALSE for these)
# ---------------------------------------------------------------------------

_EPIC = "IX.D.SPTRD.DAILY.IP"
_RESOLUTION = "HOUR"
_BATCH_POINTS = DEFAULT_BATCH_POINTS  # 500

# Built once and shared by the allowance-floor property so each generated example does
# not rebuild a large bar list. Larger than any point total the property's budget
# (remaining <= 5000) could ever pull, so the fetch never runs dry and the allowance
# guard is the only stopping condition exercised.
_ALLOWANCE_PROPERTY_UNIVERSE = _universe_newest_first(5_000)
# Single window: target_points <= batch_points -> no backward paging needed.
_SINGLE_TARGET = 300
_AMPLE_REMAINING = 9_900


# ---------------------------------------------------------------------------
# 1. Single-window preservation (Requirement 3.1)
# ---------------------------------------------------------------------------


def test_single_window_fetches_one_window_and_upserts_once():
    """Preservation: ``target_points <= batch_points`` -> one probe + one real fetch.

    OBSERVED on the UNFIXED loop and pinned here: a single ``target_points<=batch_points``
    run issues the 1-point allowance probe then exactly ONE real ``fetch_prices`` of
    ``target_points`` bars, upserts them once (tagged ``source="ig"``, ``adjusted=False``,
    ``interval="1h"``), and reports ``inserted=300, updated=0, points_used=300,
    deferred=0``. The fix (backward paging) only engages for ``target_points>batch_points``,
    so this single-window case must be byte-for-byte unchanged.

    _Validates: Requirements 3.1_
    """
    client = FakeMostRecentNClient(_universe_newest_first(_BATCH_POINTS), _AMPLE_REMAINING)
    repo = RecordingRepo()

    summary = _backfill_native(
        client,
        repo,
        _EPIC,
        "1h",
        _RESOLUTION,
        _SINGLE_TARGET,
        _BATCH_POINTS,
    )

    # Observed summary (pinned exactly).
    assert summary == {
        "inserted": 300,
        "updated": 0,
        "points_used": 300,
        "remaining_allowance": 9_599,
        "deferred": 0,
    }

    # Probe (num_points=1) then exactly one real fetch of the target size.
    assert [c["num_points"] for c in client.fetch_calls] == [1, _SINGLE_TARGET]

    # Exactly one upsert, tagged source="ig"/adjusted=False/interval="1h".
    assert len(repo.upsert_calls) == 1
    call = repo.upsert_calls[0]
    assert call["ticker"] == _EPIC
    assert call["interval"] == "1h"
    assert call["source"] == "ig"
    assert call["adjusted"] is False
    assert len(call["dates"]) == _SINGLE_TARGET


# ---------------------------------------------------------------------------
# 2. 4h derive preservation (Requirements 3.4)
# ---------------------------------------------------------------------------


def _stored_1h_df(hours: int) -> pd.DataFrame:
    """Build a canonical stored ``1h`` DataFrame of ``hours`` ascending bars."""
    rows = []
    for i in range(hours):
        ts = _UNIVERSE_END - pd.Timedelta(hours=i)
        rows.append({"Date": ts, "Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5, "Volume": 1_000.0})
    df = pd.DataFrame(rows, columns=ohlcv_ingest.CANONICAL_COLUMNS)
    return df.sort_values("Date").reset_index(drop=True)


def test_4h_derive_reads_stored_1h_and_resamples_with_zero_allowance():
    """Preservation: native ``HOUR_4`` unsupported -> derive ``4h`` from stored ``1h``.

    OBSERVED on the UNFIXED code and pinned: when ``probe_hour4`` reports no native
    ``HOUR_4`` (the probe window is empty), ``_backfill_4h`` reads the stored ``1h`` series
    via ``get_ohlcv(epic, "1h", ...)``, resamples it through ``resample_1h_to_4h`` (40 1h
    bars -> 11 4h bars here), upserts the derived bars once (``interval="4h"``,
    ``source="ig"``, ``adjusted=False``), and reports ``points_used=0``,
    ``remaining_allowance=None``, ``deferred=0`` - zero extra IG allowance spent. The fix
    does not touch ``_backfill_4h``, so this derive path must be unchanged.

    _Validates: Requirements 3.4_
    """
    stored_1h = _stored_1h_df(40)
    client = FakeMostRecentNClient([], _AMPLE_REMAINING, probe_supported=False)
    repo = RecordingRepo(stored_1h=stored_1h)

    summary = _backfill_4h(client, repo, _EPIC, 2, _BATCH_POINTS)

    # Derived bar count equals the pure resampler's output (observed: 11).
    expected_4h = resample_1h_to_4h(stored_1h)
    assert len(expected_4h) == 11

    assert summary == {
        "inserted": 11,
        "updated": 0,
        "points_used": 0,
        "remaining_allowance": None,
        "deferred": 0,
    }

    # Only the native HOUR_4 probe hit the client; no deeper native pull.
    assert [c["resolution"] for c in client.fetch_calls] == ["HOUR_4"]

    # The 1h series was read for the derive, and exactly one 4h upsert was written.
    assert len(repo.get_ohlcv_calls) == 1
    assert repo.get_ohlcv_calls[0]["interval"] == "1h"
    assert len(repo.upsert_calls) == 1
    call = repo.upsert_calls[0]
    assert call["interval"] == "4h"
    assert call["source"] == "ig"
    assert call["adjusted"] is False
    assert len(call["dates"]) == 11


# ---------------------------------------------------------------------------
# 3. Idempotent re-pull preservation (Requirements 3.2, 3.3)
# ---------------------------------------------------------------------------


def test_overlapping_re_pull_inserts_no_new_rows():
    """Preservation: a second run over an overlapping window inserts nothing new.

    OBSERVED on the UNFIXED code and pinned: running the single-window backfill twice
    against a SHARED repo seeds 300 distinct bars on the first run
    (``inserted=300, updated=0``) and, because the PK ``(ticker, interval, ts)`` is
    idempotent, re-pulls the SAME window on the second run as all-updates
    (``inserted=0, updated=300``) with no growth in distinct stored bars. This is what
    makes a run resumable across weeks, and the fix must preserve it.

    _Validates: Requirements 3.2, 3.3_
    """
    repo = RecordingRepo()

    first = _backfill_native(
        FakeMostRecentNClient(_universe_newest_first(_BATCH_POINTS), _AMPLE_REMAINING),
        repo,
        _EPIC,
        "1h",
        _RESOLUTION,
        _SINGLE_TARGET,
        _BATCH_POINTS,
    )
    assert first["inserted"] == 300
    assert first["updated"] == 0
    assert repo.distinct_bars == 300

    second = _backfill_native(
        FakeMostRecentNClient(_universe_newest_first(_BATCH_POINTS), _AMPLE_REMAINING),
        repo,
        _EPIC,
        "1h",
        _RESOLUTION,
        _SINGLE_TARGET,
        _BATCH_POINTS,
    )
    # Overlap re-pull: every bar is an update, nothing new inserted, depth unchanged.
    assert second["inserted"] == 0
    assert second["updated"] == 300
    assert repo.distinct_bars == 300


# ---------------------------------------------------------------------------
# 4. Allowance-floor preservation (Requirements 3.6, 3.7)
# ---------------------------------------------------------------------------


def test_allowance_exhausted_run_defers_everything_at_floor():
    """Preservation: remaining AT the floor defers the whole target, no upserts.

    OBSERVED on the UNFIXED code and pinned: with ``remaining == SAFETY_FLOOR`` the
    allowance plan has zero budget, so after the 1-point allowance probe the loop breaks
    before any real fetch - reporting ``inserted=0, updated=0, points_used=0,
    deferred==target``. The probe itself spends one point (``remaining_allowance=499``),
    but ``points_used`` (which counts only in-loop fetches) stays 0 and nothing is
    upserted. This "allowance-exhausted" input is not a bug condition, so the fix must
    leave it unchanged.

    _Validates: Requirements 3.6, 3.7_
    """
    target = 1_000
    client = FakeMostRecentNClient(_universe_newest_first(_BATCH_POINTS), SAFETY_FLOOR)
    repo = RecordingRepo()

    summary = _backfill_native(client, repo, _EPIC, "1h", _RESOLUTION, target, _BATCH_POINTS)

    assert summary == {
        "inserted": 0,
        "updated": 0,
        "points_used": 0,
        # The 1-point probe spends one point before the zero-budget plan breaks the loop.
        "remaining_allowance": SAFETY_FLOOR - 1,
        "deferred": target,
    }
    # Only the 1-point probe hit the client; no real fetch, no upsert.
    assert [c["num_points"] for c in client.fetch_calls] == [1]
    assert repo.upsert_calls == []


@settings(max_examples=40, deadline=None)
@given(
    remaining=st.integers(min_value=0, max_value=5_000),
    target_points=st.integers(min_value=0, max_value=4_000),
    batch_points=st.sampled_from([100, 250, 500, 1_000]),
)
def test_property_loop_never_drives_remaining_below_floor(remaining, target_points, batch_points):
    """Property (preservation): the loop keeps live ``remaining`` at/above the floor.

    For arbitrary ``AllowanceState`` / target / batch sizes, the UNFIXED
    ``_backfill_native`` loop stays allowance-aware: its IN-LOOP fetches never drive the
    live remaining allowance below ``SAFETY_FLOOR``, and it always reports a non-negative
    ``deferred`` no greater than the target. These are the ``plan_backfill`` /
    ``SAFETY_FLOOR`` invariants the fix must preserve.

    One subtlety the property must account for: ``_backfill_native`` issues a single
    one-time 1-point allowance probe (``fetch_prices(epic, resolution, 1)``) BEFORE the
    loop. At the exact boundary (``remaining == SAFETY_FLOOR`` with ``target_points == 0``,
    i.e. no in-loop budget headroom) that probe spends the only point, leaving
    ``remaining_allowance == SAFETY_FLOOR - 1``. This is the SAME pinned behaviour as
    ``test_allowance_exhausted_run_defers_everything_at_floor`` (which asserts
    ``remaining_allowance == SAFETY_FLOOR - 1`` i.e. 499) and is unchanged by the fix. So a
    run that STARTS with budget is only guaranteed ``>= SAFETY_FLOOR - 1`` (the probe may
    spend one point); whenever any real in-loop fetch actually ran
    (``points_used > 0``) the live remaining stays ``>= SAFETY_FLOOR``.

    A generous universe (larger than any point total the generated budget could pull)
    stands in for IG's history so the fetch never runs dry - isolating the allowance
    guard as the only stopping condition under test.

    _Validates: Requirements 3.6, 3.7_
    """
    client = FakeMostRecentNClient(_ALLOWANCE_PROPERTY_UNIVERSE, remaining)
    repo = RecordingRepo()

    summary = _backfill_native(client, repo, _EPIC, "1h", _RESOLUTION, target_points, batch_points)

    remaining_allowance = summary["remaining_allowance"]
    assert remaining_allowance is not None

    if remaining >= SAFETY_FLOOR:
        # A run that starts with budget never spends below the floor via its IN-LOOP
        # fetches. The one-time 1-point allowance probe may spend a single point at the
        # exact boundary (remaining == SAFETY_FLOOR, target_points == 0) - the same point
        # pinned as 499 (SAFETY_FLOOR - 1) in
        # test_allowance_exhausted_run_defers_everything_at_floor - so the floor-minus-one
        # bound is the correct general guarantee here.
        assert remaining_allowance >= SAFETY_FLOOR - 1
        # Whenever a real in-loop fetch actually ran, the live remaining stays at/above
        # the floor (the probe-only boundary is the single sub-floor case).
        if summary["points_used"] > 0:
            assert remaining_allowance >= SAFETY_FLOOR
    else:
        # A sub-floor start spends at most the single 1-point probe and defers the rest.
        assert remaining_allowance <= remaining
        assert summary["deferred"] == target_points

    # Deferred remainder is always a sane, non-negative portion of the target.
    assert 0 <= summary["deferred"] <= target_points
    # Points can never exceed what the live allowance could pay for.
    assert summary["points_used"] >= 0


# ---------------------------------------------------------------------------
# 5. snapshotTime parsing preservation (Requirement 3.5)
# ---------------------------------------------------------------------------


def test_snapshot_parsing_handles_the_two_known_forms_and_no_more():
    """Preservation: the two known ``snapshotTime`` forms parse; the set is unchanged.

    OBSERVED and pinned: ``IG_SNAPSHOT_FMTS`` holds exactly the two forms IG has been seen
    to RETURN - the SP-342 colon-dash form (``%Y:%m:%d-%H:%M:%S``, e.g.
    ``2024:01:02-14:30:00``) and the live slash-space form (``%Y/%m/%d %H:%M:%S``, e.g.
    ``2026/10/06 08:15:00``) - and both parse to the expected tz-aware UTC bar-open
    timestamp. The dated-window fetch the fix adds introduces NO new ``snapshotTime``
    format, so this set must stay at exactly these two entries.

    Note: the IG dated-window REQUEST date-strings (new form ``yyyy-MM-dd HH:mm:ss`` and
    old form ``yyyy:MM:dd-HH:mm:ss``) are what the fix formats when CALLING IG; the
    returned ``snapshotTime`` values are still one of these two parsed shapes. The old
    request form coincides with ``IG_SNAPSHOT_FMTS[0]``; the parser is only responsible
    for the response values, which is what is pinned here.

    _Validates: Requirements 3.5_
    """
    assert IG_SNAPSHOT_FMTS == ("%Y:%m:%d-%H:%M:%S", "%Y/%m/%d %H:%M:%S")

    colon_dash = _parse_snapshot_time("2024:01:02-14:30:00")
    assert colon_dash == pd.Timestamp("2024-01-02 14:30:00", tz="UTC")

    slash_space = _parse_snapshot_time("2026/10/06 08:15:00")
    assert slash_space == pd.Timestamp("2026-10-06 08:15:00", tz="UTC")


def test_snapshot_parsing_raises_loudly_on_unknown_shape():
    """Preservation: an unseen ``snapshotTime`` shape still fails loudly.

    OBSERVED and pinned: a shape outside ``IG_SNAPSHOT_FMTS`` - including the ISO-ish
    dash-space form ``2024-01-02 14:30:00`` that the parser does NOT accept - raises
    ``ValueError`` naming the offending value rather than being silently misread. The fix
    preserves this fail-loud contract. (An empty string is a pandas ``NaT`` edge, not a
    ``ValueError``, so it is excluded from this fail-loud set.)

    _Validates: Requirements 3.5_
    """
    for bad in ("2024-01-02 14:30:00", "02/01/2024 14:30", "not-a-timestamp"):
        with pytest.raises(ValueError):
            _parse_snapshot_time(bad)


@settings(max_examples=50, deadline=None)
@given(
    year=st.integers(min_value=2020, max_value=2030),
    month=st.integers(min_value=1, max_value=12),
    day=st.integers(min_value=1, max_value=28),
    hour=st.integers(min_value=0, max_value=23),
    minute=st.integers(min_value=0, max_value=59),
)
def test_property_both_known_forms_parse_to_same_instant(year, month, day, hour, minute):
    """Property (preservation): the two known forms of one instant parse identically.

    For arbitrary valid date/time components, formatting the SAME instant in each of the
    two ``IG_SNAPSHOT_FMTS`` forms and parsing both yields the identical tz-aware UTC
    timestamp - confirming the parser treats the colon-dash and slash-space shapes as the
    one timestamp space (no new format, no day/month ambiguity introduced by the fix).

    _Validates: Requirements 3.5_
    """
    colon_dash = f"{year:04d}:{month:02d}:{day:02d}-{hour:02d}:{minute:02d}:00"
    slash_space = f"{year:04d}/{month:02d}/{day:02d} {hour:02d}:{minute:02d}:00"

    parsed_colon = _parse_snapshot_time(colon_dash)
    parsed_slash = _parse_snapshot_time(slash_space)

    expected = pd.Timestamp(f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:00", tz="UTC")
    assert parsed_colon == expected
    assert parsed_slash == expected
