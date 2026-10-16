"""Shared hermetic fakes for the IG backfill backward-paging tests (SP-382).

This small helper factors out the fake IG client / recording repo shapes used across
the SP-382 backfill test modules so the task-4 coverage
(``test_ig_backfill_coverage.py``) can reuse them without duplicating the fakes already
present in ``test_ig_backfill.py`` (task 1) and ``test_ig_backfill_preservation.py``
(task 2). Those two existing modules keep their own local copies deliberately (so each
stands alone as the artefact for its workflow step); this module is additive and does
NOT alter their imports.

Everything here is pure and network-free: the fake client serves bars from an in-memory
"universe" (newest-first) and the fake repo simulates the ``(ticker, interval, ts)`` PK
in memory, so tests built on these touch no real IG object, no network, and no store.
The bar ``snapshotTime`` strings use the slash-space form (``IG_SNAPSHOT_FMTS[1]``) seen
live on the Pi, so bars flow through the real ``normalise_ig_prices`` parser unchanged.
"""

from __future__ import annotations

import pandas as pd

import vpa.market_data.ohlcv_ingest as ohlcv_ingest
from scripts.ig_backfill import BARS_PER_YEAR

# A fixed anchor "now" for the fake universe so tests are deterministic. The fake
# client's dated-window fetch compares against this universe, not the wall clock.
UNIVERSE_END = pd.Timestamp("2026-10-15 00:00:00", tz="UTC")

# GROUND-TRUTH session density, MEASURED live on demo IG (SP-382): a 7-calendar-day
# dated window for epic IX.D.SPTRD.DAILY.IP at HOUR resolution returned 120 bars, i.e.
# ~17.14 1h bars per CALENDAR day. This is deliberately anchored to the MEASUREMENT and
# is NOT derived from the production ``BARS_PER_YEAR`` constant: a realistic-density fake
# universe must reflect how many bars IG really packs into a calendar window regardless
# of what the loop THINKS the density is. If ``BARS_PER_YEAR`` ever drifts away from this
# measured truth, a window the loop sizes for ``this_batch`` points will return a
# different (realistic) number of bars - which is exactly the allowance-safety regression
# the SP-382 density-mismatch bug was (an undersized constant oversized every window and
# overspent the weekly allowance). ``density_step`` below spaces a fake universe at this
# true cadence; ``cadence_step`` (loop-matched) is retained for the preservation/coverage
# tests that intentionally line the fake up with the loop's own budgeting.
TRUE_BARS_PER_7_DAYS = 120
TRUE_BARS_PER_DAY = TRUE_BARS_PER_7_DAYS / 7

# Default per-bar spacing for ``universe_newest_first`` (module-level singleton so the
# default is not a function call in the signature, which ruff B008 flags).
_DEFAULT_STEP = pd.Timedelta(hours=1)


def cadence_step(interval: str) -> pd.Timedelta:
    """Return the calendar spacing between bars that matches the ``BARS_PER_YEAR`` cadence.

    The production ``_window_span`` sizes a dated window from a point budget using the
    session-adjusted ``BARS_PER_YEAR`` cadence (the US 500 session is ~24x5, not 24x7), so
    a window sized for ``this_batch`` points is expected to hold ~``this_batch`` bars of
    REAL history. A naive dense-hourly fake universe (8,760 bars/yr) would pack ~5x more
    bars into that calendar window than the loop budgeted for, draining the fake allowance
    far faster than production. Spacing the fake universe at
    ``365.25 days / BARS_PER_YEAR[interval]`` lines the fake up with the loop's own cadence
    so one dated window returns ~``this_batch`` bars - matching real session-gapped IG
    history rather than an unrealistic 24x7 stream.

    Args:
        interval: The interval tag (``"15m"``/``"1h"``/``"4h"``).

    Returns:
        The per-bar calendar spacing as a :class:`pandas.Timedelta`.
    """
    return pd.Timedelta(days=365.25) / BARS_PER_YEAR[interval]


def density_step(interval: str = "1h") -> pd.Timedelta:
    """Return the TRUE calendar spacing between bars from the MEASURED demo-IG density.

    Unlike :func:`cadence_step` (which spaces bars at ``365.25 / BARS_PER_YEAR`` so a
    fake universe lines up with the LOOP's own budgeting), this spaces bars at the
    ground-truth session density measured live on demo IG (SP-382: ~17.14 1h bars per
    calendar day, from 7d -> 120 bars) and is NOT a function of the production
    ``BARS_PER_YEAR`` constant. A universe spaced this way returns a REALISTIC number of
    bars for whatever calendar window the loop requests - so if ``BARS_PER_YEAR`` is
    wrong, the loop's ``_window_span`` oversizes/undersizes the window and the fake
    returns more/fewer bars than the loop budgeted for, exercising the allowance-safety
    guard exactly as the real demo run did. The 15m / 4h steps scale from the 1h truth
    (15m ~4x denser, 4h ~1/4 as dense), matching the ``BARS_PER_YEAR`` ratios.

    Args:
        interval: The interval tag (``"15m"``/``"1h"``/``"4h"``).

    Returns:
        The per-bar calendar spacing as a :class:`pandas.Timedelta`.
    """
    scale = {"1h": 1.0, "15m": 4.0, "4h": 0.25}[interval]
    bars_per_day = TRUE_BARS_PER_DAY * scale
    return pd.Timedelta(days=1) / bars_per_day


def bar_at(ts: pd.Timestamp) -> dict:
    """Build one IG ``/prices`` bar dict for bar-open ``ts`` (mid-computable OHLC).

    Uses the slash-space ``snapshotTime`` form (``IG_SNAPSHOT_FMTS[1]``) so the bar
    parses through the real ``normalise_ig_prices`` / ``IG_SNAPSHOT_FMTS`` path.

    Args:
        ts: The bar-open timestamp (tz-aware UTC).

    Returns:
        An IG ``/prices`` bar object with mid-computable OHLC and a volume.
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


def universe_newest_first(depth: int, *, step: pd.Timedelta | None = None) -> list[dict]:
    """Return ``depth`` distinct bars, newest-first, spaced by ``step`` from ``UNIVERSE_END``.

    This stands in for the "true" available history on IG: index 0 is the newest bar
    (at ``UNIVERSE_END``) and each later index steps one ``step`` further back.

    Args:
        depth: Number of distinct bars to generate.
        step: Spacing between successive bars (default one hour, :data:`_DEFAULT_STEP`).

    Returns:
        A newest-first list of IG ``/prices`` bar objects.
    """
    step = _DEFAULT_STEP if step is None else step
    return [bar_at(UNIVERSE_END - step * i) for i in range(depth)]


def _snapshot_ts(bar: dict) -> pd.Timestamp:
    """Parse a fake bar's slash-space ``snapshotTime`` into a tz-aware UTC Timestamp."""
    return pd.Timestamp(bar["snapshotTime"].replace("/", "-"), tz="UTC")


class FakeDatedClient:
    """A fake ``IGClient`` with real most-recent-N semantics AND a dated-window fetch.

    ``fetch_prices(epic, resolution, num_points)`` serves the newest ``num_points`` bars
    from the universe (newest-first), recording every call and spending one allowance
    point per returned bar - exactly how IG's most-recent-N endpoint behaves.

    ``fetch_prices_range(epic, resolution, start, end)`` serves the slice of the universe
    whose bar-open falls in ``[start, end)`` (newest-first) and spends one point per bar;
    it returns an empty window once history older than the oldest universe bar is
    requested, which is how the fixed backward-paging loop detects end-of-history.

    A ``probe_supported`` flag answers the native ``HOUR_4`` probe: when false, a
    ``HOUR_4`` ``fetch_prices`` returns an empty window so ``probe_hour4`` reports
    unsupported and the ``4h`` derive-from-``1h`` path is taken.
    """

    def __init__(
        self,
        universe: list[dict],
        allowance_remaining: int,
        *,
        probe_supported: bool = True,
    ):
        self._universe = universe  # newest-first
        self._allowance_remaining = allowance_remaining
        self._probe_supported = probe_supported
        self.fetch_calls: list[dict] = []
        self.range_calls: list[dict] = []

    def _allowance(self) -> dict:
        return {"remainingAllowance": self._allowance_remaining, "allowanceExpiry": 60}

    def login(self) -> None:
        """No-op login so the fake satisfies the ``backfill`` call path."""
        return None

    def fetch_prices(self, epic: str, resolution: str, num_points: int) -> dict:
        """Most-recent-N: the newest ``num_points`` bars (no date cursor)."""
        self.fetch_calls.append({"epic": epic, "resolution": resolution, "num_points": num_points})
        if resolution == "HOUR_4" and not self._probe_supported:
            return {"prices": [], "allowance": self._allowance()}
        window = self._universe[: max(0, num_points)]
        self._allowance_remaining = max(0, self._allowance_remaining - len(window))
        return {"prices": window, "allowance": self._allowance()}

    def fetch_prices_range(self, epic: str, resolution: str, start, end) -> dict:
        """Dated window ``[start, end)`` - the backward-paging path (newest-first)."""
        start = pd.Timestamp(start)
        end = pd.Timestamp(end)
        if start.tzinfo is None:
            start = start.tz_localize("UTC")
        if end.tzinfo is None:
            end = end.tz_localize("UTC")
        self.range_calls.append({"epic": epic, "resolution": resolution, "start": start, "end": end})
        window = [b for b in self._universe if start <= _snapshot_ts(b) < end]
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
        self._seen: set[tuple[str, str, pd.Timestamp]] = set()
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
            key = (ticker, interval, ts)
            if key in self._seen:
                updated += 1
            else:
                self._seen.add(key)
                inserted += 1
        return {"inserted": inserted, "updated": updated}

    def distinct_bars(self, ticker: str | None = None, interval: str | None = None) -> int:
        """Count distinct stored bars, optionally scoped to a ticker/interval."""
        return sum(
            1 for (t, i, _ts) in self._seen if (ticker is None or t == ticker) and (interval is None or i == interval)
        )

    def oldest_ts(self, ticker: str | None = None, interval: str | None = None) -> pd.Timestamp | None:
        """Return the oldest stored timestamp, optionally scoped to a ticker/interval."""
        matches = [
            ts for (t, i, ts) in self._seen if (ticker is None or t == ticker) and (interval is None or i == interval)
        ]
        return min(matches) if matches else None
