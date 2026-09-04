from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigurationError(ValueError):
    """Raised when a VPA configuration cannot be converted to typed settings."""


@dataclass(frozen=True)
class MAPeriods:
    short: int = 10
    medium: int = 50
    long: int = 200


@dataclass(frozen=True)
class CrossoverScores:
    short_medium: float = 5
    short_long: float = 8
    medium_long: float = 10


@dataclass(frozen=True)
class PriceVsSMACrossoverScores:
    cross_above: float = 3
    cross_below: float = 3


@dataclass(frozen=True)
class PositionScores:
    above_all: float = 5
    below_all: float = 5
    above_two: float = 2
    below_two: float = 2


@dataclass(frozen=True)
class MACrossoverSettings:
    enabled: bool = True
    ma_periods: MAPeriods = MAPeriods()
    ma_data_days: int = 300
    crossover_scores: CrossoverScores = CrossoverScores()
    position_scores: PositionScores = PositionScores()

    def __getitem__(self, key: str) -> Any:
        """Provide read-only compatibility for existing private-state tests."""
        values = {
            "enabled": self.enabled,
            "ma_periods": {
                "short": self.ma_periods.short,
                "medium": self.ma_periods.medium,
                "long": self.ma_periods.long,
            },
            "ma_data_days": self.ma_data_days,
            "crossover_scores": {
                "short_medium": self.crossover_scores.short_medium,
                "short_long": self.crossover_scores.short_long,
                "medium_long": self.crossover_scores.medium_long,
            },
            "position_scores": {
                "above_all": self.position_scores.above_all,
                "below_all": self.position_scores.below_all,
                "above_two": self.position_scores.above_two,
                "below_two": self.position_scores.below_two,
            },
        }
        return values[key]


@dataclass(frozen=True)
class DrawdownSettings:
    enabled: bool = True
    drawdown_threshold: float = 20
    momentum_period: int = 20
    data_days: int = 400


@dataclass(frozen=True)
class RSIScores:
    overbought: float = -5
    oversold: float = 5


@dataclass(frozen=True)
class RSISettings:
    enabled: bool = True
    period: int = 14
    overbought_threshold: float = 70
    oversold_threshold: float = 30
    scores: RSIScores = RSIScores()


@dataclass(frozen=True)
class PriceVsSMAScores:
    above: float = 5
    below: float = 5


@dataclass(frozen=True)
class PriceVsSMASettings:
    enabled: bool = True
    period: int = 10
    scores: PriceVsSMAScores = PriceVsSMAScores()
    detect_crossover: bool = False
    crossover_scores: PriceVsSMACrossoverScores = PriceVsSMACrossoverScores()


@dataclass(frozen=True)
class PeriodTradingParameters:
    high_spread_threshold: float = 55
    high_volume_threshold: float = 55
    anomaly_threshold: float = 20
    signal_bar_count: int = 4
    high_spread_count: int = 3
    high_volume_count: int = 3


@dataclass(frozen=True)
class TradingParameters:
    period_one: PeriodTradingParameters
    period_two: PeriodTradingParameters
    period_three: PeriodTradingParameters


@dataclass(frozen=True)
class Settings:
    enable_feature_extraction: bool
    use_real_data: bool
    rolling_window_complete_msg_display: bool
    max_rows: int
    period_one_length: int
    period_two_length: int
    period_three_length: int
    percentile_start: int
    percentile_increments: int
    ticker_symbol: str
    ma_crossover: MACrossoverSettings
    drawdown_filter: DrawdownSettings
    rsi: RSISettings
    price_vs_sma: PriceVsSMASettings
    trading_parameters: TradingParameters


def _value(data: dict[str, Any], key: str, path: str, expected_type: type) -> Any:
    if key not in data:
        raise ConfigurationError(f"Missing required setting: {path}")
    value = data[key]
    if type(value) is not expected_type:
        raise ConfigurationError(f"Invalid setting {path}: expected {expected_type.__name__}")
    return value


def _optional(data: dict[str, Any], key: str, default: Any, path: str, expected_type: type) -> Any:
    if key not in data:
        return default
    value = data[key]
    if type(value) is not expected_type:
        raise ConfigurationError(f"Invalid setting {path}: expected {expected_type.__name__}")
    return value


def _section(data: dict[str, Any], key: str, path: str) -> dict[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ConfigurationError(f"Invalid setting {path}: expected object")
    return value


def _number(data: dict[str, Any], key: str, default: float, path: str) -> float:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigurationError(f"Invalid setting {path}: expected number")
    return value


def _positive_int(value: int, path: str) -> int:
    if value < 1:
        raise ConfigurationError(f"Invalid setting {path}: expected a positive integer")
    return value


def _ma_settings(raw: dict[str, Any]) -> MACrossoverSettings:
    periods = _section(raw, "ma_periods", "ma_crossover.ma_periods")
    ma_periods = MAPeriods(
        short=_positive_int(
            _optional(periods, "short", 10, "ma_crossover.ma_periods.short", int), "ma_crossover.ma_periods.short"
        ),
        medium=_positive_int(
            _optional(periods, "medium", 50, "ma_crossover.ma_periods.medium", int), "ma_crossover.ma_periods.medium"
        ),
        long=_positive_int(
            _optional(periods, "long", 200, "ma_crossover.ma_periods.long", int), "ma_crossover.ma_periods.long"
        ),
    )
    crossover = _section(raw, "crossover_scores", "ma_crossover.crossover_scores")
    position = _section(raw, "position_scores", "ma_crossover.position_scores")
    return MACrossoverSettings(
        enabled=_optional(raw, "enabled", True, "ma_crossover.enabled", bool),
        ma_periods=ma_periods,
        ma_data_days=_positive_int(
            _optional(raw, "ma_data_days", 300, "ma_crossover.ma_data_days", int), "ma_crossover.ma_data_days"
        ),
        crossover_scores=CrossoverScores(
            short_medium=_number(crossover, "short_medium", 5, "ma_crossover.crossover_scores.short_medium"),
            short_long=_number(crossover, "short_long", 8, "ma_crossover.crossover_scores.short_long"),
            medium_long=_number(crossover, "medium_long", 10, "ma_crossover.crossover_scores.medium_long"),
        ),
        position_scores=PositionScores(
            above_all=_number(position, "above_all", 5, "ma_crossover.position_scores.above_all"),
            below_all=_number(position, "below_all", 5, "ma_crossover.position_scores.below_all"),
            above_two=_number(position, "above_two", 2, "ma_crossover.position_scores.above_two"),
            below_two=_number(position, "below_two", 2, "ma_crossover.position_scores.below_two"),
        ),
    )


def _price_vs_sma_settings(raw: dict[str, Any]) -> PriceVsSMASettings:
    scores = _section(raw, "scores", "price_vs_sma.scores")
    crossover_scores = _section(raw, "crossover_scores", "price_vs_sma.crossover_scores")
    return PriceVsSMASettings(
        enabled=_optional(raw, "enabled", True, "price_vs_sma.enabled", bool),
        period=_optional(raw, "period", 10, "price_vs_sma.period", int),
        scores=PriceVsSMAScores(
            above=_number(scores, "above", 5, "price_vs_sma.scores.above"),
            below=_number(scores, "below", 5, "price_vs_sma.scores.below"),
        ),
        detect_crossover=_optional(raw, "detect_crossover", False, "price_vs_sma.detect_crossover", bool),
        crossover_scores=PriceVsSMACrossoverScores(
            cross_above=_number(crossover_scores, "cross_above", 3, "price_vs_sma.crossover_scores.cross_above"),
            cross_below=_number(crossover_scores, "cross_below", 3, "price_vs_sma.crossover_scores.cross_below"),
        ),
    )


def _trading_parameters(raw: dict[str, Any]) -> TradingParameters:
    def build(period: str, default_signal_count: int) -> PeriodTradingParameters:
        section = _section(raw, period, f"trading_parameters.{period}")
        return PeriodTradingParameters(
            high_spread_threshold=_number(
                section, "High_Spread_Threshold", 55, f"trading_parameters.{period}.High_Spread_Threshold"
            ),
            high_volume_threshold=_number(
                section, "High_Volume_Threshold", 55, f"trading_parameters.{period}.High_Volume_Threshold"
            ),
            anomaly_threshold=_number(
                section, "Anomaly_Threshold", 20, f"trading_parameters.{period}.Anomaly_Threshold"
            ),
            signal_bar_count=_optional(
                section, "Signal_Bar_Count", default_signal_count, f"trading_parameters.{period}.Signal_Bar_Count", int
            ),
            high_spread_count=_optional(
                section, "High_Spread_Count", 3, f"trading_parameters.{period}.High_Spread_Count", int
            ),
            high_volume_count=_optional(
                section, "High_Volume_Count", 3, f"trading_parameters.{period}.High_Volume_Count", int
            ),
        )

    return TradingParameters(build("period_one", 4), build("period_two", 13), build("period_three", 26))


def load_settings(config_path: str | Path) -> Settings:
    """Load and validate a legacy VPA JSON configuration into typed settings."""
    try:
        with open(config_path, encoding="utf-8") as file:
            raw = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Unable to load configuration {config_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigurationError("Configuration root must be an object")

    period_one_length = _positive_int(_value(raw, "PERIOD_ONE_LENGTH", "PERIOD_ONE_LENGTH", int), "PERIOD_ONE_LENGTH")
    period_two_length = _positive_int(_value(raw, "PERIOD_TWO_LENGTH", "PERIOD_TWO_LENGTH", int), "PERIOD_TWO_LENGTH")
    period_three_length = _positive_int(
        _value(raw, "PERIOD_THREE_LENGTH", "PERIOD_THREE_LENGTH", int), "PERIOD_THREE_LENGTH"
    )
    percentile_start = _value(raw, "PERCENTILE_START", "PERCENTILE_START", int)
    percentile_increments = _positive_int(
        _value(raw, "PERCENTILE_INCREMENTS", "PERCENTILE_INCREMENTS", int), "PERCENTILE_INCREMENTS"
    )
    trading_raw = raw.get("trading_parameters")
    if not isinstance(trading_raw, dict):
        raise ConfigurationError("Invalid setting trading_parameters: expected object")

    return Settings(
        enable_feature_extraction=_optional(raw, "enable_feature_extraction", False, "enable_feature_extraction", bool),
        use_real_data=_value(raw, "use_real_data", "use_real_data", bool),
        rolling_window_complete_msg_display=_value(
            raw, "rolling_window_complete_msg_display", "rolling_window_complete_msg_display", bool
        ),
        max_rows=_value(raw, "MAX_ROWS", "MAX_ROWS", int),
        period_one_length=period_one_length,
        period_two_length=period_two_length,
        period_three_length=period_three_length,
        percentile_start=percentile_start,
        percentile_increments=percentile_increments,
        ticker_symbol=_value(raw, "ticker_symbol", "ticker_symbol", str),
        ma_crossover=_ma_settings(_section(raw, "ma_crossover", "ma_crossover")),
        drawdown_filter=DrawdownSettings(
            enabled=_optional(
                _section(raw, "drawdown_filter", "drawdown_filter"), "enabled", True, "drawdown_filter.enabled", bool
            ),
            drawdown_threshold=_number(
                _section(raw, "drawdown_filter", "drawdown_filter"),
                "drawdown_threshold",
                20,
                "drawdown_filter.drawdown_threshold",
            ),
            momentum_period=_optional(
                _section(raw, "drawdown_filter", "drawdown_filter"),
                "momentum_period",
                20,
                "drawdown_filter.momentum_period",
                int,
            ),
            data_days=_optional(
                _section(raw, "drawdown_filter", "drawdown_filter"), "data_days", 400, "drawdown_filter.data_days", int
            ),
        ),
        rsi=RSISettings(
            enabled=_optional(_section(raw, "rsi", "rsi"), "enabled", True, "rsi.enabled", bool),
            period=_optional(_section(raw, "rsi", "rsi"), "period", 14, "rsi.period", int),
            overbought_threshold=_number(
                _section(raw, "rsi", "rsi"), "overbought_threshold", 70, "rsi.overbought_threshold"
            ),
            oversold_threshold=_number(_section(raw, "rsi", "rsi"), "oversold_threshold", 30, "rsi.oversold_threshold"),
            scores=RSIScores(
                overbought=_number(
                    _section(_section(raw, "rsi", "rsi"), "scores", "rsi.scores"),
                    "overbought",
                    -5,
                    "rsi.scores.overbought",
                ),
                oversold=_number(
                    _section(_section(raw, "rsi", "rsi"), "scores", "rsi.scores"), "oversold", 5, "rsi.scores.oversold"
                ),
            ),
        ),
        price_vs_sma=_price_vs_sma_settings(_section(raw, "price_vs_sma", "price_vs_sma")),
        trading_parameters=_trading_parameters(trading_raw),
    )
