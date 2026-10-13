"""VPA Feature Extractor - extracts structured feature vectors from MarketAnalyzer."""

import datetime
from collections import deque

import numpy as np
import pandas as pd

from vpa.app import Candle, calculate_adx, identify_acc_or_dist
from vpa.config import load_settings
from vpa.market_data.repository import MarketDataRepository
from vpa.ml_validation.exceptions import InsufficientDataError
from vpa.ml_validation.tuning.scoring_params import ScoringParams
from vpa.rsi import calculate_rsi


def _pvs_isnan(value) -> bool:
    """NaN check that works on plain floats and numpy floats without pandas."""
    return value != value


def compute_price_vs_sma_feature(
    close,
    sma_value,
    prev_close,
    prev_sma,
    pvs_cfg,
    *,
    enabled: bool,
    has_previous: bool,
) -> tuple[float, float]:
    """Pure price-vs-SMA feature computation (SP-340).

    Reproduces ``MarketAnalyzer.detect_price_vs_sma_signals`` branch-for-branch:
    a position-based score (close vs the current SMA) plus an optional crossover
    term when ``pvs_cfg.detect_crossover`` is set and a valid previous row exists.

    Returns ``(price_vs_sma_value, price_vs_sma_signal_score)``. When the signal
    is disabled or the current SMA/close is unavailable (NaN), returns the neutral
    sentinel value ``50.0`` (mirroring ``rsi_value``) and a score of ``0.0``.

    This is a pure function of its scalar inputs and the config, so it can be unit-
    and property-tested in microseconds without driving the full extraction path.
    """
    price_vs_sma_value = 50.0
    price_vs_sma_signal_score = 0.0

    if not enabled:
        return price_vs_sma_value, price_vs_sma_signal_score
    if _pvs_isnan(sma_value) or _pvs_isnan(close):
        return price_vs_sma_value, price_vs_sma_signal_score

    price_vs_sma_value = float(sma_value)

    # Position-based (Req 3.3-3.5, 3.7)
    if close > sma_value:
        price_vs_sma_signal_score += float(pvs_cfg.scores.above)
    elif close < sma_value:
        price_vs_sma_signal_score -= float(pvs_cfg.scores.below)

    # Optional crossover (Req 3.8-3.12), requires a valid previous row
    if pvs_cfg.detect_crossover and has_previous and not (_pvs_isnan(prev_sma) or _pvs_isnan(prev_close)):
        if prev_close <= prev_sma and close > sma_value:
            price_vs_sma_signal_score += float(pvs_cfg.crossover_scores.cross_above)
        elif prev_close >= prev_sma and close < sma_value:
            price_vs_sma_signal_score -= float(pvs_cfg.crossover_scores.cross_below)

    return price_vs_sma_value, price_vs_sma_signal_score


class VPAFeatureExtractor:
    """Extracts VPA intermediate features as a structured vector for ML analysis."""

    # Fixed column order for the 33-feature vector
    FEATURE_COLUMNS = [
        "spread_pct_p1",
        "spread_pct_p2",
        "spread_pct_p3",
        "volume_pct_p1",
        "volume_pct_p2",
        "volume_pct_p3",
        "adx",
        "dm_plus_smooth",
        "dm_minus_smooth",
        "avg_true_range",
        "up_bar_ratio_p1",
        "up_bar_ratio_p2",
        "up_bar_ratio_p3",
        "is_shooting_star",
        "is_hammer",
        "is_long_legged_doji",
        "vol_backed_p1",
        "vol_backed_p2",
        "vol_backed_p3",
        "acc_dist_flag",
        "acc_dist_type",
        "single_candle_score",
        "trend_score",
        "multiple_bar_score",
        "acc_dist_score",
        "rsi_value",
        "rsi_signal_score",
        "price_vs_sma_value",
        "price_vs_sma_signal_score",
        "dss_bullish_cross",
        "dss_bearish_cross",
        "dss_oversold",
        "dss_overbought",
        "price_above_sma",
        "price_below_sma",
        "price_crossed_above_sma",
        "price_crossed_below_sma",
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
        "composite_score",
        "up_bar_current",
    ]

    # Metadata columns (excluded from the numeric feature array)
    # SP-335: add raw open/high/low alongside close
    METADATA_COLUMNS = ["date", "open", "high", "low", "close"]

    def __init__(
        self,
        config_path: str,
        ticker_symbol: str,
        enable_extraction: bool = True,
        scoring_params: ScoringParams | None = None,
    ):
        """
        Args:
            config_path: Path to the VPA config JSON.
            ticker_symbol: Ticker to analyse (e.g. "SPY").
            enable_extraction: If False, delegates to MarketAnalyzer with no extraction.
            scoring_params: Injectable VPA scoring thresholds (SP-313). When
                ``None``, defaults to ``ScoringParams.default()`` so the
                extraction path reproduces current production scoring exactly
                (Property 1).
        """
        self._config_path = config_path
        self._ticker_symbol = ticker_symbol
        self._enable_extraction = enable_extraction
        self._scoring_params = scoring_params if scoring_params is not None else ScoringParams.default()

        self._config = load_settings(config_path)

        # Store period lengths for up_bar_ratio calculations
        self._period_one_length = self._config.period_one_length
        self._period_two_length = self._config.period_two_length
        self._period_three_length = self._config.period_three_length

    def _extract_feature_vector(
        self,
        candle,
        signals: dict,
        adx_values: list,
        acc_dist_result: tuple,
        deque_dictionary: dict,
        dss_bullish_cross: int = 0,
        dss_bearish_cross: int = 0,
        dss_oversold: int = 0,
        dss_overbought: int = 0,
        price_above_sma: int = 0,
        price_below_sma: int = 0,
        price_crossed_above_sma: int = 0,
        price_crossed_below_sma: int = 0,
        combo_dss_cross_sma_pos_bull: int = 0,
        combo_dss_cross_sma_pos_bear: int = 0,
        combo_dss_cross_sma_cross_bull: int = 0,
        combo_dss_cross_sma_cross_bear: int = 0,
        combo_dss_zone_sma_cross_bull: int = 0,
        combo_dss_zone_sma_cross_bear: int = 0,
        combo_dss_cross_from_zone_bull: int = 0,
        combo_dss_cross_from_zone_bear: int = 0,
        combo_dss_cross_sma_not_ob_bull: int = 0,
        combo_dss_cross_sma_not_ob_bear: int = 0,
        price_vs_sma_value: float = 50.0,
        price_vs_sma_signal_score: float = 0.0,
    ) -> dict:
        """
        Build a single feature vector dict from intermediate MarketAnalyzer state.

        Args:
            candle: The current Candle object with spread/volume percentiles set.
            signals: The all_signals dict returned by detect_signals(), containing
                     keys like "single_candle_signal_score", "trend_signal_score",
                     "multiple_bar_signal_score", "acc_dist_signal_score",
                     and "multiple_bar_signals" (list of signal name strings).
            adx_values: List from calculate_adx() - [adx, avg_true_range, dm_plus, dm_minus].
            acc_dist_result: Tuple from identify_acc_or_dist() - (bool, str).
            deque_dictionary: Dict of period deques containing Candle objects.

        Returns:
            A dict with fixed column names and numeric values, containing all 33
            feature columns in the order defined by FEATURE_COLUMNS.
        """
        # Spread percentiles
        spread_pct_p1 = float(candle.spread_percentiles.get("period_one", 0))
        spread_pct_p2 = float(candle.spread_percentiles.get("period_two", 0))
        spread_pct_p3 = float(candle.spread_percentiles.get("period_three", 0))

        # Volume percentiles
        volume_pct_p1 = float(candle.volume_percentiles.get("period_one", 0))
        volume_pct_p2 = float(candle.volume_percentiles.get("period_two", 0))
        volume_pct_p3 = float(candle.volume_percentiles.get("period_three", 0))

        # ADX values: [adx, avg_true_range, dm_plus_smooth, dm_minus_smooth]
        adx_val = float(adx_values[0])
        dm_plus_smooth = float(adx_values[2])
        dm_minus_smooth = float(adx_values[3])
        avg_true_range = float(adx_values[1])

        # Up bar ratios for each period
        period_one_deque = deque_dictionary["period_one"]
        period_two_deque = deque_dictionary["period_two"]
        period_three_deque = deque_dictionary["period_three"]

        up_bar_ratio_p1 = (
            sum(1 for c in period_one_deque if c.up_bar) / len(period_one_deque) if len(period_one_deque) > 0 else 0.0
        )
        up_bar_ratio_p2 = (
            sum(1 for c in period_two_deque if c.up_bar) / len(period_two_deque) if len(period_two_deque) > 0 else 0.0
        )
        up_bar_ratio_p3 = (
            sum(1 for c in period_three_deque if c.up_bar) / len(period_three_deque)
            if len(period_three_deque) > 0
            else 0.0
        )

        # Candle pattern flags (0 or 1)
        is_shooting_star = int(candle.shooting_star)
        is_hammer = int(candle.hammer)
        is_long_legged_doji = int(candle.lld)

        # Volume-backed signals - extracted from the multiple_bar_signals list
        multiple_bar_signals = signals.get("multiple_bar_signals", [])
        vol_backed_p1 = 1 if "Volume Backed (period_one)" in multiple_bar_signals else 0
        vol_backed_p2 = 1 if "Volume Backed (period_two)" in multiple_bar_signals else 0
        vol_backed_p3 = 1 if "Volume Backed (period_three)" in multiple_bar_signals else 0

        # Accumulation/distribution
        acc_dist_flag = int(acc_dist_result[0])
        if acc_dist_result[0] and acc_dist_result[1] == "Acc":
            acc_dist_type = 1
        elif acc_dist_result[0] and acc_dist_result[1] == "Dist":
            acc_dist_type = -1
        else:
            acc_dist_type = 0

        # Sub-scores from signals
        single_candle_score = float(signals.get("single_candle_signal_score", 0))
        trend_score = float(signals.get("trend_signal_score", 0))
        multiple_bar_score = float(signals.get("multiple_bar_signal_score", 0))
        acc_dist_score = float(signals.get("acc_dist_signal_score", 0))

        # RSI calculation
        rsi_config = self._config.rsi
        rsi_enabled = rsi_config.enabled

        if rsi_enabled:
            period_three_closes = [c.close for c in deque_dictionary["period_three"]]
            rsi_period = rsi_config.period
            rsi_value = calculate_rsi(period_three_closes, rsi_period)

            # RSI signal score using same threshold logic as MarketAnalyzer
            overbought = rsi_config.overbought_threshold
            oversold = rsi_config.oversold_threshold
            scores = rsi_config.scores

            rsi_signal_score = 0.0
            if rsi_value > overbought:
                rsi_signal_score = float(scores.overbought)
            elif rsi_value < oversold:
                rsi_signal_score = float(scores.oversold)
        else:
            rsi_value = 50.0
            rsi_signal_score = 0.0

        # Composite score is sum of all sub-scores including RSI
        composite_score = single_candle_score + trend_score + multiple_bar_score + acc_dist_score + rsi_signal_score

        # Current candle direction
        up_bar_current = int(candle.up_bar)

        # Build the feature vector in fixed column order
        feature_vector = {
            "spread_pct_p1": spread_pct_p1,
            "spread_pct_p2": spread_pct_p2,
            "spread_pct_p3": spread_pct_p3,
            "volume_pct_p1": volume_pct_p1,
            "volume_pct_p2": volume_pct_p2,
            "volume_pct_p3": volume_pct_p3,
            "adx": adx_val,
            "dm_plus_smooth": dm_plus_smooth,
            "dm_minus_smooth": dm_minus_smooth,
            "avg_true_range": avg_true_range,
            "up_bar_ratio_p1": up_bar_ratio_p1,
            "up_bar_ratio_p2": up_bar_ratio_p2,
            "up_bar_ratio_p3": up_bar_ratio_p3,
            "is_shooting_star": is_shooting_star,
            "is_hammer": is_hammer,
            "is_long_legged_doji": is_long_legged_doji,
            "vol_backed_p1": vol_backed_p1,
            "vol_backed_p2": vol_backed_p2,
            "vol_backed_p3": vol_backed_p3,
            "acc_dist_flag": acc_dist_flag,
            "acc_dist_type": acc_dist_type,
            "single_candle_score": single_candle_score,
            "trend_score": trend_score,
            "multiple_bar_score": multiple_bar_score,
            "acc_dist_score": acc_dist_score,
            "rsi_value": rsi_value,
            "rsi_signal_score": rsi_signal_score,
            "price_vs_sma_value": price_vs_sma_value,
            "price_vs_sma_signal_score": price_vs_sma_signal_score,
            "dss_bullish_cross": int(dss_bullish_cross),
            "dss_bearish_cross": int(dss_bearish_cross),
            "dss_oversold": int(dss_oversold),
            "dss_overbought": int(dss_overbought),
            "price_above_sma": int(price_above_sma),
            "price_below_sma": int(price_below_sma),
            "price_crossed_above_sma": int(price_crossed_above_sma),
            "price_crossed_below_sma": int(price_crossed_below_sma),
            "combo_dss_cross_sma_pos_bull": int(combo_dss_cross_sma_pos_bull),
            "combo_dss_cross_sma_pos_bear": int(combo_dss_cross_sma_pos_bear),
            "combo_dss_cross_sma_cross_bull": int(combo_dss_cross_sma_cross_bull),
            "combo_dss_cross_sma_cross_bear": int(combo_dss_cross_sma_cross_bear),
            "combo_dss_zone_sma_cross_bull": int(combo_dss_zone_sma_cross_bull),
            "combo_dss_zone_sma_cross_bear": int(combo_dss_zone_sma_cross_bear),
            "combo_dss_cross_from_zone_bull": int(combo_dss_cross_from_zone_bull),
            "combo_dss_cross_from_zone_bear": int(combo_dss_cross_from_zone_bear),
            "combo_dss_cross_sma_not_ob_bull": int(combo_dss_cross_sma_not_ob_bull),
            "combo_dss_cross_sma_not_ob_bear": int(combo_dss_cross_sma_not_ob_bear),
            "composite_score": composite_score,
            "up_bar_current": up_bar_current,
        }

        return feature_vector

    def generate_dataset(
        self,
        days: int = 3650,
        repo: MarketDataRepository | None = None,
        end_date: datetime.date | str | None = None,
    ) -> pd.DataFrame:
        """
        Load OHLCV data via the market-data store and produce a labelled feature dataset.

        Sources at least ``days`` calendar days of daily data for
        self._ticker_symbol from the market-data repository (read-through: the
        store serves stored bars and fetches only the missing tail), processes
        each row through the VPA logic (replicating MarketAnalyzer behaviour),
        extracts feature vectors once rolling windows are full, labels each row
        with next-day price direction, and returns the resulting DataFrame.

        Args:
            days: Calendar days of data to load (default 3650 = ~10 years).
            repo: Optional ``MarketDataRepository`` for dependency injection in
                tests. Defaults to a new ``MarketDataRepository()``.
            end_date: Optional end of the data window (SP-313, Req 1.4). When
                ``None`` (the default), uses ``datetime.datetime.now().date()``,
                preserving the current behaviour exactly. When an explicit value
                is given it pins the window end so re-runs over the same window
                are reproducible; the start is always
                ``end_date - timedelta(days=days)``. Accepts either a
                ``datetime.date`` (the canonical type) or an ISO date string
                (``YYYY-MM-DD``), which is parsed to a ``datetime.date``.

        Returns:
            DataFrame with one row per trading day (after warm-up), containing
            all 33 feature columns, metadata columns (date, close), and the
            next_day_direction label. The final row is excluded (no next-day label).

        Raises:
            InsufficientDataError: If fewer than 2000 valid labelled rows after
                warm-up and final-row exclusion.
        """
        # --- Step 1: Load data via the market-data repository (read-through) ---
        # The loader returns the canonical Date,Open,High,Low,Close,Volume DataFrame
        # already flattened/renamed/dropna'd/sorted, so no inline normalisation is needed.
        #
        # SP-313 (Req 1.4): resolve the window end. ``None`` preserves the legacy
        # "today" behaviour exactly; an explicit date (or ISO string) pins the
        # window so the experiment layer can re-run reproducibly.
        if end_date is None:
            end_date = datetime.datetime.now().date()
        elif isinstance(end_date, str):
            end_date = datetime.date.fromisoformat(end_date)
        start_date = end_date - datetime.timedelta(days=days)

        if repo is None:
            repo = MarketDataRepository()
        df = repo.load_ohlcv(self._ticker_symbol, "1d", start_date, end_date)

        # --- Step 3b: Pre-compute DSS Bressert oscillator/trigger over the whole frame ---
        # Mirrors MarketAnalyzer.compute_dss_bressert_columns + _init_dss_bressert_config:
        # only enabled when the flag is true AND periods are ints in 1..500 AND
        # thresholds are numbers in 0..100 with oversold < overbought. When not valid,
        # dss_osc/dss_trig stay None and the crossover columns are 0 for every row.
        dss_osc: list[float] | None = None
        dss_trig: list[float] | None = None
        dss_warmup = 0
        dss_cfg = self._config.dss_bressert

        def _valid_period(value: object) -> bool:
            return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 500

        def _valid_threshold(value: object) -> bool:
            return isinstance(value, int | float) and not isinstance(value, bool) and 0 <= value <= 100

        dss_enabled = (
            bool(dss_cfg.enabled)
            and _valid_period(dss_cfg.stochastic_period)
            and _valid_period(dss_cfg.smoothing_period)
            and _valid_period(dss_cfg.trigger_period)
            and _valid_threshold(dss_cfg.oversold_threshold)
            and _valid_threshold(dss_cfg.overbought_threshold)
            and dss_cfg.oversold_threshold < dss_cfg.overbought_threshold
        )

        if dss_enabled:
            from vpa.dss_bressert import calculate_dss_bressert

            dss_osc, dss_trig = calculate_dss_bressert(
                df["High"].tolist(),
                df["Low"].tolist(),
                df["Close"].tolist(),
                dss_cfg.stochastic_period,
                dss_cfg.smoothing_period,
                dss_cfg.trigger_period,
            )
            dss_warmup = dss_cfg.stochastic_period + dss_cfg.smoothing_period + dss_cfg.trigger_period - 2

        # --- Step 3c: Pre-compute the price-vs-SMA series over the whole frame ---
        # Mirrors MarketAnalyzer.compute_price_vs_sma_column exactly:
        # rolling(window=period, min_periods=period).mean(), so the first
        # ``period - 1`` rows are NaN (warm-up, no partial-window SMA). Gated on
        # the ``enabled`` flag; when disabled, sma_series stays None and every
        # row emits a 0.0 score with the neutral value sentinel. ``closes`` is
        # kept as a list for O(1) previous-row access by positional ``pos``,
        # consistent with how the DSS block indexes dss_osc/dss_trig.
        pvs_cfg = self._config.price_vs_sma
        pvs_enabled = bool(pvs_cfg.enabled)
        sma_series: list[float] | None = None
        closes = df["Close"].tolist()
        if pvs_enabled:
            sma_series = df["Close"].rolling(window=pvs_cfg.period, min_periods=pvs_cfg.period).mean().tolist()

        # --- Step 4: Set up rolling deques ---
        deque_dictionary = {
            "period_one": deque(maxlen=self._period_one_length),
            "period_two": deque(maxlen=self._period_two_length),
            "period_three": deque(maxlen=self._period_three_length),
        }

        # Percentile storage (mirrors MarketAnalyzer.__percentiles_store)
        percentiles_store = {"spread": {}, "volume": {}}

        percentile_start = self._config.percentile_start
        percentile_increments = self._config.percentile_increments

        # --- Step 5: Process each row ---
        feature_rows = []
        previous_close = 0

        for pos, (_, row) in enumerate(df.iterrows()):
            # Create Candle (matching MarketAnalyzer open-price logic)
            if previous_close != 0:
                open_price = previous_close
            else:
                open_price = float(row["Open"])

            high = max(float(row["High"]), open_price)
            low = min(float(row["Low"]), open_price)

            this_candle = Candle(
                row["Date"],
                float(row["Volume"]),
                open_price,
                high,
                low,
                float(row["Close"]),
                shooting_star_spread_mult=self._scoring_params.shooting_star_spread_mult,
                shooting_star_lower_wick_mult=self._scoring_params.shooting_star_lower_wick_mult,
            )
            previous_close = this_candle.close

            # Add to all rolling windows
            for key in deque_dictionary:
                deque_dictionary[key].append(this_candle)

            # Skip until period_three is full (warm-up)
            if len(deque_dictionary["period_three"]) < self._period_three_length:
                continue

            # --- Step 6: Update percentiles (replicates MarketAnalyzer.update_percentiles) ---
            props = ["spread", "volume"]
            for prop in props:
                for key in deque_dictionary:
                    stats_list = [getattr(item, prop) for item in deque_dictionary[key]]
                    percentiles_store[prop][key] = np.percentile(
                        stats_list,
                        list(range(percentile_start, 100, percentile_increments)),
                    )

            # Assign percentiles to candles in each deque
            for key in deque_dictionary:
                for candle in deque_dictionary[key]:
                    for prop in props:
                        upper_percentile = percentile_start
                        for step in percentiles_store[prop][key]:
                            if getattr(candle, prop) <= step:
                                upper_percentile += percentile_increments
                        if prop == "spread":
                            candle.spread_percentiles[key] = upper_percentile
                        elif prop == "volume":
                            candle.volume_percentiles[key] = upper_percentile

            # --- Step 7: Detect signals (replicates MarketAnalyzer.detect_signals) ---
            signals = self._detect_signals(this_candle, deque_dictionary)

            # --- Step 8: Calculate ADX ---
            adx_values = calculate_adx(list(deque_dictionary["period_three"]))

            # --- Step 9: Identify accumulation/distribution ---
            acc_dist_result = identify_acc_or_dist(
                list(deque_dictionary["period_three"]),
                list(deque_dictionary["period_one"]),
                volume_percentile=self._scoring_params.acc_dist_volume_percentile,
                test_count=self._scoring_params.acc_dist_test_count,
            )

            dss_bullish_cross = 0
            dss_bearish_cross = 0
            if dss_enabled and dss_osc is not None and dss_trig is not None and pos >= dss_warmup and pos > 0:
                current_dss = dss_osc[pos]
                current_trigger = dss_trig[pos]
                previous_dss = dss_osc[pos - 1]
                previous_trigger = dss_trig[pos - 1]
                if all(np.isfinite(value) for value in (current_dss, current_trigger, previous_dss, previous_trigger)):
                    dss_bullish_cross = int(previous_dss <= previous_trigger and current_dss > current_trigger)
                    dss_bearish_cross = int(previous_dss >= previous_trigger and current_dss < current_trigger)

            # --- Step 9a: DSS zone flags (oversold/overbought) ---
            # From the oscillator vs the configured thresholds, guarded by the
            # same dss_enabled / warmup / finite checks as the cross block above.
            # Zone flags do not need pos > 0 (no previous row dependency).
            dss_oversold = 0
            dss_overbought = 0
            if dss_enabled and dss_osc is not None and pos >= dss_warmup:
                osc = dss_osc[pos]
                if np.isfinite(osc):
                    dss_oversold = int(osc <= dss_cfg.oversold_threshold)
                    dss_overbought = int(osc >= dss_cfg.overbought_threshold)

            # --- Step 9b: Price-vs-SMA position + optional crossover score ---
            # Delegates to the pure ``compute_price_vs_sma_feature`` helper so the
            # scoring logic is independently unit/property-testable without driving
            # the full extraction path. Warm-up / disabled / NaN all yield score
            # 0.0 with the value sentinel.
            if pvs_enabled and sma_series is not None:
                prev_sma = sma_series[pos - 1] if pos > 0 else float("nan")
                prev_close = closes[pos - 1] if pos > 0 else float("nan")
                price_vs_sma_value, price_vs_sma_signal_score = compute_price_vs_sma_feature(
                    closes[pos],
                    sma_series[pos],
                    prev_close,
                    prev_sma,
                    pvs_cfg,
                    enabled=True,
                    has_previous=pos > 0,
                )
            else:
                price_vs_sma_value = 50.0
                price_vs_sma_signal_score = 0.0

            # --- Step 9c: Price-vs-SMA position + cross flags ---
            # From close vs SMA (and prev-vs-curr for the crosses), guarded by the
            # same pvs_enabled / NaN checks as compute_price_vs_sma_feature.
            price_above_sma = 0
            price_below_sma = 0
            price_crossed_above_sma = 0
            price_crossed_below_sma = 0
            if pvs_enabled and sma_series is not None:
                sma = sma_series[pos]
                close = closes[pos]
                if not (_pvs_isnan(sma) or _pvs_isnan(close)):
                    price_above_sma = int(close > sma)
                    price_below_sma = int(close < sma)
                    if pos > 0:
                        prev_sma = sma_series[pos - 1]
                        prev_close = closes[pos - 1]
                        if not (_pvs_isnan(prev_sma) or _pvs_isnan(prev_close)):
                            price_crossed_above_sma = int(prev_close <= prev_sma and close > sma)
                            price_crossed_below_sma = int(prev_close >= prev_sma and close < sma)

            # --- Step 9d: Combined (confluence) columns derived from the eight flags ---
            # Each is the AND of the relevant flags per the design table (§5.2). The
            # two three-way columns include the negation of the DSS zone flag,
            # mirroring the live absence-condition semantics (Req 2.7, 2.8). These
            # are NOT folded into composite_score (SP-340 zero-regression rule).
            combo_dss_cross_sma_pos_bull = int(dss_bullish_cross and price_above_sma)
            combo_dss_cross_sma_pos_bear = int(dss_bearish_cross and price_below_sma)
            combo_dss_cross_sma_cross_bull = int(dss_bullish_cross and price_crossed_above_sma)
            combo_dss_cross_sma_cross_bear = int(dss_bearish_cross and price_crossed_below_sma)
            combo_dss_zone_sma_cross_bull = int(dss_oversold and price_crossed_above_sma)
            combo_dss_zone_sma_cross_bear = int(dss_overbought and price_crossed_below_sma)
            combo_dss_cross_from_zone_bull = int(dss_bullish_cross and dss_oversold)
            combo_dss_cross_from_zone_bear = int(dss_bearish_cross and dss_overbought)
            combo_dss_cross_sma_not_ob_bull = int(dss_bullish_cross and price_above_sma and not dss_overbought)
            combo_dss_cross_sma_not_ob_bear = int(dss_bearish_cross and price_below_sma and not dss_oversold)

            # --- Step 10: Extract feature vector ---
            feature_vector = self._extract_feature_vector(
                candle=this_candle,
                signals=signals,
                adx_values=adx_values,
                acc_dist_result=acc_dist_result,
                deque_dictionary=deque_dictionary,
                dss_bullish_cross=dss_bullish_cross,
                dss_bearish_cross=dss_bearish_cross,
                dss_oversold=dss_oversold,
                dss_overbought=dss_overbought,
                price_above_sma=price_above_sma,
                price_below_sma=price_below_sma,
                price_crossed_above_sma=price_crossed_above_sma,
                price_crossed_below_sma=price_crossed_below_sma,
                combo_dss_cross_sma_pos_bull=combo_dss_cross_sma_pos_bull,
                combo_dss_cross_sma_pos_bear=combo_dss_cross_sma_pos_bear,
                combo_dss_cross_sma_cross_bull=combo_dss_cross_sma_cross_bull,
                combo_dss_cross_sma_cross_bear=combo_dss_cross_sma_cross_bear,
                combo_dss_zone_sma_cross_bull=combo_dss_zone_sma_cross_bull,
                combo_dss_zone_sma_cross_bear=combo_dss_zone_sma_cross_bear,
                combo_dss_cross_from_zone_bull=combo_dss_cross_from_zone_bull,
                combo_dss_cross_from_zone_bear=combo_dss_cross_from_zone_bear,
                combo_dss_cross_sma_not_ob_bull=combo_dss_cross_sma_not_ob_bull,
                combo_dss_cross_sma_not_ob_bear=combo_dss_cross_sma_not_ob_bear,
                price_vs_sma_value=price_vs_sma_value,
                price_vs_sma_signal_score=price_vs_sma_signal_score,
            )

            # Add metadata
            date_val = row["Date"]
            if hasattr(date_val, "isoformat"):
                date_str = date_val.isoformat()
            else:
                date_str = str(date_val)

            feature_vector["date"] = date_str
            feature_vector["open"] = float(row["Open"])  # SP-335: raw yfinance open
            feature_vector["high"] = float(row["High"])  # SP-335: raw yfinance high
            feature_vector["low"] = float(row["Low"])  # SP-335: raw yfinance low
            feature_vector["close"] = float(row["Close"])

            feature_rows.append(feature_vector)

        # --- Step 11: Build DataFrame ---
        if not feature_rows:
            raise InsufficientDataError(
                f"No valid feature rows produced for {self._ticker_symbol}. Downloaded data may be insufficient."
            )

        result_df = pd.DataFrame(feature_rows)

        # --- Step 12: Add next_day_direction label ---
        # 1 if next day's close > current close, 0 otherwise (including equal)
        result_df["next_day_direction"] = (result_df["close"].shift(-1) > result_df["close"]).astype(int)

        # --- Step 13: Exclude final row (no next-day label) ---
        result_df = result_df.iloc[:-1].reset_index(drop=True)

        # --- Step 14: Validate minimum rows ---
        if len(result_df) < 2000:
            raise InsufficientDataError(
                f"Insufficient data for {self._ticker_symbol}: "
                f"only {len(result_df)} valid labelled rows produced "
                f"(minimum 2000 required)."
            )

        return result_df

    def _detect_signals(self, this_candle, deque_dictionary: dict) -> dict:
        """
        Replicate MarketAnalyzer.detect_signals() logic to produce signal scores.

        This is a self-contained version that does not require a MarketAnalyzer
        instance, using the deque_dictionary and config directly.

        Args:
            this_candle: The current Candle with percentiles already assigned.
            deque_dictionary: Dict of period deques containing Candle objects.

        Returns:
            Dict with keys: single_candle_signal_score, trend_signal_score,
            multiple_bar_signal_score, acc_dist_signal_score, multiple_bar_signals.
        """
        all_signals = {}

        # --- Single candle signals ---
        single_candle_signal_score = 0

        # Up or down bar
        single_candle_signal_score += 1 if this_candle.up_bar else -1

        # Wide spread + high volume per period
        for period in deque_dictionary:
            if this_candle.spread_percentiles[period] > 70:
                single_candle_signal_score += 2.5 if this_candle.up_bar else -2.5
                if this_candle.volume_percentiles[period] > 70:
                    single_candle_signal_score += 2.5 if this_candle.up_bar else -2.5

        # Candle patterns
        if this_candle.shooting_star:
            single_candle_signal_score -= 3
        elif this_candle.hammer:
            single_candle_signal_score += 3

        all_signals["single_candle_signal_score"] = single_candle_signal_score

        # --- Trend signals ---
        trend_signal_score = 0

        adx_values = calculate_adx(list(deque_dictionary["period_three"]))
        trending = adx_values[0] > 25
        trending_up = adx_values[2] > adx_values[3]
        trending_down = adx_values[3] > adx_values[2]

        if trending:
            if trending_up:
                trend_signal_score += 5
            if trending_down:
                trend_signal_score -= 5

        all_signals["trend_signal_score"] = trend_signal_score

        # --- Multiple bar signals ---
        trading_params = self._config.trading_parameters
        signals_flags = {}

        for key in deque_dictionary:
            parameters = getattr(trading_params, key)
            up_bar_count = sum(1 for candle in deque_dictionary[key] if candle.up_bar)
            high_spread_count = sum(
                1
                for candle in deque_dictionary[key]
                if candle.spread_percentiles[key] > parameters.high_spread_threshold
            )
            high_volume_count = sum(
                1
                for candle in deque_dictionary[key]
                if candle.volume_percentiles[key] > parameters.high_volume_threshold
            )
            anomaly_count = sum(
                1
                for candle in deque_dictionary[key]
                if abs(candle.spread_percentiles[key] - candle.volume_percentiles[key]) > parameters.anomaly_threshold
            )

            signals_flags[f"{key}_bull"] = False
            signals_flags[f"{key}_bear"] = False
            signals_flags[f"{key}_volume_backed"] = False

            if up_bar_count >= parameters.signal_bar_count:
                signals_flags[f"{key}_bull"] = True
            elif up_bar_count <= (self._config.period_one_length - parameters.signal_bar_count):
                signals_flags[f"{key}_bear"] = True

            if signals_flags[f"{key}_bear"] or signals_flags[f"{key}_bull"]:
                if (
                    high_spread_count >= parameters.high_spread_count
                    and high_volume_count >= parameters.high_volume_count
                    and anomaly_count <= parameters.anomaly_threshold
                ):
                    signals_flags[f"{key}_volume_backed"] = True

        multiple_bar_signals = []
        multiple_bar_signal_score = 0

        # SP-313: per-period scoring params. period_one->p1, period_two->p2,
        # period_three->p3. The period weight (Req 4) scales each period's
        # contribution; the vol_backed multiplier (Req 5) replaces the hardcoded
        # ``* 2`` doubling. Defaults reproduce current scoring exactly:
        # period_weight_pN == 1.0 (no scaling) and vol_backed_mult_pN == 2.0
        # (same doubling), so the default path is byte-identical to the legacy
        # arithmetic (Property 1).
        period_weights = {
            "period_one": self._scoring_params.period_weight_p1,
            "period_two": self._scoring_params.period_weight_p2,
            "period_three": self._scoring_params.period_weight_p3,
        }
        vol_backed_mults = {
            "period_one": self._scoring_params.vol_backed_mult_p1,
            "period_two": self._scoring_params.vol_backed_mult_p2,
            "period_three": self._scoring_params.vol_backed_mult_p3,
        }

        for period in deque_dictionary:
            for signal_type in ["bull", "bear"]:
                if signals_flags[f"{period}_{signal_type}"]:
                    multiple_bar_signals.append(f"{signal_type.capitalize()} Signal ({period})")
                    score_adjustment = 2.5 if signal_type == "bull" else -2.5
                    if signals_flags[f"{period}_volume_backed"]:
                        contribution = score_adjustment * vol_backed_mults[period]
                        multiple_bar_signals.append(f"Volume Backed ({period})")
                    else:
                        contribution = score_adjustment

                    # Apply the period weight only when it departs from the
                    # default 1.0, so the default path keeps the exact float
                    # value of the legacy expression (avoids float-formatting
                    # drift from an unnecessary ``* 1.0`` multiply).
                    weight = period_weights[period]
                    if weight != 1.0:
                        contribution *= weight

                    multiple_bar_signal_score += contribution

        all_signals["multiple_bar_signals"] = multiple_bar_signals
        all_signals["multiple_bar_signal_score"] = multiple_bar_signal_score

        # --- Accumulation/Distribution signals ---
        acc_dist_signal_score = 0

        acc_or_dist_bool, acc_or_dist = identify_acc_or_dist(
            list(deque_dictionary["period_three"]),
            list(deque_dictionary["period_one"]),
            volume_percentile=self._scoring_params.acc_dist_volume_percentile,
            test_count=self._scoring_params.acc_dist_test_count,
        )

        if acc_or_dist_bool:
            acc_dist_signal_score += 10 if acc_or_dist == "Acc" else -10

            if this_candle.spread_percentiles["period_one"] > 65 or this_candle.is_candle_pattern():
                if this_candle.volume_percentiles["period_one"] < 50:
                    acc_dist_signal_score += 5 if acc_or_dist == "Acc" else -5
                else:
                    # Test fail weakens signal
                    acc_dist_signal_score -= 2 if acc_or_dist == "Acc" else 2

            if this_candle.spread_percentiles["period_two"] < 40 and this_candle.volume_percentiles["period_two"] > 60:
                acc_dist_signal_score += 10 if acc_or_dist == "Acc" else -10

        all_signals["acc_dist_signal_score"] = acc_dist_signal_score

        return all_signals
