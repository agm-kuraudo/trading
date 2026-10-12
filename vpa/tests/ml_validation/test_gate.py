"""Unit and property-based tests for the SP-313 threshold-change gate (SP-313).

These are FAST tests: the functions under test in
``vpa.ml_validation.tuning.gate`` are pure (no model, no I/O, no global state),
so none of these carry the ``slow`` marker.

Two comparisons are covered, and they are intentionally different:

- :func:`should_apply_to_config` is the Req 6 apply gate — a ``>=`` comparison
  against ``SP312_ML_STD_PCT`` (3.09pp). Correctness Property 6 pins its
  boundary semantics: ``True`` iff ``candidate - in_effect >= 3.09``.
- :func:`exceeds_margin` is a strict ``>`` comparison used for the per-dimension
  recording margins (Req 3.3 ``+0.1pp``, Req 4.2 ``+0.10pp``).

:func:`record_shooting_star` implements the Req 2.2--2.4 recording-and-selection
logic and the tie-break toward the candidate nearest the current value (2).

# Feature: vpa-threshold-tuning-ml-revalidation, Property 6: Apply-gate threshold and idempotence
"""

from hypothesis import given, settings
from hypothesis.strategies import floats, one_of, sampled_from

from vpa.ml_validation.tuning.classify import SP312_ML_STD_PCT
from vpa.ml_validation.tuning.gate import (
    SHOOTING_STAR_CURRENT_VALUE,
    SelectionOutcome,
    exceeds_margin,
    record_shooting_star,
    should_apply_to_config,
)
from vpa.ml_validation.tuning.scoring_params import ScoringParams

# The current (in-effect) shooting-star value; ties break toward the candidate
# nearest this value (Req 2.3). Mirrors gate.SHOOTING_STAR_CURRENT_VALUE (2.0).
CURRENT = SHOOTING_STAR_CURRENT_VALUE


# --- Unit tests: should_apply_to_config (Req 6 apply gate, >= 3.09) ------


class TestShouldApplyToConfig:
    """Boundary behaviour of the Req 6 apply gate around 3.09pp.

    Deltas are constructed by anchoring on an ``in_effect`` value and adding the
    ``SP312_ML_STD_PCT`` constant (or a tiny offset) so the subtraction lands
    exactly on the inclusive boundary rather than drifting in IEEE-754.
    """

    def test_delta_exactly_at_margin_is_true(self):
        # candidate - in_effect == 3.09 exactly -> True (inclusive >=).
        in_effect = 50.0
        candidate = in_effect + SP312_ML_STD_PCT
        assert should_apply_to_config(candidate, in_effect) is True

    def test_delta_just_below_margin_is_false(self):
        # 3.08 < 3.09 -> False.
        in_effect = 50.0
        candidate = in_effect + (SP312_ML_STD_PCT - 0.01)
        assert should_apply_to_config(candidate, in_effect) is False

    def test_delta_just_above_margin_is_true(self):
        # 3.10 > 3.09 -> True.
        in_effect = 50.0
        candidate = in_effect + (SP312_ML_STD_PCT + 0.01)
        assert should_apply_to_config(candidate, in_effect) is True

    def test_zero_delta_is_false(self):
        assert should_apply_to_config(50.0, 50.0) is False

    def test_negative_delta_is_false(self):
        # A candidate worse than in-effect never clears the gate.
        assert should_apply_to_config(49.0, 50.0) is False

    def test_large_improvement_is_true(self):
        assert should_apply_to_config(60.0, 50.0) is True


# --- Unit tests: exceeds_margin (strict > per-dimension recording) -------


class TestExceedsMargin:
    """Strict ``>`` semantics of the per-dimension recording margins."""

    def test_margin_exactly_met_is_false(self):
        # candidate - baseline == margin exactly -> False (strict >). Anchor on
        # baseline 0.0 so the difference is exactly the margin in IEEE-754
        # (e.g. 50.0 + 0.1 then minus 50.0 drifts off 0.1 and spuriously passes).
        margin = 0.1
        baseline = 0.0
        candidate = margin  # candidate - baseline == margin exactly
        assert exceeds_margin(candidate, baseline, margin) is False

    def test_just_above_margin_is_true(self):
        margin = 0.1
        baseline = 0.0
        candidate = margin + 0.05
        assert exceeds_margin(candidate, baseline, margin) is True

    def test_below_margin_is_false(self):
        margin = 0.1
        baseline = 0.0
        candidate = 0.05
        assert exceeds_margin(candidate, baseline, margin) is False

    def test_zero_margin_requires_strict_increase(self):
        # With a 0.0 margin, equal accuracy does not clear a strict >.
        assert exceeds_margin(50.0, 50.0, 0.0) is False
        assert exceeds_margin(50.01, 50.0, 0.0) is True


# --- Unit tests: record_shooting_star (Req 2.2--2.4) ---------------------


class TestRecordShootingStar:
    """Recording-and-selection behaviour for the shooting-star dimension."""

    def test_no_candidate_clears_margin_retains_current(self):
        # (a) No candidate clears +0.5pp over current -> no change beneficial.
        current_accuracy = 52.0
        candidates = [
            (3.0, 52.3),  # +0.3pp, below the +0.5 margin
            (1.5, 52.4),  # +0.4pp, below the +0.5 margin
            (4.0, 51.0),  # worse than current
        ]
        outcome = record_shooting_star(current_accuracy, candidates)

        assert isinstance(outcome, SelectionOutcome)
        assert outcome.changed is False
        assert outcome.applied_value == CURRENT  # retains current (2)
        assert outcome.prior_value == CURRENT
        assert outcome.justifying_delta_pp is None
        assert outcome.new_accuracy_pct == current_accuracy
        assert "no change beneficial" in outcome.note

    def test_single_candidate_clears_is_selected(self):
        # (b) One candidate clears the +0.5pp margin -> it is applied.
        current_accuracy = 52.0
        candidates = [
            (3.0, 52.3),  # below margin
            (1.5, 53.0),  # +1.0pp, clears the +0.5 margin
        ]
        outcome = record_shooting_star(current_accuracy, candidates)

        assert outcome.changed is True
        assert outcome.applied_value == 1.5
        assert outcome.prior_value == CURRENT
        assert outcome.prior_accuracy_pct == current_accuracy
        assert outcome.new_accuracy_pct == 53.0
        assert outcome.justifying_delta_pp == 53.0 - current_accuracy

    def test_multiple_clear_highest_accuracy_selected(self):
        # (c) Multiple candidates clear -> the highest accuracy wins.
        current_accuracy = 52.0
        candidates = [
            (3.0, 52.8),  # +0.8pp
            (1.5, 53.5),  # +1.5pp  <- highest accuracy
            (4.0, 53.1),  # +1.1pp
        ]
        outcome = record_shooting_star(current_accuracy, candidates)

        assert outcome.changed is True
        assert outcome.applied_value == 1.5
        assert outcome.new_accuracy_pct == 53.5
        assert outcome.justifying_delta_pp == 53.5 - current_accuracy

    def test_exact_accuracy_tie_breaks_toward_nearest_current(self):
        # (d) Exact accuracy tie -> candidate nearest the current value (2) wins.
        current_accuracy = 52.0
        candidates = [
            (5.0, 53.0),  # |5 - 2| = 3
            (3.0, 53.0),  # |3 - 2| = 1  <- nearest to current (2)
            (6.0, 53.0),  # |6 - 2| = 4
        ]
        outcome = record_shooting_star(current_accuracy, candidates)

        assert outcome.changed is True
        assert outcome.applied_value == 3.0  # nearest to current wins the tie
        assert outcome.new_accuracy_pct == 53.0


# --- Property 6: Apply-gate threshold and idempotence --------------------

# Oversample the exact 3.09 boundary (and small offsets around it) so Hypothesis
# routinely exercises the inclusive ``>=`` comparison, alongside the real line.
_boundary_accuracies = sampled_from(
    [
        0.0,
        50.0,
        50.0 + SP312_ML_STD_PCT,  # delta == 3.09 exactly when in_effect == 50.0
        50.0 + SP312_ML_STD_PCT - 0.01,
        50.0 + SP312_ML_STD_PCT + 0.01,
        SP312_ML_STD_PCT,
        100.0,
    ]
)
_accuracy_floats = one_of(
    floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
    _boundary_accuracies,
)


@settings(max_examples=300)
@given(candidate_pct=_accuracy_floats, in_effect_pct=_accuracy_floats)
def test_property6_apply_gate_threshold(candidate_pct: float, in_effect_pct: float) -> None:
    """Property 6: the apply gate is True iff the delta reaches 3.09pp.

    For any pair ``(candidate_pct, in_effect_pct)``,
    ``should_apply_to_config`` SHALL equal the arithmetic predicate
    ``(candidate_pct - in_effect_pct) >= SP312_ML_STD_PCT`` exactly, including at
    the inclusive boundary.

    **Validates: Requirements 6.1, 6.2; Property 6**
    """
    result = should_apply_to_config(candidate_pct, in_effect_pct)
    expected = (candidate_pct - in_effect_pct) >= SP312_ML_STD_PCT
    assert result is expected, (
        f"candidate={candidate_pct}, in_effect={in_effect_pct} "
        f"(delta={candidate_pct - in_effect_pct}): got {result}, expected {expected}"
    )


@settings(max_examples=300)
@given(in_effect_pct=_accuracy_floats, delta_pp=floats(min_value=-50.0, max_value=50.0, allow_nan=False))
def test_property6_apply_gate_boundary_via_delta(in_effect_pct: float, delta_pp: float) -> None:
    """Property 6: boundary consistency when the delta is constructed directly.

    Building the candidate as ``in_effect + delta`` lets Hypothesis probe deltas
    on both sides of 3.09; the gate's answer SHALL agree with ``delta >= 3.09``
    computed on the same reconstructed difference (avoiding a spurious mismatch
    from IEEE-754 rounding of the sum).

    **Validates: Requirements 6.1, 6.2; Property 6**
    """
    candidate_pct = in_effect_pct + delta_pp
    result = should_apply_to_config(candidate_pct, in_effect_pct)
    # Compare against the gate's own arithmetic to stay faithful to its contract.
    expected = (candidate_pct - in_effect_pct) >= SP312_ML_STD_PCT
    assert result is expected


@settings(max_examples=300)
@given(
    current_accuracy=floats(min_value=0.0, max_value=100.0, allow_nan=False),
    candidate_value=floats(min_value=1.0, max_value=10.0, allow_nan=False),
    candidate_accuracy=floats(min_value=0.0, max_value=100.0, allow_nan=False),
)
def test_property6_non_clearing_candidate_is_noop(
    current_accuracy: float, candidate_value: float, candidate_accuracy: float
) -> None:
    """Property 6: a non-beneficial candidate leaves the config unchanged (no-op).

    When a single candidate does not clear the +0.5pp recording margin,
    ``record_shooting_star`` SHALL report ``changed=False`` and
    ``applied_value == prior_value``. Consequently, building a ``ScoringParams``
    from the applied value yields an object equal (by dataclass equality) to the
    prior ``ScoringParams`` — the change is a no-op.

    **Validates: Requirements 6.1, 6.2, 6.3; Property 6**
    """
    # Force a non-clearing candidate: accuracy no better than current, so the
    # +0.5pp recording margin cannot be met regardless of the candidate value.
    non_clearing_accuracy = min(candidate_accuracy, current_accuracy)
    outcome = record_shooting_star(current_accuracy, [(candidate_value, non_clearing_accuracy)])

    assert outcome.changed is False
    assert outcome.applied_value == outcome.prior_value == CURRENT
    assert outcome.justifying_delta_pp is None

    # Idempotence via dataclass equality: a ScoringParams built from the applied
    # (retained) value equals one built from the prior value.
    prior_params = ScoringParams(shooting_star_spread_mult=outcome.prior_value)
    applied_params = ScoringParams(shooting_star_spread_mult=outcome.applied_value)
    assert applied_params == prior_params
    assert applied_params == ScoringParams.default()
