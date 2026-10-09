---
inclusion: always
---

# Running tests

The default `pytest` run is the FAST path — the `slow` marker (ml_validation
tests that train real XGBoost models or run the full pipeline) is deselected
via `addopts = "-m 'not slow'"` in `pyproject.toml`. Use the default while
iterating:

    pytest                 # fast: ~67s, slow tests skipped

Run the FULL suite explicitly before a final push, before opening/merging a
PR, or before marking a Jira task Done:

    pytest -m ""           # everything (529 tests)
    pytest -m slow         # only the slow tests

If a CI pipeline is ever added, it MUST run `pytest -m ""` so the slow ML
tests are not silently skipped. Bare `pytest` in CI would skip them.

# Linting and formatting (ruff)

Run ruff lint AND format checks BEFORE the final `pytest -m ""` run and BEFORE
any push, PR open/merge, or marking a Jira task Done. The repo ships a ruff CI
workflow (`.github/workflows/ruff.yml`), so unformatted or lint-failing code
will fail CI — catch it locally first.

    ruff check .           # lint
    ruff format --check .  # formatting (does not modify files)

Fix anything they flag before proceeding:

    ruff check --fix .     # auto-fix lint issues where possible
    ruff format .          # apply formatting

Recommended pre-push / pre-PR order:

    1. ruff check .  &&  ruff format --check .   # lint + format clean
    2. pytest -m ""                              # full suite green
    3. push / open PR / mark Done

A common trip-up: files written by tooling or scripts (not an editor) can lose
the trailing newline or drift from ruff's style — always run the format check
after such writes, not just the tests.
