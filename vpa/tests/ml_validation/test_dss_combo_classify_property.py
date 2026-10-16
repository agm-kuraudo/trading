"""Property test for DSS/combo classification in the daily signal generator (SP-359).

FAST tests: ``classify_last_row`` is a pure function over an in-memory DataFrame
(no model training, no I/O), so nothing here carries the ``slow`` marker.

# Feature: dss-daily-signal-classification, Property 5: A DSS or combo type is
# classified exactly when its final-row column equals 1
"""

import math

import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from vpa.ml_validation.daily_signal import classify_last_row
from vpa.ml_validation.signal_analysis import _COMBO_COLUMN_TO_TYPE, SignalType

# The DSS crossover columns plus the ten combo columns, each mapped to the
# SignalType classify_last_row should add when the column's final-row value
# coerces to the number 1. This is the full set of types Property 5 governs.
_DSS_COLUMN_TO_TYPE: dict[str, SignalType] = {
    "dss_bullish_cross": SignalType.DSS_BULLISH,
    "dss_bearish_cross": SignalType.DSS_BEARISH,
}
_TARGET_COLUMN_TO_TYPE: dict[str, SignalType] = {
    **_DSS_COLUMN_TO_TYPE,
    **_COMBO_COLUMN_TO_TYPE,
}

# Every DSS/combo type this property governs, so we can check inclusion AND
# exclusion of the specific type under test without false positives from others.
_ALL_TARGET_TYPES: set[SignalType] = set(_TARGET_COLUMN_TO_TYPE.values())


def _coerces_to_one(value: object) -> bool:
    """Mirror classify_last_row's guard: non-NaN numeric that equals 1.

    Returns True iff ``value`` can be coerced to a finite float equal to 1.0.
    NaN, non-numeric strings and None all yield False; this is the reference
    oracle for whether the type should be classified.
    """
    if value is None:
        return False
    try:
        coerced = float(value)
    except (TypeError, ValueError):
        return False
    if math.isnan(coerced):
        return False
    return coerced == 1


# Final-row cell values spanning NaN / ints / floats / non-numeric strings so
# every branch of the coercion guard is exercised. ``None`` models an explicit
# missing value in a present column.
_cell_values = st.one_of(
    st.just(float("nan")),
    st.just(None),
    st.integers(min_value=-5, max_value=5),
    st.floats(min_value=-5.0, max_value=5.0, allow_nan=False, allow_infinity=False),
    st.sampled_from(["", "1", "1.0", "one", "yes", "NaN", "true"]),
    # Oversample the exact match so the "included" branch is hit often.
    st.sampled_from([1, 1.0]),
)


@settings(max_examples=300)
@given(
    target_column=st.sampled_from(sorted(_TARGET_COLUMN_TO_TYPE)),
    value=_cell_values,
    column_present=st.booleans(),
    n_rows=st.integers(min_value=1, max_value=4),
)
def test_property5_classified_iff_final_row_column_equals_one(
    target_column: str,
    value: object,
    column_present: bool,
    n_rows: int,
) -> None:
    """Property 5: a DSS/combo type is classified exactly when its final-row
    column is present and that final-row value coerces to the number 1.

    For any feature DataFrame, ``classify_last_row`` includes a given DSS
    (``DSS_BULLISH`` / ``DSS_BEARISH``) or combo ``SignalType`` iff that type's
    column is present AND the final row's value in that column coerces to 1.
    An absent column, or a final-row value that is NaN, non-numeric, or any
    number other than 1, excludes the type and raises no error.

    **Validates: Requirements 3.1, 3.2, 3.5, 3.6, 4.1, 4.4; Property 5**
    """
    target_type = _TARGET_COLUMN_TO_TYPE[target_column]

    # Build a minimal feature frame. Earlier rows carry a benign 0 so that the
    # *final* row is the only one that can trigger classification; this isolates
    # the "final-row" semantics of the property. The target column's final value
    # is the generated cell under test, and is only added when column_present.
    data: dict[str, list[object]] = {}
    if column_present:
        column_values: list[object] = [0] * (n_rows - 1)
        column_values.append(value)
        data[target_column] = column_values

    df = pd.DataFrame(data, index=range(n_rows))

    # Must never raise, regardless of the cell value or column presence.
    result = classify_last_row(df)

    should_be_included = column_present and _coerces_to_one(value)

    if should_be_included:
        assert target_type in result, (
            f"{target_type} should be classified when {target_column!r} " f"final-row value {value!r} coerces to 1"
        )
    else:
        assert target_type not in result, (
            f"{target_type} should NOT be classified when column_present="
            f"{column_present} and final-row value {value!r} does not coerce to 1"
        )

    # No other DSS/combo type should appear: only the single target column was
    # ever placed in the frame, so no sibling type can be spuriously classified.
    spurious = (result & _ALL_TARGET_TYPES) - ({target_type} if should_be_included else set())
    assert not spurious, f"Unexpected DSS/combo types classified: {spurious}"
