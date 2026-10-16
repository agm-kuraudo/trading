"""Property and example tests for DSS/combo classification parity (SP-359).

Covers spec tasks 4.3-4.5:

- **Property 6** (4.3): the combo ``SignalType`` set from ``classify_last_row``
  equals the set whose ``classify_signals`` matched-index list contains the
  final row's index.
- **Property 7** (4.4): adding DSS and combo columns does not disturb the core
  or price-vs-SMA classifications, and DSS membership is unaffected by combo
  columns.
- Example tests (4.5) for the DSS/combo classification edge cases (Req 7.1-7.6,
  3.7, 4.5).

These are FAST tests: ``classify_last_row`` and ``classify_signals`` are pure
functions over an in-memory DataFrame (no model, no I/O), so none carry the
``slow`` marker.

# Feature: dss-daily-signal-classification, Properties 6 and 7
"""

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vpa.ml_validation.daily_signal import classify_last_row
from vpa.ml_validation.signal_analysis import (
    _COMBO_COLUMN_TO_TYPE,
    SignalConditionalAnalyzer,
    SignalType,
)

# The two DSS crossover columns and the ten combo columns, each keyed to the
# SignalType that classify_last_row must add when the final-row value is 1.
_DSS_COLUMN_TO_TYPE: dict[str, SignalType] = {
    "dss_bullish_cross": SignalType.DSS_BULLISH,
    "dss_bearish_cross": SignalType.DSS_BEARISH,
}
_COMBO_TYPES: set[SignalType] = set(_COMBO_COLUMN_TO_TYPE.values())

# Columns classify_signals requires to be present (it reads them unconditionally).
_CORE_COLUMNS = ["composite_score", "acc_dist_flag", "acc_dist_type", "acc_dist_score"]


def _analyzer() -> SignalConditionalAnalyzer:
    # output_dir is unused by classify_signals; any path is fine.
    return SignalConditionalAnalyzer(output_dir=".")


def _base_frame(n_rows: int) -> pd.DataFrame:
    """A benign feature frame with the core columns present and non-triggering.

    composite_score 0, acc_dist flags 0 so no core signal fires; this isolates
    the DSS/combo columns the individual tests add.
    """
    return pd.DataFrame(
        {
            "composite_score": [0.0] * n_rows,
            "acc_dist_flag": [0.0] * n_rows,
            "acc_dist_type": [0.0] * n_rows,
            "acc_dist_score": [0.0] * n_rows,
        },
        index=range(n_rows),
    )


# ---------------------------------------------------------------------------
# Property 6 (task 4.3): daily combo classification agrees with classify_signals
# ---------------------------------------------------------------------------


class TestProperty6ComboAgreesWithClassifySignals:
    # Feature: dss-daily-signal-classification, Property 6: Daily combo classification agrees with classify_signals
    # Validates: Requirement 4.2
    @settings(max_examples=200, deadline=None)
    @given(
        combo_values=st.lists(
            st.lists(st.sampled_from([0, 1]), min_size=10, max_size=10),
            min_size=1,
            max_size=5,
        )
    )
    def test_combo_set_matches_final_row_membership(self, combo_values):
        n_rows = len(combo_values)
        df = _base_frame(n_rows)
        combo_cols = list(_COMBO_COLUMN_TO_TYPE.keys())
        for col_idx, col in enumerate(combo_cols):
            df[col] = [row[col_idx] for row in combo_values]

        # Daily classifier: combo types on the final row.
        daily = classify_last_row(df) & _COMBO_TYPES

        # Oracle: classify_signals matched-index lists that include the final row.
        matched = _analyzer().classify_signals(df)
        final_idx = df.index[-1]
        oracle = {combo_type for combo_type in _COMBO_TYPES if final_idx in matched.get(combo_type, [])}

        assert daily == oracle


# ---------------------------------------------------------------------------
# Property 7 (task 4.4): DSS/combo columns do not disturb other classifications
# ---------------------------------------------------------------------------


class TestProperty7NoDisturbance:
    # Feature: dss-daily-signal-classification, Property 7: Adding DSS and combo columns does not disturb other classifications  # noqa: E501
    # Validates: Requirements 3.8, 4.6
    @settings(max_examples=200, deadline=None)
    @given(
        composite=st.floats(min_value=-40, max_value=40, allow_nan=False),
        acc_flag=st.sampled_from([0, 1]),
        acc_type=st.sampled_from([-1, 0, 1]),
        acc_score=st.floats(min_value=-30, max_value=30, allow_nan=False),
        pvs_score=st.floats(min_value=-5, max_value=5, allow_nan=False),
        dss_bull=st.sampled_from([0, 1]),
        dss_bear=st.sampled_from([0, 1]),
        combo_bits=st.lists(st.sampled_from([0, 1]), min_size=10, max_size=10),
    )
    def test_core_and_pvs_membership_is_stable(
        self, composite, acc_flag, acc_type, acc_score, pvs_score, dss_bull, dss_bear, combo_bits
    ):
        base = pd.DataFrame(
            {
                "composite_score": [composite],
                "acc_dist_flag": [float(acc_flag)],
                "acc_dist_type": [float(acc_type)],
                "acc_dist_score": [acc_score],
                "price_vs_sma_signal_score": [pvs_score],
            }
        )

        core_and_pvs = {
            SignalType.STRONG_BULLISH,
            SignalType.STRONG_BEARISH,
            SignalType.ACCUMULATION,
            SignalType.ACCUMULATION_TEST_PASS,
            SignalType.DISTRIBUTION,
            SignalType.PRICE_ABOVE_SMA,
            SignalType.PRICE_BELOW_SMA,
        }

        without = classify_last_row(base) & core_and_pvs

        # Add DSS columns.
        with_dss = base.copy()
        with_dss["dss_bullish_cross"] = [dss_bull]
        with_dss["dss_bearish_cross"] = [dss_bear]
        dss_only_result = classify_last_row(with_dss)
        assert (dss_only_result & core_and_pvs) == without

        # Add combo columns on top of DSS.
        with_combo = with_dss.copy()
        for col_idx, col in enumerate(_COMBO_COLUMN_TO_TYPE.keys()):
            with_combo[col] = [combo_bits[col_idx]]
        with_combo_result = classify_last_row(with_combo)

        # Core/pvs membership still unchanged.
        assert (with_combo_result & core_and_pvs) == without
        # DSS membership unaffected by the presence of combo columns.
        dss_types = {SignalType.DSS_BULLISH, SignalType.DSS_BEARISH}
        assert (with_combo_result & dss_types) == (dss_only_result & dss_types)


# ---------------------------------------------------------------------------
# Example tests (task 4.5): classification edge cases (Req 7.1-7.6, 3.7, 4.5)
# ---------------------------------------------------------------------------


class TestClassificationEdgeCases:
    def test_dss_bullish_cross_one_yields_dss_bullish(self):
        # Req 7.1
        df = _base_frame(1)
        df["dss_bullish_cross"] = [1]
        assert SignalType.DSS_BULLISH in classify_last_row(df)

    def test_dss_bearish_cross_one_yields_dss_bearish(self):
        # Req 7.2
        df = _base_frame(1)
        df["dss_bearish_cross"] = [1]
        assert SignalType.DSS_BEARISH in classify_last_row(df)

    def test_both_dss_columns_absent_no_dss_types_no_error(self):
        # Req 7.3
        df = _base_frame(1)
        result = classify_last_row(df)
        assert SignalType.DSS_BULLISH not in result
        assert SignalType.DSS_BEARISH not in result

    @pytest.mark.parametrize("bad_value", [float("nan"), 0, 2, -1])
    def test_dss_final_value_nan_or_not_one_absent(self, bad_value):
        # Req 7.4
        df = _base_frame(1)
        df["dss_bullish_cross"] = [bad_value]
        assert SignalType.DSS_BULLISH not in classify_last_row(df)

    @pytest.mark.parametrize("combo_col,combo_type", list(_COMBO_COLUMN_TO_TYPE.items()))
    def test_each_combo_column_one_yields_its_type(self, combo_col, combo_type):
        # Req 7.5
        df = _base_frame(1)
        df[combo_col] = [1]
        assert combo_type in classify_last_row(df)

    @pytest.mark.parametrize("combo_col,combo_type", list(_COMBO_COLUMN_TO_TYPE.items()))
    def test_combo_column_absent_yields_absent(self, combo_col, combo_type):
        # Req 7.6 (absent)
        df = _base_frame(1)
        assert combo_type not in classify_last_row(df)

    @pytest.mark.parametrize("bad_value", [float("nan"), 0, 2])
    def test_combo_column_nan_or_not_one_absent_no_error(self, bad_value):
        # Req 7.6 (present but not 1)
        df = _base_frame(1)
        df["combo_dss_cross_sma_pos_bull"] = [bad_value]
        result = classify_last_row(df)
        assert SignalType.COMBO_DSS_CROSS_SMA_POS_BULL not in result

    def test_empty_frame_returns_empty_set_no_error(self):
        # Req 3.7, 4.5
        assert classify_last_row(pd.DataFrame()) == set()
