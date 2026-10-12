"""Unit and property-based tests for ``ScoringParams.validate`` (SP-313).

These are FAST tests: ``ScoringParams`` and its ``validate`` method are pure (no
model, no I/O, no global state), so none of these carry the ``slow`` marker.

``validate`` enforces the candidate range rules from the requirements:

- Req 2.5: the shooting-star multipliers must each be a positive real number
  ``>= 1``.
- Req 3.1: ``acc_dist_volume_percentile`` must be an integer in ``1..99``.
- Req 3.2: ``acc_dist_test_count`` must be an integer ``>= 1``.
- Req 5.1: each ``vol_backed_mult_pN`` must be a non-negative real number.

A ``bool`` is never accepted where an integer field is required (``bool`` is an
``int`` subclass in Python but is meaningless as a percentile/count), and ``NaN``
is never a valid real number.

``ScoringParams`` is frozen but does not coerce types, so the tests construct
instances with arbitrary values (bools / floats / ints) to probe the type and
range checks directly.

# Feature: vpa-threshold-tuning-ml-revalidation, Property 5: Candidate validation biconditional
"""

import math

from hypothesis import given, settings
from hypothesis import strategies as st

from vpa.ml_validation.tuning.scoring_params import ScoringParams

NAN = float("nan")


# --- Unit tests: default / canonical configuration -----------------------


class TestDefaultIsValid:
    """The canonical current configuration must validate cleanly."""

    def test_default_classmethod_is_valid(self):
        assert ScoringParams.default().validate() == []

    def test_bare_constructor_is_valid(self):
        assert ScoringParams().validate() == []

    def test_default_equals_bare_constructor(self):
        assert ScoringParams.default() == ScoringParams()


# --- Unit tests: shooting-star multipliers (Req 2.5) ---------------------


class TestShootingStarSpreadMult:
    """``shooting_star_spread_mult``: positive real number >= 1."""

    def test_exactly_one_accepted(self):
        assert ScoringParams(shooting_star_spread_mult=1.0).validate() == []

    def test_above_one_accepted(self):
        assert ScoringParams(shooting_star_spread_mult=3.5).validate() == []

    def test_below_one_rejected(self):
        assert ScoringParams(shooting_star_spread_mult=0.5).validate() != []

    def test_zero_non_positive_rejected(self):
        assert ScoringParams(shooting_star_spread_mult=0.0).validate() != []

    def test_negative_rejected(self):
        assert ScoringParams(shooting_star_spread_mult=-2.0).validate() != []

    def test_bool_rejected(self):
        # True == 1 numerically, but a bool is not a valid multiplier.
        assert ScoringParams(shooting_star_spread_mult=True).validate() != []

    def test_nan_rejected(self):
        assert ScoringParams(shooting_star_spread_mult=NAN).validate() != []


class TestShootingStarLowerWickMult:
    """``shooting_star_lower_wick_mult``: positive real number >= 1."""

    def test_exactly_one_accepted(self):
        assert ScoringParams(shooting_star_lower_wick_mult=1.0).validate() == []

    def test_above_one_accepted(self):
        assert ScoringParams(shooting_star_lower_wick_mult=4.0).validate() == []

    def test_below_one_rejected(self):
        assert ScoringParams(shooting_star_lower_wick_mult=0.9).validate() != []

    def test_zero_non_positive_rejected(self):
        assert ScoringParams(shooting_star_lower_wick_mult=0.0).validate() != []

    def test_bool_rejected(self):
        assert ScoringParams(shooting_star_lower_wick_mult=True).validate() != []

    def test_nan_rejected(self):
        assert ScoringParams(shooting_star_lower_wick_mult=NAN).validate() != []


# --- Unit tests: acc_dist_volume_percentile (Req 3.1) --------------------


class TestAccDistVolumePercentile:
    """``acc_dist_volume_percentile``: integer in 1..99 inclusive."""

    def test_lower_boundary_one_accepted(self):
        assert ScoringParams(acc_dist_volume_percentile=1).validate() == []

    def test_upper_boundary_ninety_nine_accepted(self):
        assert ScoringParams(acc_dist_volume_percentile=99).validate() == []

    def test_mid_range_accepted(self):
        assert ScoringParams(acc_dist_volume_percentile=65).validate() == []

    def test_zero_rejected(self):
        assert ScoringParams(acc_dist_volume_percentile=0).validate() != []

    def test_hundred_rejected(self):
        assert ScoringParams(acc_dist_volume_percentile=100).validate() != []

    def test_negative_rejected(self):
        assert ScoringParams(acc_dist_volume_percentile=-5).validate() != []

    def test_non_integer_float_rejected(self):
        # A float like 65.5 is not an integer percentile.
        assert ScoringParams(acc_dist_volume_percentile=65.5).validate() != []

    def test_integer_valued_float_rejected(self):
        # Even 65.0 is a float, not a strict int -> rejected.
        assert ScoringParams(acc_dist_volume_percentile=65.0).validate() != []

    def test_bool_rejected(self):
        # True == 1 numerically and 1 is in range, but a bool is not an int here.
        assert ScoringParams(acc_dist_volume_percentile=True).validate() != []


# --- Unit tests: acc_dist_test_count (Req 3.2) ---------------------------


class TestAccDistTestCount:
    """``acc_dist_test_count``: integer >= 1."""

    def test_one_accepted(self):
        assert ScoringParams(acc_dist_test_count=1).validate() == []

    def test_large_accepted(self):
        assert ScoringParams(acc_dist_test_count=10).validate() == []

    def test_zero_rejected(self):
        assert ScoringParams(acc_dist_test_count=0).validate() != []

    def test_negative_rejected(self):
        assert ScoringParams(acc_dist_test_count=-1).validate() != []

    def test_non_integer_float_rejected(self):
        assert ScoringParams(acc_dist_test_count=3.5).validate() != []

    def test_integer_valued_float_rejected(self):
        assert ScoringParams(acc_dist_test_count=3.0).validate() != []

    def test_bool_rejected(self):
        assert ScoringParams(acc_dist_test_count=True).validate() != []


# --- Unit tests: vol_backed multipliers (Req 5.1) ------------------------


class TestVolBackedMultipliers:
    """``vol_backed_mult_p1/p2/p3``: non-negative real numbers (0.0 allowed)."""

    def test_zero_accepted_p1(self):
        assert ScoringParams(vol_backed_mult_p1=0.0).validate() == []

    def test_zero_accepted_p2(self):
        assert ScoringParams(vol_backed_mult_p2=0.0).validate() == []

    def test_zero_accepted_p3(self):
        assert ScoringParams(vol_backed_mult_p3=0.0).validate() == []

    def test_positive_accepted(self):
        assert ScoringParams(vol_backed_mult_p1=1.0, vol_backed_mult_p2=2.5).validate() == []

    def test_negative_rejected_p1(self):
        assert ScoringParams(vol_backed_mult_p1=-0.1).validate() != []

    def test_negative_rejected_p2(self):
        assert ScoringParams(vol_backed_mult_p2=-1.0).validate() != []

    def test_negative_rejected_p3(self):
        assert ScoringParams(vol_backed_mult_p3=-5.0).validate() != []

    def test_nan_rejected(self):
        assert ScoringParams(vol_backed_mult_p1=NAN).validate() != []


# --- Property 5: Candidate validation biconditional ----------------------


def _is_real_number(value: object) -> bool:
    """Independent oracle: True for a non-bool real int/float that is not NaN.

    Deliberately re-implemented here (not imported from the module under test)
    so the property compares ``validate`` against an independent definition of
    the documented rules.
    """
    if isinstance(value, bool):
        return False
    if not isinstance(value, int | float):
        return False
    return not math.isnan(value) if isinstance(value, float) else True


def _is_strict_int(value: object) -> bool:
    """Independent oracle: True only for a genuine int (bool excluded)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _oracle_out_of_range(params: ScoringParams) -> bool:
    """Independent predicate mirroring the documented validation rules.

    Returns True iff at least one field is out of range. Built without calling
    ``validate`` so the biconditional property has an independent reference.
    """
    # Req 2.5 — shooting-star multipliers: real number and >= 1.
    for name in ("shooting_star_spread_mult", "shooting_star_lower_wick_mult"):
        value = getattr(params, name)
        if not _is_real_number(value) or value < 1:
            return True

    # Req 3.1 — acc_dist_volume_percentile: strict int in 1..99 inclusive.
    percentile = params.acc_dist_volume_percentile
    if not _is_strict_int(percentile) or not (1 <= percentile <= 99):
        return True

    # Req 3.2 — acc_dist_test_count: strict int >= 1.
    test_count = params.acc_dist_test_count
    if not _is_strict_int(test_count) or test_count < 1:
        return True

    # Req 5.1 — vol_backed multipliers: real number and >= 0.
    for name in ("vol_backed_mult_p1", "vol_backed_mult_p2", "vol_backed_mult_p3"):
        value = getattr(params, name)
        if not _is_real_number(value) or value < 0:
            return True

    return False


# Strategies that intentionally span valid and invalid inputs for each field.
# Mult fields: floats on both sides of 1, plus bools and NaN.
_mult_values = st.one_of(
    st.floats(min_value=-5.0, max_value=10.0, allow_nan=False, allow_infinity=False),
    st.sampled_from([1.0, 0.0, 0.999, NAN, True, False]),
)
# Percentile / test-count: a mix of ints (in and out of range), bools, and
# non-int floats so both the type check and the range check are exercised.
_int_field_values = st.one_of(
    st.integers(min_value=-5, max_value=105),
    st.floats(min_value=-5.0, max_value=105.0, allow_nan=False, allow_infinity=False),
    st.sampled_from([0, 1, 99, 100, 65.5, 65.0, True, False]),
)
# vol_backed: negative / zero / positive floats, plus bools and NaN.
_vol_values = st.one_of(
    st.floats(min_value=-5.0, max_value=10.0, allow_nan=False, allow_infinity=False),
    st.sampled_from([0.0, -0.0, NAN, True, False]),
)


@settings(max_examples=500)
@given(
    spread_mult=_mult_values,
    lower_wick_mult=_mult_values,
    percentile=_int_field_values,
    test_count=_int_field_values,
    vol_p1=_vol_values,
    vol_p2=_vol_values,
    vol_p3=_vol_values,
)
def test_property5_validation_biconditional(
    spread_mult,
    lower_wick_mult,
    percentile,
    test_count,
    vol_p1,
    vol_p2,
    vol_p3,
) -> None:
    """Property 5: ``validate`` is non-empty iff a field is out of range.

    For any ``ScoringParams`` built from a mix of in-range and out-of-range
    field values, ``validate()`` returns a non-empty rejection list **if and
    only if** the independent oracle reports at least one out-of-range field.

    **Validates: Requirements 2.5, 3.1, 3.2, 5.1; Property 5**
    """
    params = ScoringParams(
        shooting_star_spread_mult=spread_mult,
        shooting_star_lower_wick_mult=lower_wick_mult,
        acc_dist_volume_percentile=percentile,
        acc_dist_test_count=test_count,
        vol_backed_mult_p1=vol_p1,
        vol_backed_mult_p2=vol_p2,
        vol_backed_mult_p3=vol_p3,
    )

    has_rejection = len(params.validate()) > 0
    expected_out_of_range = _oracle_out_of_range(params)

    assert (
        has_rejection is expected_out_of_range
    ), f"validate() non-empty={has_rejection} but oracle out-of-range={expected_out_of_range} for {params!r}"
