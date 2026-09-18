"""VPA Feature Extractor - extracts structured feature vectors from MarketAnalyzer."""

import datetime
from collections import deque

import numpy as np
import pandas as pd

from vpa.app import Candle, calculate_adx, identify_acc_or_dist
from vpa.config import load_settings
from vpa.market_data.repository import MarketDataRepository
from vpa.ml_validation.exceptions import InsufficientDataError
from vpa.rsi import calculate_rsi


class VPAFeatureExtractor:
    """Extracts VPA intermediate features as a structured vector for ML analysis."""

    # Fixed column order for the 31-feature vector
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
        "dss_bullish_cross",
        "dss_bearish_cross",
        "composite_score",
        "up_bar_current",
    ]

    # Metadata columns (excluded from the numeric feature array)
    # SP-335: add raw open/high/low alongside close
    METADATA_COLUMNS = ["date", "open", "high", "low", "close"]

    def __init__(self, config_path: str, ticker_symbol: str, enable_extraction: bool = True):
        """
        Args:
            config_path: Path to the VPA config JSON.
            ticker_symbol: Ticker to analyse (e.g. "SPY").
            enable_extraction: If False, delegates to MarketAnalyzer with no extraction.
        """
        self._config_path = config_path
        self._ticker_symbol = ticker_symbol
        self._enable_extraction = enable_extraction

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
            A dict with fixed column names and numeric values, containing all 29
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
            "dss_bullish_cross": int(dss_bullish_cross),
            "dss_bearish_cross": int(dss_bearish_cross),
            "composite_score": composite_score,
            "up_bar_current": up_bar_current,
        }

        return feature_vector

    def generate_dataset(self, days: int = 3650, repo: MarketDataRepository | None = None) -> pd.DataFrame:
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

        Returns:
            DataFrame with one row per trading day (after warm-up), containing
            all 27 feature columns, metadata columns (date, close), and the
            next_day_direction label. The final row is excluded (no next-day label).

        Raises:
            InsufficientDataError: If fewer than 2000 valid labelled rows after
                warm-up and final-row exclusion.
        """
        # --- Step 1: Load data via the market-data repository (read-through) ---
        # The loader returns the canonical Date,Open,High,Low,Close,Volume DataFrame
        # already flattened/renamed/dropna'd/sorted, so no inline normalisation is needed.
        end_date = datetime.datetime.now().date()
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

            # --- Step 10: Extract feature vector ---
            feature_vector = self._extract_feature_vector(
                candle=this_candle,
                signals=signals,
                adx_values=adx_values,
                acc_dist_result=acc_dist_result,
                deque_dictionary=deque_dictionary,
                dss_bullish_cross=dss_bullish_cross,
                dss_bearish_cross=dss_bearish_cross,
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
                f"No valid feature rows produced for {self._ticker_symbol}. " f"Downloaded data may be insufficient."
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

        for period in deque_dictionary:
            for signal_type in ["bull", "bear"]:
                if signals_flags[f"{period}_{signal_type}"]:
                    multiple_bar_signals.append(f"{signal_type.capitalize()} Signal ({period})")
                    score_adjustment = 2.5 if signal_type == "bull" else -2.5
                    if signals_flags[f"{period}_volume_backed"]:
                        multiple_bar_signal_score += score_adjustment * 2
                        multiple_bar_signals.append(f"Volume Backed ({period})")
                    else:
                        multiple_bar_signal_score += score_adjustment

        all_signals["multiple_bar_signals"] = multiple_bar_signals
        all_signals["multiple_bar_signal_score"] = multiple_bar_signal_score

        # --- Accumulation/Distribution signals ---
        acc_dist_signal_score = 0

        acc_or_dist_bool, acc_or_dist = identify_acc_or_dist(
            list(deque_dictionary["period_three"]),
            list(deque_dictionary["period_one"]),
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
