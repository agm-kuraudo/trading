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


def test_combined_signals_absent_block_defaults_disabled(tmp_path):
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config.pop("combined_signals", None)

    settings = load_settings(write_config(tmp_path, config))

    assert settings.combined_signals.enabled is False
    assert settings.combined_signals.combinations == ()


def test_combined_signals_full_block_round_trips_to_typed_settings(tmp_path):
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config["combined_signals"] = {
        "enabled": True,
        "combinations": [
            {
                "name": "DSS_Cross_Plus_SMA_Position_Bull",
                "score": 10,
                "conditions": [
                    {"signal_name": "DSS Bullish Crossover", "kind": "presence"},
                    {"signal_name": "Price above SMA", "kind": "presence"},
                ],
            },
            {
                "name": "DSS_Cross_Plus_SMA_Position_Bear",
                "score": -10,
                "conditions": [
                    {"signal_name": "DSS Bearish Crossover", "kind": "presence"},
                    {"signal_name": "Price below SMA", "kind": "presence"},
                ],
            },
            {
                "name": "DSS_Zone_Plus_SMA_Cross_Bull",
                "score": 7.5,
                "conditions": [
                    {"signal_name": "DSS Oversold", "kind": "presence"},
                    {"signal_name": "Price crossed above SMA", "kind": "presence"},
                ],
            },
            {
                "name": "DSS_Zone_Plus_SMA_Cross_Bear",
                "score": -7.5,
                "conditions": [
                    {"signal_name": "DSS Overbought", "kind": "presence"},
                    {"signal_name": "Price crossed below SMA", "kind": "presence"},
                ],
            },
            {
                "name": "DSS_Cross_SMA_Not_Overbought_Bull",
                "score": 12,
                "conditions": [
                    {"signal_name": "DSS Bullish Crossover", "kind": "presence"},
                    {"signal_name": "Price above SMA", "kind": "presence"},
                    {"signal_name": "DSS Overbought", "kind": "absence"},
                ],
            },
        ],
    }

    settings = load_settings(write_config(tmp_path, config))
    combined = settings.combined_signals

    assert combined.enabled is True
    assert len(combined.combinations) == 5

    # Every one of the eight known signal-name strings is exercised across the block.
    exercised = {cond.signal_name for combo in combined.combinations for cond in combo.conditions}
    assert exercised == {
        "DSS Bullish Crossover",
        "DSS Bearish Crossover",
        "DSS Oversold",
        "DSS Overbought",
        "Price above SMA",
        "Price below SMA",
        "Price crossed above SMA",
        "Price crossed below SMA",
    }

    first = combined.combinations[0]
    assert first.name == "DSS_Cross_Plus_SMA_Position_Bull"
    assert first.score == 10
    assert len(first.conditions) == 2
    assert first.conditions[0].signal_name == "DSS Bullish Crossover"
    assert first.conditions[0].kind == "presence"
    assert first.conditions[1].signal_name == "Price above SMA"
    assert first.conditions[1].kind == "presence"

    bear = combined.combinations[1]
    assert bear.name == "DSS_Cross_Plus_SMA_Position_Bear"
    assert bear.score == -10

    # Three-condition combination including an absence (negation) condition.
    three_way = combined.combinations[4]
    assert three_way.name == "DSS_Cross_SMA_Not_Overbought_Bull"
    assert three_way.score == 12
    assert len(three_way.conditions) == 3
    assert three_way.conditions[2].signal_name == "DSS Overbought"
    assert three_way.conditions[2].kind == "absence"


def test_combined_signals_default_kind_is_presence(tmp_path):
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config["combined_signals"] = {
        "enabled": True,
        "combinations": [
            {
                "name": "Combo_Default_Kind",
                "score": 1,
                "conditions": [
                    {"signal_name": "DSS Bullish Crossover"},
                    {"signal_name": "Price above SMA"},
                ],
            }
        ],
    }

    settings = load_settings(write_config(tmp_path, config))
    combo = settings.combined_signals.combinations[0]

    assert combo.conditions[0].kind == "presence"
    assert combo.conditions[1].kind == "presence"


def test_committed_config_loads_all_ten_combined_signals():
    settings = load_settings(CONFIG_PATH)

    assert settings.combined_signals.enabled is False
    assert len(settings.combined_signals.combinations) == 10


def test_combined_signals_combinations_not_a_list_raises(tmp_path):
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config["combined_signals"] = {"enabled": True, "combinations": {"not": "a list"}}

    with pytest.raises(ConfigurationError, match="combined_signals.combinations"):
        load_settings(write_config(tmp_path, config))


def test_combined_signals_combination_not_an_object_raises(tmp_path):
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config["combined_signals"] = {"enabled": True, "combinations": ["not an object"]}

    with pytest.raises(ConfigurationError, match=r"combined_signals.combinations\[0\]"):
        load_settings(write_config(tmp_path, config))


def test_combined_signals_conditions_not_a_list_raises(tmp_path):
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config["combined_signals"] = {
        "enabled": True,
        "combinations": [{"name": "Combo_Bad_Conditions", "score": 1, "conditions": "nope"}],
    }

    with pytest.raises(ConfigurationError, match="conditions"):
        load_settings(write_config(tmp_path, config))


def test_combined_signals_name_not_a_string_raises(tmp_path):
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config["combined_signals"] = {
        "enabled": True,
        "combinations": [{"name": 123, "score": 1, "conditions": []}],
    }

    with pytest.raises(ConfigurationError, match="name"):
        load_settings(write_config(tmp_path, config))


def test_combined_signals_missing_name_raises(tmp_path):
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config["combined_signals"] = {
        "enabled": True,
        "combinations": [{"score": 1, "conditions": []}],
    }

    with pytest.raises(ConfigurationError, match="name"):
        load_settings(write_config(tmp_path, config))
