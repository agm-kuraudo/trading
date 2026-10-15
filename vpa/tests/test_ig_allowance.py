"""Unit + property tests for IG allowance planning (SP-379, Tasks 4.2, 4.3).

Pure-logic tests for ``vpa.market_data.ig_ingest.plan_backfill`` and the
``AllowanceState`` dataclass. No network and no IG transport are touched (the
``no_ig_network`` guard is applied at module scope for consistency with the other
IG test modules, though these functions never reach the transport anyway).

Covers:
- Task 4.2 - ``plan_backfill`` budget maths: ample / tight / at-or-below-floor
  allowance, batch-count rounding, and ``batch_points == 0`` not raising.
- Task 4.3 / Property 5 - allowance never over-spent: for arbitrary inputs,
  ``0 <= this_run <= target_points`` and ``this_run <= max(0, remaining - SAFETY_FLOOR)``.
"""

from __future__ import annotations

from math import ceil

import pytest
from hypothesis import given
from hypothesis import strategies as st

from vpa.market_data.ig_ingest import (
    SAFETY_FLOOR,
    WEEKLY_ALLOWANCE,
    AllowanceState,
    plan_backfill,
)

pytestmark = pytest.mark.usefixtures("no_ig_network")


def _state(remaining: int, expiry_s: int = 604_800) -> AllowanceState:
    """Build an ``AllowanceState`` with the given remaining allowance."""
    return AllowanceState(remaining=remaining, expiry_s=expiry_s)


# ---------------------------------------------------------------------------
# Task 4.2 - budget maths
# ---------------------------------------------------------------------------


def test_ample_allowance_runs_full_target_with_no_deferral():
    # remaining - SAFETY_FLOOR comfortably exceeds the target.
    plan = plan_backfill(target_points=500, batch_points=100, state=_state(WEEKLY_ALLOWANCE))

    assert plan["this_run"] == 500
    assert plan["deferred"] == 0
    assert plan["batches"] == 5  # ceil(500 / 100)


def test_tight_allowance_clamps_this_run_to_budget():
    # Budget = remaining - SAFETY_FLOOR = 700 - 500 = 200; target exceeds it.
    plan = plan_backfill(target_points=1_000, batch_points=100, state=_state(700))

    assert plan["this_run"] == 200
    assert plan["deferred"] == 800  # 1000 - 200
    assert plan["batches"] == 2  # ceil(200 / 100)


def test_remaining_at_floor_defers_everything():
    plan = plan_backfill(target_points=1_000, batch_points=100, state=_state(SAFETY_FLOOR))

    assert plan["this_run"] == 0
    assert plan["deferred"] == 1_000
    assert plan["batches"] == 0


def test_remaining_below_floor_defers_everything():
    plan = plan_backfill(target_points=1_000, batch_points=100, state=_state(SAFETY_FLOOR - 1))

    assert plan["this_run"] == 0
    assert plan["deferred"] == 1_000
    assert plan["batches"] == 0


def test_batch_count_rounds_up():
    # 250 points over batches of 100 -> ceil = 3.
    plan = plan_backfill(target_points=250, batch_points=100, state=_state(WEEKLY_ALLOWANCE))

    assert plan["this_run"] == 250
    assert plan["batches"] == 3


def test_zero_batch_points_does_not_raise():
    # Guard against a zero-division: batch_points <= 0 collapses to a single batch.
    plan = plan_backfill(target_points=300, batch_points=0, state=_state(WEEKLY_ALLOWANCE))

    assert plan["this_run"] == 300
    assert plan["batches"] == 1
    # And zero batches when there is nothing to run.
    none_plan = plan_backfill(target_points=0, batch_points=0, state=_state(WEEKLY_ALLOWANCE))
    assert none_plan["this_run"] == 0
    assert none_plan["batches"] == 0


# ---------------------------------------------------------------------------
# Task 4.3 / Property 5 - allowance never over-spent
# ---------------------------------------------------------------------------


@given(
    target_points=st.integers(min_value=0, max_value=200_000),
    batch_points=st.integers(min_value=1, max_value=10_000),
    remaining=st.integers(min_value=0, max_value=200_000),
)
def test_property_allowance_never_over_spent(target_points, batch_points, remaining):
    """Property 5: a run never exceeds the target nor drives remaining below the floor.

    Validates: Requirements 3.1, 3.2, 3.3
    """
    plan = plan_backfill(target_points, batch_points, _state(remaining))
    this_run = plan["this_run"]
    budget = max(0, remaining - SAFETY_FLOOR)

    assert 0 <= this_run <= target_points
    assert this_run <= budget
    assert plan["deferred"] == target_points - this_run
    assert plan["batches"] == ceil(this_run / batch_points)
