"""Unit tests for the inline flag + combination feature columns (SP-327, task 6.3).

Covers the eight inline flag columns and the ten ``combo_*`` combination columns
added to ``VPAFeatureExtractor`` in tasks 6.1/6.2:

- ``FEATURE_COLUMNS`` structure: all eight flags and ten combos are present, in the
  fixed order (flags before combos, combos before ``composite_score``), length 49.
- Combination derivation: each ``combo_*`` column equals the AND of its constituent
  flags on crafted rows (one per combination per direction), including the negation
  behaviour of ``combo_dss_cross_sma_not_ob_*``.
- ``composite_score`` zero-regression: the composite depends ONLY on the five signal
  sub-scores (single_candle / trend / multiple_bar / acc_dist / rsi) and is invariant
  under every flag/combo column value (SP-340 rule).

The combo derivation + flag emission are pure within ``_extract_feature_vector`` (the
flags come in as default-0 int params), so these tests drive that method directly with
crafted inputs — microseconds per case, no 2000-row extraction.

Requirements: 1.4, 2.5, 2.6, 2.7, 2.8
"""

import json
import os
import tempfile

import pytest

from vpa.ml_validation.feature_extractor import VPAFeatureExtractor

_CONFIG_PATH = "vpa/config/config.json"

_PERIODS = ("period_one", "period_two", "period_three")

# The eight inline flag columns, in their fixed FEATURE_COLUMNS order.
FLAG_COLUMNS = [
    "dss_bullish_cross",
    "dss_bearish_cross",
    "dss_oversold",
    "dss_overbought",
    "price_above_sma",
    "price_below_sma",
    "price_crossed_above_sma",
    "price_crossed_below_sma",
]

# The ten combination columns, in their fixed FEATURE_COLUMNS order.
COMBO_COLUMNS = [
    "combo_dss_cross_sma_pos_bull",
    "combo_dss_cross_sma_pos_bear",
    "combo_dss_cross_sma_cross_bull",
    "combo_dss_cross_sma_cross_bear",
    "combo_dss_zone_sma_cross_bull",
    "combo_dss_zone_sma_cross_bear",
    "combo_dss_cross_from_zone_bull",
    "combo_dss_cross_from_zone_bear",
    "combo_dss_cross_sma_not_ob_bull",
    "combo_dss_cross_sma_not_ob_bear",
]

# Each combo column -> the flag kwargs that must all be set for it to be 1
# (design §5.2). The negated flag is listed with a leading "!".
COMBO_CONSTITUENTS = {
    "combo_dss_cross_sma_pos_bull": ["dss_bullish_cross", "price_above_sma"],
    "combo_dss_cross_sma_pos_bear": ["dss_bearish_cross", "price_below_sma"],
    "combo_dss_cross_sma_cross_bull": ["dss_bullish_cross", "price_crossed_above_sma"],
    "combo_dss_cross_sma_cross_bear": ["dss_bearish_cross", "price_crossed_below_sma"],
    "combo_dss_zone_sma_cross_bull": ["dss_oversold", "price_crossed_above_sma"],
    "combo_dss_zone_sma_cross_bear": ["dss_overbought", "price_crossed_below_sma"],
    "combo_dss_cross_from_zone_bull": ["dss_bullish_cross", "dss_oversold"],
    "combo_dss_cross_from_zone_bear": ["dss_bearish_cross", "dss_overbought"],
    "combo_dss_cross_sma_not_ob_bull": ["dss_bullish_cross", "price_above_sma", "!dss_overbought"],
    "combo_dss_cross_sma_not_ob_bear": ["dss_bearish_cross", "price_below_sma", "!dss_oversold"],
}


class _FakeCandle:
    """Minimal stand-in exposing only the attributes _extract_feature_vector reads."""

    def __init__(self):
        self.spread_percentiles = {p: 0.0 for p in _PERIODS}
        self.volume_percentiles = {p: 0.0 for p in _PERIODS}
        self.up_bar = True
        self.shooting_star = False
        self.hammer = False
        self.lld = False


def _rsi_disabled_extractor():
    """Build an extractor with RSI disabled so rsi_signal_score is a deterministic 0."""
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        base = json.load(f)
    base.setdefault("rsi", {})
    base["rsi"]["enabled"] = False
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(base, f)
    try:
        return VPAFeatureExtractor(config_path=path, ticker_symbol="SPY", enable_extraction=True)
    finally:
        os.unlink(path)


def _base_kwargs(single=0.0, trend=0.0, multi=0.0, acc=0.0):
    """Build the non-flag keyword args for _extract_feature_vector with crafted sub-scores."""
    candle = _FakeCandle()
    deque_dictionary = {p: [candle] for p in _PERIODS}
    signals = {
        "single_candle_signal_score": single,
        "trend_signal_score": trend,
        "multiple_bar_signal_score": multi,
        "acc_dist_signal_score": acc,
        "multiple_bar_signals": [],
    }
    # adx_values: [adx, avg_true_range, dm_plus_smooth, dm_minus_smooth]
    adx_values = [0.0, 0.0, 0.0, 0.0]
    acc_dist_result = (False, "")
    return {
        "candle": candle,
        "signals": signals,
        "adx_values": adx_values,
        "acc_dist_result": acc_dist_result,
        "deque_dictionary": deque_dictionary,
    }


# ---------------------------------------------------------------------------
# FEATURE_COLUMNS structure (Req 1.4, 2.5-2.8)
# ---------------------------------------------------------------------------


class TestFeatureColumnsStructure:
    def test_all_eight_flag_columns_present(self):
        cols = VPAFeatureExtractor.FEATURE_COLUMNS
        for flag in FLAG_COLUMNS:
            assert flag in cols, f"missing flag column {flag}"

    def test_all_ten_combo_columns_present(self):
        cols = VPAFeatureExtractor.FEATURE_COLUMNS
        for combo in COMBO_COLUMNS:
            assert combo in cols, f"missing combo column {combo}"

    def test_feature_columns_length_is_49(self):
        assert len(VPAFeatureExtractor.FEATURE_COLUMNS) == 49

    def test_flags_appear_in_fixed_contiguous_order(self):
        cols = VPAFeatureExtractor.FEATURE_COLUMNS
        indices = [cols.index(flag) for flag in FLAG_COLUMNS]
        # Strictly increasing and contiguous.
        assert indices == sorted(indices)
        assert indices == list(range(indices[0], indices[0] + len(FLAG_COLUMNS)))

    def test_combos_appear_in_fixed_contiguous_order(self):
        cols = VPAFeatureExtractor.FEATURE_COLUMNS
        indices = [cols.index(combo) for combo in COMBO_COLUMNS]
        assert indices == sorted(indices)
        assert indices == list(range(indices[0], indices[0] + len(COMBO_COLUMNS)))

    def test_flags_before_combos_before_composite(self):
        cols = VPAFeatureExtractor.FEATURE_COLUMNS
        last_flag = max(cols.index(f) for f in FLAG_COLUMNS)
        first_combo = min(cols.index(c) for c in COMBO_COLUMNS)
        last_combo = max(cols.index(c) for c in COMBO_COLUMNS)
        i_composite = cols.index("composite_score")
        assert last_flag < first_combo
        assert last_combo < i_composite

    def test_emitted_vector_contains_flags_and_combos(self):
        extractor = _rsi_disabled_extractor()
        row = extractor._extract_feature_vector(**_base_kwargs())
        for col in FLAG_COLUMNS + COMBO_COLUMNS:
            assert col in row, f"emitted vector missing {col}"


# ---------------------------------------------------------------------------
# Combination derivation (Req 2.5, 2.6, 2.7, 2.8)
# ---------------------------------------------------------------------------


def _derive_combos(flags: dict) -> dict:
    """Reference oracle for the ten combo columns from the eight flags (design §5.2).

    Mirrors the ``int(<AND expression>)`` derivation in ``generate_dataset`` Step 9d
    exactly, so a crafted set of flags maps to the combo values the extractor pipeline
    must emit. The two ``_not_ob_`` combos include the negation of the opposite DSS
    zone flag (Req 2.7, 2.8).
    """

    def f(name):
        return int(flags.get(name, 0))

    return {
        "combo_dss_cross_sma_pos_bull": int(f("dss_bullish_cross") and f("price_above_sma")),
        "combo_dss_cross_sma_pos_bear": int(f("dss_bearish_cross") and f("price_below_sma")),
        "combo_dss_cross_sma_cross_bull": int(f("dss_bullish_cross") and f("price_crossed_above_sma")),
        "combo_dss_cross_sma_cross_bear": int(f("dss_bearish_cross") and f("price_crossed_below_sma")),
        "combo_dss_zone_sma_cross_bull": int(f("dss_oversold") and f("price_crossed_above_sma")),
        "combo_dss_zone_sma_cross_bear": int(f("dss_overbought") and f("price_crossed_below_sma")),
        "combo_dss_cross_from_zone_bull": int(f("dss_bullish_cross") and f("dss_oversold")),
        "combo_dss_cross_from_zone_bear": int(f("dss_bearish_cross") and f("dss_overbought")),
        "combo_dss_cross_sma_not_ob_bull": int(
            f("dss_bullish_cross") and f("price_above_sma") and not f("dss_overbought")
        ),
        "combo_dss_cross_sma_not_ob_bear": int(
            f("dss_bearish_cross") and f("price_below_sma") and not f("dss_oversold")
        ),
    }


class TestCombinationDerivation:
    """Each combo column equals the AND of its constituent flags (design §5.2).

    ``_extract_feature_vector`` is a faithful emitter: it threads the flags and the
    already-derived combo values into the fixed FEATURE_COLUMNS slots. So each case
    derives the ten combos from a crafted flag set via the ``_derive_combos`` oracle,
    passes BOTH the flags and the derived combos into the extractor, and asserts the
    emitted vector carries exactly those values in the right columns. The oracle itself
    is the AND-of-flags contract under test; ``TestLiveDerivation`` pins that same
    contract against the real ``generate_dataset`` Step 9d derivation.
    """

    def _emit(self, extractor, flags):
        combos = _derive_combos(flags)
        row = extractor._extract_feature_vector(**_base_kwargs(), **flags, **combos)
        return row, combos

    @pytest.mark.parametrize("combo", COMBO_COLUMNS)
    def test_combo_fires_when_constituents_set(self, combo):
        """combo == 1 when its positive constituents are 1 (and any negated flag is 0)."""
        extractor = _rsi_disabled_extractor()
        flags = {name: 1 for name in COMBO_CONSTITUENTS[combo] if not name.startswith("!")}
        row, combos = self._emit(extractor, flags)
        assert combos[combo] == 1
        assert row[combo] == 1

    @pytest.mark.parametrize("combo", COMBO_COLUMNS)
    def test_combo_is_zero_when_a_constituent_missing(self, combo):
        """Dropping any single positive constituent to 0 makes the AND 0."""
        extractor = _rsi_disabled_extractor()
        positives = [name for name in COMBO_CONSTITUENTS[combo] if not name.startswith("!")]
        for dropped in positives:
            flags = {name: 1 for name in positives if name != dropped}
            row, combos = self._emit(extractor, flags)
            assert combos[combo] == 0, f"{combo} AND should be 0 when {dropped} is unset"
            assert row[combo] == 0

    def test_negation_combo_bull_blocked_when_overbought(self):
        """combo_dss_cross_sma_not_ob_bull == 0 when dss_overbought is also 1 (Req 2.7)."""
        extractor = _rsi_disabled_extractor()
        flags = {"dss_bullish_cross": 1, "price_above_sma": 1, "dss_overbought": 1}
        row, combos = self._emit(extractor, flags)
        assert combos["combo_dss_cross_sma_not_ob_bull"] == 0
        assert row["combo_dss_cross_sma_not_ob_bull"] == 0

    def test_negation_combo_bull_fires_when_not_overbought(self):
        """combo_dss_cross_sma_not_ob_bull == 1 when dss_overbought is 0 (Req 2.7)."""
        extractor = _rsi_disabled_extractor()
        flags = {"dss_bullish_cross": 1, "price_above_sma": 1, "dss_overbought": 0}
        row, combos = self._emit(extractor, flags)
        assert combos["combo_dss_cross_sma_not_ob_bull"] == 1
        assert row["combo_dss_cross_sma_not_ob_bull"] == 1

    def test_negation_combo_bear_blocked_when_oversold(self):
        """combo_dss_cross_sma_not_ob_bear == 0 when dss_oversold is also 1 (Req 2.8)."""
        extractor = _rsi_disabled_extractor()
        flags = {"dss_bearish_cross": 1, "price_below_sma": 1, "dss_oversold": 1}
        row, combos = self._emit(extractor, flags)
        assert combos["combo_dss_cross_sma_not_ob_bear"] == 0
        assert row["combo_dss_cross_sma_not_ob_bear"] == 0

    def test_negation_combo_bear_fires_when_not_oversold(self):
        """combo_dss_cross_sma_not_ob_bear == 1 when dss_oversold is 0 (Req 2.8)."""
        extractor = _rsi_disabled_extractor()
        flags = {"dss_bearish_cross": 1, "price_below_sma": 1, "dss_oversold": 0}
        row, combos = self._emit(extractor, flags)
        assert combos["combo_dss_cross_sma_not_ob_bear"] == 1
        assert row["combo_dss_cross_sma_not_ob_bear"] == 1

    def test_all_combos_zero_when_no_flags_set(self):
        extractor = _rsi_disabled_extractor()
        row, combos = self._emit(extractor, {})
        for combo in COMBO_COLUMNS:
            assert combos[combo] == 0
            assert row[combo] == 0


# ---------------------------------------------------------------------------
# composite_score zero-regression (SP-340 rule, Req 1.4)
# ---------------------------------------------------------------------------


class TestCompositeScoreZeroRegression:
    def test_composite_equals_five_subscore_sum(self):
        extractor = _rsi_disabled_extractor()
        row = extractor._extract_feature_vector(**_base_kwargs(single=3.0, trend=-2.0, multi=1.5, acc=4.0))
        five_term = (
            row["single_candle_score"]
            + row["trend_score"]
            + row["multiple_bar_score"]
            + row["acc_dist_score"]
            + row["rsi_signal_score"]
        )
        assert row["composite_score"] == pytest.approx(float(five_term))
        # rsi disabled -> five-term reduces to the four VPA sub-scores.
        assert row["composite_score"] == pytest.approx(3.0 - 2.0 + 1.5 + 4.0)

    def test_composite_invariant_to_flag_and_combo_inputs(self):
        """Identical sub-scores + different flag/combo inputs -> identical composite_score."""
        extractor = _rsi_disabled_extractor()
        kwargs = _base_kwargs(single=3.0, trend=-2.0, multi=1.5, acc=4.0)

        # No flags set.
        row_plain = extractor._extract_feature_vector(**kwargs)

        # Every flag and every combo input forced on.
        all_on = dict.fromkeys(FLAG_COLUMNS + COMBO_COLUMNS, 1)
        row_flagged = extractor._extract_feature_vector(**kwargs, **all_on)

        assert row_flagged["composite_score"] == pytest.approx(row_plain["composite_score"])


# ---------------------------------------------------------------------------
# Live derivation (slow) — pins the real generate_dataset Step 9d AND logic
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestLiveDerivation:
    """Exercise the production combo derivation end-to-end via generate_dataset.

    The fast ``TestCombinationDerivation`` cases assert the derivation CONTRACT
    (the AND-of-flags oracle) and the extractor's faithful emission. This slow test
    pins the actual inline Step 9d derivation: on a full extraction run, every
    ``combo_*`` column must equal the AND of its real flag columns on every row, and
    ``composite_score`` must match the committed pre-SP-327 baseline (zero-regression).
    """

    def test_combos_equal_flag_ands_and_composite_unchanged(self):
        import pandas as pd

        from vpa.tests.ml_validation.test_feature_extraction_characterisation import (
            CONFIG_PATH,
            FIXTURE_PATH,
            TICKER,
            _FakeRepo,
            _make_pinned_ohlcv_dataframe,
        )

        pinned = _make_pinned_ohlcv_dataframe()
        extractor = VPAFeatureExtractor(
            config_path=CONFIG_PATH,
            ticker_symbol=TICKER,
            enable_extraction=True,
        )
        extracted = extractor.generate_dataset(days=3650, repo=_FakeRepo(pinned))

        # All flag + combo columns present.
        for col in FLAG_COLUMNS + COMBO_COLUMNS:
            assert col in extracted.columns, f"missing {col}"

        # Every combo column equals the AND of its real flag columns across all rows.
        for _, row in extracted.iterrows():
            flags = {name: int(row[name]) for name in FLAG_COLUMNS}
            expected = _derive_combos(flags)
            for combo in COMBO_COLUMNS:
                assert (
                    int(row[combo]) == expected[combo]
                ), f"{combo}={int(row[combo])} != AND-of-flags {expected[combo]} for flags {flags}"

        # composite_score byte-for-byte unchanged vs the committed baseline.
        baseline = pd.read_csv(FIXTURE_PATH)
        assert len(extracted) == len(baseline)
        pd.testing.assert_series_equal(
            extracted["composite_score"].reset_index(drop=True),
            baseline["composite_score"].reset_index(drop=True),
            check_exact=False,
            rtol=1e-9,
            atol=1e-9,
            check_names=True,
        )
