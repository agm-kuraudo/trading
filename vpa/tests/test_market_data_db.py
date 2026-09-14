"""Unit tests for ``vpa.market_data.db`` config reading and validation (SP-349).

These are pure-logic tests: they exercise ``validate_env``, ``_parse_env_file``, and
``_read_db_config`` only. There is deliberately NO database connection and NO network
I/O here — the connection helpers (``connect`` / ``connect_maintenance``) are out of
scope for this task and are not touched.

Config reading is driven off a temporary ``.env`` file written under ``tmp_path`` and
passed explicitly to ``_read_db_config(env_path=...)``, so the real project ``.env`` is
never read.

Covers Requirements 7.1 (read the five required DB keys; report missing/empty ones) and
7.3 (missing/empty configuration is surfaced together so the caller can fail loudly).
"""

from vpa.market_data.db import (
    REQUIRED_DB_KEYS,
    _parse_env_file,
    _read_db_config,
    validate_env,
)


def write_env(tmp_path, contents: str):
    """Write ``contents`` to a ``.env`` file under ``tmp_path`` and return its path."""
    path = tmp_path / ".env"
    path.write_text(contents, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# validate_env (Req 7.1, 7.3)
# ---------------------------------------------------------------------------


def test_validate_env_reports_all_keys_when_config_empty():
    missing = validate_env({}, REQUIRED_DB_KEYS)

    assert missing == REQUIRED_DB_KEYS


def test_validate_env_reports_all_keys_when_all_values_empty():
    config = dict.fromkeys(REQUIRED_DB_KEYS, "")

    missing = validate_env(config, REQUIRED_DB_KEYS)

    assert missing == REQUIRED_DB_KEYS


def test_validate_env_returns_empty_when_all_keys_present_and_non_empty():
    config = {
        "DB_HOST": "my_postgres",
        "DB_PORT": "5432",
        "DB_NAME": "market_data",
        "DB_USER": "trader",
        "DB_PWD": "secret",
    }

    missing = validate_env(config, REQUIRED_DB_KEYS)

    assert missing == []


def test_validate_env_treats_empty_string_values_as_missing():
    config = {
        "DB_HOST": "my_postgres",
        "DB_PORT": "",  # empty -> reported
        "DB_NAME": "market_data",
        "DB_USER": "",  # empty -> reported
        "DB_PWD": "secret",
    }

    missing = validate_env(config, REQUIRED_DB_KEYS)

    assert missing == ["DB_PORT", "DB_USER"]


# ---------------------------------------------------------------------------
# _parse_env_file (Req 7.1)
# ---------------------------------------------------------------------------


def test_parse_env_file_parses_key_value_lines(tmp_path):
    env_path = write_env(tmp_path, "DB_HOST=my_postgres\nDB_PORT=5432\n")

    parsed = _parse_env_file(str(env_path))

    assert parsed == {"DB_HOST": "my_postgres", "DB_PORT": "5432"}


def test_parse_env_file_ignores_comments_and_blank_lines(tmp_path):
    contents = "# leading comment\n" "\n" "DB_HOST=my_postgres\n" "   \n" "# another comment\n" "DB_USER=trader\n"
    env_path = write_env(tmp_path, contents)

    parsed = _parse_env_file(str(env_path))

    assert parsed == {"DB_HOST": "my_postgres", "DB_USER": "trader"}


def test_parse_env_file_strips_surrounding_quotes(tmp_path):
    contents = "DB_NAME=\"market_data\"\nDB_USER='trader'\nDB_PWD=plain\n"
    env_path = write_env(tmp_path, contents)

    parsed = _parse_env_file(str(env_path))

    assert parsed == {
        "DB_NAME": "market_data",
        "DB_USER": "trader",
        "DB_PWD": "plain",
    }


def test_parse_env_file_missing_file_returns_empty_dict(tmp_path):
    missing_path = tmp_path / "does_not_exist.env"

    assert _parse_env_file(str(missing_path)) == {}


# ---------------------------------------------------------------------------
# _read_db_config (Req 7.1, 7.3)
# ---------------------------------------------------------------------------


def test_read_db_config_returns_all_required_keys_from_file(tmp_path):
    contents = "DB_HOST=my_postgres\n" "DB_PORT=5432\n" "DB_NAME=market_data\n" "DB_USER=trader\n" "DB_PWD=secret\n"
    env_path = write_env(tmp_path, contents)

    config = _read_db_config(env_path=str(env_path))

    assert config == {
        "DB_HOST": "my_postgres",
        "DB_PORT": "5432",
        "DB_NAME": "market_data",
        "DB_USER": "trader",
        "DB_PWD": "secret",
    }


def test_read_db_config_fills_absent_keys_with_empty_string(tmp_path):
    # Only two of the five required keys are present in the file.
    env_path = write_env(tmp_path, "DB_HOST=my_postgres\nDB_PORT=5432\n")

    config = _read_db_config(env_path=str(env_path))

    # All five required keys are always present in the returned dict.
    assert set(config.keys()) == set(REQUIRED_DB_KEYS)
    assert config["DB_HOST"] == "my_postgres"
    assert config["DB_PORT"] == "5432"
    assert config["DB_NAME"] == ""
    assert config["DB_USER"] == ""
    assert config["DB_PWD"] == ""


def test_read_db_config_missing_file_yields_all_empty_and_all_missing(tmp_path):
    missing_path = tmp_path / "no_such.env"

    config = _read_db_config(env_path=str(missing_path))

    # Every required key present but empty, so validate_env reports them all.
    assert set(config.keys()) == set(REQUIRED_DB_KEYS)
    assert all(value == "" for value in config.values())
    assert validate_env(config, REQUIRED_DB_KEYS) == REQUIRED_DB_KEYS


def test_read_db_config_ignores_comments_and_strips_quotes(tmp_path):
    contents = (
        "# market_data DB config\n"
        "DB_HOST='my_postgres'\n"
        "\n"
        'DB_PORT="5432"\n'
        "DB_NAME=market_data\n"
        "DB_USER=trader\n"
        "DB_PWD=secret\n"
    )
    env_path = write_env(tmp_path, contents)

    config = _read_db_config(env_path=str(env_path))

    assert config["DB_HOST"] == "my_postgres"
    assert config["DB_PORT"] == "5432"
    assert validate_env(config, REQUIRED_DB_KEYS) == []
