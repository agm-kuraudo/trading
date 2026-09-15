"""Bootstrap idempotency tests for ``verify_market_data_db`` (SP-349, Task 6.4).

This module covers the idempotency contract of the verify/bootstrap script, with a
particular focus on the TimescaleDB provisioning added in Task 6.2. The relevant
requirements are:

- **7.6** — ``CREATE DATABASE`` only runs when the database is absent (a re-run
  creates nothing).
- **7.7 / 8.1-8.4** — the TimescaleDB objects (extension, hypertable, compression
  settings + policy) are provisioned idempotently, so a second full run reports
  ``created == []``.
- **8.2** — ``ohlcv`` is (and remains) a hypertable partitioned on ``ts``.
- **8.3** — exactly one compression policy exists (no duplicate policy on re-run).

Two layers of coverage are provided:

1. **Always-run fake-cursor unit tests** (no DB, no network) that exercise the
   ``created`` bookkeeping inside ``_ensure_timescale`` directly. A tiny psycopg2-like
   fake cursor answers the exact probe queries the function issues, letting us assert
   that:
     * when every object already exists, ``_ensure_timescale`` appends **nothing**;
     * when nothing exists yet, it appends
       ``["extension", "hypertable", "compression_policy"]`` in that order.
   These mirror the fake-connection approach used in
   ``test_market_data_repository_integration.py`` and give the default suite real
   coverage of the idempotency logic without a live database.

2. **A gated real-DB integration test** (opt-in via ``MARKET_DATA_TEST_DSN``) that runs
   ``verify_market_data_db`` twice against a Timescale-capable throwaway database and
   asserts the second run is a genuine no-op (``created == []``), that ``ohlcv`` is a
   hypertable on ``ts``, and that exactly one compression policy exists. It follows the
   same gating convention as ``test_market_data_repository_integration.py`` so it never
   runs by default and never touches the live Pi / shared DB.
"""

from __future__ import annotations

import os

import pytest

from scripts.verify_market_data_db import _ensure_timescale, verify_market_data_db

# ---------------------------------------------------------------------------
# Always-run fake cursor for _ensure_timescale bookkeeping (no DB, no network)
# ---------------------------------------------------------------------------


class FakeTimescaleCursor:
    """A minimal psycopg2-like cursor that answers ``_ensure_timescale``'s probes.

    ``_ensure_timescale`` issues, in order:

      1. ``SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'``  -> fetchone()
      2. ``CREATE EXTENSION IF NOT EXISTS timescaledb``                (no fetch)
      3. ``SELECT 1 FROM timescaledb_information.hypertables ...``     -> fetchone()
      4. ``SELECT create_hypertable('market_data.ohlcv', 'ts', ...)`` (no fetch)
      5. ``ALTER TABLE market_data.ohlcv SET (timescaledb.compress...)`` (no fetch)
      6. ``SELECT 1 FROM timescaledb_information.jobs ...``            -> fetchone()
      7. ``SELECT add_compression_policy(...)``                       (only if absent)

    The three booleans control whether each probed object is reported as already
    existing (``fetchone()`` returns ``(1,)``) or absent (``fetchone()`` returns
    ``None``). Every executed statement is recorded in ``executed`` so tests can
    assert whether the ``add_compression_policy`` DDL actually ran.
    """

    def __init__(self, *, extension_exists: bool, hypertable_exists: bool, policy_exists: bool):
        self._extension_exists = extension_exists
        self._hypertable_exists = hypertable_exists
        self._policy_exists = policy_exists
        self._next_one = None
        self.executed: list[str] = []

    def execute(self, sql: str, params=None) -> None:
        self.executed.append(sql)

        if "pg_extension" in sql:
            self._next_one = (1,) if self._extension_exists else None
        elif "timescaledb_information.hypertables" in sql:
            self._next_one = (1,) if self._hypertable_exists else None
        elif "timescaledb_information.jobs" in sql:
            self._next_one = (1,) if self._policy_exists else None
        else:
            # DDL statements (CREATE EXTENSION, create_hypertable, ALTER TABLE,
            # add_compression_policy) don't have a probed fetchone() result.
            self._next_one = None

    def fetchone(self):
        return self._next_one


def test_ensure_timescale_appends_nothing_when_all_objects_exist():
    """Req 7.7, 8.2, 8.3 — a fully-provisioned state creates nothing (idempotent)."""
    cursor = FakeTimescaleCursor(
        extension_exists=True,
        hypertable_exists=True,
        policy_exists=True,
    )
    created: list[str] = []

    _ensure_timescale(cursor, created)

    # Nothing new was created on this run.
    assert created == []
    # Because a policy already existed, add_compression_policy DDL must NOT run
    # (that is what guarantees "exactly one compression policy" — Req 8.3).
    assert not any("add_compression_policy" in sql for sql in cursor.executed)


def test_ensure_timescale_appends_all_in_order_when_nothing_exists():
    """Req 7.7, 8.1-8.4 — a bare state provisions all three objects, in order."""
    cursor = FakeTimescaleCursor(
        extension_exists=False,
        hypertable_exists=False,
        policy_exists=False,
    )
    created: list[str] = []

    _ensure_timescale(cursor, created)

    # The contract order the design specifies for the "created" report.
    assert created == ["extension", "hypertable", "compression_policy"]
    # The policy was absent, so add_compression_policy DDL must have run exactly once.
    assert sum("add_compression_policy" in sql for sql in cursor.executed) == 1


def test_ensure_timescale_sets_one_year_chunk_interval():
    """SP-353 — create_hypertable must set a 1-year chunk_time_interval.

    Regression guard for the OutOfMemory bug: TimescaleDB's default 7-day chunk
    interval over-chunks daily bars (~2388 chunks for full SPY history), so a
    full-range ``get_ohlcv`` read exhausts ``max_locks_per_transaction``. The
    bootstrap must pin a coarser interval (1 year, ~33 chunks) on fresh provisions so
    this does not regress the next time the hypertable is created from scratch.
    """
    cursor = FakeTimescaleCursor(
        extension_exists=False,
        hypertable_exists=False,
        policy_exists=False,
    )

    _ensure_timescale(cursor, [])

    hypertable_calls = [sql for sql in cursor.executed if "create_hypertable" in sql]
    assert len(hypertable_calls) == 1
    call = hypertable_calls[0]
    # The chunk interval must be explicitly set (not left at the 7-day default) and
    # sized for daily bars.
    assert "chunk_time_interval" in call
    assert "INTERVAL '1 year'" in call


# ---------------------------------------------------------------------------
# Gated real-DB integration test — never runs by default.
#
# Enable by pointing MARKET_DATA_TEST_DSN at a THROWAWAY Timescale-capable DB, e.g.
#   MARKET_DATA_TEST_DSN=postgresql://user:pwd@host:5432/market_data_test
# The DSN's database MUST be a dedicated test DB (NOT 'market_data' prod, NOT
# 'bf_trader'). This test does not CREATE/DROP the database itself: it assumes an
# already-created (possibly empty) Timescale-capable test DB and only asserts the
# idempotency of the schema/timescale objects. verify_market_data_db reads its config
# from a .env via _read_db_config(env_path), so we synthesise a temp .env from the DSN
# (or from MARKET_DATA_TEST_DB_* overrides) and pass env_path explicitly.
# ---------------------------------------------------------------------------


def _test_db_config_from_env():  # pragma: no cover - only used in the gated path
    """Derive DB_* values for the temp .env from the test env vars.

    Prefers the discrete ``MARKET_DATA_TEST_DB_*`` vars when present; otherwise
    parses ``MARKET_DATA_TEST_DSN``. Guards against ever targeting the prod
    ``market_data`` DB or Betfair's ``bf_trader`` DB.
    """
    from urllib.parse import urlparse

    host = os.environ.get("MARKET_DATA_TEST_DB_HOST")
    port = os.environ.get("MARKET_DATA_TEST_DB_PORT")
    name = os.environ.get("MARKET_DATA_TEST_DB_NAME")
    user = os.environ.get("MARKET_DATA_TEST_DB_USER")
    pwd = os.environ.get("MARKET_DATA_TEST_DB_PWD")

    if not name:
        dsn = os.environ["MARKET_DATA_TEST_DSN"]
        parsed = urlparse(dsn)
        host = host or parsed.hostname
        port = port or (str(parsed.port) if parsed.port else "5432")
        name = (parsed.path or "").lstrip("/")
        user = user or parsed.username
        pwd = pwd or parsed.password

    if name in {"market_data", "bf_trader"}:
        raise AssertionError(
            f"Refusing to run the gated idempotency test against '{name}': "
            "use a dedicated throwaway test database, not prod/Betfair."
        )

    return {
        "DB_HOST": host or "",
        "DB_PORT": port or "5432",
        "DB_NAME": name or "",
        "DB_USER": user or "",
        "DB_PWD": pwd or "",
    }


@pytest.mark.skipif(
    not os.environ.get("MARKET_DATA_TEST_DSN"),
    reason="MARKET_DATA_TEST_DSN not set; skipping live-DB bootstrap idempotency test",
)
def test_real_db_bootstrap_idempotency(tmp_path):  # pragma: no cover - opt-in only
    """Req 7.6, 7.7, 8.2, 8.3 — running the bootstrap twice is a no-op the 2nd time.

    Asserts: first run reachable and created at least the schema/table/timescale
    objects; second run created nothing (``created == []``); ohlcv is a hypertable on
    ts; exactly one compression policy exists.
    """
    import psycopg2  # imported lazily so the default suite never needs it.

    config = _test_db_config_from_env()

    # Write a temp .env with DB_* derived from the test DSN and point the bootstrap
    # at it, so it targets the dedicated throwaway test DB rather than prod.
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(f"{key}={value}" for key, value in config.items()) + "\n",
        encoding="utf-8",
    )

    first = verify_market_data_db(env_path=str(env_path))
    assert first["error"] is None
    assert first["reachable"] is True
    assert first["db_ready"] is True
    assert first["schema_ready"] is True

    second = verify_market_data_db(env_path=str(env_path))
    assert second["error"] is None
    assert second["reachable"] is True
    # The core idempotency assertion: the second full run creates nothing.
    assert second["created"] == []

    # Directly verify the Timescale state on the test DB.
    conn = psycopg2.connect(
        host=config["DB_HOST"],
        port=config["DB_PORT"],
        dbname=config["DB_NAME"],
        user=config["DB_USER"],
        password=config["DB_PWD"],
        connect_timeout=10,
    )
    try:
        with conn.cursor() as cur:
            # ohlcv is a hypertable partitioned on ts (Req 8.2).
            cur.execute(
                "SELECT column_name FROM timescaledb_information.dimensions "
                "WHERE hypertable_schema = 'market_data' AND hypertable_name = 'ohlcv'"
            )
            dimensions = [row[0] for row in cur.fetchall()]
            assert "ts" in dimensions

            cur.execute(
                "SELECT 1 FROM timescaledb_information.hypertables "
                "WHERE hypertable_schema = 'market_data' AND hypertable_name = 'ohlcv'"
            )
            assert cur.fetchone() is not None

            # Exactly one compression policy exists (Req 8.3).
            cur.execute(
                "SELECT count(*) FROM timescaledb_information.jobs "
                "WHERE proc_name = 'policy_compression' "
                "AND hypertable_schema = 'market_data' AND hypertable_name = 'ohlcv'"
            )
            assert cur.fetchone()[0] == 1
    finally:
        conn.close()
