<!-- Generated with GitHub Copilot in VS Code; reviewed for handoff to Kiro. -->

# Implementation Plan: Typed Configuration

## Overview

Create a shared typed settings contract for the existing JSON configuration and migrate the live and ML consumers without changing their public constructors or observable signal behavior.

## Tasks

- [x] 1. Define the typed settings module
  - [x] 1.1 Create `vpa/config/__init__.py` exports for the settings API.
  - [x] 1.2 Create `vpa/config/settings.py` with dataclasses for root settings and nested MA, drawdown, RSI, price-SMA, score, period, and trading-parameter sections.
  - [x] 1.3 Add `ConfigurationError` and typed conversion helpers that include the failing JSON path.
  - _Requirements: 1.1-1.5, 3.1-3.2_

- [x] 2. Implement JSON loading and defaults
  - [x] 2.1 Implement `load_settings(config_path)` using the existing JSON schema and explicit key mappings.
  - [x] 2.2 Preserve all current defaults for omitted optional feature sections.
  - [x] 2.3 Preserve unknown keys without exposing the raw dictionary as the consumer interface.
  - [x] 2.4 Validate required root fields, nested object shapes, scalar types, positive periods, and percentile values.
  - _Requirements: 2.1-2.5, 3.1-3.5, 5.1-5.5_

- [x] 3. Add settings-loader tests
  - [x] 3.1 Test the complete `vpa/config/config.json` loads and representative typed values are available.
  - [x] 3.2 Test omitted optional sections receive current defaults.
  - [x] 3.3 Test malformed required and nested values raise `ConfigurationError` with a useful path.
  - [x] 3.4 Test unknown keys do not break loading.
  - _Requirements: 5.1-5.5, 6.1-6.3_

- [x] 4. Migrate `MarketAnalyzer`
  - [x] 4.1 Replace direct JSON loading in `vpa/app_runner.py` with `load_settings`.
  - [x] 4.2 Replace root and nested raw-key reads with typed settings access.
  - [x] 4.3 Preserve MA/RSI/price-SMA validation, warning messages, and `ma_data_days` correction behavior.
  - [x] 4.4 Preserve data-window selection, rolling-window behavior, and signal scores.
  - _Requirements: 3.4, 4.1, 4.3-4.4, 5.2-5.4_

- [x] 5. Migrate `VPAFeatureExtractor`
  - [x] 5.1 Replace direct JSON loading in `vpa/ml_validation/feature_extractor.py` with the shared loader.
  - [x] 5.2 Replace period, percentile, trading-parameter, and RSI raw-key reads with typed settings access.
  - [x] 5.3 Preserve feature column order, extracted values, and constructor behavior.
  - _Requirements: 4.2-4.5, 6.4_

- [x] 6. Add consumer regression coverage
  - [x] 6.1 Run and adapt existing analyzer tests to verify behavior through typed settings.
  - [x] 6.2 Add extractor regression coverage for representative feature vectors and RSI/trading parameters.
  - [x] 6.3 Verify both consumers use the same loader and no independent JSON parsing remains.
  - _Requirements: 4.1-4.5, 6.4-6.5_

- [x] 7. Documentation and quality checks
  - [x] 7.1 Review `README.md`; update configuration documentation only if public usage changes.
  - [x] 7.2 Run focused settings, analyzer, and extractor pytest modules.
  - [x] 7.3 Run Ruff format check and lint on changed Python files.
  - [x] 7.4 Run the full pytest suite and resolve regressions caused by the migration.
  - [ ] 7.5 Add a completion comment to Jira `SP-308` summarizing the implementation, verification results, and PR/readiness state.
  - [ ] 7.6 Transition Jira to Mostly Done only after the implementation is verified and code is ready to merge; do not transition to Done without explicit user confirmation.
  - _Requirements: 6.5_

## Notes

- Keep `config_path` constructor arguments unchanged.
- Do not change signal algorithms or the external JSON schema.
- No Jira status change is part of spec creation; Jira updates occur only at completion per the ticket lifecycle.
