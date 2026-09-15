"""Verify + bootstrap the dedicated ``market_data`` store (SP-349).

Trading equivalent of the Betfair project's ``bf_trader_py/scripts/verify_db.py``.
It idempotently ensures that:

1. the DB connection details are present in ``.env`` (surfacing all missing keys
   at once, without connecting — Req 7.1); and
2. the dedicated ``market_data`` **database** exists — created via a *maintenance*
   (autocommit) connection to the ``postgres`` database if absent, because
   ``CREATE DATABASE`` cannot run inside a transaction and cannot use
   ``IF NOT EXISTS`` (Req 7.5, 7.6); and
3. the ``market_data`` schema, the ``ohlcv`` table (exact SP-324 §7 columns with
   PK ``(ticker, interval, ts)``), and its index exist — all via idempotent
   ``CREATE ... IF NOT EXISTS`` DDL (Req 7.8, 1.1, 1.2, 1.3, 1.7).

It returns a structured result dict; the CLI/exit-code wrapper (``main()``) and the
TimescaleDB provisioning (extension + hypertable + compression) are added by later
tasks — see the seam comments below.

Platform note: pure-logic checks (config validation) are cross-platform, but this
script is expected to run against the ``my_postgres`` container on the always-on
Raspberry Pi (Linux/ARM), the shared Postgres host.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import psycopg2

from vpa.market_data.db import (
    REQUIRED_DB_KEYS,
    _read_db_config,
    connect,
    connect_maintenance,
    validate_env,
)

# Dedicated database this store owns end-to-end (from DB_NAME). Created via the
# maintenance connection if absent. Never 'bf_trader' (that is Betfair's).
TARGET_DB = "market_data"

# The schema OHLCV bars live in inside the dedicated database.
MARKET_DATA_SCHEMA = "market_data"

# Idempotent schema DDL, run on a connection to the dedicated ``market_data``
# database (Step 2). The exact SP-324 §7 columns are preserved as-is: the PK
# ``(ticker, interval, ts)`` already includes ``ts`` so it stays compatible with the
# hypertable conversion added in Task 6.2.
#
# NOTE (Task 6.2 seam): the TimescaleDB provisioning statements
# (``CREATE EXTENSION IF NOT EXISTS timescaledb``, ``create_hypertable(...)``,
# ``ALTER TABLE ... SET (timescaledb.compress, ...)`` and
# ``add_compression_policy(...)``) are appended by Task 6.2. Keep them out of this
# base DDL string so the base schema can be created independently of Timescale.
BASE_SCHEMA_DDL = """
CREATE SCHEMA IF NOT EXISTS market_data;

CREATE TABLE IF NOT EXISTS market_data.ohlcv (
    ticker      TEXT        NOT NULL,
    interval    TEXT        NOT NULL,
    ts          TIMESTAMPTZ NOT NULL,
    open        DOUBLE PRECISION NOT NULL,
    high        DOUBLE PRECISION NOT NULL,
    low         DOUBLE PRECISION NOT NULL,
    close       DOUBLE PRECISION NOT NULL,
    volume      DOUBLE PRECISION,
    adjusted    BOOLEAN     NOT NULL DEFAULT TRUE,
    source      TEXT        NOT NULL DEFAULT 'yfinance',
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, interval, ts)
);

CREATE INDEX IF NOT EXISTS ix_ohlcv_ticker_interval_ts
    ON market_data.ohlcv (ticker, interval, ts);
"""


def _database_exists(cursor, datname: str) -> bool:
    """Return True if a database named ``datname`` exists on the server.

    Uses ``pg_database`` with a parameterised lookup (``datname`` is a value here,
    unlike in ``CREATE DATABASE`` where it is an identifier).
    """
    cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (datname,))
    return cursor.fetchone() is not None


def _ensure_database(config: dict, created: list) -> None:
    """Ensure the dedicated ``market_data`` database exists (Step 1).

    Runs on a **maintenance** (autocommit) connection to the ``postgres`` database.
    ``CREATE DATABASE`` cannot run inside a transaction and cannot use
    ``IF NOT EXISTS``, so we check ``pg_database`` first and create only if absent
    (Req 7.5, 7.6). The database name is a SQL identifier and therefore cannot be
    parameterised; ``TARGET_DB`` is a fixed module constant (not user input).

    Appends ``"database"`` to ``created`` when a new database is created.
    """
    mconn = connect_maintenance(config)
    try:
        with mconn.cursor() as cursor:
            if not _database_exists(cursor, TARGET_DB):
                # Identifier — cannot be parameterised. TARGET_DB is a constant.
                cursor.execute(f"CREATE DATABASE {TARGET_DB}")
                created.append("database")
    finally:
        mconn.close()


def _ensure_timescale(cursor, created: list) -> None:
    """Provision the TimescaleDB objects on ``market_data.ohlcv`` (Req 7.7, 8.1-8.4).

    Runs AFTER the base schema/table/index already exist (the caller executes
    ``BASE_SCHEMA_DDL`` first — order matters, because both ``create_hypertable`` and
    the compression policy operate on the existing table). Every step is idempotent:
    the extension uses ``IF NOT EXISTS``, ``create_hypertable`` uses
    ``if_not_exists => TRUE``, enabling compression via ``ALTER TABLE ... SET`` is a
    no-op if already set, and the compression policy is only added when one is not
    already present.

    To keep the ``created`` report accurate on re-runs, each object's presence is
    probed *before* the (idempotent) DDL runs, and the name is appended to ``created``
    only when the object was previously absent. The reported names match the design's
    contract: ``"extension"``, ``"hypertable"``, ``"compression_policy"``. So a second
    full run appends nothing for Timescale (``created == []``).
    """
    # --- Extension: append "extension" only if timescaledb was not already installed.
    cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'")
    extension_existed = cursor.fetchone() is not None
    cursor.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    if not extension_existed:
        created.append("extension")

    # --- Hypertable: append "hypertable" only if ohlcv was not already a hypertable.
    # ``create_hypertable(..., if_not_exists => TRUE)`` is safe to call regardless.
    #
    # ``chunk_time_interval`` is set to 1 year (SP-353). TimescaleDB defaults to a
    # 7-day chunk interval, which is far too granular for daily bars (~52 chunks/yr):
    # a full-history SPY series (1993->today) produced ~2388 chunks, and a full-range
    # ``get_ohlcv`` read locks one chunk each, exhausting the default
    # ``max_locks_per_transaction`` (64) with a ``psycopg2 OutOfMemory: out of shared
    # memory`` error. A 1-year interval yields ~33 chunks for the same history, well
    # under the lock budget, while still keeping chunks small enough for compression
    # and retention to work sensibly. NOTE: ``chunk_time_interval`` only applies to
    # chunks created *after* this call — it does not re-chunk existing data, so an
    # already over-chunked table must be recreated (drop + recreate + re-backfill).
    cursor.execute(
        "SELECT 1 FROM timescaledb_information.hypertables "
        "WHERE hypertable_schema = 'market_data' AND hypertable_name = 'ohlcv'"
    )
    hypertable_existed = cursor.fetchone() is not None
    cursor.execute(
        "SELECT create_hypertable('market_data.ohlcv', 'ts', "
        "chunk_time_interval => INTERVAL '1 year', if_not_exists => TRUE)"
    )
    if not hypertable_existed:
        created.append("hypertable")

    # --- Compression settings: enable columnar compression, segmenting by the query
    # --- keys. ``ALTER TABLE ... SET`` is idempotent and MUST run before
    # --- ``add_compression_policy`` (the policy requires compression to be enabled).
    cursor.execute(
        "ALTER TABLE market_data.ohlcv SET ("
        "timescaledb.compress, "
        "timescaledb.compress_segmentby = 'ticker, interval')"
    )

    # --- Compression policy: ``add_compression_policy`` errors / is a no-op if a
    # --- policy already exists, so probe for an existing job first and only add when
    # --- absent. Append "compression_policy" only when newly added.
    cursor.execute(
        "SELECT 1 FROM timescaledb_information.jobs "
        "WHERE proc_name = 'policy_compression' "
        "AND hypertable_schema = 'market_data' AND hypertable_name = 'ohlcv'"
    )
    policy_existed = cursor.fetchone() is not None
    if not policy_existed:
        cursor.execute("SELECT add_compression_policy('market_data.ohlcv', INTERVAL '30 days')")
        created.append("compression_policy")


def _ensure_schema(config: dict, created: list) -> None:
    """Ensure the schema/table/index (+ Timescale objects) exist in the dedicated DB.

    Opens a fresh connection to the dedicated ``market_data`` database (via
    ``connect(config)`` — ``config["DB_NAME"]`` should be ``market_data``) and runs
    the idempotent ``BASE_SCHEMA_DDL`` first. All base statements use
    ``IF NOT EXISTS`` so a re-run is a no-op (Req 7.8, 1.1, 1.2, 1.3, 1.7).

    Then, on the same connection/transaction, the TimescaleDB provisioning runs via
    ``_ensure_timescale`` (Req 7.7, 8.1-8.4) — after the base schema exists, because
    the hypertable conversion and compression policy operate on the existing table.
    Both phases share one commit so the whole Step 2 is atomic.
    """
    conn = connect(config)
    try:
        with conn.cursor() as cursor:
            cursor.execute(BASE_SCHEMA_DDL)
            # --- Task 6.2 seam: TimescaleDB provisioning runs after the base schema.
            _ensure_timescale(cursor, created)
        conn.commit()
    finally:
        conn.close()


def verify_market_data_db(env_path=None) -> dict:
    """Verify + bootstrap the dedicated ``market_data`` store.

    Validates: Requirements 7.1, 7.2, 7.5, 7.6, 7.8, 1.1, 1.2, 1.3, 1.7

    Args:
        env_path: Optional explicit path to the ``.env`` file (mainly for tests).

    Returns:
        A dict with the contract:
            ``reachable`` (bool): True if the server connection(s) succeeded within
                the configured timeout.
            ``missing_config`` (list): Required DB keys absent/empty in ``.env``.
            ``db_ready`` (bool): The dedicated ``market_data`` database exists after
                the run.
            ``schema_ready`` (bool): The schema + table + index exist after the run.
            ``created`` (list): Objects this run created — a subset of
                ``["database", "schema", "table", "index", "extension",
                "hypertable", "compression_policy"]``.
            ``error`` (str | None): An operator-facing error message, or None.
    """
    result = {
        "reachable": False,
        "missing_config": [],
        "db_ready": False,
        "schema_ready": False,
        "created": [],
        "error": None,
    }

    # --- Config check (Req 7.1): do not connect if required keys are missing. ---
    config = _read_db_config(env_path)
    missing_config = validate_env(config, REQUIRED_DB_KEYS)
    if missing_config:
        result["missing_config"] = missing_config
        result["error"] = "Missing required DB connection details in .env: " + ", ".join(missing_config)
        return result

    created: list = []

    # --- Step 1 (Req 7.5, 7.6): ensure the dedicated database exists. ---
    try:
        _ensure_database(config, created)
    except (Exception, psycopg2.DatabaseError) as error:
        result["error"] = f"Data store unreachable / could not ensure database: {error}"
        return result

    # --- Step 2 (Req 7.8, 1.1, 1.2, 1.3, 1.7): ensure schema/table/index exist. ---
    try:
        _ensure_schema(config, created)
    except (Exception, psycopg2.DatabaseError) as error:
        result["error"] = f"Failed to confirm/create market_data schema: {error}"
        return result

    result["reachable"] = True
    result["db_ready"] = True
    result["schema_ready"] = True
    result["created"] = created
    return result


def main() -> int:
    """CLI entry: print the verification result and return an exit code.

    Validates: Requirements 7.3, 7.4, 7.9

    Mirrors the Betfair project's ``verify_db.py`` main(): print the structured
    result in a readable block, then gate on it. Returns a non-zero exit code when
    required config is missing or the store is unreachable, so a scheduler/deploy
    step can gate on it (Req 7.3, 7.4). ``missing_config`` is checked before
    ``reachable`` because missing config short-circuits before any connection is
    attempted (Req 7.9).
    """
    result = verify_market_data_db()

    print("market_data store verification result:")
    print(f"  reachable      : {result['reachable']}")
    print(f"  missing_config : {result['missing_config']}")
    print(f"  db_ready       : {result['db_ready']}")
    print(f"  schema_ready   : {result['schema_ready']}")
    print(f"  created        : {result['created']}")
    print(f"  error          : {result['error']}")

    if result["missing_config"]:
        print(
            "market_data store NOT stood up: required DB connection details are missing.",
            file=sys.stderr,
        )
        return 2
    if not result["reachable"]:
        print(
            "market_data store NOT stood up: data store is unreachable.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
