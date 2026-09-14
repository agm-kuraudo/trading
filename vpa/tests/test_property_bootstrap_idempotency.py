"""Property 5 — Bootstrap idempotency incl. Timescale objects (SP-349, Task 10.5).

**Validates: Requirements 11.5, 7.6, 7.7, 8.2, 8.3**

This is the property-based (hypothesis) counterpart to the example-based idempotency
coverage in ``test_verify_market_data_db_idempotency.py``. It exercises the *universal*
correctness property from the design (Correctness Property 5):

    Running ``verify_market_data_db`` when the store is already provisioned is a
    no-op — the database, schema, ``ohlcv`` table, index, ``timescaledb`` extension,
    hypertable, and compression policy already exist, so nothing new is created
    (``created == []``) and no duplicate compression policy is added.

``verify_market_data_db`` opens real ``psycopg2`` connections (a maintenance/autocommit
connection for ``CREATE DATABASE``, and a per-run connection to the ``market_data``
database for the schema + Timescale DDL). To exercise it hermetically — no real DB and
no network — we model the server with an in-memory FAKE that tracks provisioning state
and answers the *exact* probe queries the code issues, then drive it via hypothesis over
arbitrary INITIAL provisioning states.

The property asserted, for *every* generated initial state ``S``:

  * After the FIRST run the server is fully provisioned (database, schema, table,
    index, extension, hypertable all present; **exactly one** compression policy —
    never more, even if ``S`` already had one).
  * After the SECOND run ``result["created"] == []`` (nothing new created),
    ``result["reachable"] is True``, ``ohlcv`` is still a hypertable, and the
    compression-policy count is still exactly one (no duplicate).
  * ``add_compression_policy`` is NEVER called while a policy already exists (checked
    via a call counter on the fake), which is what guarantees "exactly one policy".

All ``mock.patch`` calls are applied INSIDE the test body (not via function-scoped
fixtures) so hypothesis re-runs are clean and there is no fixture-scope warning.
"""

from __future__ import annotations

from unittest import mock

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from scripts.verify_market_data_db import verify_market_data_db

# A complete, valid fake DB config so ``validate_env`` reports no missing keys and the
# bootstrap proceeds to the (faked) connection steps. Values are arbitrary — the fake
# connection ignores them; only their non-emptiness matters for the config gate.
FAKE_CONFIG = {
    "DB_HOST": "fake-host",
    "DB_PORT": "5432",
    "DB_NAME": "market_data",
    "DB_USER": "fake-user",
    "DB_PWD": "fake-pwd",
}


class FakeServer:
    """In-memory model of the Postgres/TimescaleDB server's provisioning state.

    Tracks the boolean presence of each object the bootstrap provisions plus the
    number of compression policies, and counts how many times
    ``add_compression_policy`` is invoked. A single ``FakeServer`` instance persists
    across the two ``verify_market_data_db`` runs in one property example, so the second
    run sees the state the first run left behind — exactly like a real server.
    """

    def __init__(
        self,
        *,
        database_exists: bool,
        schema_exists: bool,
        table_exists: bool,
        index_exists: bool,
        extension_exists: bool,
        hypertable_exists: bool,
        policy_count: int,
    ):
        self.database_exists = database_exists
        self.schema_exists = schema_exists
        self.table_exists = table_exists
        self.index_exists = index_exists
        self.extension_exists = extension_exists
        self.hypertable_exists = hypertable_exists
        self.policy_count = policy_count
        # Instrumentation: how many times add_compression_policy actually ran.
        self.add_policy_calls = 0


class FakeCursor:
    """A psycopg2-like cursor answering the exact probes ``verify_market_data_db`` issues.

    The cursor mutates and reads a shared :class:`FakeServer`. It recognises the
    statements by substring (matching the SQL the code under test emits) and, for the
    ``SELECT`` probes, stashes the row that the following ``fetchone()`` should return.
    ``IF NOT EXISTS`` / ``if_not_exists => TRUE`` DDL is modelled as a no-op when the
    object already exists, mutating state only when absent — i.e. genuinely idempotent.
    """

    def __init__(self, server: FakeServer):
        self._server = server
        self._next_one = None

    # -- context-manager protocol (used as ``with conn.cursor() as cursor:``) --------
    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def execute(self, sql: str, params=None) -> None:  # noqa: C901 - a flat probe router
        server = self._server
        self._next_one = None

        # --- _database_exists: SELECT 1 FROM pg_database WHERE datname = %s ----------
        if "pg_database" in sql:
            self._next_one = (1,) if server.database_exists else None
            return

        # --- CREATE DATABASE market_data (maintenance conn; no IF NOT EXISTS) --------
        # Only reached when _database_exists returned False, so this always creates it.
        if "CREATE DATABASE" in sql:
            server.database_exists = True
            return

        # --- Base schema DDL: one multi-statement string with IF NOT EXISTS ----------
        # _ensure_schema executes BASE_SCHEMA_DDL as a single execute() call.
        if "CREATE SCHEMA IF NOT EXISTS" in sql:
            # Idempotent: only "create" what is absent.
            server.schema_exists = True
            server.table_exists = True
            server.index_exists = True
            return

        # --- Extension probe + create ------------------------------------------------
        if "pg_extension" in sql:
            self._next_one = (1,) if server.extension_exists else None
            return
        if "CREATE EXTENSION IF NOT EXISTS timescaledb" in sql:
            server.extension_exists = True
            return

        # --- Hypertable probe + create ----------------------------------------------
        if "timescaledb_information.hypertables" in sql:
            self._next_one = (1,) if server.hypertable_exists else None
            return
        if "create_hypertable" in sql:
            # if_not_exists => TRUE: idempotent, marks ohlcv as a hypertable.
            server.hypertable_exists = True
            return

        # --- Enable compression settings (idempotent ALTER TABLE ... SET) -----------
        if "SET (" in sql and "timescaledb.compress" in sql:
            return

        # --- Compression-policy probe -----------------------------------------------
        if "timescaledb_information.jobs" in sql:
            self._next_one = (1,) if server.policy_count >= 1 else None
            return

        # --- add_compression_policy: only called by the code when a policy is absent.
        if "add_compression_policy" in sql:
            server.add_policy_calls += 1
            # Adding a policy establishes exactly one (never a duplicate).
            server.policy_count = 1
            return

        # Any other statement is an unexpected probe — surface it loudly so the test
        # fails rather than silently passing on a mis-modelled query.
        raise AssertionError(f"Unexpected SQL issued to FakeCursor: {sql!r}")

    def fetchone(self):
        return self._next_one


class FakeConnection:
    """A psycopg2-like connection over a shared :class:`FakeServer`.

    Supports the surface ``verify_market_data_db`` uses: ``cursor()`` (as a context
    manager), ``commit()``, ``close()`` and the ``autocommit`` attribute set by
    ``connect_maintenance``.
    """

    def __init__(self, server: FakeServer):
        self._server = server
        self.autocommit = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self._server)

    def commit(self) -> None:
        return None

    def close(self) -> None:
        return None


# ---------------------------------------------------------------------------
# Hypothesis strategy: an arbitrary INITIAL server state.
# policy_count is constrained to {0, 1} — a well-formed server never has a duplicate
# policy to begin with, and the property is precisely that no run ever creates one.
# ---------------------------------------------------------------------------
initial_states = st.fixed_dictionaries(
    {
        "database_exists": st.booleans(),
        "schema_exists": st.booleans(),
        "table_exists": st.booleans(),
        "index_exists": st.booleans(),
        "extension_exists": st.booleans(),
        "hypertable_exists": st.booleans(),
        "policy_count": st.integers(min_value=0, max_value=1),
    }
)


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(state=initial_states)
def test_bootstrap_idempotency_property(state):
    """Property 5: verify_market_data_db is idempotent from ANY provisioned state.

    **Validates: Requirements 11.5, 7.6, 7.7, 8.2, 8.3**

    For an arbitrary initial server state, running the bootstrap twice against the same
    evolving fake server leaves it fully provisioned with exactly one compression
    policy, and the second run creates nothing and adds no duplicate policy.
    """
    server = FakeServer(**state)

    def fake_connect(config=None):
        return FakeConnection(server)

    def fake_connect_maintenance(config=None):
        conn = FakeConnection(server)
        conn.autocommit = True
        return conn

    # All patches applied INSIDE the test body so each hypothesis example is clean.
    with (
        mock.patch("scripts.verify_market_data_db.connect", side_effect=fake_connect),
        mock.patch(
            "scripts.verify_market_data_db.connect_maintenance",
            side_effect=fake_connect_maintenance,
        ),
        mock.patch(
            "scripts.verify_market_data_db._read_db_config",
            return_value=dict(FAKE_CONFIG),
        ),
        mock.patch(
            "scripts.verify_market_data_db.validate_env",
            return_value=[],
        ),
    ):
        first = verify_market_data_db(env_path="dummy-env")

        # --- After the FIRST run the server is fully provisioned. ------------------
        assert first["error"] is None
        assert first["reachable"] is True
        assert first["db_ready"] is True
        assert first["schema_ready"] is True
        assert first["missing_config"] == []
        assert server.database_exists is True
        assert server.schema_exists is True
        assert server.table_exists is True
        assert server.index_exists is True
        assert server.extension_exists is True
        assert server.hypertable_exists is True
        # Exactly one compression policy — never more, even if it started at 1.
        assert server.policy_count == 1

        # The policy is added at most once across the whole first run, and never when
        # one already existed at the start.
        if state["policy_count"] >= 1:
            assert server.add_policy_calls == 0
        else:
            assert server.add_policy_calls == 1

        calls_after_first = server.add_policy_calls

        # --- SECOND run against the same (now fully provisioned) fake server. ------
        second = verify_market_data_db(env_path="dummy-env")

        # The core idempotency assertion: the second full run creates nothing.
        assert second["created"] == []
        assert second["reachable"] is True
        assert second["error"] is None
        assert second["db_ready"] is True
        assert second["schema_ready"] is True

        # ohlcv is still a hypertable, and there is still exactly one policy.
        assert server.hypertable_exists is True
        assert server.policy_count == 1

        # add_compression_policy was NEVER called during the second run (a policy
        # already exists), guaranteeing no duplicate policy is added.
        assert server.add_policy_calls == calls_after_first
