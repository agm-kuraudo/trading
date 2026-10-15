"""Allowance-aware IG intraday backfill (SP-379).

Seeds the SP-349 ``market_data.ohlcv`` store with intraday IG history for the US 500
spread-bet epic, respecting IG's 10,000-points-per-week historical-data allowance so a
backfill run can never drive the remaining allowance below ``SAFETY_FLOOR``. It mirrors
the yfinance ``backfill_market_data.py`` seed script but for IG, flowing bars through the
same ``normalise_ig_prices`` -> ``MarketDataRepository.upsert_bars`` path tagged
``source="ig"``, ``adjusted=FALSE`` so re-pulling an overlapping window inserts no new
rows (idempotent on the ``(ticker, interval, ts)`` PK).

Allowance strategy (SP-342 numbers):

- ``1h`` deep: ~2 yrs (~3,500 points) seeds comfortably within a single week's budget,
  so a ``--interval 1h --years 2`` run completes in one pass.
- ``15m``: ~2 yrs is ~50k points (5+ weekly budgets), so it is seeded incrementally
  across successive weekly runs — each run spends down toward ``SAFETY_FLOOR`` and
  reports the ``deferred`` remainder; resumability comes free from the idempotent PK
  (re-pulling an overlap inserts nothing new), so the next week's run simply resumes.
- ``4h``: ``probe_hour4`` is called first. If native ``HOUR_4`` is supported for the
  epic, ``4h`` is pulled like ``1h`` (spending allowance like ``1h``). Otherwise ``4h``
  is DERIVED from the already-stored ``1h`` series via ``resample_1h_to_4h`` and upserted,
  spending ZERO extra IG allowance (this requires the ``1h`` series to be seeded first).

Before each fetch the loop calls ``plan_backfill`` against the latest observed allowance,
and after each batch it re-checks the live ``allowance.remainingAllowance`` and stops
early (reporting ``deferred``) if the next batch would breach the floor.

Invocations (run standalone from the repo root; hits the IG network + the live store):

    python scripts/ig_backfill.py --epic IX.D.SPTRD.DAILY.IP --interval 1h --years 2
    python scripts/ig_backfill.py --epic IX.D.SPTRD.DAILY.IP --interval 15m --years 2
    python scripts/ig_backfill.py --epic IX.D.SPTRD.DAILY.IP --interval 4h --years 2

The ``1h`` run should be done first; the ``15m`` run is repeated weekly until it reports
``deferred=0``; and the ``4h`` run derives from the stored ``1h`` series when the epic
does not serve native ``HOUR_4`` (so run the ``1h`` backfill before ``4h``).

Platform note: the config-driven store this writes to is the ``my_postgres`` container on
the always-on Raspberry Pi (Linux/ARM), the shared Postgres host.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd

from vpa.market_data.ig_client import IGClient
from vpa.market_data.ig_ingest import (
    IG_RESOLUTION,
    SAFETY_FLOOR,
    AllowanceState,
    normalise_ig_prices,
    plan_backfill,
    probe_hour4,
    resample_1h_to_4h,
)
from vpa.market_data.repository import MarketDataRepository

# Approximate bars-per-year by interval for the US 500 session (~weekday, nearly 24x5,
# excluding the ~1h daily break). SP-342 observed ~3,500 1h points for ~2 years, i.e.
# ~1,750 1h bars/year; 15m is ~4x that, and native 4h is ~1/4 of 1h.
BARS_PER_YEAR = {
    "1h": 1_750,
    "15m": 7_000,
    "4h": 440,
}

# Points fetched per IG /prices request. Keeps each request modest so the live
# allowance can be re-checked between batches and the loop can stop before breaching
# the floor; one point is consumed per returned bar.
DEFAULT_BATCH_POINTS = 500


def _target_points(interval: str, years: int) -> int:
    """Approximate the number of IG points needed to seed ``years`` of ``interval``.

    Uses the per-year bar estimates in :data:`BARS_PER_YEAR` (session-adjusted from the
    SP-342 observation of ~3,500 ``1h`` points over ~2 years). A point corresponds to one
    fetched bar, so this is also the ideal points to spend.

    Args:
        interval: One of ``"15m"``, ``"1h"``, ``"4h"``.
        years: The depth of history to seed, in years.

    Returns:
        The approximate target point count for the run.
    """
    return BARS_PER_YEAR[interval] * years


def _allowance_state(allowance: dict) -> AllowanceState:
    """Build an :class:`AllowanceState` from an IG ``allowance`` block.

    Args:
        allowance: The ``allowance`` dict from an IG ``/prices`` response (carrying
            ``remainingAllowance`` and ``allowanceExpiry``). Missing values default to 0.

    Returns:
        The populated :class:`AllowanceState`.
    """
    return AllowanceState(
        remaining=int(allowance.get("remainingAllowance", 0) or 0),
        expiry_s=int(allowance.get("allowanceExpiry", 0) or 0),
    )


def _backfill_native(
    client: IGClient,
    repo: MarketDataRepository,
    epic: str,
    interval: str,
    resolution: str,
    target_points: int,
    batch_points: int,
) -> dict:
    """Pull ``interval`` bars natively from IG, allowance-aware, and upsert them.

    Loops ``fetch_prices`` in batches of ``batch_points``. Before each fetch it calls
    :func:`plan_backfill` against the latest observed allowance; if the plan has no
    budget for a batch (``this_run`` would breach ``SAFETY_FLOOR``) it stops early and
    reports the untouched points as ``deferred``. After each batch it re-checks the live
    ``allowance.remainingAllowance`` and stops before the next fetch if the remaining
    minus the next batch would fall below the floor.

    Each batch is normalised via :func:`normalise_ig_prices` and upserted idempotently
    via :meth:`MarketDataRepository.upsert_bars` (``source="ig"``, ``adjusted=False``).

    Args:
        client: A logged-in :class:`IGClient`.
        repo: The destination :class:`MarketDataRepository`.
        epic: The IG epic (ticker tag for stored bars).
        interval: The interval tag (``"15m"``/``"1h"``/``"4h"``).
        resolution: The IG resolution enum for the interval.
        target_points: The ideal number of points to seed this run.
        batch_points: Points fetched per IG request.

    Returns:
        A summary dict ``{inserted, updated, points_used, remaining_allowance,
        deferred}``.
    """
    inserted = 0
    updated = 0
    points_used = 0
    remaining = target_points

    # Prime the allowance with one small probe request so planning uses live numbers.
    probe = client.fetch_prices(epic, resolution, 1)
    state = _allowance_state(probe["allowance"])

    while remaining > 0:
        plan = plan_backfill(remaining, batch_points, state)
        if plan["this_run"] <= 0:
            # No budget left this week without breaching the floor; defer the rest.
            break

        this_batch = min(batch_points, plan["this_run"])

        # Stop before a fetch that would drive the live remaining below the floor.
        if state.remaining - this_batch < SAFETY_FLOOR:
            break

        raw = client.fetch_prices(epic, resolution, this_batch)
        df = normalise_ig_prices(raw)
        if not df.empty:
            result = repo.upsert_bars(df, epic, interval, source="ig", adjusted=False)
            inserted += result["inserted"]
            updated += result["updated"]

        fetched = len(raw.get("prices", []))
        points_used += fetched
        remaining -= this_batch

        # Re-check the LIVE allowance after the batch (it may have cost more than
        # projected) and stop early if it has reached the floor.
        state = _allowance_state(raw["allowance"])
        if state.remaining <= SAFETY_FLOOR:
            break

        # IG returns the most-recent N bars for a given num_points, so once a batch
        # returns fewer bars than requested there is no deeper history to seed.
        if fetched < this_batch:
            remaining = 0
            break

    return {
        "inserted": inserted,
        "updated": updated,
        "points_used": points_used,
        "remaining_allowance": state.remaining,
        "deferred": max(0, remaining),
    }


def _backfill_4h(
    client: IGClient,
    repo: MarketDataRepository,
    epic: str,
    years: int,
    batch_points: int,
) -> dict:
    """Seed ``4h`` history: native ``HOUR_4`` if supported, else derive from stored ``1h``.

    Probes the epic for native ``HOUR_4`` first. When supported, ``4h`` is pulled like
    ``1h`` (spending allowance in the same allowance-aware manner). Otherwise ``4h`` is
    DERIVED from the already-stored ``1h`` series via :func:`resample_1h_to_4h` and
    upserted, spending ZERO extra IG allowance — this requires the ``1h`` series to have
    been seeded first.

    Args:
        client: A logged-in :class:`IGClient`.
        repo: The destination :class:`MarketDataRepository`.
        epic: The IG epic.
        years: The depth of history to seed, in years.
        batch_points: Points fetched per IG request (native path only).

    Returns:
        A summary dict ``{inserted, updated, points_used, remaining_allowance,
        deferred}``.
    """
    if probe_hour4(client, epic):
        return _backfill_native(
            client,
            repo,
            epic,
            "4h",
            IG_RESOLUTION["4h"],
            _target_points("4h", years),
            batch_points,
        )

    # Derive path: read the stored 1h series and resample to 4h (zero extra allowance).
    # Pull the stored 1h history over the requested depth; a generous window is fine
    # because get_ohlcv is a bounded range read and only stored bars are returned.
    end = pd.Timestamp.now(tz="UTC")
    start = end - pd.Timedelta(days=365 * years + 7)
    df_1h = repo.get_ohlcv(epic, "1h", start, end)
    df_4h = resample_1h_to_4h(df_1h)

    inserted = 0
    updated = 0
    if not df_4h.empty:
        result = repo.upsert_bars(df_4h, epic, "4h", source="ig", adjusted=False)
        inserted = result["inserted"]
        updated = result["updated"]

    return {
        "inserted": inserted,
        "updated": updated,
        "points_used": 0,
        "remaining_allowance": None,
        "deferred": 0,
    }


def backfill(epic: str, interval: str, years: int, batch_points: int = DEFAULT_BATCH_POINTS) -> dict:
    """Run an allowance-aware IG backfill for ``epic``/``interval`` over ``years``.

    Logs in a read-only :class:`IGClient`, computes the target points from ``years`` and
    the interval bar size, then seeds the store allowance-aware. ``15m``/``1h`` pull
    natively from IG; ``4h`` probes for native ``HOUR_4`` and otherwise derives from the
    stored ``1h`` series (zero extra allowance).

    Args:
        epic: The IG epic (e.g. ``IX.D.SPTRD.DAILY.IP``).
        interval: One of ``"15m"``, ``"1h"``, ``"4h"``.
        years: The depth of history to seed, in years.
        batch_points: Points fetched per IG request (default
            :data:`DEFAULT_BATCH_POINTS`).

    Returns:
        A summary dict ``{inserted, updated, points_used, remaining_allowance,
        deferred}``.
    """
    client = IGClient()
    client.login()
    repo = MarketDataRepository()

    if interval == "4h":
        return _backfill_4h(client, repo, epic, years, batch_points)

    return _backfill_native(
        client,
        repo,
        epic,
        interval,
        IG_RESOLUTION[interval],
        _target_points(interval, years),
        batch_points,
    )


def _parse_args(argv=None) -> argparse.Namespace:
    """Parse CLI arguments for the IG backfill script.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        The parsed ``argparse.Namespace`` with ``epic``, ``interval``, ``years``, and
        ``batch_points``.
    """
    parser = argparse.ArgumentParser(
        description="Allowance-aware IG intraday backfill into the market_data store.",
    )
    parser.add_argument(
        "--epic",
        required=True,
        help="IG epic to backfill (e.g. IX.D.SPTRD.DAILY.IP).",
    )
    parser.add_argument(
        "--interval",
        required=True,
        choices=sorted(IG_RESOLUTION),
        help="Intraday interval to seed: 15m, 1h, or 4h.",
    )
    parser.add_argument(
        "--years",
        type=int,
        default=2,
        help="Depth of history to seed, in years (default: 2).",
    )
    parser.add_argument(
        "--batch-points",
        type=int,
        default=DEFAULT_BATCH_POINTS,
        help=f"Points fetched per IG request (default: {DEFAULT_BATCH_POINTS}).",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    """CLI entry point: run the backfill and print the summary.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code (``0`` on success).
    """
    args = _parse_args(argv)
    result = backfill(args.epic, args.interval, args.years, args.batch_points)
    print(
        f"IG backfill {args.epic} ({args.interval}, {args.years}y): "
        f"inserted={result['inserted']}, updated={result['updated']}, "
        f"points_used={result['points_used']}, "
        f"remaining_allowance={result['remaining_allowance']}, "
        f"deferred={result['deferred']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
