"""Repository layer for the market-data store (SP-349).

``MarketDataRepository`` is the thin access layer over ``market_data.ohlcv``. It
implements the write path (``upsert_bars``) and the read paths: ``get_ohlcv``
(offline range read), ``load_ohlcv`` (read-through that fetches only the missing
tail from yfinance), and ``export_ohlcv`` (scoped CSV/Parquet export).

The repository takes a connection factory (defaulting to
``vpa.market_data.db.connect``) so tests can inject a fake or local connection
without touching the live PostgreSQL server.
"""

from __future__ import annotations

import pandas as pd

from utils.utils import trading_days_between
from vpa.market_data.db import connect
from vpa.market_data.ohlcv_ingest import CANONICAL_COLUMNS, fetch_yf, normalise_yf_download, to_store_rows

# Idempotent upsert (Req 2.1–2.4, 3.4). The PK (ticker, interval, ts) prevents
# duplicate bars, so re-ingesting a day is safe. RETURNING (xmax = 0) is TRUE for a
# freshly-inserted row and FALSE for a row that took the DO UPDATE branch, which lets
# us count inserts vs updates accurately.
_UPSERT_SQL = """
INSERT INTO market_data.ohlcv (ticker, interval, ts, open, high, low, close, volume, adjusted, source, ingested_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
ON CONFLICT (ticker, interval, ts) DO UPDATE SET
  open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
  close=EXCLUDED.close, volume=EXCLUDED.volume,
  adjusted=EXCLUDED.adjusted, source=EXCLUDED.source, ingested_at=now()
RETURNING (xmax = 0) AS inserted;
"""

# Offline range read (Req 3.1). Ordered by ts so the returned DataFrame is already
# sorted by Date; the range is inclusive on both ends to match the design SQL.
_SELECT_SQL = """
SELECT ts, open, high, low, close, volume
FROM market_data.ohlcv
WHERE ticker = %s AND interval = %s AND ts >= %s AND ts <= %s
ORDER BY ts;
"""

# Number of row upserts committed per transaction (Req 2.1–2.4 scaling fix). Each
# hypertable chunk touched inside a transaction holds a lock; committing in bounded
# batches caps the live-lock count so a full-history backfill (~8000 daily bars)
# cannot exhaust ``max_locks_per_transaction`` (psycopg2 OutOfMemory: out of shared
# memory). 500 keeps transactions small while limiting round-trip/commit overhead.
UPSERT_BATCH_SIZE = 500

# Intraday interval tags -> bar length in minutes (SP-379, Req 5.1). Only these
# intervals get the session-aware ``_expected_last`` treatment; ``1d`` keeps its
# business-day logic and every other tag keeps the plain ``end`` fallback.
INTRADAY_MINUTES = {"15m": 15, "1h": 60}

# The IG US 500 spread-bet epic. IG bars are stored under this epic string so they
# never collide with the yfinance ``SPY`` baseline (SP-379 design, Data Models). The
# read-through routes the intraday tail fetch to IG for this ticker; everything else
# keeps the yfinance tail path.
IG_EPIC = "IX.D.SPTRD.DAILY.IP"


def _is_ig_ticker(ticker: str) -> bool:
    """Return whether ``ticker`` is served by IG (the US 500 epic).

    Centralises the source routing used by ``load_ohlcv``: an IG epic ticker fetches
    its missing tail via the IG-backed intraday fetcher, while every other ticker
    keeps the yfinance ``fetch_yf`` path. Kept as a small helper so the routing rule
    lives in one place and is trivial to extend if more IG epics are added.
    """
    return ticker == IG_EPIC


# Minutes-per-day used to size the IG ``num_points`` request from a tail date range.
# IG's ``GET /prices`` is parameterised by a bar COUNT, not a date window, so the
# adapter converts the requested ``[tail_start, end]`` span into a generous number of
# most-recent bars, then trims to the range. The US 500 spread bet trades nearly 24h
# on weekdays, so we size against a full 24h day (an over-estimate is safe — IG caps
# at the available history and the extra bars are trimmed locally).
_MINUTES_PER_DAY = 24 * 60
# A small floor so a very short tail still asks for a handful of bars.
_MIN_IG_POINTS = 4
# A cap so a pathologically wide range cannot request an unbounded pull (and blow the
# allowance). The grow-forward tail is always small; a backfill uses the dedicated
# allowance-aware CLI, not this read-through adapter.
_MAX_IG_POINTS = 5000


def make_ig_tail_fetcher(client=None):
    """Build the default IG-backed intraday tail fetcher used by ``load_ohlcv``.

    The returned callable has the SAME signature as ``ohlcv_ingest.fetch_yf``
    (``fetcher(ticker, interval, start, end) -> canonical DataFrame``) so the one
    read-through algorithm in ``load_ohlcv`` is source-agnostic — only the fetcher
    differs. Internally it:

    1. maps the interval tag to an IG resolution (``ig_ingest.IG_RESOLUTION``),
    2. sizes a generous ``num_points`` from the ``[start, end]`` span,
    3. calls ``client.fetch_prices(epic, resolution, num_points)`` (read-only),
    4. normalises via ``ig_ingest.normalise_ig_prices`` (bid/ask -> mid, UTC ts), and
    5. trims the normalised frame to ``[start, end]`` so it mirrors ``fetch_yf``'s
       range-bounded contract.

    The IG client is created lazily on first use (so merely constructing a
    ``MarketDataRepository`` never touches IG or the network); tests inject a fake
    ``client`` to stay hermetic.

    Args:
        client: An object exposing ``fetch_prices(epic, resolution, num_points)``.
            Defaults to a lazily-constructed ``IGClient`` (live), created on first
            call so repository construction stays network-free.

    Returns:
        A ``fetcher(ticker, interval, start, end)`` callable returning a canonical
        DataFrame (``CANONICAL_COLUMNS``) for the requested range.
    """
    # Local imports keep ``requests``/IG wiring out of the module import path and off
    # the hot daily read-through; they are only needed when IG is actually used.
    from vpa.market_data.ig_ingest import IG_RESOLUTION, normalise_ig_prices

    state = {"client": client}

    def _get_client():
        if state["client"] is None:
            from vpa.market_data.ig_client import IGClient

            state["client"] = IGClient()
        return state["client"]

    def _num_points(interval: str, start, end) -> int:
        minutes = INTRADAY_MINUTES.get(interval)
        if not minutes:
            return _MIN_IG_POINTS
        span = _to_naive_utc(end) - _to_naive_utc(start)
        span_minutes = max(0.0, span.total_seconds() / 60.0)
        bars = int(span_minutes // minutes) + _MIN_IG_POINTS
        return max(_MIN_IG_POINTS, min(_MAX_IG_POINTS, bars))

    def _fetch(ticker: str, interval: str, start, end) -> pd.DataFrame:
        resolution = IG_RESOLUTION.get(interval)
        if resolution is None:
            # Not an IG-supported intraday interval; nothing to fetch.
            return pd.DataFrame(columns=CANONICAL_COLUMNS)

        raw = _get_client().fetch_prices(ticker, resolution, _num_points(interval, start, end))
        df = normalise_ig_prices(raw)
        if df.empty:
            return df

        # Trim to the requested [start, end] window (IG returns the most-recent N
        # bars; the read-through only wants the missing tail). Compare on tz-naive
        # UTC to match the stored/expected-last convention.
        start_ts = _to_naive_utc(start)
        end_ts = _to_naive_utc(end)
        dates = pd.to_datetime(df["Date"], utc=True).dt.tz_convert("UTC").dt.tz_localize(None)
        mask = (dates >= start_ts) & (dates <= end_ts)
        return df.loc[mask].reset_index(drop=True)

    return _fetch


# US 500 (IG epic ``IX.D.SPTRD.DAILY.IP``) trading-session model (SP-379, Req 5.1).
# The spread bet trades nearly 24h on weekdays with a short daily break between the
# underlying-futures close and reopen. We model the session as "weekday, excluding
# the daily break" in UTC: open all day Monday–Friday except a one-hour break at
# [_SESSION_BREAK_START_H, _SESSION_BREAK_END_H), and closed across the weekend
# (Saturday and Sunday). This weekday + break model, combined with flooring to the
# interval grid, is sufficient for intraday gap detection (design §4). The exact
# break boundary is not critical to correctness — it only shifts which single
# interval bar is treated as the last completed one around the break — but a fixed,
# monotonic boundary is required so ``_expected_last`` stays monotonic in ``end``.
_SESSION_BREAK_START_H = 21  # 21:00 UTC — daily break begins
_SESSION_BREAK_END_H = 22  # 22:00 UTC — session resumes


def _to_naive_utc(value) -> pd.Timestamp:
    """Normalise any timestamp-like ``value`` to a tz-naive UTC ``pd.Timestamp``.

    tz-aware inputs are converted to UTC then stripped of tzinfo; naive inputs are
    assumed to already be in UTC and returned unchanged (beyond coercion). This keeps
    every intraday comparison on one tz-naive UTC footing.
    """
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts


def _in_session(ts: pd.Timestamp) -> bool:
    """Return ``True`` iff ``ts`` falls within the US 500 weekday trading session.

    The session is open on weekdays (Mon–Fri) at every instant except the one-hour
    daily break ``[21:00, 22:00)`` UTC, and closed all weekend. ``ts`` must be a
    tz-naive timestamp already expressed in UTC (the caller normalises).
    """
    # weekday(): Monday=0 .. Sunday=6. Saturday/Sunday are closed.
    if ts.weekday() >= 5:
        return False
    # The daily break [21:00, 22:00) UTC is closed on weekdays.
    if _SESSION_BREAK_START_H <= ts.hour < _SESSION_BREAK_END_H:
        return False
    return True


def _floor_to_interval_grid(ts: pd.Timestamp, minutes: int) -> pd.Timestamp:
    """Floor ``ts`` down to the start of its ``minutes``-sized bar on the UTC grid.

    The grid is anchored at the UTC day boundary (midnight), so 15m bars open at
    :00/:15/:30/:45 and 1h bars open on the hour. ``ts`` is a tz-naive UTC timestamp.
    """
    return ts.floor(f"{minutes}min")


def _previous_session_instant(ts: pd.Timestamp) -> pd.Timestamp:
    """Return the latest in-session UTC instant at or before ``ts``.

    Walks backward out of a weekend or the daily break to the most recent moment the
    session was open. ``ts`` is a tz-naive UTC timestamp. Used to find the session a
    completed bar belongs to when ``end`` lands out of hours.
    """
    cursor = ts
    # Step back a minute at a time until we land inside the session. Out-of-hours
    # gaps are at most ~63h (Fri 21:00 -> Mon 00:00), so this terminates quickly; we
    # cap the walk defensively to avoid any pathological loop.
    for _ in range(63 * 60 + 1):
        if _in_session(cursor):
            return cursor
        cursor = cursor - pd.Timedelta(minutes=1)
    return cursor


class MarketDataRepository:
    """Access layer over the ``market_data.ohlcv`` table.

    Args:
        conn_factory: A zero-argument callable returning an open DB connection.
            Defaults to :func:`vpa.market_data.db.connect`. Tests can inject a
            fake/local connection factory to avoid the live server.
        ig_tail_fetcher: Optional callable
            ``fetcher(ticker, interval, start, end) -> canonical DataFrame`` used by
            :meth:`load_ohlcv` to fetch the missing intraday tail for IG tickers.
            Defaults to :func:`make_ig_tail_fetcher` (an IG-backed ``fetch_prices``
            adapter). The default client is constructed lazily on first use, so
            merely building a repository never touches IG or the network; tests
            inject a fake fetcher to stay hermetic and assert call arguments. The
            daily/yfinance path always uses ``fetch_yf`` regardless of this value, so
            there is a single read-through algorithm with only the tail fetcher
            differing by source.
    """

    def __init__(self, conn_factory=connect, ig_tail_fetcher=None):
        self._conn_factory = conn_factory
        # Hold the provided fetcher (if any). The default IG-backed adapter is built
        # lazily on first intraday-IG use via :meth:`_intraday_tail_fetcher` so
        # construction stays free of any IG/network wiring.
        self._ig_tail_fetcher = ig_tail_fetcher

    def _intraday_tail_fetcher(self):
        """Return the intraday tail fetcher, building the default lazily on demand.

        Uses an injected fetcher when one was supplied to the constructor; otherwise
        builds the default IG-backed adapter via :func:`make_ig_tail_fetcher` on
        first use (and caches it) so repository construction never touches IG.
        """
        if self._ig_tail_fetcher is None:
            self._ig_tail_fetcher = make_ig_tail_fetcher()
        return self._ig_tail_fetcher

    def upsert_bars(
        self,
        df: pd.DataFrame,
        ticker: str,
        interval: str,
        source: str = "yfinance",
        adjusted: bool = True,
    ) -> dict:
        """Idempotently upsert canonical OHLCV bars into ``market_data.ohlcv``.

        Converts the canonical DataFrame to store-row tuples via
        :func:`vpa.market_data.ohlcv_ingest.to_store_rows`, then runs the
        ``ON CONFLICT (ticker, interval, ts) DO UPDATE`` statement per row. Each
        execution returns ``(xmax = 0)`` — TRUE for an inserted row, FALSE for an
        updated one — which is used to tally the two counts. The connection is
        committed in batches of :data:`UPSERT_BATCH_SIZE` rows (with a final commit
        for any remainder) and always closed (try/finally). Batching bounds the
        number of hypertable chunk locks held per transaction so a full-history
        backfill cannot exhaust ``max_locks_per_transaction``; because each row is
        independently idempotent under ``ON CONFLICT``, splitting the commits does
        not change the counts or the idempotency guarantee.

        Re-running with the same bars changes no row count (PK invariant): the
        second run updates every row rather than inserting.

        Args:
            df: A canonical DataFrame (``Date, Open, High, Low, Close, Volume``).
            ticker: The instrument symbol (e.g. ``"SPY"``).
            interval: The bar interval tag (e.g. ``"1d"``).
            source: The data source tag. Defaults to ``"yfinance"``.
            adjusted: Whether the series is adjusted. Defaults to ``True``.

        Returns:
            A dict ``{"inserted": n, "updated": m}`` counting new vs updated rows.
        """
        rows = to_store_rows(df, ticker, interval, source, adjusted)

        inserted = 0
        updated = 0
        conn = self._conn_factory()
        try:
            with conn.cursor() as cur:
                pending = 0  # rows executed since the last commit
                for row in rows:
                    cur.execute(_UPSERT_SQL, row)
                    was_insert = cur.fetchone()[0]
                    if was_insert:
                        inserted += 1
                    else:
                        updated += 1
                    pending += 1
                    # Commit each full batch so the live hypertable-chunk lock count
                    # stays bounded. psycopg2 keeps the cursor valid across commits
                    # on the same connection, so we reuse the single cursor.
                    if pending >= UPSERT_BATCH_SIZE:
                        conn.commit()
                        pending = 0
                # Commit any rows left over in the final partial batch.
                if pending:
                    conn.commit()
        finally:
            conn.close()

        return {"inserted": inserted, "updated": updated}

    def get_ohlcv(
        self,
        ticker: str,
        interval: str,
        start,
        end,
    ) -> pd.DataFrame:
        """Read stored OHLCV bars for a ticker/interval range — strictly offline.

        Runs the range ``SELECT`` (inclusive of both ``start`` and ``end``) and maps
        the result into the canonical read shape: a DataFrame with exactly
        ``["Date", "Open", "High", "Low", "Close", "Volume"]`` (``ts`` mapped to
        ``Date``), ordered by ``Date`` (the SQL already orders by ``ts``). The
        connection is always closed (try/finally).

        Performs **no** network I/O — this is the offline read path (Req 3.1).

        Args:
            ticker: The instrument symbol (e.g. ``"SPY"``).
            interval: The bar interval tag (e.g. ``"1d"``).
            start: Inclusive range start (anything psycopg2 accepts as a timestamp).
            end: Inclusive range end.

        Returns:
            A canonical DataFrame (``Date, Open, High, Low, Close, Volume``) ordered
            by ``Date``. Empty (with the canonical columns) when no rows match.
        """
        conn = self._conn_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(_SELECT_SQL, (ticker, interval, start, end))
                fetched = cur.fetchall()
        finally:
            conn.close()

        # Build the canonical frame, mapping ts -> Date. Constructing from the
        # explicit column list keeps the output shape stable even when empty.
        df = pd.DataFrame(
            fetched,
            columns=["Date", "Open", "High", "Low", "Close", "Volume"],
        )
        return df[CANONICAL_COLUMNS]

    def load_ohlcv(
        self,
        ticker: str,
        interval: str,
        start,
        end,
    ) -> pd.DataFrame:
        """Read-through load: return stored bars, fetching only the missing tail.

        Reads the store offline first via :meth:`get_ohlcv`. It then computes the
        last bar-open that *should* exist on/before ``end`` (``expected_last``) and
        compares it against the newest stored bar (``have_last``). If the store is
        empty or stale (``have_last < expected_last``), it fetches **only the missing
        tail** from yfinance — starting the day after ``have_last`` when a prefix is
        already stored, otherwise from ``start`` — drops any incomplete final bar,
        upserts the tail idempotently, and re-reads the merged range. When the store
        is already current, no network call is made.

        Only the missing tail is fetched; a stored prefix is never re-downloaded
        (Req 3.2, 3.3, 5.3).

        The read-through is a SINGLE algorithm: it is source-agnostic except for the
        tail fetcher. For IG intraday tickers (the US 500 epic, ``source="ig"``) the
        tail is fetched via the injectable IG-backed fetcher
        (:meth:`_intraday_tail_fetcher`); every other ticker (the daily/yfinance
        path) keeps using ``fetch_yf`` + ``normalise_yf_download`` unchanged. Either
        way the fetched tail has its incomplete in-progress final bar dropped
        (:meth:`_drop_incomplete_final_bar`) before the idempotent upsert.

        Args:
            ticker: The instrument symbol (e.g. ``"SPY"``).
            interval: The bar interval tag (e.g. ``"1d"``).
            start: Inclusive range start.
            end: Inclusive range end.

        Returns:
            A canonical DataFrame (``Date, Open, High, Low, Close, Volume``) covering
            the requested range, ordered by ``Date``.
        """
        stored = self.get_ohlcv(ticker, interval, start, end)

        expected_last = self._expected_last(interval, start, end)
        have_last = stored["Date"].max() if not stored.empty else None

        # Normalise to comparable tz-naive UTC timestamps for the staleness check.
        # Stored ts values are TIMESTAMPTZ (tz-aware UTC), while `expected_last` is
        # tz-naive by construction, so strip the tz to keep the comparison valid.
        have_last_ts = None
        if have_last is not None and not pd.isna(have_last):
            have_last_ts = _to_naive_utc(have_last)

        # Route the tail fetch by source: IG intraday tickers use the injectable
        # IG-backed fetcher; everything else keeps the yfinance tail path. This is
        # the ONLY difference between the two sources — the algorithm below is shared.
        is_ig_intraday = _is_ig_ticker(ticker) and interval in INTRADAY_MINUTES

        # Compare at the right granularity: intraday compares the exact bar-open
        # instants (a day-level normalise would hide intraday gaps), daily keeps the
        # original day-level comparison so existing behaviour is byte-for-byte.
        if is_ig_intraday:
            needs_tail = expected_last is not None and (have_last_ts is None or have_last_ts < expected_last)
        else:
            needs_tail = expected_last is not None and (
                have_last_ts is None or have_last_ts.normalize() < expected_last.normalize()
            )

        if needs_tail:
            if have_last_ts is not None:
                if is_ig_intraday:
                    # Fetch from just after the newest stored bar (missing tail only),
                    # at the interval's own granularity.
                    tail_start = have_last_ts + pd.Timedelta(minutes=INTRADAY_MINUTES[interval])
                else:
                    # Fetch from the day after the newest stored bar.
                    tail_start = have_last_ts.normalize() + pd.Timedelta(days=1)
            else:
                tail_start = start

            if is_ig_intraday:
                # IG adapter returns an already-normalised canonical frame.
                tail = self._intraday_tail_fetcher()(ticker, interval, tail_start, end)
            else:
                raw_tail = fetch_yf(ticker, interval, tail_start, end)
                tail = normalise_yf_download(raw_tail) if not raw_tail.empty else raw_tail

            tail = self._drop_incomplete_final_bar(tail, interval)

            if not tail.empty:
                if is_ig_intraday:
                    # IG bars are stored as mid-price, source-tagged and unadjusted.
                    self.upsert_bars(tail, ticker, interval, source="ig", adjusted=False)
                else:
                    self.upsert_bars(tail, ticker, interval)
                stored = self.get_ohlcv(ticker, interval, start, end)

        return stored

    def export_ohlcv(
        self,
        ticker: str,
        interval: str,
        start,
        end,
        path: str,
        fmt: str = "csv",
    ) -> str:
        """Export a scoped OHLCV range to CSV or Parquet for offline consumers.

        Reads the requested range offline via :meth:`get_ohlcv` and writes it to
        ``path``. This is a **scoped** export (only the requested range), never a
        standing full-history copy — the Pi's disk is constrained (Req 3.5, 3.6).

        Args:
            ticker: The instrument symbol (e.g. ``"SPY"``).
            interval: The bar interval tag (e.g. ``"1d"``).
            start: Inclusive range start.
            end: Inclusive range end.
            path: Destination file path.
            fmt: Output format — ``"csv"`` (default) or ``"parquet"``.

        Returns:
            The ``path`` that was written.

        Raises:
            ValueError: If ``fmt`` is not ``"csv"`` or ``"parquet"``.
        """
        df = self.get_ohlcv(ticker, interval, start, end)

        fmt_lower = fmt.lower()
        if fmt_lower == "csv":
            df.to_csv(path, index=False)
        elif fmt_lower == "parquet":
            df.to_parquet(path, index=False)
        else:
            raise ValueError(f"Unsupported export format: {fmt!r} (expected 'csv' or 'parquet')")

        return path

    @staticmethod
    def _expected_last(interval: str, start, end) -> pd.Timestamp | None:
        """Return the last bar-open that should exist on/before ``end``.

        For daily bars this is the most recent business day in ``[start, end]``,
        derived from ``utils.utils.trading_days_between`` (the codebase's pandas
        business-day helper) so gap detection stays consistent with the rest of the
        project. Returns ``None`` when the range contains no trading days (nothing is
        expected, so no tail fetch is triggered).

        For intraday intervals (``15m``/``1h``, see :data:`INTRADAY_MINUTES`) this is
        the open time of the last *completed* bar on/before ``end`` within the US 500
        trading session (SP-379, Req 5.1): a bar whose open is in session and whose
        full interval has elapsed by ``end``. Out-of-hours (weekend or the daily
        break) this is the last completed bar of the most recent session, never
        ``end`` itself. Returns ``None`` when ``[start, end]`` contains no session
        time (e.g. a weekend-only range), so no tail fetch is triggered. The result
        is monotonic non-decreasing in ``end``.

        Every other (non-daily, non-intraday) interval falls back to ``end``.
        """
        if interval == "1d":
            if trading_days_between(start, end) == 0:
                return None
            # The last business day on/before `end` within the range.
            business_days = pd.date_range(start=start, end=end, freq="B")
            if len(business_days) == 0:
                return None
            return pd.Timestamp(business_days[-1]).tz_localize(None)

        if interval in INTRADAY_MINUTES:
            return MarketDataRepository._expected_last_intraday(INTRADAY_MINUTES[interval], start, end)

        # Non-daily, non-intraday fallback: treat `end` itself as the expected last
        # bar-open, normalised to a tz-naive timestamp for comparison.
        return _to_naive_utc(end)

    @staticmethod
    def _expected_last_intraday(minutes: int, start, end) -> pd.Timestamp | None:
        """Session-aware expected-last for an intraday bar of ``minutes`` length.

        See :meth:`_expected_last` for the contract. The algorithm:

        1. Normalise ``start``/``end`` to tz-naive UTC.
        2. If the whole ``[start, end]`` range is out of session (no weekday session
           instant falls inside it), return ``None`` — nothing is expected.
        3. Otherwise find the latest in-session instant at or before ``end``
           (stepping back out of a weekend/break), subtract one interval so only a
           *completed* bar qualifies, floor to the interval grid, and step the floored
           open back into session if the subtraction/floor landed it in the break.
        4. Never return a bar-open earlier than ``start``'s own session floor — the
           expected-last stays within the requested range.
        """
        start_ts = _to_naive_utc(start)
        end_ts = _to_naive_utc(end)
        if end_ts < start_ts:
            return None

        # (2) Reject ranges containing no session time. The last in-session instant
        # on/before `end` must still be >= `start`, else the range is entirely out of
        # hours (e.g. a weekend-only window) and nothing is expected.
        last_session_instant = _previous_session_instant(end_ts)
        if last_session_instant < start_ts:
            return None

        # (3) The last *completed* bar has fully elapsed by `end`: its open is at or
        # before (last in-session instant) - interval. Subtract the interval, then
        # floor to the grid, then pull back into session if we landed in the break.
        interval = pd.Timedelta(minutes=minutes)
        candidate = _floor_to_interval_grid(last_session_instant, minutes)
        # A bar is only COMPLETE if its whole interval elapsed by `end`; if the
        # floored open + interval runs past `end`, step back one bar.
        if candidate + interval > end_ts:
            candidate = _floor_to_interval_grid(candidate - interval, minutes)
        # If flooring/subtracting dropped the open into the daily break or a weekend,
        # walk it back to the previous in-session instant and re-floor to the grid.
        if not _in_session(candidate):
            candidate = _floor_to_interval_grid(_previous_session_instant(candidate), minutes)

        # (4) Keep the expected-last within the requested range.
        if candidate < start_ts:
            return None
        return candidate

    @staticmethod
    def _drop_incomplete_final_bar(df: pd.DataFrame, interval: str) -> pd.DataFrame:
        """Drop a partial in-progress final bar before persisting.

        For intraday intervals (``15m``/``1h``, see :data:`INTRADAY_MINUTES`) a
        mid-bar grow-forward run would otherwise capture the current, still-forming
        bar — the newest (last, since the frame is sorted ascending by ``Date``) row.
        This drops that final row so only completed bars are persisted (SP-379,
        Req 5.2). The dropped bar reappears complete on a later run and lands
        idempotently via the ``(ticker, interval, ts)`` upsert.

        For daily bars this is a no-op: a scheduled run occurs after the session
        closes, so the last daily bar is already complete (the design notes this is
        trivial for daily and relevant only for intraday). Any non-intraday interval
        is likewise returned unchanged.

        An empty frame is returned unchanged (nothing to drop).

        Args:
            df: A canonical DataFrame (``CANONICAL_COLUMNS``) sorted ascending by
                ``Date``, as produced by the normalisers / tail fetchers.
            interval: The bar interval tag (e.g. ``"15m"``, ``"1h"``, ``"1d"``).

        Returns:
            The frame with its final (in-progress) intraday bar removed, or the frame
            unchanged for daily / non-intraday intervals or an empty input.
        """
        if interval not in INTRADAY_MINUTES or df.empty:
            return df
        # Frame is sorted ascending by Date, so the last row is the newest, still
        # in-progress bar; drop it and keep a clean RangeIndex.
        return df.iloc[:-1].reset_index(drop=True)
