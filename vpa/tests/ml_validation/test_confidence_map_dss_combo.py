"""Unit tests for the CONFIDENCE_MAP DSS and combo entries (SP-359, task 6.2).

Covers the default confidence levels added to ``CONFIDENCE_MAP`` in
``vpa/ml_validation/daily_signal.py`` for the DSS crossover signal types and the
ten DSS/SMA combo (confluence) signal types:

- ``DSS_BULLISH`` / ``DSS_BEARISH`` have an entry whose value ranks strictly above
  ``"Low"`` in ``CONFIDENCE_ORDER`` (Req 5.1, 5.2).
- Each of the ten combo ``SignalType``s (sourced from ``_COMBO_COLUMN_TO_TYPE`` in
  ``signal_analysis.py``) has an entry equal to ``"Medium-High"`` (Req 5.3, 5.4).

These are static-content assertions on a module-level dict, so the tests read the
mapping directly — no DataFrames, no network, no model training.

Requirements: 5.1, 5.2, 5.3, 5.4
"""

from vpa.ml_validation.daily_signal import CONFIDENCE_MAP, CONFIDENCE_ORDER
from vpa.ml_validation.signal_analysis import _COMBO_COLUMN_TO_TYPE, SignalType


class TestDSSConfidenceEntries:
    """DSS_BULLISH / DSS_BEARISH rank strictly above "Low" (Req 5.1, 5.2)."""

    def test_dss_bullish_ranks_strictly_above_low(self) -> None:
        assert SignalType.DSS_BULLISH in CONFIDENCE_MAP
        confidence = CONFIDENCE_MAP[SignalType.DSS_BULLISH]
        assert confidence in CONFIDENCE_ORDER
        assert CONFIDENCE_ORDER.index(confidence) < CONFIDENCE_ORDER.index("Low")

    def test_dss_bearish_ranks_strictly_above_low(self) -> None:
        assert SignalType.DSS_BEARISH in CONFIDENCE_MAP
        confidence = CONFIDENCE_MAP[SignalType.DSS_BEARISH]
        assert confidence in CONFIDENCE_ORDER
        assert CONFIDENCE_ORDER.index(confidence) < CONFIDENCE_ORDER.index("Low")


class TestComboConfidenceEntries:
    """Each of the ten combo types maps to "Medium-High" (Req 5.3, 5.4)."""

    def test_there_are_exactly_ten_combo_types(self) -> None:
        # Guards the parametrised coverage below against the map drifting.
        assert len(_COMBO_COLUMN_TO_TYPE) == 10

    def test_every_combo_type_is_medium_high(self) -> None:
        for column, combo_type in _COMBO_COLUMN_TO_TYPE.items():
            assert combo_type in CONFIDENCE_MAP, f"{column} ({combo_type}) missing from CONFIDENCE_MAP"
            assert (
                CONFIDENCE_MAP[combo_type] == "Medium-High"
            ), f"{column} ({combo_type}) should default to 'Medium-High'"

    def test_medium_high_is_present_in_confidence_order(self) -> None:
        # The chosen combo band must be a real, rankable confidence level.
        assert "Medium-High" in CONFIDENCE_ORDER
