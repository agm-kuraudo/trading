import json
from pathlib import Path

import pytest

from vpa.config import ConfigurationError, load_settings

CONFIG_PATH = Path(__file__).parents[1] / "config" / "config.json"


def write_config(tmp_path, config):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def test_load_complete_config_returns_typed_nested_settings():
    settings = load_settings(CONFIG_PATH)

    assert settings.period_one_length == 5
    assert settings.ma_crossover.ma_periods.long == 200
    assert settings.rsi.scores.oversold == 5
    assert settings.trading_parameters.period_three.signal_bar_count == 26
    assert settings.dss_bressert.stochastic_period == 10
    assert settings.dss_bressert.scores.bullish_crossover == 0


def test_missing_optional_sections_use_existing_defaults(tmp_path):
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config.pop("ma_crossover")
    config.pop("drawdown_filter")
    config.pop("rsi")
    config.pop("price_vs_sma")

    settings = load_settings(write_config(tmp_path, config))

    assert settings.ma_crossover.ma_data_days == 300
    assert settings.drawdown_filter.data_days == 400
    assert settings.rsi.period == 14
    assert settings.price_vs_sma.period == 10
    assert settings.dss_bressert.enabled is True
    assert settings.dss_bressert.smoothing_period == 9
    assert settings.dss_bressert.trigger_period == 5
    assert settings.dss_bressert.overbought_threshold == 80
    assert settings.dss_bressert.oversold_threshold == 20


def test_dss_bressert_full_config_round_trips_to_typed_settings(tmp_path):
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config["dss_bressert"] = {
        "enabled": False,
        "stochastic_period": 12,
        "smoothing_period": 7,
        "trigger_period": 3,
        "overbought_threshold": 75.5,
        "oversold_threshold": 18.5,
        "scores": {
            "bullish_crossover": 4,
            "bearish_crossover": 6,
            "oversold": 2,
            "overbought": -3,
        },
    }

    settings = load_settings(write_config(tmp_path, config))

    assert settings.dss_bressert.enabled is False
    assert settings.dss_bressert.stochastic_period == 12
    assert settings.dss_bressert.smoothing_period == 7
    assert settings.dss_bressert.trigger_period == 3
    assert settings.dss_bressert.overbought_threshold == 75.5
    assert settings.dss_bressert.oversold_threshold == 18.5
    assert settings.dss_bressert.scores.bullish_crossover == 4
    assert settings.dss_bressert.scores.bearish_crossover == 6
    assert settings.dss_bressert.scores.oversold == 2
    assert settings.dss_bressert.scores.overbought == -3


def test_invalid_nested_type_reports_configuration_path(tmp_path):
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config["rsi"]["period"] = "14"

    with pytest.raises(ConfigurationError, match="rsi.period"):
        load_settings(write_config(tmp_path, config))


def test_invalid_required_type_reports_configuration_path(tmp_path):
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config["PERIOD_ONE_LENGTH"] = 0

    with pytest.raises(ConfigurationError, match="PERIOD_ONE_LENGTH"):
        load_settings(write_config(tmp_path, config))


def test_unknown_keys_do_not_break_loading(tmp_path):
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config["future_setting"] = {"enabled": True}
    config["rsi"]["future_rsi_setting"] = 42

    settings = load_settings(write_config(tmp_path, config))

    assert settings.ticker_symbol == "SPY"
