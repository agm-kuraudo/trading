"""DB config/connection helper for the market-data store (SP-349, Req 7.1, 7.2, 9.2).

Mirrors the Betfair project's ``bf_trader_py/scripts/verify_db.py`` connection
conventions so both projects behave identically against the shared ``my_postgres``
PostgreSQL server:

- the required DB keys are read from the project ``.env`` (``_read_db_config``);
- missing/empty keys are surfaced together via ``validate_env`` rather than failing
  on the first one;
- connections are opened with psycopg2 and a **10-second** ``connect_timeout``.

The only intentional difference from Betfair is ``DB_NAME``: trading points it at its
own dedicated ``market_data`` database (NOT ``bf_trader``). ``connect`` uses whatever
``DB_NAME`` is configured; ``connect_maintenance`` ignores it and connects to the
``postgres`` maintenance database (autocommit) so the bootstrap script can run
``CREATE DATABASE``, which cannot execute inside a transaction.

Unlike Betfair, the trading project has no DotenvLoader dependency, so this module
uses a tiny inline ``.env`` parser (ignore comments/blank lines, strip quotes) to
avoid introducing a new heavy dependency.
"""

import os

import psycopg2

# Required DB connection keys read from .env (Req 7.1).
REQUIRED_DB_KEYS = ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PWD"]

# Connection timeout in seconds — mirrors Betfair's verify_db.py (Req 7.2).
CONNECT_TIMEOUT_S = 10

# Maintenance database used only to CREATE DATABASE the dedicated market_data DB.
MAINTENANCE_DB = "postgres"

# Project root .env path (this file lives at <root>/vpa/market_data/db.py).
_DEFAULT_ENV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    ".env",
)


def _parse_env_file(env_path: str) -> dict:
    """Parse a ``.env`` file into a dict of ``KEY -> VALUE``.

    A deliberately tiny, dependency-light parser: it ignores blank lines and
    comment lines (starting with ``#``), splits on the first ``=``, trims
    surrounding whitespace, and strips a single layer of matching single or
    double quotes from the value. Missing file yields an empty dict so callers
    can still report every required key as missing.

    Args:
        env_path: Path to the ``.env`` file.

    Returns:
        A dict of the key/value pairs found in the file (possibly empty).
    """
    values: dict = {}
    if not env_path or not os.path.isfile(env_path):
        return values

    with open(env_path, encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            values[key] = value
    return values


def _read_db_config(env_path: str | None = None) -> dict:
    """Read the required DB keys from the project ``.env``.

    Missing or empty keys are returned as empty strings rather than raising, so
    ``validate_env`` can report the full set of offending keys at once (Req 7.1)
    instead of failing on the first one. Mirrors Betfair's ``_read_db_config``.

    Args:
        env_path: Optional explicit path to the ``.env`` file. Defaults to the
            project root ``.env``.

    Returns:
        A dict mapping each key in ``REQUIRED_DB_KEYS`` to its value (or "").
    """
    parsed = _parse_env_file(env_path if env_path is not None else _DEFAULT_ENV_PATH)
    config = {}
    for key in REQUIRED_DB_KEYS:
        value = parsed.get(key, "")
        config[key] = value if value is not None else ""
    return config


def validate_env(config: dict, required_keys: list[str]) -> list[str]:
    """Return the list of required keys whose value is missing or empty.

    Args:
        config: The config dict (typically from ``_read_db_config``).
        required_keys: The keys that must be present and non-empty.

    Returns:
        The subset of ``required_keys`` that are absent or empty in ``config``.
    """
    return [key for key in required_keys if not config.get(key)]


def connect(config: dict | None = None):
    """Open a psycopg2 connection to the configured database.

    Mirrors Betfair's connection style with a 10-second ``connect_timeout``
    (Req 7.2). ``DB_NAME`` points at the dedicated ``market_data`` database (NOT
    ``bf_trader``); this function simply uses whatever ``DB_NAME`` is configured.

    Args:
        config: Optional config dict. If ``None``, ``_read_db_config()`` is used.

    Returns:
        An open ``psycopg2`` connection.
    """
    if config is None:
        config = _read_db_config()
    return psycopg2.connect(
        host=config["DB_HOST"],
        port=config["DB_PORT"],
        dbname=config["DB_NAME"],
        user=config["DB_USER"],
        password=config["DB_PWD"],
        connect_timeout=CONNECT_TIMEOUT_S,
    )


def connect_maintenance(config: dict | None = None):
    """Open an autocommit connection to the maintenance database.

    Like :func:`connect` but connects to the maintenance database
    (``MAINTENANCE_DB`` = ``"postgres"``) rather than ``config["DB_NAME"]``, and
    sets ``autocommit = True``. This is required by the bootstrap script because
    ``CREATE DATABASE`` cannot run inside a transaction.

    Args:
        config: Optional config dict. If ``None``, ``_read_db_config()`` is used.

    Returns:
        An open, autocommit ``psycopg2`` connection to the maintenance database.
    """
    if config is None:
        config = _read_db_config()
    conn = psycopg2.connect(
        host=config["DB_HOST"],
        port=config["DB_PORT"],
        dbname=MAINTENANCE_DB,
        user=config["DB_USER"],
        password=config["DB_PWD"],
        connect_timeout=CONNECT_TIMEOUT_S,
    )
    conn.autocommit = True
    return conn
