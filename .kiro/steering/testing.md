---
inclusion: always
---

# When to run tests and linting (read this first)

Do NOT run pytest or ruff after every individual edit, and do NOT re-run the
full suite repeatedly during a task. Running them per-change wastes time.

The policy is:

- **While iterating / mid-task:** do not run the suite at all. At most, run the
  narrow set of tests directly covering the code you just changed
  (e.g. `pytest tests/test_thing.py::test_case`) when you need to confirm a
  specific fix. Prefer reasoning over re-running.
- **Once, at the end of the task** (the single verification gate — see
  "Recommended pre-push / pre-PR order" below): run ruff, then the full suite.
  This is also the gate before any push, PR open/merge, or marking a Jira task
  Done. Run it one time, not after each sub-step.

If a task is split into spec tasks, treat the final verification as its own
step at the end of the whole feature, not a per-task action — unless a given
task explicitly asks for verification.

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

Ruff runs at the SAME end-of-task gate as the full test suite — NOT after each
edit or each file write. Run the lint and format checks once, as the first step
of the final verification gate, immediately before the full `pytest -m ""` run
and before any push, PR open/merge, or marking a Jira task Done. The repo ships
a ruff CI workflow (`.github/workflows/ruff.yml`), so unformatted or
lint-failing code will fail CI — catch it locally at that final gate.

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
the trailing newline or drift from ruff's style. You do NOT need to run the
format check after each such write — but be aware of this when the final gate's
`ruff format --check .` flags files you generated, and fix them there.
