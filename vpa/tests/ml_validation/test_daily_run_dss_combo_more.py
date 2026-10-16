"""Property and example tests for the daily run's DSS/combo columns (SP-359).

Covers spec tasks 2.7-2.10:

- **Property 2** (2.7): DSS disabled zeroes every DSS and combo column, and
  ``calculate_dss_bressert`` is never called.
- **Property 3** (2.8): pre-warm-up rows carry no DSS or combo signal.
- **Property 4** (2.9): the four DSS and ten combo columns are always integer
  0/1, enabled or disabled.
- Example tests (2.10) for the crossover and combo derivation (Req 7.9, 7.10).

FAST: pure in-memory frames driven through ``DailySignalGenerator.run`` with
``yfinance.download`` monkeypatched; no network, no model training.

# Feature: dss-daily-signal-classification, Properties 2, 3, 4
"""

import json

import pandas as pd
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from vpa.ml_validation import daily_signal as ds

_CONFIG_PATH = "vpa/config/config.json"

DSS_COLUMNS = [
    "dss_bullish_cross",
    "dss_bearish_cross",
    "dss_oversold",
    "dss_overbought",
]

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

TARGET_COLUMNS = DSS_COLUMNS + COMBO_COLUMNS


def _load_config() -> dict:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


@st.composite
def _ohlcv_frames(draw) -> pd.DataFrame:
    """Well-formed OHLCV frame with >= 60 rows (clears the period-three warm-up)."""
    n = draw(st.integers(min_value=60, max_value=90))
    # Each step moves the close by a magnitude of at least 0.5 in one direction,
    # so consecutive candles always differ. This guarantees real directional
    # movement, which keeps calculate_adx well-defined (it divides by the sum of
    # directional indicators, which is 0 for a perfectly flat/zero-DM series).
    steps = draw(
        st.lists(
            st.tuples(
                st.sampled_from([-1.0, 1.0]),
                st.floats(min_value=0.5, max_value=6.0, allow_nan=False, allow_infinity=False),
            ),
            min_size=n,
            max_size=n,
        )
    )
    closes: list[float] = []
    price = 100.0
    for direction, magnitude in steps:
        price = max(5.0, price + direction * magnitude)
        closes.append(round(price, 4))

    rows = []
    for i, close in enumerate(closes):
        open_ = closes[i - 1] if i > 0 else close
        spread = draw(st.floats(min_value=0.5, max_value=4.0, allow_nan=False, allow_infinity=False))
        high = max(open_, close) + spread
        low = max(1.0, min(open_, close) - spread)
        volume = draw(st.integers(min_value=100_000, max_value=5_000_000))
        rows.append((open_, high, low, close, volume))

    frame = pd.DataFrame(
        rows,
        columns=["Open", "High", "Low", "Close", "Volume"],
        index=pd.date_range("2020-01-01", periods=n, freq="D"),
    )
    frame.index.name = "Date"
    return frame


def _run_and_capture(frame: pd.DataFrame, monkeypatch, tmp_path) -> pd.DataFrame:
    """Run the daily pipeline and return the feature DataFrame it builds."""
    monkeypatch.setattr(ds.yf, "download", lambda *a, **k: frame.copy())

    captured: dict[str, pd.DataFrame] = {}
    original = ds.classify_last_row

    def _capture(result_df):
        captured["df"] = result_df
        return original(result_df)

    monkeypatch.setattr(ds, "classify_last_row", _capture)

    generator = ds.DailySignalGenerator(output_dir=tmp_path, lookback_days=400, ticker="SPY")
    generator.run()
    return captured["df"]


def _disable_dss(monkeypatch) -> dict:
    """Patch VPAFeatureExtractor so its config has dss_bressert disabled.

    The settings dataclasses are frozen, so we rebuild the extractor's ``_config``
    with ``dataclasses.replace`` after construction rather than mutating in place.
    Returns a dict counter recording how many times ``calculate_dss_bressert`` was
    called (it must stay 0 when DSS is disabled).
    """
    import dataclasses

    import vpa.dss_bressert as dssmod
    from vpa.ml_validation.feature_extractor import VPAFeatureExtractor

    called = {"count": 0}
    real = dssmod.calculate_dss_bressert

    def _spy(*a, **k):
        called["count"] += 1
        return real(*a, **k)

    # daily_signal.run imports calculate_dss_bressert lazily from the module, so
    # patching the module attribute intercepts the production call site.
    monkeypatch.setattr(dssmod, "calculate_dss_bressert", _spy)

    original_init = VPAFeatureExtractor.__init__

    def _patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        disabled_dss = dataclasses.replace(self._config.dss_bressert, enabled=False)
        self._config = dataclasses.replace(self._config, dss_bressert=disabled_dss)

    monkeypatch.setattr(VPAFeatureExtractor, "__init__", _patched_init)
    return called


# ---------------------------------------------------------------------------
# Property 2 (task 2.7): DSS disabled zeroes everything, never calls the calc
# ---------------------------------------------------------------------------


class TestProperty2DSSDisabled:
    # Feature: dss-daily-signal-classification, Property 2: DSS disabled zeroes every DSS and combo column
    # Validates: Requirements 1.5, 2.4
    @settings(
        max_examples=40,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    )
    @given(frame=_ohlcv_frames())
    def test_disabled_zeroes_all_and_never_calls_calc(self, frame, monkeypatch, tmp_path):
        called = _disable_dss(monkeypatch)
        result_df = _run_and_capture(frame, monkeypatch, tmp_path)

        for col in TARGET_COLUMNS:
            assert col in result_df.columns, f"missing {col}"
            assert (result_df[col] == 0).all(), f"{col} not all zero when DSS disabled"

        assert called["count"] == 0, "calculate_dss_bressert called while DSS disabled"


# ---------------------------------------------------------------------------
# Property 3 (task 2.8): pre-warm-up rows carry no DSS or combo signal
# ---------------------------------------------------------------------------


class TestProperty3PreWarmup:
    # Feature: dss-daily-signal-classification, Property 3: Pre-warm-up rows carry no DSS or combo signal
    # Validates: Requirements 1.6, 2.2
    @settings(
        max_examples=40,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    )
    @given(frame=_ohlcv_frames())
    def test_pre_warmup_rows_are_zero(self, frame, monkeypatch, tmp_path):
        config = _load_config()
        dss_cfg = config["dss_bressert"]
        dss_warmup = dss_cfg["stochastic_period"] + dss_cfg["smoothing_period"] + dss_cfg["trigger_period"] - 2

        result_df = _run_and_capture(frame, monkeypatch, tmp_path)

        # The daily run starts emitting at pos == PERIOD_THREE_LENGTH - 1.
        first_emitted_pos = config["PERIOD_THREE_LENGTH"] - 1
        for i in range(len(result_df)):
            pos = first_emitted_pos + i
            if pos < dss_warmup:
                for col in TARGET_COLUMNS:
                    assert (
                        int(result_df.iloc[i][col]) == 0
                    ), f"row i={i} pos={pos} (< warmup {dss_warmup}) column {col} nonzero"


# ---------------------------------------------------------------------------
# Property 4 (task 2.9): columns are always integer 0/1, enabled or disabled
# ---------------------------------------------------------------------------


class TestProperty4AlwaysZeroOrOne:
    # Feature: dss-daily-signal-classification, Property 4: DSS and combo columns are always 0 or 1 integers
    # Validates: Requirements 1.7, 2.5
    @settings(
        max_examples=40,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    )
    @given(frame=_ohlcv_frames(), disable=st.booleans())
    def test_values_are_zero_or_one_integers(self, frame, disable, monkeypatch, tmp_path):
        if disable:
            _disable_dss(monkeypatch)
        result_df = _run_and_capture(frame, monkeypatch, tmp_path)

        for col in TARGET_COLUMNS:
            for value in result_df[col].tolist():
                assert int(value) == value, f"{col} value {value!r} is not integral"
                assert int(value) in (0, 1), f"{col} value {value!r} not in (0, 1)"


# ---------------------------------------------------------------------------
# Example tests (task 2.10): crossover and combo derivation (Req 7.9, 7.10)
# ---------------------------------------------------------------------------


class TestDailyRunColumnExamples:
    def _make_frame(self, n: int = 70) -> pd.DataFrame:
        # Deterministic oscillating series so some crossovers/zones fire.
        closes = []
        price = 100.0
        for i in range(n):
            price += 8.0 if (i // 3) % 2 == 0 else -8.0
            closes.append(max(10.0, round(price, 2)))
        rows = []
        for i, close in enumerate(closes):
            open_ = closes[i - 1] if i > 0 else close
            high = max(open_, close) + 1.0
            low = min(open_, close) - 1.0
            rows.append((open_, high, low, close, 1_000_000))
        frame = pd.DataFrame(
            rows,
            columns=["Open", "High", "Low", "Close", "Volume"],
            index=pd.date_range("2020-01-01", periods=n, freq="D"),
        )
        frame.index.name = "Date"
        return frame

    def test_enabled_frame_emits_binary_dss_and_combo_columns(self, monkeypatch, tmp_path):
        # Req 7.9 / 7.10: enabled run yields present, binary columns.
        frame = self._make_frame()
        result_df = _run_and_capture(frame, monkeypatch, tmp_path)
        for col in TARGET_COLUMNS:
            assert col in result_df.columns
            assert set(result_df[col].astype(int).unique()).issubset({0, 1})

    def test_disabled_frame_zeroes_dss_and_combo_columns(self, monkeypatch, tmp_path):
        # Req 7.9 / 7.10: disabled run zeroes every DSS and combo column.
        _disable_dss(monkeypatch)
        frame = self._make_frame()
        result_df = _run_and_capture(frame, monkeypatch, tmp_path)
        for col in TARGET_COLUMNS:
            assert (result_df[col] == 0).all()

    def test_combo_columns_respect_and_expressions(self, monkeypatch, tmp_path):
        # Req 7.10: every combo column equals the AND of its driver flags, row by row.
        frame = self._make_frame()
        result_df = _run_and_capture(frame, monkeypatch, tmp_path)

        def col(name):
            return result_df[name].astype(int).tolist()

        bull_cross = col("dss_bullish_cross")
        bear_cross = col("dss_bearish_cross")
        oversold = col("dss_oversold")
        overbought = col("dss_overbought")
        # Price-vs-SMA flags are not emitted as standalone columns in result_df,
        # so validate only the combo expressions that depend solely on DSS flags.
        from_zone_bull = col("combo_dss_cross_from_zone_bull")
        from_zone_bear = col("combo_dss_cross_from_zone_bear")

        for i in range(len(result_df)):
            assert from_zone_bull[i] == int(bull_cross[i] and oversold[i])
            assert from_zone_bear[i] == int(bear_cross[i] and overbought[i])
