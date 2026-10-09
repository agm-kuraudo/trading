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
