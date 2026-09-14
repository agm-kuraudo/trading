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


class MarketDataRepository:
    """Access layer over the ``market_data.ohlcv`` table.

    Args:
        conn_factory: A zero-argument callable returning an open DB connection.
            Defaults to :func:`vpa.market_data.db.connect`. Tests can inject a
            fake/local connection factory to avoid the live server.
    """

    def __init__(self, conn_factory=connect):
        self._conn_factory = conn_factory

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

        # Normalise to comparable tz-naive daily timestamps for the staleness check.
        # Stored ts values are TIMESTAMPTZ (tz-aware UTC), while `expected_last` is
        # tz-naive by construction, so strip the tz to keep the comparison valid.
        have_last_ts = None
        if have_last is not None and not pd.isna(have_last):
            have_last_ts = pd.Timestamp(have_last)
            if have_last_ts.tzinfo is not None:
                have_last_ts = have_last_ts.tz_convert("UTC").tz_localize(None)

        needs_tail = expected_last is not None and (
            have_last_ts is None or have_last_ts.normalize() < expected_last.normalize()
        )

        if needs_tail:
            if have_last_ts is not None:
                # Fetch from the day after the newest stored bar (missing tail only).
                tail_start = have_last_ts.normalize() + pd.Timedelta(days=1)
            else:
                tail_start = start

            raw_tail = fetch_yf(ticker, interval, tail_start, end)
            tail = normalise_yf_download(raw_tail) if not raw_tail.empty else raw_tail
            tail = self._drop_incomplete_final_bar(tail, interval)

            if not tail.empty:
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
        expected, so no tail fetch is triggered). Non-daily intervals fall back to
        ``end`` — session-aware intraday calendars are out of scope for now.
        """
        if interval == "1d":
            if trading_days_between(start, end) == 0:
                return None
            # The last business day on/before `end` within the range.
            business_days = pd.date_range(start=start, end=end, freq="B")
            if len(business_days) == 0:
                return None
            return pd.Timestamp(business_days[-1]).tz_localize(None)

        # Non-daily fallback: treat `end` itself as the expected last bar-open,
        # normalised to a tz-naive timestamp for comparison.
        end_ts = pd.Timestamp(end)
        if end_ts.tzinfo is not None:
            end_ts = end_ts.tz_convert("UTC").tz_localize(None)
        return end_ts

    @staticmethod
    def _drop_incomplete_final_bar(df: pd.DataFrame, interval: str) -> pd.DataFrame:
        """Drop a partial in-progress final bar before persisting.

        For daily bars this is a no-op: a scheduled run occurs after the session
        closes, so the last daily bar is already complete (the design notes this is
        trivial for daily and relevant only for intraday). The hook exists so
        intraday intervals can drop an in-progress bar later without changing the
        read-through flow. Returns the frame unchanged for now.
        """
        return df
