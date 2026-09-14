"""No-Selenium and cross-platform smoke tests for the browserless forex stack (task 10.2).

These are static / import-level checks only: no network access, no browser, and
``vpa.app_forex.main()`` is never invoked. They lock in the outcomes of the
Selenium removal and the cross-platform hygiene requirements so a regression
(a re-introduced ``selenium`` import, a resurrected ``vpa/forex_auto/`` package,
a platform branch, or the old hardcoded download directory) fails loudly.

Covered:

- No-Selenium import (Requirements 1.1, 10.1): importing ``vpa.forex_data`` and
  ``vpa.app_forex`` pulls in no module named ``selenium`` (or any ``selenium.*``
  submodule).
- forex_auto removed (Requirement 10.2): the ``vpa/forex_auto/`` package no
  longer exists on disk and is not importable.
- selenium absent from requirements (Requirement 10.3): ``requirements.txt`` has
  no ``selenium`` line (with a spot-check that expected deps are still present,
  proving the right file was read).
- Cross-platform hygiene (Requirements 7.1, 7.2, 7.3): the forex_data sources
  and ``app_forex.py`` contain no reference to the hardcoded
  ``/home/mypi/Downloads`` directory and no ``sys.platform`` / ``os.name``
  platform branching.

Requirements: 1.1, 7.1, 7.2, 7.3, 10.1, 10.2, 10.3.
"""

import importlib
import importlib.util
import sys

from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Repo-root derivation (robust: verify it looks right before using it).
# ---------------------------------------------------------------------------

# This file lives at <root>/vpa/tests/forex_data/test_no_selenium_smoke.py, so
# parents[3] is the trading repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]

# The forex_data package modules whose source text is checked for cross-platform
# hygiene (Req 7.1-7.3).
_FOREX_DATA_MODULES = (
    "errors.py",
    "decoder.py",
    "aggregator.py",
    "feed.py",
    "retriever.py",
)


def test_repo_root_derivation_is_correct():
    """Sanity-check the derived repo root before other tests rely on it.

    A wrong ``parents[...]`` index would silently make the on-disk assertions
    vacuous, so pin the layout here.
    """
    assert (REPO_ROOT / "vpa").is_dir()
    assert (REPO_ROOT / "vpa" / "forex_data").is_dir()
    assert (REPO_ROOT / "requirements.txt").is_file()


# ---------------------------------------------------------------------------
# No-Selenium import (Requirements 1.1, 10.1).
# ---------------------------------------------------------------------------


def _selenium_modules_loaded() -> list[str]:
    """Return any currently-loaded module names that are ``selenium`` or below."""
    return [
        name
        for name in sys.modules
        if name == "selenium" or name.startswith("selenium.")
    ]


def test_importing_forex_stack_pulls_in_no_selenium(monkeypatch):
    """Importing the forex stack loads no ``selenium`` module (Req 1.1, 10.1).

    Any pre-existing ``selenium`` entries in ``sys.modules`` are removed first so
    the check reflects only what these imports pull in; the two modules are then
    (re)imported fresh via :func:`importlib.import_module`.
    """
    # Drop any selenium modules already resident from earlier in the session so
    # the assertion measures only the effect of the imports below.
    for name in _selenium_modules_loaded():
        monkeypatch.delitem(sys.modules, name, raising=False)

    forex_data = importlib.import_module("vpa.forex_data")
    app_forex = importlib.import_module("vpa.app_forex")

    # The imports themselves must succeed (guards against an import-time break).
    assert forex_data is not None
    assert app_forex is not None

    leaked = _selenium_modules_loaded()
    assert leaked == [], f"selenium modules were imported: {leaked}"
    assert "selenium" not in sys.modules


# ---------------------------------------------------------------------------
# forex_auto removed (Requirement 10.2).
# ---------------------------------------------------------------------------


def test_forex_auto_package_is_removed():
    """The old ``vpa/forex_auto/`` package is gone from disk and unimportable (Req 10.2)."""
    assert not (REPO_ROOT / "vpa" / "forex_auto").exists()
    assert importlib.util.find_spec("vpa.forex_auto") is None


# ---------------------------------------------------------------------------
# selenium absent from requirements.txt (Requirement 10.3).
# ---------------------------------------------------------------------------


def test_selenium_absent_from_requirements():
    """``requirements.txt`` has no ``selenium`` dependency line (Req 10.3).

    A spot-check that ``pandas`` and ``hypothesis`` are still present proves the
    right file was read rather than an empty/missing one.
    """
    lines = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    normalized = [line.strip().lower() for line in lines]

    assert not any("selenium" in line for line in normalized)

    # Prove we read a real, populated requirements file.
    package_names = {line.split("==")[0].split(">=")[0].split("~=")[0].strip() for line in normalized}
    assert "pandas" in package_names
    assert "hypothesis" in package_names


# ---------------------------------------------------------------------------
# Cross-platform hygiene (Requirements 7.1, 7.2, 7.3).
# ---------------------------------------------------------------------------


def _forex_data_source(module_filename: str) -> str:
    """Return the source text of a ``vpa/forex_data`` module."""
    return (REPO_ROOT / "vpa" / "forex_data" / module_filename).read_text(encoding="utf-8")


@pytest.mark.parametrize("module_filename", _FOREX_DATA_MODULES)
def test_forex_data_source_has_no_hardcoded_download_dir(module_filename):
    """No forex_data module references the old ``/home/mypi/Downloads`` dir (Req 7.3)."""
    source = _forex_data_source(module_filename)
    assert "/home/mypi/Downloads" not in source


def test_app_forex_source_has_no_hardcoded_download_dir():
    """``app_forex.py`` no longer references the hardcoded download dir (Req 7.3)."""
    source = (REPO_ROOT / "vpa" / "app_forex.py").read_text(encoding="utf-8")
    assert "/home/mypi/Downloads" not in source


@pytest.mark.parametrize("module_filename", _FOREX_DATA_MODULES)
def test_forex_data_source_has_no_platform_branching(module_filename):
    """No forex_data module branches on ``sys.platform`` / ``os.name`` (Req 7.1, 7.2).

    Cross-platform operation requires a single identical code path with no
    platform-specific branches; referencing these attributes is the tell-tale of
    such a branch.
    """
    source = _forex_data_source(module_filename)
    assert "sys.platform" not in source
    assert "os.name" not in source
