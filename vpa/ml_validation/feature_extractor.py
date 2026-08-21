"""VPA Feature Extractor - extracts structured feature vectors from MarketAnalyzer."""

import datetime
import json
from collections import deque

import numpy as np
import pandas as pd
import yfinance as yf

from vpa.app import Candle, calculate_adx, identify_acc_or_dist
from vpa.ml_validation.exceptions import InsufficientDataError
from vpa.rsi import calculate_rsi


class VPAFeatureExtractor:
    """Extracts VPA intermediate features as a structured vector for ML analysis."""

    # Fixed column order for the 29-feature vector
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
        "composite_score",
        "up_bar_current",
    ]

    # Metadata columns (excluded from the numeric feature array)
    METADATA_COLUMNS = ["date", "close"]

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

        # Load configuration
        with open(config_path) as f:
            self._config = json.load(f)

        # Store period lengths for up_bar_ratio calculations
        self._period_one_length = self._config["PERIOD_ONE_LENGTH"]
        self._period_two_length = self._config["PERIOD_TWO_LENGTH"]
        self._period_three_length = self._config["PERIOD_THREE_LENGTH"]

    def _extract_feature_vector(
        self,
        candle,
        signals: dict,
        adx_values: list,
        acc_dist_result: tuple,
        deque_dictionary: dict,
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
        rsi_config = self._config.get(
            "rsi",
            {
                "enabled": True,
                "period": 14,
                "overbought_threshold": 70,
                "oversold_threshold": 30,
                "scores": {"overbought": -5, "oversold": 5},
            },
        )
        rsi_enabled = rsi_config.get("enabled", True)

        if rsi_enabled:
            period_three_closes = [c.close for c in deque_dictionary["period_three"]]
            rsi_period = rsi_config.get("period", 14)
            rsi_value = calculate_rsi(period_three_closes, rsi_period)

            # RSI signal score using same threshold logic as MarketAnalyzer
            overbought = rsi_config.get("overbought_threshold", 70)
            oversold = rsi_config.get("oversold_threshold", 30)
            scores = rsi_config.get("scores", {"overbought": -5, "oversold": 5})

            rsi_signal_score = 0.0
            if rsi_value > overbought:
                rsi_signal_score = float(scores["overbought"])
            elif rsi_value < oversold:
                rsi_signal_score = float(scores["oversold"])
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
            "composite_score": composite_score,
            "up_bar_current": up_bar_current,
        }

        return feature_vector

    def generate_dataset(self, days: int = 3650) -> pd.DataFrame:
        """
        Download OHLCV data and produce a labelled feature dataset.

        Downloads at least ``days`` calendar days of daily data from yfinance for
        self._ticker_symbol, processes each row through the VPA logic (replicating
        MarketAnalyzer behaviour), extracts feature vectors once rolling windows
        are full, labels each row with next-day price direction, and returns the
        resulting DataFrame.

        Args:
            days: Calendar days of data to download (default 3650 = ~10 years).

        Returns:
            DataFrame with one row per trading day (after warm-up), containing
            all 27 feature columns, metadata columns (date, close), and the
            next_day_direction label. The final row is excluded (no next-day label).

        Raises:
            InsufficientDataError: If fewer than 2000 valid labelled rows after
                warm-up and final-row exclusion.
        """
        # --- Step 1: Download data from yfinance ---
        end_date = datetime.datetime.now().date()
        start_date = end_date - datetime.timedelta(days=days)

        df = yf.download(
            self._ticker_symbol,
            start=start_date,
            end=end_date,
            auto_adjust=True,
            progress=False,
        )

        # Reset index so Date becomes a column
        df = df.reset_index()

        # Normalise column names (yfinance may return MultiIndex for single ticker)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] if col[1] == "" else col[0] for col in df.columns]

        # Ensure expected columns exist
        required_cols = ["Date", "Open", "High", "Low", "Close", "Volume"]
        # Handle case-insensitive column matching
        col_map = {c.lower(): c for c in df.columns}
        rename_map = {}
        for rc in required_cols:
            if rc not in df.columns and rc.lower() in col_map:
                rename_map[col_map[rc.lower()]] = rc
        if rename_map:
            df = df.rename(columns=rename_map)

        # --- Step 2: Drop NaN rows in OHLCV columns ---
        ohlcv_cols = ["Open", "High", "Low", "Close", "Volume"]
        df = df.dropna(subset=ohlcv_cols)

        # --- Step 3: Sort by date ---
        df = df.sort_values("Date").reset_index(drop=True)

        # --- Step 4: Set up rolling deques ---
        deque_dictionary = {
            "period_one": deque(maxlen=self._period_one_length),
            "period_two": deque(maxlen=self._period_two_length),
            "period_three": deque(maxlen=self._period_three_length),
        }

        # Percentile storage (mirrors MarketAnalyzer.__percentiles_store)
        percentiles_store = {"spread": {}, "volume": {}}

        percentile_start = self._config["PERCENTILE_START"]
        percentile_increments = self._config["PERCENTILE_INCREMENTS"]

        # --- Step 5: Process each row ---
        feature_rows = []
        previous_close = 0

        for _, row in df.iterrows():
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

            # --- Step 10: Extract feature vector ---
            feature_vector = self._extract_feature_vector(
                candle=this_candle,
                signals=signals,
                adx_values=adx_values,
                acc_dist_result=acc_dist_result,
                deque_dictionary=deque_dictionary,
            )

            # Add metadata
            date_val = row["Date"]
            if hasattr(date_val, "isoformat"):
                date_str = date_val.isoformat()
            else:
                date_str = str(date_val)

            feature_vector["date"] = date_str
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
        trading_params = self._config["trading_parameters"]
        signals_flags = {}

        for key in deque_dictionary:
            up_bar_count = sum(1 for candle in deque_dictionary[key] if candle.up_bar)
            high_spread_count = sum(
                1
                for candle in deque_dictionary[key]
                if candle.spread_percentiles[key] > trading_params[key]["High_Spread_Threshold"]
            )
            high_volume_count = sum(
                1
                for candle in deque_dictionary[key]
                if candle.volume_percentiles[key] > trading_params[key]["High_Volume_Threshold"]
            )
            anomaly_count = sum(
                1
                for candle in deque_dictionary[key]
                if abs(candle.spread_percentiles[key] - candle.volume_percentiles[key])
                > trading_params[key]["Anomaly_Threshold"]
            )

            signals_flags[f"{key}_bull"] = False
            signals_flags[f"{key}_bear"] = False
            signals_flags[f"{key}_volume_backed"] = False

            if up_bar_count >= trading_params[key]["Signal_Bar_Count"]:
                signals_flags[f"{key}_bull"] = True
            elif up_bar_count <= (self._config["PERIOD_ONE_LENGTH"] - trading_params[key]["Signal_Bar_Count"]):
                signals_flags[f"{key}_bear"] = True

            if signals_flags[f"{key}_bear"] or signals_flags[f"{key}_bull"]:
                if (
                    high_spread_count >= trading_params[key]["High_Spread_Count"]
                    and high_volume_count >= trading_params[key]["High_Volume_Count"]
                    and anomaly_count <= trading_params[key]["Anomaly_Threshold"]
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
