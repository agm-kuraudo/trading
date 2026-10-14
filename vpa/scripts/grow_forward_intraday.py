"""Grow-forward maintenance job for IG intraday OHLCV (SP-379).

Keeps the ``market_data.ohlcv`` store current for the US 500 spread-bet epic by
reading-through :meth:`MarketDataRepository.load_ohlcv` over a recent window per
interval, so only the missing tail is fetched from IG and upserted idempotently.
This is the scheduled counterpart to the one-off allowance-aware backfill: the
backfill seeds deep history, this job tops up the newest bars on each run.

Run it as a module (this is what the Rundeck shell entrypoint invokes)::

    python -m vpa.scripts.grow_forward_intraday

``grow_forward(epic, intervals, repo=None, now=None)`` returns a per-interval
summary ``{interval: {"fetched": int, "inserted": int, "updated": int}}`` and the
``main`` entry point exits non-zero on any failure so Rundeck surfaces it.

**4h handling.** If native IG ``HOUR_4`` is supported for the epic (``hour4_native``
true), ``4h`` grows forward exactly like ``15m``/``1h`` via the read-through tail
fetch. If ``4h`` is DERIVED (the default — SP-342 validated only ``MINUTE_15`` /
``HOUR`` for this epic), the job makes NO separate IG call for ``4h``: after the
``1h`` tail is refreshed it recomputes/upserts the affected ``4h`` bars from the
freshly-updated ``1h`` tail via :func:`resample_1h_to_4h`, which is idempotent on the
``(ticker, interval, ts)`` PK and costs zero extra IG allowance. ``1h`` is therefore
grown forward BEFORE ``4h`` in the derived path.

The ``repo`` and ``now`` parameters are injectable so the job can be driven with a
fake repository and a fixed clock under test (no live IG calls).
"""

from __future__ import annotations

import sys

import pandas as pd

from vpa.market_data.ig_ingest import resample_1h_to_4h
from vpa.market_data.repository import MarketDataRepository

# The US 500 spread-bet epic; IG bars are stored under this ticker so they never
# collide with the yfinance ``SPY`` baseline (design Decision #1).
EPIC = "IX.D.SPTRD.DAILY.IP"

# The intraday intervals the grow-forward job maintains.
INTERVALS = ["15m", "1h", "4h"]

# How far back the recent read-through window reaches from ``now``. A week comfortably
# covers the missing tail between scheduled runs (and a weekend/holiday gap) while
# staying tiny next to the backfill's multi-year seed. The read-through fetches only
# the bars actually missing within this window, so a generous window is cheap.
WINDOW_DAYS = 7

# Canonical order the job processes intervals in. ``1h`` MUST precede ``4h`` so the
# derived ``4h`` path resamples a freshly-updated ``1h`` tail (design §5).
_INTERVAL_ORDER = ["15m", "1h", "4h"]


def _ordered(intervals) -> list[str]:
    """Return ``intervals`` in the canonical processing order (1h before 4h).

    Any interval not in :data:`_INTERVAL_ORDER` is appended afterwards in its given
    order, so an unexpected interval is still processed rather than silently dropped.
    """
    known = [i for i in _INTERVAL_ORDER if i in intervals]
    extra = [i for i in intervals if i not in _INTERVAL_ORDER]
    return known + extra


def _recent_window(now: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return the ``(start, end)`` read-through window ending at ``now``.

    The window spans :data:`WINDOW_DAYS` back from ``now``. Both ends are tz-aware
    UTC so they compare cleanly against the TIMESTAMPTZ ``ts`` column.
    """
    end = pd.Timestamp(now)
    if end.tzinfo is None:
        end = end.tz_localize("UTC")
    else:
        end = end.tz_convert("UTC")
    start = end - pd.Timedelta(days=WINDOW_DAYS)
    return start, end


def _stored_timestamps(repo, epic: str, interval: str, start, end) -> set:
    """Return the set of stored bar-open ``Date`` values in ``[start, end]``.

    Used to measure the store before and after a read-through so inserted/updated can
    be derived without the repository having to surface upsert counts from inside
    ``load_ohlcv``.
    """
    df = repo.get_ohlcv(epic, interval, start, end)
    if df.empty:
        return set()
    return set(pd.to_datetime(df["Date"], utc=True))


def _grow_native(repo, epic: str, interval: str, start, end) -> dict:
    """Grow one interval forward via the read-through tail fetch (15m/1h/native 4h).

    Snapshots the stored bar-opens before and after :meth:`load_ohlcv` so the summary
    reports exact counts: ``inserted`` = bar-opens that appeared, ``updated`` =
    returned bar-opens that already existed (the overlap the read-through refreshed),
    ``fetched`` = ``inserted + updated`` (the bars the read-through landed/refreshed).
    """
    before = _stored_timestamps(repo, epic, interval, start, end)
    merged = repo.load_ohlcv(epic, interval, start, end)
    after = _stored_timestamps(repo, epic, interval, start, end)

    inserted = len(after - before)
    merged_ts = set() if merged.empty else set(pd.to_datetime(merged["Date"], utc=True))
    # Bars present in the merged result that were already stored before the run are
    # the overlap the read-through re-fetched/updated.
    updated = len(merged_ts & before)
    return {"fetched": inserted + updated, "inserted": inserted, "updated": updated}


def _grow_derived_4h(repo, epic: str, start, end) -> dict:
    """Derive ``4h`` from the freshly-updated ``1h`` tail (zero extra IG allowance).

    Reads the stored ``1h`` series over the window (which ``1h`` grow-forward has just
    refreshed), resamples it to ``4h`` via :func:`resample_1h_to_4h`, and upserts the
    result idempotently as ``source="ig"``, ``interval="4h"``, ``adjusted=False``. No
    IG request is issued. The ``inserted``/``updated`` counts come straight from the
    idempotent upsert; ``fetched`` is the number of derived ``4h`` bars.
    """
    df_1h = repo.get_ohlcv(epic, "1h", start, end)
    derived = resample_1h_to_4h(df_1h)
    if derived.empty:
        return {"fetched": 0, "inserted": 0, "updated": 0}

    result = repo.upsert_bars(derived, epic, "4h", source="ig", adjusted=False)
    return {
        "fetched": len(derived),
        "inserted": result["inserted"],
        "updated": result["updated"],
    }


def grow_forward(
    epic: str = EPIC,
    intervals=INTERVALS,
    repo=None,
    now=None,
    *,
    hour4_native: bool = False,
) -> dict:
    """Top up the newest intraday bars for each interval via read-through.

    For each interval (processed ``15m`` -> ``1h`` -> ``4h`` so the derived ``4h``
    path sees a refreshed ``1h`` tail), reads-through :meth:`load_ohlcv` over a recent
    window ending at ``now`` so only the missing tail is fetched from IG and upserted
    idempotently. ``4h`` is grown natively (like ``1h``) when ``hour4_native`` is true,
    otherwise derived from the just-refreshed stored ``1h`` series via
    :func:`resample_1h_to_4h` (no extra IG call).

    Args:
        epic: The IG instrument identifier used as the stored ``ticker``.
        intervals: The intraday intervals to maintain.
        repo: A :class:`MarketDataRepository` (or compatible). Defaults to a fresh
            ``MarketDataRepository()``; tests inject a fake.
        now: The run instant (anything ``pd.Timestamp`` accepts). Defaults to the
            current UTC time; tests pass a fixed clock.
        hour4_native: Whether the epic serves native IG ``HOUR_4`` (set from the
            build-time probe). ``False`` (the default) selects the derive-from-1h path.

    Returns:
        A per-interval summary ``{interval: {"fetched", "inserted", "updated"}}``.
    """
    if repo is None:
        repo = MarketDataRepository()
    if now is None:
        now = pd.Timestamp.now(tz="UTC")

    start, end = _recent_window(now)

    summary: dict[str, dict] = {}
    for interval in _ordered(intervals):
        if interval == "4h" and not hour4_native:
            summary[interval] = _grow_derived_4h(repo, epic, start, end)
        else:
            summary[interval] = _grow_native(repo, epic, interval, start, end)
    return summary


def main(argv=None) -> int:
    """CLI entry point: run the grow-forward job and print the per-interval summary.

    Returns ``0`` on success. Any failure prints the error to stderr and returns a
    non-zero exit code so the Rundeck job surfaces the failure.

    Args:
        argv: Unused; present for a consistent entry-point signature.

    Returns:
        Process exit code (``0`` on success, ``1`` on any failure).
    """
    try:
        summary = grow_forward()
    except Exception as exc:  # noqa: BLE001 — surface any failure to Rundeck via exit code.
        print(f"grow_forward_intraday failed: {exc}", file=sys.stderr)
        return 1

    for interval, counts in summary.items():
        print(
            f"{interval}: fetched={counts['fetched']}, " f"inserted={counts['inserted']}, updated={counts['updated']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
