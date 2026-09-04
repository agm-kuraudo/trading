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
