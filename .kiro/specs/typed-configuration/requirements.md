<!-- Generated with GitHub Copilot in VS Code; reviewed for handoff to Kiro. -->

# Requirements Document

## Introduction

SP-308 extracts the VPA application's JSON configuration into a typed settings module. The change provides one validated configuration contract shared by the live `MarketAnalyzer` path and the ML `VPAFeatureExtractor` path, while preserving the existing JSON file format, default behavior, constructor arguments, and signal outputs.

## Glossary

- **Settings**: The typed root configuration object returned by the configuration loader.
- **Settings Loader**: The module-level function that reads a JSON configuration file and constructs `Settings`.
- **Feature Settings**: Typed nested settings for MA crossover, drawdown, RSI, and price-versus-SMA behavior.
- **Required Setting**: A root configuration value needed for normal operation and present in the current configuration schema.
- **Optional Section**: A nested configuration object that may be omitted and receives the existing application defaults.
- **Configuration Compatibility**: Existing `config.json` files and `config_path` constructor arguments continue to work without migration.

## Requirements

### Requirement 1: Typed Configuration Contract

**User Story:** As a developer, I want configuration values represented by typed settings objects so that invalid access patterns are detected early and configuration usage is discoverable.

#### Acceptance Criteria

1. The system SHALL expose a typed `Settings` object for the root configuration values currently consumed by VPA application code.
2. The system SHALL expose typed nested settings for `ma_crossover`, `drawdown_filter`, `rsi`, `price_vs_sma`, and `trading_parameters`.
3. Typed settings SHALL provide explicit attribute access for values currently read through string keys, including period lengths, percentile parameters, ticker selection, and feature thresholds or scores.
4. Settings objects SHALL use concrete type annotations for booleans, integers, floats, strings, lists, and nested settings as applicable.
5. Consumers SHALL not need to know the JSON key names after configuration has been loaded.

### Requirement 2: JSON Loading and Compatibility

**User Story:** As an operator, I want the existing JSON configuration file and application entry points to continue working while the internal representation becomes typed.

#### Acceptance Criteria

1. The Settings Loader SHALL load the existing `vpa/config/config.json` structure without requiring a file format migration.
2. `MarketAnalyzer(config_path=...)` and `VPAFeatureExtractor(config_path=...)` SHALL retain their current constructor signatures and accept the same path values.
3. Existing configuration files with omitted optional feature sections SHALL receive the same defaults currently used by the consumers.
4. Loading a valid configuration SHALL preserve the effective values and behavior of the current implementation.
5. The loader SHALL avoid exposing the mutable raw JSON dictionary as the primary configuration interface to consumers.

### Requirement 3: Validation and Errors

**User Story:** As a developer, I want malformed configuration to fail clearly at the configuration boundary rather than later as an unrelated runtime error.

#### Acceptance Criteria

1. The loader SHALL validate the types and required presence of root settings needed by the application.
2. The loader SHALL validate nested settings needed to construct typed objects and SHALL identify the affected configuration path in an error.
3. Invalid period lengths, percentile increments, or other values that cannot support the existing algorithms SHALL raise a clear configuration error at load time, unless the current feature-specific behavior explicitly disables or corrects that value.
4. Existing feature-specific rules that disable invalid MA/RSI/price-SMA configurations or auto-correct `ma_data_days` SHALL remain behaviorally unchanged unless the approved design explicitly moves that rule into the loader.
5. Configuration errors SHALL not be silently replaced with unrelated defaults for fields that are present but malformed.

### Requirement 4: Consumer Integration

**User Story:** As a maintainer, I want all current configuration consumers to share one typed loader so that the live and ML paths do not drift in their parsing logic.

#### Acceptance Criteria

1. `MarketAnalyzer` SHALL obtain its root and nested configuration from the shared Settings Loader.
2. `VPAFeatureExtractor` SHALL obtain its root and nested configuration from the shared Settings Loader.
3. The consumers SHALL use typed attributes or typed nested objects rather than direct raw dictionary indexing for values handled by the typed settings module.
4. Signal scores, rolling-window lengths, data-window selection, RSI behavior, and feature-vector values SHALL remain unchanged for an equivalent configuration.
5. The two consumers SHALL not each implement independent JSON parsing or duplicate conversion logic.

### Requirement 5: Defaults and Backward Behavior

**User Story:** As a user of an older configuration file, I want configuration extraction to preserve current defaults and runtime behavior.

#### Acceptance Criteria

1. Missing optional sections SHALL use the defaults currently defined in `MarketAnalyzer` and `VPAFeatureExtractor`.
2. The default period lengths SHALL remain 5, 25, and 50 for periods one, two, and three.
3. The default percentile settings SHALL remain `PERCENTILE_START=5` and `PERCENTILE_INCREMENTS=5`.
4. Existing defaults for MA crossover, drawdown, RSI, and price-versus-SMA sections SHALL remain unchanged.
5. The loader SHALL preserve unknown JSON keys for forward compatibility or explicitly document and test the chosen behavior.

### Requirement 6: Testability and Documentation

**User Story:** As a maintainer, I want focused tests around the configuration boundary so that future schema changes do not silently alter trading signals.

#### Acceptance Criteria

1. Tests SHALL cover loading the complete current configuration and accessing representative typed root and nested values.
2. Tests SHALL cover omitted optional sections and verify their defaults.
3. Tests SHALL cover malformed required values and assert clear configuration errors.
4. Tests SHALL verify that both `MarketAnalyzer` and `VPAFeatureExtractor` can consume the shared settings without changing their existing observable behavior.
5. The README SHALL be updated if the public configuration workflow or supported configuration file usage changes.
