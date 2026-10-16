"""Property test: the daily run reproduces the feature extractor's DSS/zone/combo columns.

SP-359, task 2.6 — design "Property 1: Daily run reproduces the feature extractor's
DSS, zone, and combo columns".

``DailySignalGenerator.run`` and ``VPAFeatureExtractor.generate_dataset`` are two
copies of the same rolling-window algorithm (see the design "mirror, don't share"
decision). ``generate_dataset`` cannot be driven directly as the oracle here — it
enforces a 2000-row floor and loads via a ``MarketDataRepository`` — so this test
pins the daily run against a faithful re-derivation of ``generate_dataset``'s
Steps 3b / 9 / 9a / 9c / 9d logic. The DSS half of the oracle calls the *same*
shared ``calculate_dss_bressert`` the production path calls, and reads the DSS
thresholds / periods from the *same* ``config.json``, so the oracle shares the real
arithmetic rather than hard-coding expectations.

The test:
  * generates OHLCV frames long enough to clear the period-three warm-up (50),
  * monkeypatches ``yfinance.download`` so ``run`` is deterministic and offline,
  * captures the feature DataFrame ``run`` builds (by wrapping ``classify_last_row``),
  * asserts every emitted row's four DSS columns and ten combo columns equal the
    oracle for the identical input and configuration.

FAST: pure in-memory frames, no model training, no network. Runs under ``pytest``.
"""

import json

import numpy as np
import pandas as pd
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from vpa.dss_bressert import calculate_dss_bressert
from vpa.ml_validation import daily_signal as ds

_CONFIG_PATH = "vpa/config/config.json"

# The four DSS feature columns and the ten combo columns the daily run must
# reproduce from the feature extractor (design Data Models tables).
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


# ---------------------------------------------------------------------------
# Config access — read the same config.json the daily run reads so the oracle
# shares the real periods / thresholds / warm-up lengths.
# ---------------------------------------------------------------------------


def _load_config() -> dict:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# OHLCV frame generator — realistic enough to drive the full pipeline.
# ---------------------------------------------------------------------------


@st.composite
def _ohlcv_frames(draw) -> pd.DataFrame:
    """Generate an OHLCV frame with >= 60 rows so some rows clear the period-three
    warm-up (50) and the daily run's >= 50 raw-row floor.

    Prices are positive with ``High >= max(Open, Close)`` and ``Low <= min(Open, Close)``
    so the candles are well-formed. Enough variation is injected (via per-row deltas)
    that DSS crossovers and zone flags actually fire across the frame rather than the
    oscillator sitting flat at the neutral sentinel.
    """
    n = draw(st.integers(min_value=60, max_value=90))
    # A random walk of closes keeps the series realistic and gives the oscillator
    # something to cross over. Each step has a non-zero magnitude in one
    # direction so consecutive candles always differ, which guarantees real
    # directional movement and keeps calculate_adx well-defined (it divides by
    # the sum of directional indicators, which is 0 for a perfectly flat series).
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


# ---------------------------------------------------------------------------
# Oracle — re-derive generate_dataset's DSS / zone / combo columns per row.
# ---------------------------------------------------------------------------


def _expected_columns(frame: pd.DataFrame, config: dict) -> dict[int, dict[str, int]]:
    """Return ``{pos: {column: 0/1}}`` for every positional row of ``frame``.

    Mirrors ``VPAFeatureExtractor.generate_dataset`` Steps 3b / 9 / 9a / 9c / 9d
    verbatim: same DSS validity gate, same warm-up, same finite guards, same
    price-vs-SMA flag derivation, and the same combo AND-expressions. The DSS
    series comes from the shared ``calculate_dss_bressert``; the SMA series from
    the identical ``rolling(window=period, min_periods=period).mean()`` the
    production path uses.
    """
    dss_cfg = config["dss_bressert"]
    pvs_cfg = config["price_vs_sma"]

    def _valid_period(value: object) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 500

    def _valid_threshold(value: object) -> bool:
        return isinstance(value, int | float) and not isinstance(value, bool) and 0 <= value <= 100

    dss_enabled = (
        bool(dss_cfg["enabled"])
        and _valid_period(dss_cfg["stochastic_period"])
        and _valid_period(dss_cfg["smoothing_period"])
        and _valid_period(dss_cfg["trigger_period"])
        and _valid_threshold(dss_cfg["oversold_threshold"])
        and _valid_threshold(dss_cfg["overbought_threshold"])
        and dss_cfg["oversold_threshold"] < dss_cfg["overbought_threshold"]
    )

    closes = frame["Close"].tolist()

    dss_osc = None
    dss_trig = None
    dss_warmup = 0
    if dss_enabled:
        dss_osc, dss_trig = calculate_dss_bressert(
            frame["High"].tolist(),
            frame["Low"].tolist(),
            frame["Close"].tolist(),
            dss_cfg["stochastic_period"],
            dss_cfg["smoothing_period"],
            dss_cfg["trigger_period"],
        )
        dss_warmup = dss_cfg["stochastic_period"] + dss_cfg["smoothing_period"] + dss_cfg["trigger_period"] - 2

    pvs_enabled = bool(pvs_cfg["enabled"])
    sma_series = None
    if pvs_enabled:
        sma_series = frame["Close"].rolling(window=pvs_cfg["period"], min_periods=pvs_cfg["period"]).mean().tolist()

    def _isnan(v) -> bool:
        return v != v

    expected: dict[int, dict[str, int]] = {}
    for pos in range(len(frame)):
        # DSS crossover flags (Step 9)
        dss_bullish_cross = 0
        dss_bearish_cross = 0
        if dss_enabled and dss_osc is not None and dss_trig is not None and pos >= dss_warmup and pos > 0:
            current_dss = dss_osc[pos]
            current_trigger = dss_trig[pos]
            previous_dss = dss_osc[pos - 1]
            previous_trigger = dss_trig[pos - 1]
            if all(np.isfinite(v) for v in (current_dss, current_trigger, previous_dss, previous_trigger)):
                dss_bullish_cross = int(previous_dss <= previous_trigger and current_dss > current_trigger)
                dss_bearish_cross = int(previous_dss >= previous_trigger and current_dss < current_trigger)

        # DSS zone flags (Step 9a) — no pos > 0 requirement
        dss_oversold = 0
        dss_overbought = 0
        if dss_enabled and dss_osc is not None and pos >= dss_warmup:
            osc = dss_osc[pos]
            if np.isfinite(osc):
                dss_oversold = int(osc <= dss_cfg["oversold_threshold"])
                dss_overbought = int(osc >= dss_cfg["overbought_threshold"])

        # Price-vs-SMA position + cross flags (Step 9c)
        price_above_sma = 0
        price_below_sma = 0
        price_crossed_above_sma = 0
        price_crossed_below_sma = 0
        if pvs_enabled and sma_series is not None:
            sma = sma_series[pos]
            close = closes[pos]
            if not (_isnan(sma) or _isnan(close)):
                price_above_sma = int(close > sma)
                price_below_sma = int(close < sma)
                if pos > 0:
                    prev_sma = sma_series[pos - 1]
                    prev_close = closes[pos - 1]
                    if not (_isnan(prev_sma) or _isnan(prev_close)):
                        price_crossed_above_sma = int(prev_close <= prev_sma and close > sma)
                        price_crossed_below_sma = int(prev_close >= prev_sma and close < sma)

        # Combo columns (Step 9d)
        expected[pos] = {
            "dss_bullish_cross": dss_bullish_cross,
            "dss_bearish_cross": dss_bearish_cross,
            "dss_oversold": dss_oversold,
            "dss_overbought": dss_overbought,
            "combo_dss_cross_sma_pos_bull": int(dss_bullish_cross and price_above_sma),
            "combo_dss_cross_sma_pos_bear": int(dss_bearish_cross and price_below_sma),
            "combo_dss_cross_sma_cross_bull": int(dss_bullish_cross and price_crossed_above_sma),
            "combo_dss_cross_sma_cross_bear": int(dss_bearish_cross and price_crossed_below_sma),
            "combo_dss_zone_sma_cross_bull": int(dss_oversold and price_crossed_above_sma),
            "combo_dss_zone_sma_cross_bear": int(dss_overbought and price_crossed_below_sma),
            "combo_dss_cross_from_zone_bull": int(dss_bullish_cross and dss_oversold),
            "combo_dss_cross_from_zone_bear": int(dss_bearish_cross and dss_overbought),
            "combo_dss_cross_sma_not_ob_bull": int(dss_bullish_cross and price_above_sma and not dss_overbought),
            "combo_dss_cross_sma_not_ob_bear": int(dss_bearish_cross and price_below_sma and not dss_oversold),
        }

    return expected


# ---------------------------------------------------------------------------
# Capture helper — run the daily pipeline and grab the feature DataFrame it
# builds (the frame passed to classify_last_row), keyed by positional index.
# ---------------------------------------------------------------------------


def _run_and_capture(frame: pd.DataFrame, monkeypatch, tmp_path) -> pd.DataFrame:
    """Run ``DailySignalGenerator.run`` over ``frame`` and return its feature DataFrame.

    ``yfinance.download`` is patched to return the generated frame (with a Date index,
    exactly as yfinance yields it), and ``classify_last_row`` is wrapped to capture the
    ``result_df`` the run assembles so the emitted DSS/combo columns can be inspected.
    """
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


# ---------------------------------------------------------------------------
# Property 1
# ---------------------------------------------------------------------------


class TestPropertyDailyRunReproducesExtractorColumns:
    # Feature: dss-daily-signal-classification, Property 1: For any OHLCV frame long enough to clear the warm-up and any valid DSS configuration, DailySignalGenerator.run produces, for every emitted row, the same dss_bullish_cross, dss_bearish_cross, dss_oversold, dss_overbought, and ten combo_* column values that VPAFeatureExtractor.generate_dataset produces for the same row given identical input and configuration.  # noqa: E501
    # Validates: Requirements 1.1, 1.3, 1.4, 2.1, 2.3, 2.6
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    )
    @given(frame=_ohlcv_frames())
    def test_daily_run_columns_match_feature_extractor(self, frame, monkeypatch, tmp_path):
        config = _load_config()
        expected = _expected_columns(frame, config)

        result_df = _run_and_capture(frame, monkeypatch, tmp_path)

        # Every target column must be present in the emitted feature DataFrame.
        for col in TARGET_COLUMNS:
            assert col in result_df.columns, f"emitted feature frame missing {col}"

        # The daily run emits rows only after the period-three warm-up fills, so map
        # each emitted row back to its positional index in the source frame via Date.
        period_three_length = config["PERIOD_THREE_LENGTH"]
        # ``run`` starts emitting at pos == period_three_length - 1 (deque first full).
        first_emitted_pos = period_three_length - 1
        n_emitted = len(result_df)
        assert n_emitted > 0, "daily run produced no feature rows"

        for i in range(n_emitted):
            pos = first_emitted_pos + i
            exp = expected[pos]
            for col in TARGET_COLUMNS:
                actual = int(result_df.iloc[i][col])
                assert actual == exp[col], (
                    f"row i={i} (pos={pos}) column {col}: daily run emitted {actual}, "
                    f"feature-extractor oracle expected {exp[col]}"
                )
