"""Integration tests for ``MarketDataRepository`` (SP-349, Tasks 4.5 and 4.6).

These are integration-style tests for the repository access layer, but they run
**reliably in the normal test suite without any live database and without any
network I/O**. Both requirements are met by injecting a small in-memory,
psycopg2-like fake connection via the repository's ``conn_factory`` seam.

The fake (:class:`FakeConnection` / :class:`FakeCursor`) simulates the
``market_data.ohlcv`` table as a dict keyed by ``(ticker, interval, ts)`` and
implements just enough of the psycopg2 cursor API that the repository uses:
``cursor()`` as a context manager, ``execute(sql, params)``, ``fetchone()``,
``fetchall()``, ``commit()`` and ``close()``. It recognises the repository's two
statements by matching on distinctive SQL fragments:

- **UPSERT** — inserts or updates the keyed row and, matching the real
  ``RETURNING (xmax = 0) AS inserted`` semantics, makes ``fetchone()`` return
  ``(True,)`` when the key was newly inserted and ``(False,)`` when it already
  existed. This exercises the ``inserted`` / ``updated`` tally in ``upsert_bars``.
- **SELECT** — returns the ``(ts, open, high, low, close, volume)`` rows for the
  requested ``(ticker, interval)`` whose ``ts`` falls within the inclusive
  ``[start, end]`` range, ordered by ``ts`` (matching ``ORDER BY ts``).

Task 4.5 covers idempotency / append behaviour (Requirements 2.2, 2.3, 2.4).
Task 4.6 covers the offline-read guarantee that ``get_ohlcv`` and ``export_ohlcv``
perform no network I/O (Requirements 3.1, 3.6).

An optional real-DB smoke test is included at the end, guarded by the
``MARKET_DATA_TEST_DSN`` environment variable, so it never runs by default.
"""

from __future__ import annotations

import os

import pandas as pd
import pytest

from vpa.market_data.repository import MarketDataRepository

# ---------------------------------------------------------------------------
# In-memory psycopg2-like fake connection (shared by both task groups)
# ---------------------------------------------------------------------------


class FakeCursor:
    """A minimal psycopg2-like cursor backed by a shared in-memory store.

    ``store`` is a dict keyed by ``(ticker, interval, ts)`` whose values are the
    full store-row tuples. The cursor recognises the repository's two SQL statements
    by matching distinctive fragments and mutates / queries ``store`` accordingly.
    """

    def __init__(self, store: dict):
        self._store = store
        self._last_one = None  # result for the next fetchone() (UPSERT RETURNING)
        self._last_all = None  # result for the next fetchall() (SELECT)

    # Context-manager protocol (repository uses ``with conn.cursor() as cur:``).
    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, sql: str, params=None) -> None:
        """Dispatch on the statement kind and record the pending result."""
        params = params or ()

        if "INSERT INTO market_data.ohlcv" in sql:
            self._execute_upsert(params)
        elif "SELECT ts, open, high, low, close, volume" in sql:
            self._execute_select(params)
        else:  # pragma: no cover - defensive; the repo issues only these two.
            raise AssertionError(f"Unexpected SQL issued to FakeCursor:\n{sql}")

    def _execute_upsert(self, params) -> None:
        # store-row order: (ticker, interval, ts, open, high, low, close,
        #                   volume, adjusted, source)
        ticker, interval, ts = params[0], params[1], params[2]
        key = (ticker, interval, ts)
        was_insert = key not in self._store
        # Insert or update the keyed row (idempotent on the PK, like ON CONFLICT).
        self._store[key] = tuple(params)
        # Mirror ``RETURNING (xmax = 0) AS inserted``.
        self._last_one = (was_insert,)

    def _execute_select(self, params) -> None:
        ticker, interval, start, end = params
        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)

        selected = []
        for (row_ticker, row_interval, row_ts), row in self._store.items():
            if row_ticker != ticker or row_interval != interval:
                continue
            row_ts_cmp = pd.Timestamp(row_ts)
            # Compare on the same tz-awareness footing as the stored ts.
            lo = _match_tz(start_ts, row_ts_cmp)
            hi = _match_tz(end_ts, row_ts_cmp)
            if lo <= row_ts_cmp <= hi:
                # SELECT projection: ts, open, high, low, close, volume.
                selected.append((row[2], row[3], row[4], row[5], row[6], row[7]))

        selected.sort(key=lambda r: pd.Timestamp(r[0]))  # ORDER BY ts
        self._last_all = selected

    def fetchone(self):
        return self._last_one

    def fetchall(self):
        return self._last_all

    def close(self) -> None:
        return None


def _match_tz(bound: pd.Timestamp, reference: pd.Timestamp) -> pd.Timestamp:
    """Align ``bound``'s tz-awareness to ``reference`` for a safe comparison.

    Stored ``ts`` values are UTC tz-aware (per ``to_store_rows``); range bounds in
    tests may be naive strings/timestamps. If one side is tz-aware and the other is
    naive, localise/convert the bound to match so the ``<=`` comparison is valid.
    """
    if reference.tzinfo is not None and bound.tzinfo is None:
        return bound.tz_localize("UTC")
    if reference.tzinfo is None and bound.tzinfo is not None:
        return bound.tz_convert("UTC").tz_localize(None)
    return bound


class FakeConnection:
    """A psycopg2-like connection sharing one in-memory ``store`` dict.

    Every cursor opened on the connection reads/writes the same ``store``, so
    writes via ``upsert_bars`` are visible to subsequent ``get_ohlcv`` reads — even
    though the repository opens a fresh connection per call (the factory returns a
    connection bound to the same store).
    """

    def __init__(self, store: dict):
        self._store = store
        self.commits = 0
        self.closed = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self._store)

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        self.closed = True


def make_conn_factory():
    """Return ``(store, conn_factory)`` sharing one in-memory store.

    ``conn_factory`` is a zero-arg callable suitable for
    ``MarketDataRepository(conn_factory=...)``; each call returns a fresh
    :class:`FakeConnection` bound to the shared ``store`` dict, mirroring how the
    real factory opens a new connection per operation against one database.
    """
    store: dict = {}

    def conn_factory() -> FakeConnection:
        return FakeConnection(store)

    return store, conn_factory


# ---------------------------------------------------------------------------
# Canonical DataFrame builder
# ---------------------------------------------------------------------------


def make_canonical_df(dates) -> pd.DataFrame:
    """Build a canonical ``Date, Open, High, Low, Close, Volume`` frame.

    Each row gets distinct, deterministic values so tests can assert values land in
    the right places and rows are neither transposed nor reordered.
    """
    dates = list(dates)
    n = len(dates)
    return pd.DataFrame(
        {
            "Date": [pd.Timestamp(d) for d in dates],
            "Open": [100.0 + i for i in range(n)],
            "High": [110.0 + i for i in range(n)],
            "Low": [90.0 + i for i in range(n)],
            "Close": [105.0 + i for i in range(n)],
            "Volume": [1_000_000 + i for i in range(n)],
        }
    )


# ===========================================================================
# Task 4.5 — integration test: idempotency / append (Req 2.2, 2.3, 2.4)
# ===========================================================================


def test_first_upsert_reports_all_inserted_and_stores_all_rows():
    store, conn_factory = make_conn_factory()
    repo = MarketDataRepository(conn_factory=conn_factory)
    df = make_canonical_df(["2024-01-02", "2024-01-03", "2024-01-04"])

    result = repo.upsert_bars(df, "SPY", "1d")

    assert result == {"inserted": 3, "updated": 0}
    assert len(store) == 3  # one row per (ticker, interval, ts)


def test_second_upsert_of_same_bars_is_all_updates_no_duplicates():
    store, conn_factory = make_conn_factory()
    repo = MarketDataRepository(conn_factory=conn_factory)
    df = make_canonical_df(["2024-01-02", "2024-01-03", "2024-01-04"])

    first = repo.upsert_bars(df, "SPY", "1d")
    second = repo.upsert_bars(df, "SPY", "1d")

    assert first == {"inserted": 3, "updated": 0}
    # Re-ingesting the same bars updates every row and inserts none (PK invariant).
    assert second == {"inserted": 0, "updated": 3}
    # No duplicates: the distinct (ticker, interval, ts) key count is unchanged.
    assert len(store) == 3


def test_overlapping_upsert_splits_counts_and_unions_rows():
    store, conn_factory = make_conn_factory()
    repo = MarketDataRepository(conn_factory=conn_factory)

    initial = make_canonical_df(["2024-01-02", "2024-01-03", "2024-01-04"])
    repo.upsert_bars(initial, "SPY", "1d")

    # Overlapping set: two existing ts (01-03, 01-04) + two new (01-05, 01-08).
    overlap = make_canonical_df(["2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"])
    result = repo.upsert_bars(overlap, "SPY", "1d")

    assert result == {"inserted": 2, "updated": 2}
    # Total distinct rows == union of both date sets (5 distinct days).
    assert len(store) == 5


def test_upsert_commits_and_closes_connection():
    store, conn_factory = make_conn_factory()

    # Wrap the factory to capture the connection objects it produces.
    produced = []

    def tracking_factory():
        conn = conn_factory()
        produced.append(conn)
        return conn

    repo = MarketDataRepository(conn_factory=tracking_factory)
    repo.upsert_bars(make_canonical_df(["2024-01-02"]), "SPY", "1d")

    assert len(produced) == 1
    assert produced[0].commits == 1
    assert produced[0].closed is True


# ===========================================================================
# Task 4.6 — integration test: offline read performs no network I/O
#            (Req 3.1, 3.6)
# ===========================================================================


@pytest.fixture
def no_network(monkeypatch):
    """Make any accidental network fetch fail loudly.

    Patches both ``yfinance.download`` and the ingestion wrapper
    ``vpa.market_data.ohlcv_ingest.fetch_yf`` so that if either the offline read or
    the export path were to touch the network, the test fails deterministically with
    an ``AssertionError`` instead of making a real request.
    """

    def _raise(*args, **kwargs):
        raise AssertionError("network access attempted during an offline read")

    monkeypatch.setattr("yfinance.download", _raise)
    monkeypatch.setattr("vpa.market_data.ohlcv_ingest.fetch_yf", _raise)
    return _raise


def test_get_ohlcv_reads_offline_without_network(no_network):
    store, conn_factory = make_conn_factory()
    repo = MarketDataRepository(conn_factory=conn_factory)
    df = make_canonical_df(["2024-01-02", "2024-01-03", "2024-01-04"])
    repo.upsert_bars(df, "SPY", "1d")

    # Reads over the range and returns the canonical frame — no network call.
    out = repo.get_ohlcv("SPY", "1d", "2024-01-01", "2024-01-31")

    assert list(out.columns) == ["Date", "Open", "High", "Low", "Close", "Volume"]
    assert len(out) == 3
    # Ordered by Date ascending.
    assert list(out["Date"]) == sorted(out["Date"])
    # Values round-trip (OHLCV) for the first bar.
    first = out.iloc[0]
    assert (first["Open"], first["High"], first["Low"], first["Close"]) == (100.0, 110.0, 90.0, 105.0)
    assert first["Volume"] == 1_000_000.0


def test_get_ohlcv_respects_range_bounds(no_network):
    store, conn_factory = make_conn_factory()
    repo = MarketDataRepository(conn_factory=conn_factory)
    df = make_canonical_df(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-08"])
    repo.upsert_bars(df, "SPY", "1d")

    # Inclusive range that excludes the first and last stored bars.
    out = repo.get_ohlcv("SPY", "1d", "2024-01-03", "2024-01-04")

    assert len(out) == 2
    days = [pd.Timestamp(d).day for d in out["Date"]]
    assert days == [3, 4]


def test_export_ohlcv_writes_csv_without_network(no_network, tmp_path):
    store, conn_factory = make_conn_factory()
    repo = MarketDataRepository(conn_factory=conn_factory)
    df = make_canonical_df(["2024-01-02", "2024-01-03", "2024-01-04"])
    repo.upsert_bars(df, "SPY", "1d")

    out_path = tmp_path / "SPY_ohlcv.csv"
    returned = repo.export_ohlcv("SPY", "1d", "2024-01-01", "2024-01-31", str(out_path))

    # The file is written and the path is returned; no network was touched.
    assert returned == str(out_path)
    assert out_path.exists()

    # Read it back and confirm columns and row count match.
    read_back = pd.read_csv(out_path)
    assert list(read_back.columns) == ["Date", "Open", "High", "Low", "Close", "Volume"]
    assert len(read_back) == 3
    assert list(read_back["Close"]) == [105.0, 106.0, 107.0]


# ===========================================================================
# Optional real-DB smoke test — never runs by default.
# Set MARKET_DATA_TEST_DSN (and ensure the schema exists) to exercise it.
# ===========================================================================


@pytest.mark.skipif(
    not os.environ.get("MARKET_DATA_TEST_DSN"),
    reason="MARKET_DATA_TEST_DSN not set; skipping live-DB integration smoke test",
)
def test_real_db_idempotency_smoke():  # pragma: no cover - opt-in only
    import psycopg2  # imported lazily so the default suite never needs it.

    dsn = os.environ["MARKET_DATA_TEST_DSN"]

    def conn_factory():
        return psycopg2.connect(dsn)

    repo = MarketDataRepository(conn_factory=conn_factory)
    df = make_canonical_df(["2024-01-02", "2024-01-03", "2024-01-04"])

    first = repo.upsert_bars(df, "SPY_TEST", "1d")
    second = repo.upsert_bars(df, "SPY_TEST", "1d")

    assert first["inserted"] == 3
    assert second["updated"] == 3
    assert second["inserted"] == 0

    out = repo.get_ohlcv("SPY_TEST", "1d", "2024-01-01", "2024-01-31")
    assert len(out) == 3


# ===========================================================================
# Batched-commit scaling fix (SP-349 Task 12.4 defect): a large backfill must
# commit in bounded batches rather than one giant transaction, so hypertable
# chunk locks stay under max_locks_per_transaction. Counts must be unchanged.
# ===========================================================================


def test_large_upsert_commits_in_multiple_batches():
    from vpa.market_data.repository import UPSERT_BATCH_SIZE

    store, conn_factory = make_conn_factory()

    # Capture the connection objects so we can read the commit counter afterwards.
    produced = []

    def tracking_factory():
        conn = conn_factory()
        produced.append(conn)
        return conn

    repo = MarketDataRepository(conn_factory=tracking_factory)

    # More than one full batch of distinct business days ensures >1 commit.
    n = UPSERT_BATCH_SIZE + 250
    dates = pd.bdate_range(start="2000-01-03", periods=n)
    assert len(dates) == n  # distinct dates => distinct (ticker, interval, ts) keys
    df = make_canonical_df(dates)

    result = repo.upsert_bars(df, "SPY", "1d")

    # (a) Counts are correct: every distinct-date row is a fresh insert.
    assert result == {"inserted": n, "updated": 0}
    assert len(store) == n

    # (b) The connection committed more than once, proving batched commits.
    assert len(produced) == 1
    assert produced[0].commits > 1
    # Precisely: one commit per full batch plus one for the remainder.
    expected_commits = (n + UPSERT_BATCH_SIZE - 1) // UPSERT_BATCH_SIZE
    assert produced[0].commits == expected_commits


def test_large_upsert_batching_preserves_idempotency():
    from vpa.market_data.repository import UPSERT_BATCH_SIZE

    store, conn_factory = make_conn_factory()
    repo = MarketDataRepository(conn_factory=conn_factory)

    n = UPSERT_BATCH_SIZE + 250
    dates = pd.bdate_range(start="2000-01-03", periods=n)
    df = make_canonical_df(dates)

    first = repo.upsert_bars(df, "SPY", "1d")
    second = repo.upsert_bars(df, "SPY", "1d")

    # Re-running yields inserted=0/updated=n despite committing in batches.
    assert first == {"inserted": n, "updated": 0}
    assert second == {"inserted": 0, "updated": n}
    assert len(store) == n
