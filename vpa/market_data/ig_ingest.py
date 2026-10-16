"""IG intraday ingestion helpers (SP-379).

Pure, network-free helpers for IG intraday OHLCV ingestion: mid-price
normalisation (``_mid`` / ``normalise_ig_prices``) and allowance-aware backfill
planning (``AllowanceState`` / ``plan_backfill``).

``normalise_ig_prices`` maps an IG ``/prices`` payload to the canonical OHLCV shape,
collapsing each bid/ask OHLC field to the **mid-price** ``(bid + ask) / 2`` so IG bars
flow through the *same* ``ohlcv_ingest.to_store_rows`` -> ``upsert_bars`` path as the
yfinance baseline (tagged ``source="ig"``, ``adjusted=FALSE``). It mirrors
``ohlcv_ingest.normalise_yf_download``'s output contract: exactly
``ohlcv_ingest.CANONICAL_COLUMNS`` in order, OHLCV dropped of any missing value, sorted
ascending by ``Date``.

The ``4h`` interval is sourced native-if-available, else derived: ``probe_hour4``
issues one small read-only ``GET /prices`` for ``HOUR_4`` and reports whether the epic
serves usable OHLC + volume at that resolution; when it does not, ``resample_1h_to_4h``
derives canonical ``4h`` bars from the already-stored ``1h`` series over a fixed 4-hour
grid (zero extra IG allowance). Either path flows through the same ``upsert_bars`` path
tagged ``source="ig"``, ``interval="4h"``, ``adjusted=FALSE``.

``plan_backfill`` translates IG's weekly historical-data allowance into a safe
per-run point budget so a backfill never drives the remaining allowance below
``SAFETY_FLOOR``.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil

import pandas as pd

from vpa.market_data import ohlcv_ingest

# Our interval tag -> IG resolution enum. ``HOUR_4`` is used ONLY when ``probe_hour4``
# confirms the epic serves usable OHLC + volume at that resolution; 15m/1h are the
# SP-342-validated natives. IG's documented resolution enum does include ``HOUR_4``
# (IG Labs: https://labs.ig.com/reference/prices-epic-resolution-numpoints.html), but
# SP-342 only empirically validated ``MINUTE_15``/``HOUR`` for this epic, so ``HOUR_4``
# support is unknown until probed at build time (``probe_hour4``); when the probe fails
# the 4h series is derived from the stored 1h bars (``resample_1h_to_4h``) instead.
IG_RESOLUTION = {"15m": "MINUTE_15", "1h": "HOUR", "4h": "HOUR_4"}

# IG ``snapshotTime`` formats (UTC). IG has been observed returning more than one
# shape across endpoints/account types: the colon-dash form documented by the SP-342
# spike (e.g. "2024:01:02-14:30:00") and a slash-space form seen live on the grow-
# forward job (e.g. "2026/10/06 08:15:00"). We try each KNOWN explicit format in order
# rather than inferring, so day/month order is never guessed and an unseen third shape
# fails loudly (``_parse_snapshot_time``). ``IG_SNAPSHOT_FMT`` is retained as the
# primary (spike) format for back-compat.
IG_SNAPSHOT_FMT = "%Y:%m:%d-%H:%M:%S"
IG_SNAPSHOT_FMTS = (
    "%Y:%m:%d-%H:%M:%S",  # SP-342 documented form, e.g. 2024:01:02-14:30:00
    "%Y/%m/%d %H:%M:%S",  # live form seen on the Pi, e.g. 2026/10/06 08:15:00
)


def _parse_snapshot_time(snapshot: str) -> pd.Timestamp:
    """Parse an IG ``snapshotTime`` into a tz-aware UTC ``pd.Timestamp``.

    Tries each known explicit format in :data:`IG_SNAPSHOT_FMTS` in order (no format
    inference, so day/month order is never guessed). Raises ``ValueError`` naming the
    offending value if none match, so a new IG format surfaces loudly instead of being
    silently misread.

    Args:
        snapshot: The raw IG ``snapshotTime`` string.

    Returns:
        The parsed bar-open timestamp, tz-aware in UTC.

    Raises:
        ValueError: If ``snapshot`` matches none of the known formats.
    """
    for fmt in IG_SNAPSHOT_FMTS:
        try:
            return pd.to_datetime(snapshot, format=fmt, utc=True)
        except (ValueError, TypeError):
            continue
    raise ValueError(
        f"IG snapshotTime {snapshot!r} matches none of the known formats "
        f"{IG_SNAPSHOT_FMTS}; add the new format to IG_SNAPSHOT_FMTS."
    )


# IG historical-data allowance: points per week (SP-342).
WEEKLY_ALLOWANCE = 10_000
# Stop before this many points remain so an over-pull cannot lock the account
# out of historical data for the week (fail safe).
SAFETY_FLOOR = 500


def _mid(field: dict) -> float:
    """Return the mid-price ``(bid + ask) / 2`` for one IG OHLC field object.

    Args:
        field: An IG OHLC field object (e.g. ``openPrice``) with ``bid`` and ``ask``
            entries. Either value may be ``None``.

    Returns:
        The mid-price. When only one side is present, that side is used directly.

    Raises:
        ValueError: If both ``bid`` and ``ask`` are ``None`` (no price to compute).
    """
    bid = field.get("bid")
    ask = field.get("ask")
    if bid is None and ask is None:
        raise ValueError("IG OHLC field has neither bid nor ask")
    if bid is None:
        return float(ask)
    if ask is None:
        return float(bid)
    return (float(bid) + float(ask)) / 2


# IG OHLC field names on a /prices bar, in canonical order.
_OHLC_FIELDS = ("openPrice", "highPrice", "lowPrice", "closePrice")


def _is_priceless_bar(bar: dict) -> bool:
    """Return ``True`` iff a bar carries no usable price on ANY OHLC field.

    A bar is treated as a no-data placeholder only when every one of its
    ``openPrice`` / ``highPrice`` / ``lowPrice`` / ``closePrice`` fields has both
    ``bid`` and ``ask`` ``None``. IG emits such bars at illiquid/closed-market moments
    (e.g. session-boundary 22:00 bars) sometimes still carrying a tiny
    ``lastTradedVolume``; they hold no price and must be skipped rather than aborting
    the run.

    A bar with *some* priced fields and *some* fully-null fields is NOT price-less
    here: that is anomalous/partial data, so this returns ``False`` and the normal
    ``_mid`` path is allowed to fail loud on it (we never fabricate a bar).

    Args:
        bar: An IG ``/prices`` bar object.

    Returns:
        ``True`` iff all four OHLC fields have ``bid is None`` and ``ask is None``.
    """
    return all(bar[field].get("bid") is None and bar[field].get("ask") is None for field in _OHLC_FIELDS)


def normalise_ig_prices(raw: dict) -> pd.DataFrame:
    """Normalise an IG ``/prices`` payload into the canonical OHLCV shape.

    For each bar in ``raw["prices"]``:

    - ``Date``   <- ``snapshotTime`` parsed as a tz-aware UTC bar-open timestamp.
    - ``Open``   <- ``_mid(openPrice)``;  ``High`` <- ``_mid(highPrice)``.
    - ``Low``    <- ``_mid(lowPrice)``;   ``Close`` <- ``_mid(closePrice)``.
    - ``Volume`` <- ``lastTradedVolume`` (``None`` -> NaN, dropped by the canonical
      dropna).

    Whole no-price **placeholder** bars are skipped (not appended, not fatal): IG
    returns occasional bars at illiquid/closed-market moments where ALL FOUR OHLC
    fields have both ``bid`` and ``ask`` ``None`` (sometimes still carrying a tiny
    ``lastTradedVolume``). Such a bar holds no price, so it is dropped up front rather
    than letting ``_mid`` raise and abort the entire run — consistent with the
    normaliser's existing drop-no-data philosophy. The skip rule is deliberately
    narrow: a bar is only skipped when *every* OHLC field is fully null. A bar with
    *some* priced fields and *some* fully-null fields is anomalous/partial data and is
    left to ``_mid`` to fail loud on (we never fabricate a bar from corrupt input).

    Then ``dropna`` on the OHLCV columns, ``sort_values("Date")`` ascending, and return
    exactly ``ohlcv_ingest.CANONICAL_COLUMNS`` in order. Pure (no network). Mirrors
    ``normalise_yf_download``'s output contract so IG rows flow through the same
    ``to_store_rows`` / ``upsert_bars`` path tagged ``source="ig"``, ``adjusted=FALSE``.

    Args:
        raw: An IG ``/prices`` payload, i.e. a dict with a ``"prices"`` list of bar
            objects (each with ``snapshotTime``, ``openPrice`` / ``highPrice`` /
            ``lowPrice`` / ``closePrice`` field objects, and ``lastTradedVolume``).

    Returns:
        A DataFrame with exactly ``CANONICAL_COLUMNS`` (``Date, Open, High, Low,
        Close, Volume``), sorted ascending by ``Date`` with a fresh RangeIndex.
    """
    rows: list[dict] = []
    for bar in raw.get("prices", []):
        # No-data placeholder bar (all OHLC fields fully null) -> skip, don't abort.
        if _is_priceless_bar(bar):
            continue
        ts = _parse_snapshot_time(bar["snapshotTime"])
        volume = bar.get("lastTradedVolume")
        rows.append(
            {
                "Date": ts,
                "Open": _mid(bar["openPrice"]),
                "High": _mid(bar["highPrice"]),
                "Low": _mid(bar["lowPrice"]),
                "Close": _mid(bar["closePrice"]),
                "Volume": None if volume is None else float(volume),
            }
        )

    df = pd.DataFrame(rows, columns=ohlcv_ingest.CANONICAL_COLUMNS)

    # Drop rows missing any OHLCV value (mirrors the canonical yfinance normaliser).
    df = df.dropna(subset=ohlcv_ingest._OHLCV_COLUMNS)

    # Sort ascending by Date and reset the index.
    df = df.sort_values("Date").reset_index(drop=True)

    # Return exactly the canonical columns, in order.
    return df[ohlcv_ingest.CANONICAL_COLUMNS]


def probe_hour4(client, epic: str) -> bool:
    """Probe IG once for native ``HOUR_4`` support on ``epic``.

    Issues a single small read-only ``GET /prices`` for the ``HOUR_4`` resolution via
    the client (which uses the injected transport, so this stays hermetic under test)
    and reports whether IG serves *usable* OHLC + volume at that resolution. "Usable"
    means a non-empty ``prices`` list where every bar's OHLC fields are mid-computable
    (``_mid`` does not raise) and ``lastTradedVolume`` is present/non-null. Any empty
    result, missing field, or error from the probe is treated as "unsupported" so the
    caller falls back to the derive-from-1h path (``resample_1h_to_4h``).

    This is a pure read: it never mutates account state and performs exactly one price
    request (via ``client.fetch_prices``). It consumes a tiny amount of IG allowance
    (a couple of points) only when the native path is viable.

    Args:
        client: An ``IGClient`` (or compatible) exposing
            ``fetch_prices(epic, resolution, num_points)``.
        epic: The IG instrument identifier (e.g. ``IX.D.SPTRD.DAILY.IP``).

    Returns:
        ``True`` iff IG returns usable ``HOUR_4`` OHLC + volume; ``False`` otherwise
        (empty, unsupported, malformed, or any error) — the signal to derive instead.
    """
    try:
        raw = client.fetch_prices(epic, IG_RESOLUTION["4h"], 2)
    except Exception:
        # Any failure (unsupported resolution, auth, transport) -> derive path.
        return False

    prices = raw.get("prices", []) if isinstance(raw, dict) else []
    if not prices:
        return False

    for bar in prices:
        volume = bar.get("lastTradedVolume")
        if volume is None:
            return False
        try:
            _mid(bar["openPrice"])
            _mid(bar["highPrice"])
            _mid(bar["lowPrice"])
            _mid(bar["closePrice"])
        except (KeyError, TypeError, ValueError):
            return False
    return True


def resample_1h_to_4h(df_1h: pd.DataFrame) -> pd.DataFrame:
    """Derive canonical ``4h`` bars from a stored ``1h`` series (pure, no network).

    Groups the ascending ``1h`` series into fixed 4-hour windows aligned to the session
    grid (each ``Date`` floored to a 4-hour boundary in UTC). For each non-empty window
    the derived bar is:

    - ``Open``   <- the first (earliest) ``1h`` bar's Open in the window.
    - ``High``   <- the window maximum High.
    - ``Low``    <- the window minimum Low.
    - ``Close``  <- the last (latest) ``1h`` bar's Close in the window.
    - ``Volume`` <- the sum of the window's Volume.
    - ``Date``   <- the first ``1h`` bar's bar-open ts (tz-aware UTC), the existing
      bar-open convention.

    Operates on the store, not a separate IG pull, so it costs zero extra IG allowance;
    the ``1h`` series must be present/current first. Returns exactly
    ``ohlcv_ingest.CANONICAL_COLUMNS`` in order, sorted ascending by ``Date``, so the
    rows flow through the same ``to_store_rows`` / ``upsert_bars`` path as native bars.

    Args:
        df_1h: A canonical ``1h`` DataFrame (``CANONICAL_COLUMNS``) whose ``Date`` is a
            tz-aware UTC bar-open timestamp.

    Returns:
        A canonical ``4h`` DataFrame (``CANONICAL_COLUMNS``). Empty in, empty out.
    """
    columns = ohlcv_ingest.CANONICAL_COLUMNS
    if df_1h.empty:
        return pd.DataFrame(columns=columns)

    df = df_1h.sort_values("Date").reset_index(drop=True)

    # Floor each 1h bar-open to a fixed 4-hour boundary (session grid) and group.
    window = pd.to_datetime(df["Date"], utc=True).dt.floor("4h")

    rows: list[dict] = []
    for _, group in df.groupby(window, sort=True):
        if group.empty:
            continue
        first = group.iloc[0]
        last = group.iloc[-1]
        rows.append(
            {
                "Date": first["Date"],
                "Open": first["Open"],
                "High": group["High"].max(),
                "Low": group["Low"].min(),
                "Close": last["Close"],
                "Volume": group["Volume"].sum(),
            }
        )

    out = pd.DataFrame(rows, columns=columns)
    out = out.sort_values("Date").reset_index(drop=True)
    return out[columns]


@dataclass
class AllowanceState:
    """Snapshot of IG's historical-data allowance from the last response.

    Attributes:
        remaining: ``allowance.remainingAllowance`` — points left this week.
        expiry_s: ``allowance.allowanceExpiry`` — seconds until the weekly reset.
    """

    remaining: int
    expiry_s: int


def plan_backfill(target_points: int, batch_points: int, state: AllowanceState) -> dict:
    """Decide how much to pull this run without exhausting the weekly allowance.

    The per-run budget is derived from the latest remaining allowance, leaving
    ``SAFETY_FLOOR`` points unspent. The run is clamped to that budget so it can
    never drive ``remainingAllowance`` below the floor; any points that cannot be
    pulled this run are reported as ``deferred`` for a future week.

    Args:
        target_points: How many points this backfill would ideally pull.
        batch_points: Points fetched per batch (used to size the batch count).
            Values <= 0 are treated as a single batch to avoid a zero-division.
        state: The latest observed allowance state.

    Returns:
        A dict ``{"this_run": int, "batches": int, "deferred": int}`` where
        ``this_run`` is the number of points to pull now, ``batches`` is the
        number of fetches that covers it, and ``deferred`` is the remainder.
    """
    budget = max(0, state.remaining - SAFETY_FLOOR)
    this_run = min(target_points, budget)
    if batch_points > 0:
        batches = ceil(this_run / batch_points)
    else:
        batches = 1 if this_run > 0 else 0
    return {
        "this_run": this_run,
        "batches": batches,
        "deferred": target_points - this_run,
    }
