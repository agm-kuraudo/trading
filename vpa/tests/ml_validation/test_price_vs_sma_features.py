"""Unit + property tests for the price-vs-SMA ML feature (SP-340).

The scoring logic lives in the pure helper
``vpa.ml_validation.feature_extractor.compute_price_vs_sma_feature`` so it can be
tested directly with scalar inputs — microseconds per case, exact expectations,
no 2000-row extraction. A single slow test (marked ``slow``) exercises the full
``generate_dataset`` wiring end-to-end; everything else runs on the fast path.

Property 2 uses ``MarketAnalyzer.detect_price_vs_sma_signals`` ONLY as a test
oracle, driven over a SMALL dataframe; production code never imports or calls
``MarketAnalyzer`` (inline-reimplementation constraint, Req 3 / design).

Requirements: 2.1, 2.2, 2.4, 3.1-3.12, 4.1-4.3, 8.2
"""

import json
import os
import tempfile
from dataclasses import dataclass

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vpa.ml_validation.feature_extractor import (
    VPAFeatureExtractor,
    compute_price_vs_sma_feature,
)

NAN = float("nan")


# ---------------------------------------------------------------------------
# Lightweight config stand-ins (mirror PriceVsSMASettings attribute access)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Scores:
    above: float
    below: float


@dataclass(frozen=True)
class _CrossScores:
    cross_above: float
    cross_below: float


@dataclass(frozen=True)
class _PvsCfg:
    scores: _Scores
    crossover_scores: _CrossScores
    detect_crossover: bool = False


def _cfg(above=5.0, below=5.0, detect_crossover=False, cross_above=3.0, cross_below=3.0) -> _PvsCfg:
    return _PvsCfg(
        scores=_Scores(above, below),
        crossover_scores=_CrossScores(cross_above, cross_below),
        detect_crossover=detect_crossover,
    )


def _score(close, sma, prev_close=NAN, prev_sma=NAN, cfg=None, *, enabled=True, has_previous=False):
    cfg = cfg if cfg is not None else _cfg()
    return compute_price_vs_sma_feature(
        close, sma, prev_close, prev_sma, cfg, enabled=enabled, has_previous=has_previous
    )


# ---------------------------------------------------------------------------
# Helpers for the composite-score (P4) test — exercise the real
# _extract_feature_vector path with lightweight crafted state.
# ---------------------------------------------------------------------------

_PERIODS = ("period_one", "period_two", "period_three")


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
    """Build an extractor whose config has RSI disabled (rsi_signal_score == 0).

    Uses the real config with the rsi section forced disabled so the composite path
    runs with a deterministic zero RSI term.
    """
    base = json.loads(open(_CONFIG_PATH, encoding="utf-8").read())
    base.setdefault("rsi", {})
    base["rsi"]["enabled"] = False
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(base, f)
    try:
        return VPAFeatureExtractor(config_path=path, ticker_symbol="SPY", enable_extraction=True)
    finally:
        os.unlink(path)


def _extract_kwargs(single, trend, multi, acc):
    """Build the keyword args for _extract_feature_vector with crafted sub-scores."""
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
# Task 1.6 — FEATURE_COLUMNS structure (Req 2.1, 2.2, 2.4)
# ---------------------------------------------------------------------------


class TestFeatureColumnsStructure:
    def test_both_new_columns_present(self):
        cols = VPAFeatureExtractor.FEATURE_COLUMNS
        assert "price_vs_sma_value" in cols
        assert "price_vs_sma_signal_score" in cols

    def test_feature_columns_length_is_33(self):
        assert len(VPAFeatureExtractor.FEATURE_COLUMNS) == 33

    def test_new_columns_ordered_after_rsi_before_dss(self):
        cols = VPAFeatureExtractor.FEATURE_COLUMNS
        i_rsi = cols.index("rsi_signal_score")
        i_val = cols.index("price_vs_sma_value")
        i_score = cols.index("price_vs_sma_signal_score")
        i_dss = cols.index("dss_bullish_cross")
        assert i_val == i_rsi + 1
        assert i_score == i_val + 1
        assert i_dss == i_score + 1


# ---------------------------------------------------------------------------
# Task 1.5 — position + crossover scoring (Req 3.2-3.6, 3.8-3.12)
# ---------------------------------------------------------------------------


class TestPositionScoring:
    def test_above_sma_adds_scores_above(self):
        assert _score(55.0, 50.0) == (50.0, 5.0)

    def test_below_sma_subtracts_scores_below(self):
        assert _score(45.0, 50.0) == (50.0, -5.0)

    def test_equal_sma_scores_zero(self):
        assert _score(50.0, 50.0) == (50.0, 0.0)

    def test_custom_weights_respected(self):
        cfg = _cfg(above=8.0, below=3.0)
        assert _score(55.0, 50.0, cfg=cfg)[1] == pytest.approx(8.0)
        assert _score(45.0, 50.0, cfg=cfg)[1] == pytest.approx(-3.0)


class TestWarmupAndDisabled:
    def test_nan_sma_scores_zero_with_sentinel(self):
        assert _score(55.0, NAN) == (50.0, 0.0)

    def test_nan_close_scores_zero_with_sentinel(self):
        assert _score(NAN, 50.0) == (50.0, 0.0)

    def test_disabled_scores_zero_with_sentinel(self):
        # enabled=False short-circuits regardless of close/sma.
        assert _score(55.0, 50.0, enabled=False) == (50.0, 0.0)


class TestCrossoverScoring:
    def test_cross_above_adds_position_plus_cross_above(self):
        cfg = _cfg(detect_crossover=True)
        # prev below (45<=50), now above (55>50) -> +5 +3 = +8
        assert _score(55.0, 50.0, prev_close=45.0, prev_sma=50.0, cfg=cfg, has_previous=True)[1] == pytest.approx(8.0)

    def test_cross_below_subtracts_position_plus_cross_below(self):
        cfg = _cfg(detect_crossover=True)
        # prev at/above (52>=50), now below (48<50) -> -5 -3 = -8
        assert _score(48.0, 50.0, prev_close=52.0, prev_sma=50.0, cfg=cfg, has_previous=True)[1] == pytest.approx(-8.0)

    def test_crossover_off_is_position_only(self):
        cfg = _cfg(detect_crossover=False)
        assert _score(55.0, 50.0, prev_close=45.0, prev_sma=50.0, cfg=cfg, has_previous=True)[1] == pytest.approx(5.0)

    def test_already_above_no_fresh_cross_has_no_crossover_term(self):
        cfg = _cfg(detect_crossover=True)
        # prev also above (55>50) -> no fresh cross -> position only +5
        assert _score(55.0, 50.0, prev_close=55.0, prev_sma=50.0, cfg=cfg, has_previous=True)[1] == pytest.approx(5.0)

    def test_no_previous_row_has_no_crossover_term(self):
        cfg = _cfg(detect_crossover=True)
        # has_previous False -> crossover suppressed, position only
        assert _score(55.0, 50.0, cfg=cfg, has_previous=False)[1] == pytest.approx(5.0)

    def test_nan_previous_has_no_crossover_term(self):
        cfg = _cfg(detect_crossover=True)
        assert _score(55.0, 50.0, prev_close=NAN, prev_sma=NAN, cfg=cfg, has_previous=True)[1] == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# Shared property strategies
# ---------------------------------------------------------------------------

_finite = st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False)
_weights = st.floats(min_value=0.0, max_value=20.0, allow_nan=False, allow_infinity=False)


@st.composite
def _cfgs(draw) -> _PvsCfg:
    return _cfg(
        above=draw(_weights),
        below=draw(_weights),
        detect_crossover=draw(st.booleans()),
        cross_above=draw(_weights),
        cross_below=draw(_weights),
    )


# ---------------------------------------------------------------------------
# Task 1.7 — Property P1: SMA value equals the reference rolling mean
# ---------------------------------------------------------------------------


class TestPropertyP1SMAValue:
    # Feature: sp-340-price-vs-sma-ml-integration, Property 1: For all close-price series and valid periods, emitted price_vs_sma_value equals pandas rolling(window=period, min_periods=period).mean() within float tolerance  # noqa: E501
    @settings(max_examples=200, deadline=None)
    @given(
        closes=st.lists(_finite, min_size=1, max_size=60),
        period=st.integers(min_value=2, max_value=20),
    )
    def test_emitted_value_equals_rolling_mean(self, closes, period):
        series = pd.Series(closes)
        rolling = series.rolling(window=period, min_periods=period).mean()
        for i in range(len(closes)):
            sma = rolling.iloc[i]
            value, _ = _score(closes[i], sma)
            if pd.isna(sma):
                assert value == pytest.approx(50.0)
            else:
                assert value == pytest.approx(float(sma), rel=1e-9, abs=1e-9)


# ---------------------------------------------------------------------------
# Task 1.8 — Property P2: combined score equals the MarketAnalyzer oracle
# ---------------------------------------------------------------------------

_CONFIG_PATH = "vpa/config/config.json"


def _small_df(closes):
    n = len(closes)
    return pd.DataFrame(
        {
            "Date": pd.date_range("2024-01-01", periods=n),
            "Close": closes,
            "High": [c + 1 for c in closes],
            "Low": [c - 1 for c in closes],
            "Open": closes,
            "Volume": [1_000_000] * n,
        }
    )


def _oracle_analyzer(closes, cfg: _PvsCfg, period: int):
    from vpa.app_runner import MarketAnalyzer

    base = json.loads(open(_CONFIG_PATH, encoding="utf-8").read())
    base["price_vs_sma"] = {
        "enabled": True,
        "period": period,
        "scores": {"above": cfg.scores.above, "below": cfg.scores.below},
        "detect_crossover": cfg.detect_crossover,
        "crossover_scores": {
            "cross_above": cfg.crossover_scores.cross_above,
            "cross_below": cfg.crossover_scores.cross_below,
        },
    }
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(base, f)
    try:
        analyzer = MarketAnalyzer(
            config_path=path,
            fixed_df=_small_df(closes),
            log_level="ERROR",
            log_prefix="test_pvs_oracle",
        )
    finally:
        os.unlink(path)
    analyzer.compute_price_vs_sma_column()
    return analyzer


class TestPropertyP2Oracle:
    # Feature: sp-340-price-vs-sma-ml-integration, Property 2: For all close series and configs, the extractor combined score equals MarketAnalyzer.detect_price_vs_sma_signals for the same row/config  # noqa: E501
    @settings(max_examples=120, deadline=None)
    @given(
        closes=st.lists(_finite, min_size=12, max_size=30),
        cfg=_cfgs(),
        frac=st.floats(min_value=0.0, max_value=0.999),
    )
    def test_score_matches_oracle(self, closes, cfg, frac):
        period = 5
        analyzer = _oracle_analyzer(closes, cfg, period)
        df = analyzer.get_dataframe()
        sma = df["SMA_price_vs"]
        row = int(frac * len(closes))
        oracle = analyzer.detect_price_vs_sma_signals(row, log=False)["price_vs_sma_signal_score"]
        prev_close = closes[row - 1] if row > 0 else NAN
        prev_sma = sma.iloc[row - 1] if row > 0 else NAN
        _, mine = _score(
            closes[row], sma.iloc[row], prev_close=prev_close, prev_sma=prev_sma, cfg=cfg, has_previous=row > 0
        )
        assert mine == pytest.approx(float(oracle), rel=1e-9, abs=1e-9)


# ---------------------------------------------------------------------------
# Task 1.9 — Property P3: crossover disabled yields the position-only score
# ---------------------------------------------------------------------------


class TestPropertyP3CrossoverToggle:
    # Feature: sp-340-price-vs-sma-ml-integration, Property 3: For all close series, the score with detect_crossover=false equals the position-only score; toggling the flag changes the score only by the crossover term  # noqa: E501
    @settings(max_examples=200, deadline=None)
    @given(
        close=_finite,
        sma=_finite,
        prev_close=_finite,
        prev_sma=_finite,
        above=_weights,
        below=_weights,
        cross_above=_weights,
        cross_below=_weights,
    )
    def test_toggle_changes_only_crossover_term(
        self, close, sma, prev_close, prev_sma, above, below, cross_above, cross_below
    ):
        off = _cfg(above, below, False, cross_above, cross_below)
        on = _cfg(above, below, True, cross_above, cross_below)
        _, off_score = _score(close, sma, prev_close, prev_sma, off, has_previous=True)
        _, on_score = _score(close, sma, prev_close, prev_sma, on, has_previous=True)

        # off score is pure position: one of {0, +above, -below}
        assert (
            off_score == pytest.approx(0.0) or off_score == pytest.approx(above) or off_score == pytest.approx(-below)
        )
        delta = on_score - off_score
        assert (
            delta == pytest.approx(0.0) or delta == pytest.approx(cross_above) or delta == pytest.approx(-cross_below)
        )


# ---------------------------------------------------------------------------
# Task 1.10 — Property P4: composite_score invariant under pvs config
# ---------------------------------------------------------------------------


class TestPropertyP4CompositeInvariance:
    # Feature: sp-340-price-vs-sma-ml-integration, Property 4: For all rows and all pairs of price_vs_sma configs (enabled/disabled, crossover on/off), composite_score is identical and equals the five-term sum  # noqa: E501
    @settings(max_examples=150, deadline=None)
    @given(
        single=st.floats(-50, 50, allow_nan=False),
        trend=st.floats(-50, 50, allow_nan=False),
        multi=st.floats(-50, 50, allow_nan=False),
        acc=st.floats(-50, 50, allow_nan=False),
        pvs_a=st.floats(-50, 50, allow_nan=False),
        pvs_b=st.floats(-50, 50, allow_nan=False),
    )
    def test_composite_invariant_and_equals_five_term_sum(self, single, trend, multi, acc, pvs_a, pvs_b):
        """composite_score must equal the five sub-scores summed and be invariant to
        the price_vs_sma pass-through value (Req 4.1-4.3).

        Drives the real ``_extract_feature_vector`` with crafted stand-in state so the
        actual composite computation path is exercised, with ``rsi`` disabled so the
        extractor contributes rsi_signal_score == 0 and the five-term sum reduces to the
        four VPA sub-scores (rsi term 0). The two differing price_vs_sma scores
        (``pvs_a`` vs ``pvs_b``) must never change composite_score.
        """
        extractor = _rsi_disabled_extractor()
        kwargs = _extract_kwargs(single, trend, multi, acc)

        row_a = extractor._extract_feature_vector(price_vs_sma_signal_score=pvs_a, **kwargs)
        row_b = extractor._extract_feature_vector(price_vs_sma_signal_score=pvs_b, **kwargs)

        # Invariant across the two differing pvs pass-through scores.
        assert row_a["composite_score"] == pytest.approx(row_b["composite_score"])
        # Equals the five-term sum (rsi included; pvs excluded). rsi disabled -> 0.
        five_term = (
            row_a["single_candle_score"]
            + row_a["trend_score"]
            + row_a["multiple_bar_score"]
            + row_a["acc_dist_score"]
            + row_a["rsi_signal_score"]
        )
        assert row_a["composite_score"] == pytest.approx(float(five_term))


# ---------------------------------------------------------------------------
# Task 1.11 + full-wiring: slow end-to-end check via generate_dataset
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestFullWiringAndCompositeBaseline:
    """End-to-end: the feature flows through generate_dataset and composite is unchanged."""

    def test_composite_score_matches_committed_baseline_and_columns_present(self):
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

        # New columns are present and emitted.
        assert "price_vs_sma_value" in extracted.columns
        assert "price_vs_sma_signal_score" in extracted.columns

        # Composite is byte-for-byte unchanged vs the pre-feature committed baseline.
        baseline = pd.read_csv(FIXTURE_PATH)
        assert "composite_score" in baseline.columns
        assert len(extracted) == len(baseline)
        pd.testing.assert_series_equal(
            extracted["composite_score"].reset_index(drop=True),
            baseline["composite_score"].reset_index(drop=True),
            check_exact=False,
            rtol=1e-9,
            atol=1e-9,
            check_names=True,
        )


# ---------------------------------------------------------------------------
# Task 3.3 / 3.4 — signal_analysis registration + classify_signals (Req 5.1-5.7)
# ---------------------------------------------------------------------------

from vpa.ml_validation.signal_analysis import (  # noqa: E402
    SIGNAL_DIRECTIONS,
    SignalConditionalAnalyzer,
    SignalDirection,
    SignalType,
)


def _signal_frame(scores, *, include_pvs=True):
    """Build a full-schema feature frame classify_signals can consume.

    classify_signals always reads composite_score + acc_dist_* columns, so they must be
    present. They are set to neutral values (0 / no acc-dist) so only the price_vs_sma
    classification under test can fire. When ``include_pvs`` is False the price_vs_sma
    column is omitted (absent-column case).
    """
    n = len(scores)
    data = {
        "composite_score": [0.0] * n,
        "acc_dist_flag": [0] * n,
        "acc_dist_type": [0] * n,
        "acc_dist_score": [0.0] * n,
    }
    if include_pvs:
        data["price_vs_sma_signal_score"] = list(scores)
    return pd.DataFrame(data)


def _classify(scores):
    """Run classify_signals over a full-schema frame varying only price_vs_sma score."""
    df = _signal_frame(scores)
    return SignalConditionalAnalyzer(output_dir=".").classify_signals(df)


class TestSignalAnalysisRegistration:
    def test_new_signal_types_exist(self):
        assert SignalType.PRICE_ABOVE_SMA.value == "price_above_sma"
        assert SignalType.PRICE_BELOW_SMA.value == "price_below_sma"

    def test_signal_directions_mapped(self):
        assert SIGNAL_DIRECTIONS[SignalType.PRICE_ABOVE_SMA] is SignalDirection.UP
        assert SIGNAL_DIRECTIONS[SignalType.PRICE_BELOW_SMA] is SignalDirection.DOWN

    def test_absent_column_leaves_empty_lists(self):
        # A frame without the price_vs_sma column must leave both match lists empty.
        df = _signal_frame([0.0, 1.0, -1.0], include_pvs=False)
        result = SignalConditionalAnalyzer(output_dir=".").classify_signals(df)
        assert result[SignalType.PRICE_ABOVE_SMA] == []
        assert result[SignalType.PRICE_BELOW_SMA] == []

    def test_positive_above_negative_below_zero_nan_neither(self):
        result = _classify([5.0, -5.0, 0.0, float("nan"), 8.0, -3.0])
        assert result[SignalType.PRICE_ABOVE_SMA] == [0, 4]
        assert result[SignalType.PRICE_BELOW_SMA] == [1, 5]


class TestPropertyP5ClassifySignalsSignPartition:
    # Feature: sp-340-price-vs-sma-ml-integration, Property 5: For all feature DataFrames with price_vs_sma_signal_score, classify_signals returns PRICE_ABOVE_SMA exactly for non-NaN strictly-positive rows, PRICE_BELOW_SMA exactly for non-NaN strictly-negative rows, and neither for zero/NaN  # noqa: E501
    @settings(max_examples=200, deadline=None)
    @given(
        scores=st.lists(
            st.one_of(
                st.floats(allow_nan=False, allow_infinity=False, min_value=-50, max_value=50),
                st.just(0.0),
                st.just(float("nan")),
            ),
            min_size=0,
            max_size=40,
        )
    )
    def test_sign_partition(self, scores):
        result = _classify(scores)
        above = set(result[SignalType.PRICE_ABOVE_SMA])
        below = set(result[SignalType.PRICE_BELOW_SMA])
        expected_above = {i for i, s in enumerate(scores) if (s == s) and s > 0}
        expected_below = {i for i, s in enumerate(scores) if (s == s) and s < 0}
        assert above == expected_above
        assert below == expected_below
        # Disjoint and no zero/NaN row in either set.
        assert above.isdisjoint(below)


# ---------------------------------------------------------------------------
# Task 4.4 / 4.5 — daily_signal CONFIDENCE_MAP + classify_last_row (Req 6.1-6.5)
# ---------------------------------------------------------------------------

from vpa.ml_validation.daily_signal import (  # noqa: E402
    CONFIDENCE_MAP,
    CONFIDENCE_ORDER,
    classify_last_row,
)


def _last_row_frame(pvs_score, *, include_pvs=True):
    """One-row full-schema frame with neutral acc/composite, varying price_vs_sma score."""
    data = {
        "composite_score": [0.0],
        "acc_dist_flag": [0],
        "acc_dist_type": [0],
        "acc_dist_score": [0.0],
    }
    if include_pvs:
        data["price_vs_sma_signal_score"] = [pvs_score]
    return pd.DataFrame(data)


class TestDailySignalConfidenceMap:
    def test_both_types_present_with_valid_labels(self):
        assert CONFIDENCE_MAP[SignalType.PRICE_ABOVE_SMA] in CONFIDENCE_ORDER
        assert CONFIDENCE_MAP[SignalType.PRICE_BELOW_SMA] in CONFIDENCE_ORDER


class TestDailySignalClassifyLastRow:
    def test_positive_adds_above(self):
        result = classify_last_row(_last_row_frame(5.0))
        assert SignalType.PRICE_ABOVE_SMA in result
        assert SignalType.PRICE_BELOW_SMA not in result

    def test_negative_adds_below(self):
        result = classify_last_row(_last_row_frame(-5.0))
        assert SignalType.PRICE_BELOW_SMA in result
        assert SignalType.PRICE_ABOVE_SMA not in result

    def test_zero_adds_neither(self):
        result = classify_last_row(_last_row_frame(0.0))
        assert SignalType.PRICE_ABOVE_SMA not in result
        assert SignalType.PRICE_BELOW_SMA not in result

    def test_nan_adds_neither(self):
        result = classify_last_row(_last_row_frame(float("nan")))
        assert SignalType.PRICE_ABOVE_SMA not in result
        assert SignalType.PRICE_BELOW_SMA not in result

    def test_absent_column_adds_neither(self):
        result = classify_last_row(_last_row_frame(0.0, include_pvs=False))
        assert SignalType.PRICE_ABOVE_SMA not in result
        assert SignalType.PRICE_BELOW_SMA not in result


class TestPropertyP6ClassifyLastRowSign:
    # Feature: sp-340-price-vs-sma-ml-integration, Property 6: For all feature DataFrames, classify_last_row includes PRICE_ABOVE_SMA iff the last row score is non-NaN and strictly positive, PRICE_BELOW_SMA iff non-NaN strictly negative, and neither when absent/NaN/zero  # noqa: E501
    @settings(max_examples=200, deadline=None)
    @given(
        score=st.one_of(
            st.floats(allow_nan=False, allow_infinity=False, min_value=-50, max_value=50),
            st.just(0.0),
            st.just(float("nan")),
            st.none(),
        )
    )
    def test_last_row_sign(self, score):
        include = score is not None
        pvs = score if include else 0.0
        result = classify_last_row(_last_row_frame(pvs, include_pvs=include))
        is_pos = include and (score == score) and score > 0
        is_neg = include and (score == score) and score < 0
        assert (SignalType.PRICE_ABOVE_SMA in result) == is_pos
        assert (SignalType.PRICE_BELOW_SMA in result) == is_neg


# ---------------------------------------------------------------------------
# Task 4.3 — daily_signal inline-loop wiring (end-to-end, slow)
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestDailyLoopWiring:
    """The DailySignalGenerator inline loop must emit non-zero price_vs_sma scores.

    Proves task 4.3: the daily path precomputes the SMA series and threads the score
    through ``_extract_feature_vector`` (otherwise the column would be a constant 0.0
    sentinel and the daily signal would be inert for this feature).
    """

    def test_daily_run_emits_price_vs_sma_signal(self, monkeypatch, tmp_path):
        from vpa.ml_validation import daily_signal as ds

        # A strong, steady uptrend so the latest closes sit well above their SMA-10.
        n = 120
        closes = [100.0 + i for i in range(n)]
        frame = pd.DataFrame(
            {
                "Open": closes,
                "High": [c + 1 for c in closes],
                "Low": [c - 1 for c in closes],
                "Close": closes,
                "Volume": [1_000_000] * n,
            },
            index=pd.date_range("2024-01-01", periods=n, freq="D"),
        )
        frame.index.name = "Date"

        monkeypatch.setattr(ds.yf, "download", lambda *a, **k: frame.copy())
        # Run from the repo root so the relative config path resolves.
        monkeypatch.chdir(os.getcwd())

        gen = ds.DailySignalGenerator(output_dir=tmp_path, lookback_days=200, ticker="SPY")
        records = gen.run()

        # In a steady uptrend the final row is above its SMA, so a PRICE_ABOVE_SMA
        # record must be present. SignalRecord.signal_type is the enum *value* (str).
        types = {r.signal_type for r in records}
        assert SignalType.PRICE_ABOVE_SMA.value in types, f"expected price_above_sma in daily records, got {types}"
