<!-- Generated with GitHub Copilot in VS Code; reviewed for handoff to Kiro. -->

# Design Document: Typed Configuration

## Overview

Introduce a typed settings module under `vpa/config/` that owns JSON parsing, defaults, and structural validation. `MarketAnalyzer` and `VPAFeatureExtractor` continue accepting `config_path`, but delegate configuration loading to the shared module and consume typed settings objects.

The design deliberately preserves the current JSON schema and feature behavior. Feature-specific runtime rules already present in `MarketAnalyzer`, such as disabling invalid MA/RSI configurations or correcting `ma_data_days`, remain in the owning feature logic unless they are proven to be structural validation concerns.

## Design Decisions

1. **Use standard-library dataclasses**: The project already targets Python 3.11 and does not need a new runtime dependency for this configuration layer.
2. **Keep JSON as the external format**: Operators do not need to migrate `config.json` files.
3. **Centralize parsing**: One `load_settings(config_path)` function reads JSON and constructs the full typed object graph.
4. **Typed nested sections**: Root settings and feature sections are represented by separate dataclasses, including typed period, score, and trading-parameter objects.
5. **Defaults at construction time**: Missing optional sections use the same defaults currently embedded in the consumers.
6. **Clear boundary errors**: A dedicated `ConfigurationError` identifies malformed values and their configuration paths.
7. **Preserve unknown keys**: Unknown JSON keys are ignored during construction so newer configuration files remain usable; only consumed fields are typed and validated.
8. **Preserve public APIs**: Existing `config_path` parameters remain unchanged. No raw dictionary is required by either consumer after loading.

## Proposed Module Structure

```text
vpa/
  config/
    __init__.py
    config.json
    settings.py
```

`settings.py` owns:

- Dataclasses for root and nested settings.
- Default constants for optional sections.
- `ConfigurationError`.
- `load_settings(config_path: str | os.PathLike[str]) -> Settings`.
- Small validation/conversion helpers that report paths such as `rsi.period`.

## Data Model

The exact field names should use Python snake_case, while the loader maps existing JSON keys such as `PERIOD_ONE_LENGTH` and `High_Spread_Threshold` explicitly.

```text
Settings
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

MACrossoverSettings
  enabled: bool
  ma_periods: MAPeriods
  ma_data_days: int
  crossover_scores: CrossoverScores
  position_scores: PositionScores

TradingParameters
  period_one: PeriodTradingParameters
  period_two: PeriodTradingParameters
  period_three: PeriodTradingParameters
```

Nested score fields should use numeric types compatible with current arithmetic. Defaults must match `config.json` and current fallback dictionaries exactly.

## Loading and Validation Flow

```text
load_settings(path)
  -> open and json.load(path)
  -> validate root object
  -> map required root keys to typed fields
  -> map optional sections using defaults
  -> validate scalar types and supported ranges
  -> return Settings
```

Required root fields are the values needed by current execution: feature-extraction switch, real-data switch, rolling-window message flag, row limit, period lengths, percentile parameters, ticker symbol, and trading parameters. Optional feature sections receive existing defaults when absent.

Validation should reject booleans supplied as integers, non-integer period lengths, non-positive periods/increments, and malformed objects. MA ordering and feature-specific disable/correction behavior remain in `MarketAnalyzer` to preserve its current warning and fallback semantics.

## Consumer Changes

### `vpa/app_runner.py`

- Replace `json` loading with `load_settings(config_path)`.
- Store a typed `Settings` instance.
- Replace root accesses with typed attributes.
- Use typed nested settings as the source for feature initialization, while retaining current feature-level validation and mutable corrected values in consumer-local state where required.
- Preserve logging, data loading, signal scores, and constructor behavior.

### `vpa/ml_validation/feature_extractor.py`

- Replace direct JSON loading with `load_settings(config_path)`.
- Store typed settings.
- Replace period, percentile, trading-parameter, and RSI accesses with typed attributes.
- Preserve feature column order and all extracted numeric values.

## Testing Strategy

Add `vpa/tests/test_settings.py` covering:

- Complete config loading and representative nested attributes.
- Optional-section defaults.
- Invalid root and nested types with configuration paths in errors.
- Invalid positive/range values.
- Unknown-key compatibility.

Extend or add consumer tests to verify:

- `MarketAnalyzer` and `VPAFeatureExtractor` still accept temporary JSON paths.
- Existing config-driven defaults and feature behavior remain unchanged.
- Equivalent settings produce equivalent rolling lengths, signal scores, and feature-vector values.

Use fixed DataFrames and temporary JSON files; no network calls are required.

## Compatibility and Risks

- The JSON schema remains unchanged.
- Existing tests that inspect name-mangled dictionaries may need to assert typed values or public behavior instead.
- Settings dataclasses should not be mutated by consumers; feature-specific corrected values can remain in local runtime state.
- The ML path and live path must use the same loader to avoid parsing drift.
- Full regression tests are required because configuration values influence nearly every signal path.
